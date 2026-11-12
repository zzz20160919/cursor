#!/usr/bin/env python3
"""Build the Hou–Li–Zheng paper sample on Polymarket (Step 1).

The sample is a metadata screen of binary contracts. It does not price
markets, build a daily tradable set, or collapse an event to one contract.

Paper screens, mapped off Kalshi wording:

1. Reported cumulative volume is at least 10,000. The paper counts
   contracts. Gamma ``volumeNum`` (else ``volume``) is the lifetime
   figure and is typically USD notional, not a contract count. The
   numeric cutoff is still applied to that figure.
2. Scheduled life is at least two days: expiry minus the opening
   timestamp, in elapsed days. Opening prefers ``startDate`` /
   ``startDateIso``, then the parent event start, then ``createdAt``.
   Expiry prefers ``endDate`` / ``endDateIso``, then the parent event
   end. ``closedTime`` is the actual close, not the scheduled expiry.
   ``gameStartTime`` is a sports fixture time, not the contract open.
3. The opening date (UTC calendar date) is on or before the sample end
   date. The default end date is today UTC. ``--end-date`` overrides it.
   April 28, 2026 is the Kalshi paper's archive cutoff. This script
   leaves that date unset unless it is passed on the command line.

Each binary market is one contract, including when several markets share
an event. Open markets and closed/settled markets both stay in when they
pass the screens. Gamma is read with ``/markets/keyset`` ordered by
lifetime ``volumeNum``. Offset paging rejects offsets above 2000, and
ordering by ``volume1wk`` would drop quiet or already-closed contracts
that still have a large lifetime volume.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


OUTPUT_DIR = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section"
DEFAULT_OUTPUT = OUTPUT_DIR / "paper_sample_markets.csv"
DEFAULT_META = OUTPUT_DIR / "paper_sample_meta.json"
DEFAULT_SUMMARY = OUTPUT_DIR / "SUMMARY.md"
DEFAULT_CACHE = OUTPUT_DIR / "cache"
PAGE_LIMIT = 100
CACHE_VERSION = 1
# Requests started per second across all band workers. Gamma allows more;
# staying under the published /markets budget avoids 429 bursts.
REQUESTS_PER_SECOND = 20.0
# A closed band below this lifetime volume is dense on Gamma. An empty
# file there means the pull stopped short.
DENSE_CLOSED_MAX = 100_000.0
# Head/tail checks. They are completeness guards for this pull, not sample rules.
FLOOR_AUDIT_SLACK = 100.0
HEAD_VOLUME_MIN = 1_000_000.0

COLUMNS = (
    "market_id",
    "question",
    "event_id",
    "event_title",
    "cumulative_volume",
    "volume_unit",
    "scheduled_life_days",
    "open_date",
    "expiry",
    "closed",
    "open_date_source",
    "expiry_source",
    "slug",
    "outcomes",
    "yes_token",
    "sample_end_date",
    "condition_id",
    "closed_time",
    "life_mode",
    "observed_life_days",
)

# (container, field, label). Start fields outrank createdAt: createdAt can
# be the draft timestamp, hours or days before the contract opens.
OPEN_CANDIDATES = (
    ("market", "startDate", "startDate"),
    ("market", "startDateIso", "startDateIso"),
    ("event", "startDate", "event.startDate"),
    ("market", "createdAt", "createdAt"),
    ("event", "createdAt", "event.createdAt"),
    ("event", "creationDate", "event.creationDate"),
)
EXPIRY_CANDIDATES = (
    ("market", "endDate", "endDate"),
    ("market", "endDateIso", "endDateIso"),
    ("event", "endDate", "event.endDate"),
    ("event", "endDateIso", "event.endDateIso"),
)

FAILURE_ORDER = (
    "missing_id",
    "below_volume",
    "non_binary",
    "missing_open",
    "missing_expiry",
    "life_below_min",
    "opened_after_cutoff",
)


@dataclass(frozen=True)
class Decision:
    reason: str
    row: dict[str, str] | None = None


@dataclass(frozen=True)
class BandResult:
    closed: bool
    volume_min: float
    volume_max: float | None
    rows: int
    cached: bool
    path: Path


class RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_at)
            self.next_at = slot + self.interval
            delay = slot - now
        if delay > 0:
            time.sleep(delay)


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            year, month, day = (int(part) for part in text.split("-"))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_num(value: float | None) -> int | float | None:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return float(value)


def query_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return float(value)


def one_line(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def iter_events(market: dict[str, Any]) -> list[dict[str, Any]]:
    events = market.get("events")
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except json.JSONDecodeError:
            return []
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def lifetime_volume(market: dict[str, Any]) -> tuple[float | None, str]:
    """Gamma lifetime size. ``volumeNum`` wins when it is present, including 0."""
    number = as_float(market.get("volumeNum"))
    if number is not None:
        return number, "volumeNum"
    fallback = as_float(market.get("volume"))
    if fallback is not None:
        return fallback, "volume"
    return None, ""


def outcome_labels(market: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in parse_json_list(market.get("outcomes")):
        text = str(item).strip()
        if text:
            labels.append(text)
    return labels


def yes_token(market: dict[str, Any], labels: list[str]) -> str:
    tokens = [str(item) for item in parse_json_list(market.get("clobTokenIds"))]
    for index, label in enumerate(labels):
        if label.lower() == "yes" and index < len(tokens) and tokens[index]:
            return tokens[index]
    return ""


def resolve_field(
    market: dict[str, Any],
    event: dict[str, Any] | None,
    candidates: tuple[tuple[str, str, str], ...],
) -> tuple[datetime, str] | None:
    containers = {"market": market, "event": event or {}}
    for which, key, label in candidates:
        parsed = parse_dt(containers[which].get(key))
        if parsed is not None:
            return parsed, label
    return None


def screen_market(
    market: dict[str, Any],
    *,
    sample_end: date,
    min_volume: float,
    min_life_days: float,
    volume_above: bool = False,
    life_mode: str = "scheduled",
) -> Decision:
    """Apply the paper screens. The first failing rule is the funnel reason.

    ``volume_above`` makes the floor exclusive (volume must be above the
    cutoff). Appendix A.3 says "above 2,000". ``life_mode="observed"`` uses
    the span from the opening timestamp to the earlier of close and the
    sample end, instead of scheduled expiry minus open.
    """
    market_id = str(market.get("id") or "").strip()
    if not market_id:
        return Decision("missing_id")
    volume, volume_field = lifetime_volume(market)
    # Numeric threshold matches the paper. The unit does not: Polymarket
    # volume is USD notional, while the paper counts Kalshi contracts.
    if volume is None or (volume <= min_volume if volume_above else volume < min_volume):
        return Decision("below_volume")
    labels = outcome_labels(market)
    if len(labels) != 2:
        return Decision("non_binary")
    event = iter_events(market)
    primary = event[0] if event else None
    opened = resolve_field(market, primary, OPEN_CANDIDATES)
    if opened is None:
        return Decision("missing_open")
    expired = resolve_field(market, primary, EXPIRY_CANDIDATES)
    if expired is None:
        return Decision("missing_expiry")
    open_dt, open_source = opened
    expiry_dt, expiry_source = expired
    closed_at = parse_dt(market.get("closedTime"))
    sample_cap = datetime.combine(sample_end, datetime.max.time(), tzinfo=timezone.utc)
    if life_mode == "observed":
        if closed_at is not None:
            observed_end = min(closed_at, sample_cap)
        else:
            observed_end = min(expiry_dt, sample_cap)
        life_days = (observed_end - open_dt).total_seconds() / 86400.0
    elif life_mode == "scheduled":
        life_days = (expiry_dt - open_dt).total_seconds() / 86400.0
    else:
        raise ValueError(f"unknown life_mode {life_mode}")
    scheduled_days = (expiry_dt - open_dt).total_seconds() / 86400.0
    if life_mode == "observed":
        observed_days = life_days
    else:
        if closed_at is not None:
            observed_end = min(closed_at, sample_cap)
        else:
            observed_end = min(expiry_dt, sample_cap)
        observed_days = (observed_end - open_dt).total_seconds() / 86400.0
    if life_days < min_life_days:
        return Decision("life_below_min")
    if open_dt.date() > sample_end:
        return Decision("opened_after_cutoff")
    event_id = str((primary or {}).get("id") or "").strip()
    event_title = one_line((primary or {}).get("title"))
    if not event_id:
        event_id = f"market:{market_id}"
    closed = as_bool(market.get("closed"))
    if closed is None:
        closed_text = ""
    else:
        closed_text = "true" if closed else "false"
    row = {
        "market_id": market_id,
        "question": one_line(market.get("question")),
        "event_id": event_id,
        "event_title": event_title,
        "cumulative_volume": f"{volume:.6f}",
        "volume_unit": "usd_notional",
        "scheduled_life_days": f"{scheduled_days:.6f}",
        "open_date": iso_z(open_dt),
        "expiry": iso_z(expiry_dt),
        "closed": closed_text,
        "open_date_source": open_source,
        "expiry_source": expiry_source,
        "slug": one_line(market.get("slug")),
        "outcomes": " | ".join(labels),
        "yes_token": yes_token(market, labels),
        "sample_end_date": sample_end.isoformat(),
        "condition_id": str(market.get("conditionId") or ""),
        "closed_time": "" if closed_at is None else iso_z(closed_at),
        "life_mode": life_mode,
        "observed_life_days": f"{observed_days:.6f}",
    }
    return Decision("selected", row)


def percentile(values: list[float], probability: float) -> float:
    """Linear percentile (NumPy's default; Hyndman-Fan type 7)."""
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * probability
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def volume_stats(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("empty")
    return {
        "min": min(values),
        "median": float(median(values)),
        "mean": float(mean(values)),
        "p90": percentile(values, 0.90),
        "max": max(values),
    }


def volume_bands(floor: float) -> list[tuple[float, float | None]]:
    """Inclusive lifetime-volume slices covering ``[floor, infinity)``.

    Closed markets above the paper floor are too numerous for one cursor
    to finish quickly. Adjacent slices share the boundary value; callers
    dedupe by market id, so an inclusive max does not drop or double-count
    a contract in the screened sample.
    """
    if floor < 0:
        raise ValueError("volume floor must be non-negative")
    edges = [float(floor)]
    schedule = (
        (30_000.0, 1_000.0),
        (100_000.0, 5_000.0),
        (500_000.0, 25_000.0),
        (2_000_000.0, 100_000.0),
    )
    for cap, step in schedule:
        while edges[-1] < cap:
            nxt = edges[-1] + step
            if nxt > cap:
                nxt = cap
            if nxt <= edges[-1]:
                raise RuntimeError("volume band schedule did not advance")
            edges.append(nxt)
            if len(edges) > 100_000:
                raise RuntimeError("volume band schedule ran away")
    bands = [(edges[index], edges[index + 1]) for index in range(len(edges) - 1)]
    bands.append((edges[-1], None))
    return bands


def band_slug(closed: bool, volume_min: float, volume_max: float | None) -> str:
    side = "closed" if closed else "open"
    high = "inf" if volume_max is None else str(query_number(volume_max))
    return f"{side}-{query_number(volume_min)}-{high}"


def get_json(url: str, limiter: RateLimiter, timeout: int = 45) -> Any:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(5):
        limiter.wait()
        try:
            return pm.http_json(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode(errors="replace")[:300]
            except Exception:
                detail = ""
            exc.close()
            last_error = RuntimeError(f"HTTP {exc.code} for {url}: {detail}")
            if exc.code in {429, 500, 502, 503, 504} and attempt < 4:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry_after) if retry_after and str(retry_after).isdigit() else delay
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            raise last_error from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= 4:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"request failed: {url}") from last_error


def keyset_url(params: dict[str, Any]) -> str:
    return f"{pm.GAMMA_API}/markets/keyset?{urllib.parse.urlencode(params)}"


def iter_keyset_markets(
    get: Any,
    *,
    closed: bool,
    volume_min: float,
    volume_max: float | None,
    limit: int = PAGE_LIMIT,
) -> Iterator[dict[str, Any]]:
    """Follow ``next_cursor`` until Gamma ends the slice.

    Do not stop because ``volume1wk`` is small. Lifetime volume is already
    bounded by ``volume_num_min`` / ``volume_num_max``. A short page, a
    missing cursor, or a repeated cursor ends the slice.
    """
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, Any] = {
            "limit": limit,
            "closed": "true" if closed else "false",
            "order": "volumeNum",
            "ascending": "false",
            "volume_num_min": query_number(volume_min),
        }
        if volume_max is not None:
            params["volume_num_max"] = query_number(volume_max)
        if cursor:
            params["after_cursor"] = cursor
        payload = get(params)
        if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
            raise RuntimeError(
                "Gamma /markets/keyset did not return a markets list "
                f"(closed={closed}, min={volume_min}, max={volume_max})"
            )
        markets = [row for row in payload["markets"] if isinstance(row, dict)]
        yield from markets
        nxt = payload.get("next_cursor")
        if not markets or not isinstance(nxt, str) or not nxt or len(payload["markets"]) < limit:
            break
        if nxt in seen_cursors:
            break
        seen_cursors.add(nxt)
        cursor = nxt


def slim_market(market: dict[str, Any], closed_hint: bool | None = None) -> dict[str, Any]:
    events = []
    for event in iter_events(market):
        events.append(
            {
                "id": event.get("id"),
                "title": event.get("title"),
                "startDate": event.get("startDate"),
                "endDate": event.get("endDate"),
                "endDateIso": event.get("endDateIso"),
                "createdAt": event.get("createdAt"),
                "creationDate": event.get("creationDate"),
            }
        )
    closed = market.get("closed")
    if closed is None and closed_hint is not None:
        closed = closed_hint
    return {
        "id": market.get("id"),
        "question": market.get("question"),
        "slug": market.get("slug"),
        "conditionId": market.get("conditionId") or "",
        "volumeNum": market.get("volumeNum"),
        "volume": market.get("volume"),
        "startDate": market.get("startDate"),
        "startDateIso": market.get("startDateIso"),
        "createdAt": market.get("createdAt"),
        "endDate": market.get("endDate"),
        "endDateIso": market.get("endDateIso"),
        "closed": closed,
        "closedTime": market.get("closedTime"),
        "outcomes": market.get("outcomes"),
        "clobTokenIds": market.get("clobTokenIds"),
        "events": events,
    }


def done_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".done")


def read_done(path: Path, closed: bool, volume_min: float, volume_max: float | None) -> int | None:
    marker = done_path(path)
    if not path.exists() or not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None
    if payload.get("closed") is not closed:
        return None
    if payload.get("volume_min") != json_num(volume_min):
        return None
    if payload.get("volume_max") != json_num(volume_max):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, int) or rows < 0:
        return None
    return rows


def write_done(path: Path, rows: int, closed: bool, volume_min: float, volume_max: float | None) -> None:
    payload = {
        "version": CACHE_VERSION,
        "rows": rows,
        "closed": closed,
        "volume_min": json_num(volume_min),
        "volume_max": json_num(volume_max),
    }
    done_path(path).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def fetch_band(
    *,
    closed: bool,
    volume_min: float,
    volume_max: float | None,
    path: Path,
    limiter: RateLimiter,
    refresh: bool,
    print_lock: threading.Lock,
) -> BandResult:
    cached_rows = None if refresh else read_done(path, closed, volume_min, volume_max)
    label = band_slug(closed, volume_min, volume_max)
    if cached_rows is not None:
        with print_lock:
            print(f"band {label}: cache {cached_rows}", flush=True)
        return BandResult(closed, volume_min, volume_max, cached_rows, True, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    rows = 0
    pages = 0

    def get(params: dict[str, Any]) -> Any:
        return get_json(keyset_url(params), limiter)

    with partial.open("w", encoding="utf-8") as handle:
        page_rows = 0
        for market in iter_keyset_markets(
            get,
            closed=closed,
            volume_min=volume_min,
            volume_max=volume_max,
        ):
            handle.write(json.dumps(slim_market(market, closed_hint=closed), ensure_ascii=False) + "\n")
            rows += 1
            page_rows += 1
            if page_rows >= PAGE_LIMIT:
                pages += 1
                page_rows = 0
                if pages % 25 == 0:
                    with print_lock:
                        print(f"paging {label} page {pages} rows {rows}", flush=True)
    partial.replace(path)
    write_done(path, rows, closed, volume_min, volume_max)
    with print_lock:
        print(f"band {label}: fetched {rows}", flush=True)
    return BandResult(closed, volume_min, volume_max, rows, False, path)


def fetch_gamma_markets(
    *,
    min_volume: float,
    cache_dir: Path,
    workers: int,
    refresh: bool,
    max_bands: int,
) -> list[BandResult]:
    """Page open and closed markets by lifetime volume.

    The previous Step 1 fetcher ordered open markets by ``volume1wk`` and
    stopped when that trailing week fell through the floor. That is not
    the paper screen: a contract can be quiet this week, or already
    settled, and still have cumulative volume above 10,000. Offset paging
    also fails past 2000 (``offset too large, use /markets/keyset``).
    ``order=volume_num`` is rejected; the keyset field name is ``volumeNum``.
    """
    bands = volume_bands(min_volume)
    if max_bands > 0:
        bands = bands[:max_bands]
    tasks: list[tuple[bool, float, float | None, Path]] = []
    for closed in (False, True):
        for volume_min, volume_max in bands:
            path = cache_dir / "bands" / f"{band_slug(closed, volume_min, volume_max)}.jsonl"
            tasks.append((closed, volume_min, volume_max, path))
    limiter = RateLimiter(REQUESTS_PER_SECOND)
    print_lock = threading.Lock()
    results: list[BandResult] = []
    failures: list[tuple[str, Exception]] = []

    def run(task: tuple[bool, float, float | None, Path]) -> BandResult:
        closed, volume_min, volume_max, path = task
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return fetch_band(
                    closed=closed,
                    volume_min=volume_min,
                    volume_max=volume_max,
                    path=path,
                    limiter=limiter,
                    refresh=refresh if attempt == 0 else True,
                    print_lock=print_lock,
                )
            except Exception as exc:  # noqa: BLE001 — retry the band, then fail the pull
                last_error = exc
                time.sleep(2 ** attempt)
        assert last_error is not None
        raise last_error

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(run, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            label = band_slug(task[0], task[1], task[2])
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 — collected and raised below
                failures.append((label, exc))
                with print_lock:
                    print(f"band failed {label}: {exc}", flush=True)
    if failures:
        summary = "; ".join(f"{label}: {exc}" for label, exc in failures[:5])
        raise SystemExit(f"{len(failures)} volume bands failed. {summary}")
    return results


def audit_bands(results: list[BandResult], *, min_volume: float, max_bands: int) -> None:
    if max_bands > 0:
        return
    closed = [band for band in results if band.closed]
    if not closed:
        raise SystemExit("closed-market paging produced no bands")
    empty_dense = [
        band_slug(band.closed, band.volume_min, band.volume_max)
        for band in closed
        if band.rows == 0 and band.volume_min < DENSE_CLOSED_MAX
    ]
    if empty_dense:
        raise SystemExit(
            "closed volume bands below "
            f"{DENSE_CLOSED_MAX:.0f} came back empty: {', '.join(empty_dense[:8])}"
        )
    top = [band for band in closed if band.volume_max is None]
    if not top or top[0].rows < 1:
        raise SystemExit("the open-ended closed volume band was empty")
    if min_volume <= 10_000 and not any(band.rows > 0 for band in results if not band.closed):
        raise SystemExit("open-market paging returned no markets")


def screen_cached(
    results: list[BandResult],
    *,
    sample_end: date,
    min_volume: float,
    min_life_days: float,
    volume_above: bool = False,
    life_mode: str = "scheduled",
) -> tuple[list[dict[str, str]], Counter[str], dict[str, Any]]:
    seen: set[str] = set()
    selected: list[dict[str, str]] = []
    reasons: Counter[str] = Counter()
    duplicates = 0
    raw_rows = 0
    observed: dict[bool, list[float]] = {False: [], True: []}
    for band in sorted(results, key=lambda item: (item.closed, item.volume_min)):
        with band.path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_rows += 1
                market = json.loads(line)
                if not isinstance(market, dict):
                    reasons["bad_row"] += 1
                    continue
                market_id = str(market.get("id") or "").strip()
                if market_id and market_id in seen:
                    duplicates += 1
                    continue
                if market_id:
                    seen.add(market_id)
                volume, _field = lifetime_volume(market)
                closed_flag = as_bool(market.get("closed"))
                if volume is not None and closed_flag is not None:
                    observed[closed_flag].append(volume)
                decision = screen_market(
                    market,
                    sample_end=sample_end,
                    min_volume=min_volume,
                    min_life_days=min_life_days,
                    volume_above=volume_above,
                    life_mode=life_mode,
                )
                reasons[decision.reason] += 1
                if decision.row is not None:
                    selected.append(decision.row)
    selected.sort(key=lambda row: (-float(row["cumulative_volume"]), row["market_id"]))
    coverage = {
        "raw_rows": raw_rows,
        "unique_markets": len(seen),
        "boundary_duplicates": duplicates,
        "open_observed": len(observed[False]),
        "closed_observed": len(observed[True]),
        "open_volume_min": min(observed[False]) if observed[False] else None,
        "open_volume_max": max(observed[False]) if observed[False] else None,
        "closed_volume_min": min(observed[True]) if observed[True] else None,
        "closed_volume_max": max(observed[True]) if observed[True] else None,
    }
    return selected, reasons, coverage


def audit_coverage(coverage: dict[str, Any], *, min_volume: float, max_bands: int) -> None:
    if max_bands > 0:
        return
    for side in ("open", "closed"):
        observed_min = coverage.get(f"{side}_volume_min")
        observed_max = coverage.get(f"{side}_volume_max")
        if observed_min is None or observed_max is None:
            raise SystemExit(f"{side} markets were not observed after dedupe")
        if observed_min > min_volume + FLOOR_AUDIT_SLACK:
            raise SystemExit(
                f"{side} minimum lifetime volume is {observed_min}, "
                f"more than {FLOOR_AUDIT_SLACK} above the {min_volume} floor. "
                "The pull did not reach the bottom of the book."
            )
        if side == "closed" and observed_max < HEAD_VOLUME_MIN:
            raise SystemExit(
                f"closed maximum lifetime volume is {observed_max}, below {HEAD_VOLUME_MIN}. "
                "The pull did not reach the head of the book."
            )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def fmt_count(value: int) -> str:
    return f"{value:,}"


def fmt_volume(value: float) -> str:
    return f"{value:,.2f}"


def render_summary(meta: dict[str, Any]) -> str:
    stats = meta["volume_stats"]
    end = meta["sample_end_date"]
    contracts = fmt_count(meta["n_contracts"])
    events = fmt_count(meta["n_events"])
    n_open = fmt_count(meta["n_open_contracts"])
    n_closed = fmt_count(meta["n_closed_contracts"])
    funnel = meta["funnel"]
    if meta.get("volume_above"):
        volume_rule = (
            f"1. Lifetime volume above {fmt_volume(meta['min_volume'])} "
            "(strict). Appendix A.3's Polymarket floor, in USD notional, not a contract count."
        )
        volume_rule_zh = (
            f"1. 累计成交额严格大于 {fmt_volume(meta['min_volume'])} 美元名义。"
            "对应附录 A.3 的 “above 2,000”，不是合约张数。"
        )
    else:
        volume_rule = (
            f"1. Lifetime volume ≥ {fmt_volume(meta['min_volume'])}. "
            "Paper threshold: 10,000 contracts. Polymarket's figure is USD notional."
        )
        volume_rule_zh = (
            f"1. 累计成交量 ≥ {fmt_volume(meta['min_volume'])}。"
            "论文门槛是 10,000 张合约；Polymarket 这里用的是美元名义金额。"
        )
    if meta.get("life_mode") == "observed":
        life_rule = (
            f"2. Observed life ≥ {meta['min_life_days']:g} days. "
            "The end is closedTime when Gamma has it, otherwise expiry, capped at the sample-end day."
        )
        life_rule_zh = (
            f"2. 观察存续 ≥ {meta['min_life_days']:g} 天。"
            "结束时刻优先用 closedTime，否则用到期时刻，并截到样本截止日。"
        )
    else:
        life_rule = (
            f"2. Scheduled life ≥ {meta['min_life_days']:g} days, elapsed time from the opening timestamp to expiry."
        )
        life_rule_zh = (
            f"2. 预定存续期 ≥ {meta['min_life_days']:g} 天，即到期时刻减去开盘时刻的实际时长。"
        )
    lines = [
        "# HLZ Polymarket paper sample / Hou–Li–Zheng 论文样本",
        "",
        f"Sample end / 样本截止: **{end} UTC**.",
        "",
        "The sample end date is the UTC date of this run unless `--end-date` set it. "
        "The Hou–Li–Zheng Kalshi archive cutoff is April 28, 2026. This file uses that "
        "date only when the command line passes it.",
        "",
        "样本截止日是本次运行的 UTC 日期；若命令行传入 `--end-date`，则以该日期为准。"
        "Hou–Li–Zheng 论文的 Kalshi 档案截止日是 2026-04-28。只有命令行传入该日期时，这里才会使用它。",
        "",
        "## Counts / 数量",
        "",
        "| | |",
        "| --- | ---: |",
        f"| Contracts / 合约 | {contracts} |",
        f"| Events / 事件 | {events} |",
        f"| Open contracts / 未结束合约 | {n_open} |",
        f"| Closed or settled contracts / 已结束或已结算合约 | {n_closed} |",
        f"| Contracts with no parent event id / 没有父事件 id 的合约 | {fmt_count(meta['n_contracts_without_event'])} |",
        "",
        "## Cumulative volume / 累计成交量",
        "",
        "Unit / 单位: USD notional (`volumeNum`, else `volume`) / 美元名义金额，不是论文里的合约张数。",
        "",
        "| | USD notional |",
        "| --- | ---: |",
        f"| min | {fmt_volume(stats['min'])} |",
        f"| median | {fmt_volume(stats['median'])} |",
        f"| mean | {fmt_volume(stats['mean'])} |",
        f"| p90 | {fmt_volume(stats['p90'])} |",
        f"| max | {fmt_volume(stats['max'])} |",
        "",
        "p90 is a linear percentile (NumPy's default).",
        "",
        "p90 为线性分位数（与 NumPy 默认百分位相同）。",
        "",
        "## Screens / 筛选规则",
        "",
        "A row is one binary Polymarket market, which is the contract. "
        "Markets that share an event each stay in the file.",
        "",
        "每一行是一个二元 Polymarket 市场，也就是一张合约。同一事件下的多个市场都保留。",
        "",
        volume_rule,
        life_rule,
        f"3. Opening date (UTC calendar date) is on or before {end}.",
        "",
        volume_rule_zh,
        life_rule_zh,
        f"3. 开盘日（UTC 日历日）不晚于 {end}。",
        "",
        "Opening timestamp, in order: `startDate`, `startDateIso`, the parent event `startDate`, "
        "`createdAt`, the event `createdAt`, the event `creationDate`. "
        "Expiry, in order: `endDate`, `endDateIso`, the event `endDate`, the event `endDateIso`. "
        + (
            "Observed life uses `closedTime` when Gamma has it, otherwise expiry, and both are capped at the end of the sample-end day. `gameStartTime` is not used."
            if meta.get("life_mode") == "observed"
            else "`closedTime` and `gameStartTime` are not used."
        ),
        "",
        "开盘时刻按以下顺序取第一个能解析的字段：`startDate`、`startDateIso`、父事件 `startDate`、"
        "`createdAt`、事件 `createdAt`、事件 `creationDate`。"
        "到期时刻按 `endDate`、`endDateIso`、事件 `endDate`、事件 `endDateIso`。"
        + (
            "观察存续用 Gamma 的 `closedTime`（没有则用到期时刻），并截到样本截止日结束。不用 `gameStartTime`。"
            if meta.get("life_mode") == "observed"
            else "不用 `closedTime`（实际结束时间），也不用 `gameStartTime`（比赛开始时间）。"
        ),
        "",
        "These are not inclusion rules / 以下不是纳入条件:",
        "",
        "- Trailing 7-day average volume / 近 7 日平均成交量",
        "- Days to expiry on a trade date / 某个交易日的剩余到期天数",
        "- YES price inside [0.10, 0.90] / YES 价格落在 [0.10, 0.90]",
        "- One market per event / 每个事件只留一个市场",
        "- Drop the day when fewer than 10 markets pass / 当天不足 10 个市场则整日剔除",
        "",
        "## How to read the CSV / 如何读 CSV",
        "",
        "`paper_sample_markets.csv` is UTF-8, one contract per row, largest lifetime volume first.",
        "",
        "`paper_sample_markets.csv` 为 UTF-8，一行一张合约，按累计成交量从高到低排列。",
        "",
        "| Column | Meaning / 含义 |",
        "| --- | --- |",
        "| `market_id` | Gamma market id / Gamma 市场 id |",
        "| `question` | Contract question / 合约问题 |",
        "| `event_id`, `event_title` | Parent event. `market:<id>` means Gamma did not attach an event / 父事件。`market:<id>` 表示 Gamma 没有挂上事件 |",
        "| `cumulative_volume`, `volume_unit` | Lifetime size. `usd_notional` means USD notional, not a contract count / 累计规模。`usd_notional` 表示美元名义金额，不是张数 |",
        "| `scheduled_life_days` | Expiry minus open, in days / 到期减去开盘，单位为天 |",
        "| `open_date`, `expiry` | UTC timestamps used for the two rules above / 上面两条规则使用的 UTC 时间 |",
        "| `open_date_source`, `expiry_source` | Which Gamma field supplied that timestamp / 该时间来自哪个 Gamma 字段 |",
        "| `closed` | `true` if Gamma reports the market closed / Gamma 标记为已结束时为 `true` |",
        "| `outcomes` | The two outcome labels / 两个结果标签 |",
        "| `yes_token` | CLOB YES token when an outcome is labeled Yes. Empty is still in the sample / 结果名为 Yes 时的 CLOB token。为空仍然留在样本里 |",
        "| `sample_end_date` | Opening-date cutoff for every row / 每一行使用的开盘日截止 |",
        "",
        "Companion file / 配套文件: `paper_sample_meta.json` (funnel, paging, volume stats).",
        "",
        "## Funnel / 过滤过程",
        "",
        "Each fetched market is counted once, at the first rule it fails. "
        "Boundary duplicates created by overlapping volume bands are removed before this count.",
        "",
        "每个抓取到的市场只计一次，记在它第一次失败的规则上。重叠成交量区间造成的边界重复已在计数前去掉。",
        "",
        "| Reason / 原因 | Markets / 市场数 |",
        "| --- | ---: |",
        f"| Fetched unique / 去重后抓取 | {fmt_count(meta['n_fetched_unique'])} |",
        f"| Below volume / 成交量不足 | {fmt_count(funnel.get('below_volume', 0))} |",
        f"| Not binary (not exactly two outcomes) / 不是二元（结果不是恰好两个） | {fmt_count(funnel.get('non_binary', 0))} |",
        f"| Missing opening timestamp / 缺少开盘时间 | {fmt_count(funnel.get('missing_open', 0))} |",
        f"| Missing expiry / 缺少到期时间 | {fmt_count(funnel.get('missing_expiry', 0))} |",
        f"| Scheduled life under the minimum / 预定存续期不足 | {fmt_count(funnel.get('life_below_min', 0))} |",
        f"| Opened after the sample end / 开盘晚于样本截止 | {fmt_count(funnel.get('opened_after_cutoff', 0))} |",
        f"| Selected / 入选 | {fmt_count(funnel.get('selected', 0))} |",
        "",
        "## Paging / 翻页",
        "",
        "Gamma `/markets/keyset` ordered by `volumeNum`, with `volume_num_min` at the paper floor. "
        "Open (`closed=false`) and closed (`closed=true`) markets are both paged. "
        "The volume range is split into inclusive bands so the closed book finishes in parallel. "
        "Band edges overlap and are deduped by `market_id`. "
        "`volume1wk` is not a stop rule.",
        "",
        "使用 Gamma `/markets/keyset`，按 `volumeNum` 排序，并用 `volume_num_min` 设在论文门槛上。"
        "未结束（`closed=false`）和已结束（`closed=true`）都会翻页。"
        "成交量区间被切成闭区间分段并行抓取已结束市场。区间边界会重叠，按 `market_id` 去重。"
        "`volume1wk` 不作为停止条件。",
        "",
        "Rebuild / 重跑:",
        "",
        "```bash",
        "python3 scripts/strategy/hlz_cross_section/build_universe.py --self-test",
        f"python3 scripts/strategy/hlz_cross_section/build_universe.py --end-date {end}",
        "```",
        "",
    ]
    if meta.get("incomplete"):
        lines.extend(
            [
                "This run used `--max-bands` and is an incomplete pull.",
                "",
                "本次使用了 `--max-bands`，抓取不完整。",
                "",
            ]
        )
    return "\n".join(lines)


def build_meta(
    *,
    sample_end: date,
    min_volume: float,
    min_life_days: float,
    rows: list[dict[str, str]],
    reasons: Counter[str],
    coverage: dict[str, Any],
    bands: list[BandResult],
    elapsed_seconds: float,
    max_bands: int,
    output: Path,
    summary: Path,
) -> dict[str, Any]:
    volumes = [float(row["cumulative_volume"]) for row in rows]
    stats = volume_stats(volumes) if volumes else None
    event_ids = {row["event_id"] for row in rows}
    synthetic = sum(1 for row in rows if row["event_id"].startswith("market:"))
    funnel = {key: int(reasons.get(key, 0)) for key in (*FAILURE_ORDER, "selected")}
    for key, count in reasons.items():
        funnel.setdefault(key, int(count))
    return {
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "sample_end_date": sample_end.isoformat(),
        "sample_end_note": (
            "Opening date (UTC calendar date) must fall on or before sample_end_date. "
            "The default is the UTC date of the run. April 28, 2026 is the Hou–Li–Zheng "
            "Kalshi archive cutoff and is left unset unless --end-date passes it."
        ),
        "min_volume": min_volume,
        "min_life_days": min_life_days,
        "volume_definition": (
            "cumulative_volume is Gamma volumeNum when that field is present, otherwise volume. "
            "The paper threshold of 10,000 counts Kalshi contracts. Polymarket volumeNum/volume "
            "is lifetime size and is typically USD notional, not a contract count. "
            "volume_unit in the CSV is usd_notional."
        ),
        "life_definition": (
            "scheduled_life_days = (expiry - opening timestamp) in days of 86400 seconds. "
            "Opening prefers startDate, startDateIso, event.startDate, then createdAt, "
            "event.createdAt, event.creationDate. Expiry prefers endDate, endDateIso, "
            "event.endDate, event.endDateIso. closedTime and gameStartTime are not used."
        ),
        "unit_of_analysis": (
            "One binary market (exactly two outcomes) is one contract, including siblings "
            "in the same event. Open and closed markets are both eligible."
        ),
        "not_inclusion_rules": [
            "trailing 7-day average volume",
            "days to expiry on a trade date",
            "YES price in [0.10, 0.90]",
            "one market per event",
            "cash day when fewer than 10 markets pass",
        ],
        "n_contracts": len(rows),
        "n_events": len(event_ids),
        "n_open_contracts": sum(1 for row in rows if row["closed"] == "false"),
        "n_closed_contracts": sum(1 for row in rows if row["closed"] == "true"),
        "n_contracts_without_event": synthetic,
        "n_fetched_unique": coverage["unique_markets"],
        "funnel": funnel,
        "coverage": coverage,
        "volume_stats": stats,
        "incomplete": max_bands > 0,
        "paging": {
            "endpoint": "/markets/keyset",
            "order": "volumeNum",
            "volume_num_min": min_volume,
            "closed_values": ["false", "true"],
            "bands": len(bands),
            "fetched_rows_including_band_edges": sum(band.rows for band in bands),
            "cached_bands": sum(1 for band in bands if band.cached),
            "elapsed_seconds": round(elapsed_seconds, 1),
            "note": (
                "Offset paging fails above 2000. order=volume_num is rejected; "
                "the JSON field is volumeNum. Bands overlap on the boundary and "
                "market ids are deduped. volume1wk is not a stop rule. "
                "A live check on 2026-11-07 found the archived query parameter ignored, "
                "so closed markets are whatever closed=true returns."
            ),
        },
        "output": repo_path(output),
        "summary": repo_path(summary),
    }


def fill_identifiers(
    rows: list[dict[str, str]],
    sample_end: date,
    min_life_days: float,
    life_mode: str,
    workers: int,
) -> tuple[list[dict[str, str]], int]:
    """Fill conditionId and closedTime from Gamma when the band cache lacks them.

    ``GET /markets?id=`` ignores the filter and returns an empty list. The
    working route is ``GET /markets/{id}``. Responses are cached so a rerun
    does not repeat the lookup.
    """
    needed = [
        row["market_id"]
        for row in rows
        if not row.get("condition_id")
        or (life_mode == "observed" and row.get("closed") == "true" and not row.get("closed_time"))
    ]
    cache_path = DEFAULT_CACHE / "gamma_market_ids.jsonl"
    found: dict[str, dict[str, Any]] = {}
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                found[str(record.get("id") or "")] = record
    needed = [market_id for market_id in needed if market_id not in found]
    if not needed and not found:
        return rows, 0
    # Gamma's published /markets budget is about 300 calls per 10 seconds.
    limiter = RateLimiter(30.0)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    print(f"gamma identifier lookups remaining {len(needed)} cached {len(found)}", flush=True)

    def run(market_id: str) -> tuple[str, dict[str, Any]]:
        url = f"{pm.GAMMA_API}/markets/{urllib.parse.quote(market_id)}"
        last_error: Exception | None = None
        for _attempt in range(4):
            try:
                payload = get_json(url, limiter)
                break
            except RuntimeError as exc:
                if "HTTP 404" in str(exc) or "HTTP 422" in str(exc):
                    return market_id, {"id": market_id, "conditionId": "", "closedTime": None}
                last_error = exc
                time.sleep(5)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(5)
        else:
            raise RuntimeError(f"identifier lookup failed for {market_id}") from last_error
        if not isinstance(payload, dict):
            return market_id, {"id": market_id, "conditionId": "", "closedTime": None}
        return market_id, {
            "id": market_id,
            "conditionId": payload.get("conditionId") or "",
            "closedTime": payload.get("closedTime"),
        }

    done = 0
    with cache_path.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            for start in range(0, len(needed), 2000):
                chunk = needed[start : start + 2000]
                futures = [pool.submit(run, market_id) for market_id in chunk]
                for future in as_completed(futures):
                    market_id, record = future.result()
                    found[market_id] = record
                    with lock:
                        handle.write(json.dumps(record) + "\n")
                        handle.flush()
                    done += 1
                    if done % 500 == 0 or done == len(needed):
                        print(f"identifiers {done}/{len(needed)}", flush=True)
    sample_cap = datetime.combine(sample_end, datetime.max.time(), tzinfo=timezone.utc)
    kept: list[dict[str, str]] = []
    dropped = 0
    for row in rows:
        market = found.get(row["market_id"])
        if market is not None:
            if not row.get("condition_id"):
                row["condition_id"] = str(market.get("conditionId") or "")
            closed_at = parse_dt(market.get("closedTime"))
            if closed_at is not None:
                row["closed_time"] = iso_z(closed_at)
        if life_mode == "observed" and row.get("closed_time"):
            opened = parse_dt(row.get("open_date"))
            closed_at = parse_dt(row.get("closed_time"))
            if opened is not None and closed_at is not None:
                observed_end = min(closed_at, sample_cap)
                observed_days = (observed_end - opened).total_seconds() / 86400.0
                row["observed_life_days"] = f"{observed_days:.6f}"
                if observed_days < min_life_days:
                    dropped += 1
                    continue
        kept.append(row)
    return kept, dropped


def build_universe(args: argparse.Namespace) -> int:
    try:
        sample_end = (
            date.fromisoformat(args.end_date)
            if args.end_date
            else datetime.now(timezone.utc).date()
        )
    except ValueError as exc:
        raise SystemExit(f"--end-date must be YYYY-MM-DD ({exc})") from exc
    if args.min_volume < 0 or args.min_life_days < 0:
        raise SystemExit("volume and life floors must be non-negative")
    started = time.monotonic()
    bands = fetch_gamma_markets(
        min_volume=args.min_volume,
        cache_dir=args.cache_dir,
        workers=args.workers,
        refresh=args.refresh,
        max_bands=args.max_bands,
    )
    audit_bands(bands, min_volume=args.min_volume, max_bands=args.max_bands)
    rows, reasons, coverage = screen_cached(
        bands,
        sample_end=sample_end,
        min_volume=args.min_volume,
        min_life_days=args.min_life_days,
        volume_above=args.volume_above,
        life_mode=args.life_mode,
    )
    if args.fill_identifiers:
        rows, dropped = fill_identifiers(rows, sample_end, args.min_life_days, args.life_mode, args.workers)
        reasons["dropped_after_closed_time"] = dropped
        print(f"identifiers filled, dropped_for_observed_life {dropped}, remaining {len(rows)}", flush=True)
    audit_coverage(coverage, min_volume=args.min_volume, max_bands=args.max_bands)
    print(
        f"funnel { {key: int(reasons.get(key, 0)) for key in (*FAILURE_ORDER, 'selected')} } "
        f"unique={coverage['unique_markets']} "
        f"open_vol={coverage['open_volume_min']}..{coverage['open_volume_max']} "
        f"closed_vol={coverage['closed_volume_min']}..{coverage['closed_volume_max']}",
        flush=True,
    )
    if not rows:
        raise SystemExit("the paper screens selected no contracts")
    meta = build_meta(
        sample_end=sample_end,
        min_volume=args.min_volume,
        min_life_days=args.min_life_days,
        rows=rows,
        reasons=reasons,
        coverage=coverage,
        bands=bands,
        elapsed_seconds=time.monotonic() - started,
        max_bands=args.max_bands,
        output=args.output,
        summary=args.summary,
    )
    write_csv(args.output, rows)
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    summary = render_summary(meta)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(summary, encoding="utf-8")
    stats = meta["volume_stats"]
    print(
        f"sample_end={sample_end.isoformat()} contracts={meta['n_contracts']} "
        f"events={meta['n_events']} open={meta['n_open_contracts']} "
        f"closed={meta['n_closed_contracts']}",
        flush=True,
    )
    print(
        "volume_usd "
        f"min={stats['min']:.2f} median={stats['median']:.2f} "
        f"mean={stats['mean']:.2f} p90={stats['p90']:.2f} max={stats['max']:.2f}",
        flush=True,
    )
    print(f"wrote {args.output}", flush=True)
    print(f"wrote {args.summary}", flush=True)
    return 0


def _market(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "1",
        "question": "Will example happen?",
        "slug": "example",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-11T00:00:00Z",
        "createdAt": "2025-12-01T00:00:00Z",
        "closed": False,
        "volumeNum": 50_000,
        "volume": 50_000,
        "volume1wk": 0,
        "events": [{"id": "10", "title": "Example event"}],
    }
    base.update(overrides)
    return base


def _self_test() -> None:
    sample_end = date(2026, 11, 7)
    kept = screen_market(_market(), sample_end=sample_end, min_volume=10_000, min_life_days=2)
    assert kept.reason == "selected" and kept.row is not None
    assert screen_market(
        _market(volumeNum=2000),
        sample_end=sample_end,
        min_volume=2000,
        min_life_days=2,
        volume_above=True,
    ).reason == "below_volume"
    assert screen_market(
        _market(volumeNum=2000.01),
        sample_end=sample_end,
        min_volume=2000,
        min_life_days=2,
        volume_above=True,
    ).reason == "selected"
    assert screen_market(
        _market(closedTime="2026-01-02T00:00:00Z", endDate="2026-06-01T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
        life_mode="observed",
    ).reason == "life_below_min"
    assert kept.row["yes_token"] == "yes-token"
    assert kept.row["event_id"] == "10"
    assert kept.row["volume_unit"] == "usd_notional"
    assert kept.row["open_date_source"] == "startDate"
    assert float(kept.row["cumulative_volume"]) == 50_000
    # volume1wk is zero. The paper screen uses lifetime volume, so the row stays.
    assert kept.row["scheduled_life_days"] == "10.000000"

    low = screen_market(
        _market(volumeNum=9_999.99),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert low.reason == "below_volume"
    exact = screen_market(
        _market(volumeNum=10_000),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert exact.reason == "selected"

    fallback = screen_market(
        _market(volumeNum=None, volume="20000"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert fallback.reason == "selected"
    assert fallback.row is not None and fallback.row["cumulative_volume"] == "20000.000000"
    prefer_num = screen_market(
        _market(volumeNum=15_000, volume=100),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert prefer_num.row is not None
    assert prefer_num.row["cumulative_volume"] == "15000.000000"

    short = screen_market(
        _market(endDate="2026-01-02T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert short.reason == "life_below_min"
    two_days = screen_market(
        _market(endDate="2026-01-03T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert two_days.reason == "selected"
    assert two_days.row is not None and two_days.row["scheduled_life_days"] == "2.000000"

    # startDate is the open. createdAt is a month earlier and must not lengthen life.
    start_wins = screen_market(
        _market(startDate="2026-01-10T00:00:00Z", createdAt="2025-12-01T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert start_wins.reason == "life_below_min"

    event_start = screen_market(
        _market(
            startDate=None,
            startDateIso=None,
            createdAt="2025-12-01T00:00:00Z",
            events=[{"id": "10", "title": "Example", "startDate": "2026-01-10T00:00:00Z"}],
        ),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert event_start.reason == "life_below_min"
    assert event_start.row is None

    created_fallback = screen_market(
        _market(startDate=None, startDateIso=None, createdAt="2026-01-01T00:00:00Z", events=[]),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert created_fallback.reason == "selected"
    assert created_fallback.row is not None
    assert created_fallback.row["open_date_source"] == "createdAt"
    assert created_fallback.row["event_id"] == "market:1"

    event_end = screen_market(
        _market(endDate=None, endDateIso=None, events=[{"id": "11", "title": "E", "endDate": "2026-01-11T00:00:00Z"}]),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert event_end.reason == "selected"
    assert event_end.row is not None and event_end.row["expiry_source"] == "event.endDate"

    # closedTime would make this look long-lived. Scheduled endDate does not.
    early_close = screen_market(
        _market(
            closed=True,
            endDate="2026-01-02T00:00:00Z",
            closedTime="2026-06-01T00:00:00Z",
        ),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert early_close.reason == "life_below_min"

    closed_ok = screen_market(
        _market(id="253591", closed=True),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert closed_ok.reason == "selected"
    assert closed_ok.row is not None and closed_ok.row["closed"] == "true"

    late_open = screen_market(
        _market(startDate="2026-11-08T00:00:00Z", endDate="2026-11-20T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert late_open.reason == "opened_after_cutoff"
    on_cutoff = screen_market(
        _market(startDate="2026-11-07T23:00:00Z", endDate="2026-11-20T00:00:00Z"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert on_cutoff.reason == "selected"

    date_only = screen_market(
        _market(startDate=None, endDate=None, startDateIso="2026-01-01", endDateIso="2026-01-03"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert date_only.reason == "selected"
    one_calendar = screen_market(
        _market(startDate=None, endDate=None, startDateIso="2026-01-01", endDateIso="2026-01-02"),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert one_calendar.reason == "life_below_min"

    over_under = screen_market(
        _market(outcomes='["Over", "Under"]', clobTokenIds='["a", "b"]'),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert over_under.reason == "selected"
    assert over_under.row is not None and over_under.row["yes_token"] == ""
    three = screen_market(
        _market(outcomes='["A", "B", "C"]'),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert three.reason == "non_binary"

    sibling = screen_market(
        _market(id="2", question="Second contract", events=[{"id": "10", "title": "Example event"}]),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert sibling.reason == "selected" and sibling.row is not None
    assert sibling.row["event_id"] == kept.row["event_id"]
    assert sibling.row["market_id"] != kept.row["market_id"]

    missing_end = screen_market(
        _market(endDate=None, endDateIso=None, events=[{"id": "10", "title": "Example"}]),
        sample_end=sample_end,
        min_volume=10_000,
        min_life_days=2,
    )
    assert missing_end.reason == "missing_expiry"

    stats = volume_stats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert stats["min"] == 1 and stats["max"] == 10
    assert stats["median"] == 5.5 and stats["mean"] == 5.5
    assert abs(stats["p90"] - 9.1) < 1e-9

    bands = volume_bands(10_000)
    assert bands[0] == (10_000.0, 11_000.0)
    assert bands[-1] == (2_000_000.0, None)
    for (left_min, left_max), (right_min, _right_max) in zip(bands, bands[1:]):
        assert left_max == right_min
    assert volume_bands(2_000_000) == [(2_000_000.0, None)]

    calls: list[dict[str, Any]] = []

    def fake_get(params: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(params))
        if params["closed"] == "false" and "after_cursor" not in params:
            page = []
            for index in range(PAGE_LIMIT):
                page.append({"id": str(index), "volumeNum": 50_000 - index, "volume1wk": 0})
            return {"markets": page, "next_cursor": "cursor-2"}
        if params.get("after_cursor") == "cursor-2":
            page = [
                {"id": f"p2-{index}", "volumeNum": 20_000, "volume1wk": 1}
                for index in range(PAGE_LIMIT - 1)
            ]
            page.append({"id": "low-week", "volumeNum": 12_000, "volume1wk": 1})
            return {"markets": page, "next_cursor": "cursor-3"}
        if params.get("after_cursor") == "cursor-3":
            return {"markets": [{"id": "tail", "volumeNum": 11_000, "volume1wk": 0}]}
        if params["closed"] == "true":
            return {"markets": [{"id": "settled", "volumeNum": 80_000, "closed": True}]}
        raise AssertionError(params)

    paged = list(
        iter_keyset_markets(
            fake_get,
            closed=False,
            volume_min=10_000,
            volume_max=11_000,
        )
    )
    assert [row["id"] for row in paged[:1]] == ["0"]
    assert paged[-2]["id"] == "low-week"
    assert paged[-1]["id"] == "tail"
    assert any(call.get("order") == "volumeNum" for call in calls)
    assert all(call.get("order") != "volume1wk" for call in calls)
    assert calls[0]["volume_num_min"] == 10_000
    assert calls[0]["volume_num_max"] == 11_000
    # Page 1 reported volume1wk 0. Paging still continued.
    assert any(call.get("after_cursor") == "cursor-2" for call in calls)
    closed_page = list(
        iter_keyset_markets(fake_get, closed=True, volume_min=10_000, volume_max=None)
    )
    assert closed_page[0]["id"] == "settled"

    parser_args = parse_args([])
    assert parser_args.end_date == ""
    assert parser_args.min_volume == 10_000
    assert parser_args.min_life_days == 2
    help_text = build_parser().format_help()
    assert "2026-04-28" in help_text
    assert "volumeNum" in (__doc__ or "")
    assert "volume1wk" in (__doc__ or "")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "a.jsonl"
        second = root / "b.jsonl"
        first.write_text(json.dumps(slim_market(_market(id="1"))) + "\n", encoding="utf-8")
        second.write_text(
            "\n".join(
                [
                    json.dumps(slim_market(_market(id="1"))),
                    json.dumps(slim_market(_market(id="2", question="Sibling"))),
                    json.dumps(
                        slim_market(
                            _market(
                                id="3",
                                outcomes='["Up", "Down"]',
                                startDate="2026-01-01T00:00:00Z",
                                endDate="2026-01-01T01:00:00Z",
                            )
                        )
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        band_a = BandResult(False, 10_000, 11_000, 1, True, first)
        band_b = BandResult(False, 11_000, 12_000, 3, True, second)
        rows, reasons, coverage = screen_cached(
            [band_a, band_b],
            sample_end=sample_end,
            min_volume=10_000,
            min_life_days=2,
        )
        assert coverage["boundary_duplicates"] == 1
        assert [row["market_id"] for row in rows] == ["1", "2"]
        assert reasons["life_below_min"] == 1
        assert reasons["selected"] == 2
        meta = build_meta(
            sample_end=sample_end,
            min_volume=10_000,
            min_life_days=2,
            rows=rows,
            reasons=reasons,
            coverage=coverage,
            bands=[band_a, band_b],
            elapsed_seconds=1,
            max_bands=0,
            output=root / "out.csv",
            summary=root / "SUMMARY.md",
        )
        text = render_summary(meta)
        assert "合约" in text and "Contracts" in text
        assert "2026-04-28" in text
        assert "usd_notional" in text or "美元" in text
        assert "volume1wk" in text
        write_csv(root / "out.csv", rows)
        written = (root / "out.csv").read_text(encoding="utf-8").splitlines()
        assert written[0].split(",")[0] == "market_id"
        assert len(written) == 3
    print("self-test ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the HLZ Polymarket paper-sample contract universe. "
            "The sample end date defaults to today UTC. "
            "The Kalshi paper cutoff 2026-04-28 is used only when passed as --end-date."
        )
    )
    parser.add_argument(
        "--end-date",
        default="",
        help=(
            "UTC sample end date YYYY-MM-DD. Opening dates after this date are out. "
            "Default: today UTC. The paper's Kalshi archive cutoff was 2026-04-28; "
            "pass that date only when you want that archive cutoff."
        ),
    )
    parser.add_argument("--min-volume", type=float, default=10_000.0)
    parser.add_argument(
        "--volume-above",
        action="store_true",
        help="Exclusive floor. Appendix A.3 keeps volume above the cutoff, not equal to it.",
    )
    parser.add_argument("--life-mode", choices=("scheduled", "observed"), default="scheduled")
    parser.add_argument(
        "--fill-identifiers",
        action="store_true",
        help="Fetch Gamma conditionId and closedTime when the band cache does not have them.",
    )
    parser.add_argument("--min-life-days", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-bands", type=int, default=0, help="Debug cap on volume bands per side. 0 means all.")
    parser.add_argument("--refresh", action="store_true", help="Ignore the Gamma band cache.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--fill-only",
        action="store_true",
        help="Do not page Gamma bands. Fill conditionId and closedTime on the CSV at --output, then rewrite that CSV.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def refill_output(args: argparse.Namespace) -> int:
    """Second pass for a CSV whose band cache had no conditionId or closedTime."""
    if not args.output.exists():
        raise SystemExit(f"missing {args.output}")
    with args.output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sample_end = date.fromisoformat(args.end_date) if args.end_date else date.fromisoformat(rows[0]["sample_end_date"])
    rows, dropped = fill_identifiers(rows, sample_end, args.min_life_days, args.life_mode, args.workers)
    rows.sort(key=lambda row: (-float(row["cumulative_volume"]), row["market_id"]))
    write_csv(args.output, rows)
    meta_path = args.meta
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["min_volume"] = args.min_volume
    meta["min_life_days"] = args.min_life_days
    meta["volume_above"] = bool(args.volume_above)
    meta["life_mode"] = args.life_mode
    meta["sample_end_date"] = sample_end.isoformat()
    meta["n_contracts"] = len(rows)
    meta["n_events"] = len({row["event_id"] for row in rows})
    meta["n_open_contracts"] = sum(1 for row in rows if row["closed"] == "false")
    meta["n_closed_contracts"] = sum(1 for row in rows if row["closed"] == "true")
    meta["n_contracts_without_event"] = sum(1 for row in rows if row["event_id"].startswith("market:"))
    meta["volume_stats"] = volume_stats([float(row["cumulative_volume"]) for row in rows])
    funnel = meta.get("funnel") or {}
    funnel["selected"] = len(rows)
    funnel["dropped_after_closed_time"] = dropped
    meta["funnel"] = funnel
    meta["n_missing_condition_id"] = sum(1 for row in rows if not row.get("condition_id"))
    meta["generated_at"] = iso_z(datetime.now(timezone.utc))
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    args.summary.write_text(render_summary(meta), encoding="utf-8")
    print(
        f"refilled contracts {len(rows)} dropped_for_observed_life {dropped} "
        f"missing_condition {meta['n_missing_condition_id']}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    if args.fill_only:
        return refill_output(args)
    return build_universe(args)


if __name__ == "__main__":
    raise SystemExit(main())
