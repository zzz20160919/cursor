#!/usr/bin/env python3
"""Build the daily Hou–Li–Zheng Polymarket universe (Step 1 only).

Reads the public Gamma market list and CLOB YES price history. Does not
place orders and does not need API keys.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section" / "universe_daily.csv"
DEFAULT_COVERAGE = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section" / "universe_daily_coverage.csv"
DEFAULT_META = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section" / "universe_daily_meta.json"
DEFAULT_CACHE = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section" / "cache"
GAMMA_PAGE_SIZE = 100
VOLUME_WINDOW_DAYS = 7

COLUMNS = (
    "date",
    "market_id",
    "event_id",
    "event_title",
    "question",
    "slug",
    "yes_token",
    "yes_price",
    "volume_7d_avg",
    "volume_7d",
    "volume_asof",
    "expiry",
    "days_to_expiry",
)


@dataclass(frozen=True)
class Candidate:
    market_id: str
    event_id: str
    event_title: str
    question: str
    slug: str
    yes_token: str
    expiry: datetime
    volume_7d: float
    volume_7d_avg: float
    lifetime_volume: float
    volume_asof: date


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if text.endswith("+00"):
        text += ":00"
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


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(url: str, timeout: int = 45) -> Any:
    delay = 1.0
    for attempt in range(5):
        try:
            return pm.http_json(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in {429, 500, 502, 503, 504} and attempt < 4:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry_after) if retry_after and str(retry_after).isdigit() else delay
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            raise
        except urllib.error.URLError:
            if attempt >= 4:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"request failed: {url}")


def gamma_page(params: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{pm.GAMMA_API}/markets?{urllib.parse.urlencode(params)}"
    payload = get_json(url)
    if not isinstance(payload, list):
        raise RuntimeError(f"Gamma /markets did not return a list: {url}")
    return [row for row in payload if isinstance(row, dict)]


def fetch_gamma_markets(min_week_volume: float) -> list[dict[str, Any]]:
    """Page open Gamma markets until trailing-week volume falls through the floor."""
    base = {"closed": "false", "active": "true", "order": "volume1wk", "ascending": "false"}
    found: dict[str, dict[str, Any]] = {}
    for page in range(80):
        batch = gamma_page({"limit": GAMMA_PAGE_SIZE, "offset": page * GAMMA_PAGE_SIZE, **base})
        if not batch:
            break
        stop = False
        kept = 0
        for row in batch:
            week = as_float(row.get("volume1wk"))
            if week is None:
                week = as_float(row.get("volume1wkClob")) or 0.0
            if week < min_week_volume:
                stop = True
                break
            market_id = str(row.get("id") or "")
            if market_id and market_id not in found:
                found[market_id] = row
                kept += 1
        print(f"gamma open page {page}: kept {kept}, running {len(found)}", flush=True)
        if stop or len(batch) < GAMMA_PAGE_SIZE:
            break
    return list(found.values())


def yes_token(market: dict[str, Any]) -> str | None:
    outcomes = [str(item).strip().lower() for item in parse_json_list(market.get("outcomes"))]
    tokens = [str(item) for item in parse_json_list(market.get("clobTokenIds"))]
    if len(outcomes) != 2 or set(outcomes) != {"yes", "no"} or len(tokens) < 2:
        return None
    token = tokens[outcomes.index("yes")]
    return token or None


def event_fields(market: dict[str, Any]) -> tuple[str, str]:
    events = market.get("events")
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except json.JSONDecodeError:
            events = []
    if isinstance(events, list) and events and isinstance(events[0], dict):
        event_id = str(events[0].get("id") or "")
        title = str(events[0].get("title") or "")
        if event_id:
            return event_id, title
    return f"market:{market.get('id')}", ""


def effective_expiry(market: dict[str, Any]) -> datetime | None:
    end = parse_dt(market.get("endDate"))
    closed_time = parse_dt(market.get("closedTime")) if market.get("closed") else None
    times = [moment for moment in (end, closed_time) if moment is not None]
    if not times:
        return None
    return min(times)


def live_volume_asof(market: dict[str, Any]) -> date | None:
    """Date of Gamma's live trailing-week volume. Resolved markets are excluded.

    Closed markets leave `volume24hr` empty and freeze `volume1wk`, so that
    figure is not a trailing week. Open markets publish both.
    """
    if market.get("closed"):
        return None
    if as_float(market.get("volume24hr")) is None and as_float(market.get("volume24hrClob")) is None:
        return None
    updated = parse_dt(market.get("updatedAt"))
    if updated is None:
        return None
    return updated.date()


def candidate_from_market(market: dict[str, Any], min_avg_volume: float) -> Candidate | None:
    if market.get("archived") is True or market.get("enableOrderBook") is False:
        return None
    token = yes_token(market)
    expiry = effective_expiry(market)
    volume_asof = live_volume_asof(market)
    if token is None or expiry is None or volume_asof is None:
        return None
    week = as_float(market.get("volume1wk"))
    if week is None:
        week = as_float(market.get("volume1wkClob"))
    if week is None:
        return None
    average = week / VOLUME_WINDOW_DAYS
    if average < min_avg_volume:
        return None
    event_id, event_title = event_fields(market)
    lifetime = as_float(market.get("volumeNum"))
    if lifetime is None:
        lifetime = as_float(market.get("volume")) or 0.0
    return Candidate(
        market_id=str(market.get("id") or ""),
        event_id=event_id,
        event_title=event_title,
        question=str(market.get("question") or ""),
        slug=str(market.get("slug") or ""),
        yes_token=token,
        expiry=expiry,
        volume_7d=week,
        volume_7d_avg=average,
        lifetime_volume=lifetime,
        volume_asof=volume_asof,
    )


def rank_key(candidate: Candidate) -> tuple[float, float, int]:
    try:
        market_num = int(candidate.market_id)
    except ValueError:
        market_num = 0
    return (candidate.volume_7d_avg, candidate.lifetime_volume, -market_num)


def tradable_in_window(candidate: Candidate, start: date, min_days_to_expiry: int) -> bool:
    """True when the market still has a date in the window at least `min_days_to_expiry` out."""
    return (candidate.expiry.date() - start).days >= min_days_to_expiry


def select_one_per_event(candidates: list[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.event_id)
        if current is None or rank_key(candidate) > rank_key(current):
            best[candidate.event_id] = candidate
    return list(best.values())


def daily_closes(history: list[dict[str, Any]]) -> dict[date, float]:
    latest: dict[date, tuple[int, float]] = {}
    for point in history:
        try:
            stamp = int(point["t"])
            price = float(point["p"])
        except (KeyError, TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(stamp, timezone.utc).date()
        previous = latest.get(day)
        if previous is None or stamp >= previous[0]:
            latest[day] = (stamp, price)
    return {day: price for day, (_, price) in latest.items()}


def prices_on_calendar(
    closes: dict[date, float],
    start: date,
    end: date,
    max_stale_days: int,
) -> dict[date, float]:
    if not closes or max_stale_days < 0:
        return {}
    ordered = sorted(closes)
    out: dict[date, float] = {}
    index = -1
    day = start
    while day <= end:
        while index + 1 < len(ordered) and ordered[index + 1] <= day:
            index += 1
        if index >= 0 and (day - ordered[index]).days <= max_stale_days:
            out[day] = closes[ordered[index]]
        day += timedelta(days=1)
    return out


def build_tables(
    candidates: list[Candidate],
    history_by_token: dict[str, list[dict[str, Any]]],
    start: date,
    end: date,
    min_price: float,
    max_price: float,
    min_days_to_expiry: int,
    min_markets: int,
    max_stale_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_day: dict[date, list[tuple[Candidate, float, int]]] = {}
    for candidate in candidates:
        closes = prices_on_calendar(
            daily_closes(history_by_token.get(candidate.yes_token, [])),
            start,
            end,
            max_stale_days,
        )
        day = start
        while day <= end:
            price = closes.get(day)
            days_left = (candidate.expiry.date() - day).days
            if (
                price is not None
                and min_price <= price <= max_price
                and days_left >= min_days_to_expiry
            ):
                by_day.setdefault(day, []).append((candidate, price, days_left))
            day += timedelta(days=1)

    rows: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    day = start
    while day <= end:
        chosen = by_day.get(day, [])
        included = len(chosen) >= min_markets
        coverage.append(
            {
                "date": day.isoformat(),
                "n_markets": len(chosen),
                "status": "included" if included else "cash",
            }
        )
        if included:
            chosen.sort(key=lambda item: rank_key(item[0]), reverse=True)
            for candidate, price, days_left in chosen:
                rows.append(
                    {
                        "date": day.isoformat(),
                        "market_id": candidate.market_id,
                        "event_id": candidate.event_id,
                        "event_title": candidate.event_title,
                        "question": candidate.question,
                        "slug": candidate.slug,
                        "yes_token": candidate.yes_token,
                        "yes_price": f"{price:.6f}",
                        "volume_7d_avg": f"{candidate.volume_7d_avg:.2f}",
                        "volume_7d": f"{candidate.volume_7d:.2f}",
                        "volume_asof": candidate.volume_asof.isoformat(),
                        "expiry": iso_z(candidate.expiry),
                        "days_to_expiry": days_left,
                    }
                )
        day += timedelta(days=1)
    return rows, coverage


def fetch_price_history(token: str, cache_dir: Path, refresh: bool) -> list[dict[str, Any]]:
    cache_path = cache_dir / "prices" / f"{token}.json"
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        history = cached.get("history") if isinstance(cached, dict) else None
        if isinstance(history, list):
            return history
    params = urllib.parse.urlencode({"market": token, "interval": "max", "fidelity": 1440})
    url = f"{pm.CLOB_HOST}/prices-history?{params}"
    try:
        payload = get_json(url)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in {400, 404}:
            return []
        raise
    if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
        raise RuntimeError(f"unexpected prices-history payload for {token}")
    history = [row for row in payload["history"] if isinstance(row, dict)]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"history": history}), encoding="utf-8")
    return history


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...] | list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_histories(
    candidates: list[Candidate],
    cache_dir: Path,
    refresh: bool,
    workers: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []
    tokens = [candidate.yes_token for candidate in candidates]
    if not tokens:
        return histories, failures
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {
            pool.submit(fetch_price_history, token, cache_dir, refresh): token for token in tokens
        }
        done = 0
        for future in as_completed(futures):
            token = futures[future]
            done += 1
            try:
                histories[token] = future.result()
            except Exception as exc:  # noqa: BLE001 — keep the rest of the cross-section
                failures.append(f"{token}: {exc}")
                print(f"price failed {done}/{len(tokens)} {token}: {exc}", flush=True)
                continue
            if done % 25 == 0 or done == len(tokens):
                print(f"prices {done}/{len(tokens)}", flush=True)
    return histories, failures


def build_universe(args: argparse.Namespace) -> int:
    end = date.fromisoformat(args.end_date) if args.end_date else datetime.now(timezone.utc).date()
    start = end - timedelta(days=args.lookback_days - 1)
    if start > end:
        raise SystemExit("lookback window is empty")
    min_week = args.min_volume_7d_avg * VOLUME_WINDOW_DAYS
    raw_markets = fetch_gamma_markets(min_week)
    parsed = [
        candidate
        for market in raw_markets
        if (candidate := candidate_from_market(market, args.min_volume_7d_avg)) is not None
    ]
    eligible = [
        candidate
        for candidate in parsed
        if tradable_in_window(candidate, start, args.min_days_to_expiry)
    ]
    representatives = select_one_per_event(eligible)
    representatives.sort(key=rank_key, reverse=True)
    if args.max_markets > 0:
        representatives = representatives[: args.max_markets]
    print(
        f"markets gamma={len(raw_markets)} binary={len(parsed)} "
        f"in_window={len(eligible)} events={len(representatives)}",
        flush=True,
    )
    histories, failures = load_histories(
        representatives,
        args.cache_dir,
        args.refresh,
        args.workers,
    )
    rows, coverage = build_tables(
        representatives,
        histories,
        start,
        end,
        args.min_price,
        args.max_price,
        args.min_days_to_expiry,
        args.min_markets,
        args.max_stale_days,
    )
    write_csv(args.output, rows, COLUMNS)
    write_csv(args.coverage, coverage, ("date", "n_markets", "status"))
    included_days = sum(1 for row in coverage if row["status"] == "included")
    meta = {
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "min_volume_7d_avg": args.min_volume_7d_avg,
        "min_days_to_expiry": args.min_days_to_expiry,
        "min_price": args.min_price,
        "max_price": args.max_price,
        "min_markets": args.min_markets,
        "max_stale_days": args.max_stale_days,
        "volume_definition": (
            "volume_7d_avg = Gamma volume1wk / 7 for open markets that still publish "
            "volume24hr. That is one live trailing-week snapshot dated volume_asof, "
            "not a historical daily volume path. The same snapshot screens every date "
            "in the lookback. Daily YES prices come from CLOB prices-history. "
            "Resolved markets are omitted because Gamma freezes volume1wk after close."
        ),
        "n_gamma_markets": len(raw_markets),
        "n_binary": len(parsed),
        "n_in_window": len(eligible),
        "n_events": len(representatives),
        "n_price_failures": len(failures),
        "price_failures": failures,
        "n_included_days": included_days,
        "n_cash_days": len(coverage) - included_days,
        "n_rows": len(rows),
        "output": str(args.output),
        "coverage": str(args.coverage),
    }
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {len(rows)} rows, {included_days} included days, "
        f"{len(coverage) - included_days} cash days -> {args.output}",
        flush=True,
    )
    return 1 if failures else 0


def _self_test() -> None:
    expiry = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
    open_market = {
        "id": "1",
        "question": "Will example happen?",
        "slug": "example",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "endDate": "2026-11-20T00:00:00Z",
        "closed": False,
        "volume1wk": 70000,
        "volume24hr": 1000,
        "volumeNum": 90000,
        "updatedAt": "2026-11-07T00:00:00Z",
        "events": [{"id": "10", "title": "Example event"}],
        "enableOrderBook": True,
    }
    candidate = candidate_from_market(open_market, 10000)
    assert candidate is not None
    assert candidate.yes_token == "yes-token"
    assert candidate.event_id == "10"
    assert candidate.volume_7d_avg == 10000
    assert candidate.volume_asof == date(2026, 11, 7)
    assert tradable_in_window(candidate, date(2026, 11, 1), 3)
    assert not tradable_in_window(candidate, date(2026, 11, 18), 3)
    poor = {**open_market, "id": "4", "volume1wk": 6999}
    assert candidate_from_market(poor, 10000) is None

    stale_closed = {
        **open_market,
        "id": "2",
        "closed": True,
        "closedTime": "2026-06-01T00:00:00Z",
        "updatedAt": "2026-11-01T00:00:00Z",
        "volume24hr": None,
    }
    assert candidate_from_market(stale_closed, 10000) is None

    early_close = {
        **open_market,
        "id": "3",
        "closed": True,
        "endDate": "2026-12-31T00:00:00Z",
        "closedTime": "2026-11-05T00:00:00Z",
        "updatedAt": "2026-11-05T12:00:00Z",
        "volume24hr": None,
        "events": [{"id": "11", "title": "Closed event"}],
    }
    assert candidate_from_market(early_close, 10000) is None

    sibling = Candidate(
        **{**candidate.__dict__, "market_id": "9", "volume_7d_avg": 15000, "volume_7d": 105000}
    )
    assert select_one_per_event([candidate, sibling])[0].market_id == "9"

    day0 = date(2026, 11, 1)
    history = [
        {"t": int(datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()), "p": 0.40},
        {"t": int(datetime(2026, 11, 1, 12, tzinfo=timezone.utc).timestamp()), "p": 0.10},
        {"t": int(datetime(2026, 11, 3, 12, tzinfo=timezone.utc).timestamp()), "p": 0.50},
        {"t": int(datetime(2026, 11, 4, 18, tzinfo=timezone.utc).timestamp()), "p": 0.91},
    ]
    filled = prices_on_calendar(daily_closes(history), day0, date(2026, 11, 5), 1)
    assert filled[date(2026, 11, 1)] == 0.10
    assert filled[date(2026, 11, 2)] == 0.10
    assert date(2026, 11, 5) not in prices_on_calendar(daily_closes(history), day0, date(2026, 11, 5), 0)

    names = [
        Candidate(
            **{
                **candidate.__dict__,
                "market_id": str(100 + i),
                "event_id": str(100 + i),
                "yes_token": f"t{i}",
            }
        )
        for i in range(9)
    ]
    histories = {name.yes_token: history for name in names}
    rows, coverage = build_tables(names, histories, day0, date(2026, 11, 7), 0.10, 0.90, 3, 10, 1)
    assert rows == []
    assert all(row["status"] == "cash" for row in coverage)
    tenth = Candidate(
        **{**candidate.__dict__, "market_id": "200", "event_id": "200", "yes_token": "t9"}
    )
    names.append(tenth)
    histories["t9"] = history
    rows, coverage = build_tables(
        names, histories, date(2026, 10, 20), date(2026, 11, 7), 0.10, 0.90, 3, 10, 1
    )
    included = {row["date"] for row in rows}
    # The volume snapshot is dated Nov 7; October still qualifies on price and expiry.
    assert "2026-10-20" in included
    assert "2026-11-01" in included
    assert "2026-11-02" in included
    assert "2026-11-03" in included
    # 0.91 is outside the band, and Nov 4 is not filled from Nov 3 when the print exists but fails.
    assert "2026-11-04" not in included
    # Nov 5 would be a stale 0.91, still outside the band.
    assert "2026-11-05" not in included
    # Expiry is Nov 20, so days-to-expiry is not the reason Nov 4 dropped.
    assert (expiry.date() - date(2026, 11, 4)).days >= 3
    nov1 = [row for row in rows if row["date"] == "2026-11-01"]
    assert len(nov1) == 10
    assert all(row["yes_price"] == "0.100000" for row in nov1)
    print("self-test ok")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the daily Polymarket HLZ universe table.")
    parser.add_argument("--lookback-days", type=int, default=183)
    parser.add_argument("--end-date", default="", help="UTC end date YYYY-MM-DD. Default: today.")
    parser.add_argument("--min-volume-7d-avg", type=float, default=10_000.0)
    parser.add_argument("--min-days-to-expiry", type=int, default=3)
    parser.add_argument("--min-price", type=float, default=0.10)
    parser.add_argument("--max-price", type=float, default=0.90)
    parser.add_argument("--min-markets", type=int, default=10)
    parser.add_argument("--max-stale-days", type=int, default=1)
    parser.add_argument("--max-markets", type=int, default=0, help="Cap event representatives. 0 means all.")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--refresh", action="store_true", help="Ignore the CLOB price cache.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    return build_universe(args)


if __name__ == "__main__":
    raise SystemExit(main())
