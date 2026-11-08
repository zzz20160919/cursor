#!/usr/bin/env python3
"""HLZ Step 2: YESMV, log odds ratio, and category portfolios.

The definitions follow Hou, Li, and Zheng. Formation is 4:00 p.m. Eastern,
daylight-saving aware. Lookbacks use prices at or before that timestamp.

Eq. (1)  YESMV_{i,t} = P^form_{i,t} * OI_{i,t}
Eq. (2)  R^{pp}_{i,t+1} = P^end_{i,t+1} - P^form_{i,t}
Eq. (5)  LOR_{i,t}(h) = logit(P^form_{i,t}) - logit(P^form_{i,t-h})
         logit(p) = log[p / (1-p)], h = 1..6

Polymarket does not publish the paper's hourly open-interest path. See
STEP2_SUMMARY.md for the substitute and what it changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


EASTERN = ZoneInfo("America/New_York")
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section"
DEFAULT_UNIVERSE = OUTPUT_DIR / "paper_sample_markets.csv"
DEFAULT_FACTORS = OUTPUT_DIR / "factor_daily.csv"
DEFAULT_SPREADS = OUTPUT_DIR / "portfolio_spreads.csv"
DEFAULT_DAILY = OUTPUT_DIR / "portfolio_spreads_daily.csv"
DEFAULT_META = OUTPUT_DIR / "step2_meta.json"
DEFAULT_SUMMARY = OUTPUT_DIR / "STEP2_SUMMARY.md"
DEFAULT_CACHE = OUTPUT_DIR / "cache" / "step2"
PRICE_CHUNK_SECONDS = 12 * 86400
PRICE_FRESH_HOURS = 2.0
TRADE_LOOKBACK_DAYS = 7
LOR_HORIZONS = (1, 2, 3, 4, 5, 6)
NW_LAGS = 7
REQUESTS_PER_SECOND = 12.0

# Coarse Gamma tag slugs, in the order used when a market carries several.
# This is not Kalshi's official category list. It is the closest public
# Polymarket taxonomy that still leaves more than one contract in a cell.
BROAD_TAGS = (
    "sports",
    "politics",
    "elections",
    "crypto",
    "cryptocurrency",
    "business",
    "finance",
    "economics",
    "science",
    "tech",
    "technology",
    "pop-culture",
    "culture",
    "entertainment",
    "world",
    "geopolitics",
    "weather",
    "climate",
)

FACTOR_COLUMNS = (
    "date",
    "market_id",
    "question",
    "event_id",
    "event_title",
    "category",
    "category_source",
    "yes_token",
    "condition_id",
    "p_form",
    "p_form_obs",
    "p_form_age_hours",
    "price_fresh",
    "traded_prior_7d",
    "oi_usdc",
    "oi_shares",
    "oi_timing",
    "yesmv",
    "lor_1",
    "lor_2",
    "lor_3",
    "lor_4",
    "lor_5",
    "lor_6",
    "p_end",
    "p_end_source",
    "p_end_age_hours",
    "r_pp",
    "in_portfolio_sample",
)

SPREAD_COLUMNS = (
    "characteristic",
    "n_dates",
    "mean_low_cents",
    "mean_middle_cents",
    "mean_high_cents",
    "mean_high_minus_low_cents",
    "newey_west_lags",
    "t_newey_west",
    "mean_categories",
    "mean_contracts",
)

DAILY_COLUMNS = (
    "date",
    "characteristic",
    "n_categories",
    "n_contracts",
    "low_cents",
    "middle_cents",
    "high_cents",
    "high_minus_low_cents",
)

CHARACTERISTICS = ("yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6")


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
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def formation_time(day: date) -> datetime:
    """4:00 p.m. Eastern on ``day``, including daylight saving time."""
    return datetime(day.year, day.month, day.day, 16, 0, tzinfo=EASTERN)


def formation_epoch(day: date) -> int:
    return int(formation_time(day).timestamp())


def eastern_date(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, tz=EASTERN).date()


def logit(price: float) -> float | None:
    """logit(p) = log[p / (1-p)]. Undefined at 0 and 1."""
    if price <= 0.0 or price >= 1.0:
        return None
    return math.log(price / (1.0 - price))


def percentile(sorted_values: list[float], probability: float) -> float:
    """Linear percentile (NumPy default, Hyndman-Fan type 7)."""
    if not sorted_values:
        raise ValueError("empty")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * probability
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def winsorize(values: list[float], low_p: float = 0.01, high_p: float = 0.99) -> list[float]:
    """Winsorize at the 1st and 99th percentiles of this cross-section."""
    ordered = sorted(values)
    floor = percentile(ordered, low_p)
    cap = percentile(ordered, high_p)
    if cap < floor:
        floor, cap = cap, floor
    return [min(max(value, floor), cap) for value in values]


def last_at_or_before(history: list[tuple[int, float]], epoch: int) -> tuple[float, int] | None:
    """Most recent observation with timestamp <= epoch. History is sorted."""
    if not history:
        return None
    lo = 0
    hi = len(history)
    while lo < hi:
        mid = (lo + hi) // 2
        if history[mid][0] <= epoch:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    obs_epoch, price = history[lo - 1]
    return price, obs_epoch


def normalize_history(points: Iterable[tuple[int, float]]) -> list[tuple[int, float]]:
    latest: dict[int, float] = {}
    for epoch, price in points:
        latest[int(epoch)] = float(price)
    return sorted(latest.items())


def price_at_formation(
    history: list[tuple[int, float]],
    day: date,
) -> tuple[float | None, int | None, float | None]:
    """Return price, observation epoch, and age in hours at 4:00 p.m. Eastern."""
    found = last_at_or_before(history, formation_epoch(day))
    if found is None:
        return None, None, None
    price, obs_epoch = found
    age_hours = (formation_epoch(day) - obs_epoch) / 3600.0
    return price, obs_epoch, age_hours


def traded_on_day(history: list[tuple[int, float]], day: date) -> bool:
    """True when the price history has any point whose Eastern date is ``day``.

    CLOB ``prices-history`` does not label trades versus carried prints. A
    point on that Eastern date is the available proxy for "traded that day".
    """
    for epoch, _price in history:
        if eastern_date(epoch) == day:
            return True
        if eastern_date(epoch) > day:
            break
    return False


def traded_preceding_week(history: list[tuple[int, float]], day: date) -> bool:
    """Paper: traded on at least one of the preceding seven calendar days."""
    for lag in range(1, TRADE_LOOKBACK_DAYS + 1):
        if traded_on_day(history, day - timedelta(days=lag)):
            return True
    return False


def lor_value(price_now: float | None, price_then: float | None) -> float | None:
    if price_now is None or price_then is None:
        return None
    now = logit(price_now)
    then = logit(price_then)
    if now is None or then is None:
        return None
    return now - then


def yes_share_proxy(oi_usdc: float | None, yes_price: float | None) -> float | None:
    """Map priced-gross USDC open interest into a share count.

    Data API v2 defines value as
    sum_outcomes ((shares - fee_receiver_shares) / 1e6 * outcome_price).
    When the YES and NO prices sum to one, that sum equals the outstanding
    complete-set count. We do not observe a historical NO price, so the
    complementary price 1 - P^form is the assumption that makes
    oi_shares = oi_usdc. YESMV is then P^form * oi_shares, not the price alone.
    """
    if oi_usdc is None or oi_usdc <= 0 or yes_price is None:
        return None
    if yes_price <= 0 or yes_price >= 1:
        return None
    complement = 1.0 - yes_price
    price_sum = yes_price + complement
    if price_sum <= 0:
        return None
    return oi_usdc / price_sum


def choose_category(tags: list[dict[str, Any]]) -> tuple[str, str]:
    """One category per contract from Gamma tags.

    A broad slug in ``BROAD_TAGS`` wins over a narrower tag. Markets with
    only narrow tags keep the first tag, so they are not dropped.
    """
    cleaned = [tag for tag in tags if isinstance(tag, dict) and tag.get("slug")]
    by_slug = {str(tag["slug"]): str(tag.get("label") or tag["slug"]) for tag in cleaned}
    for slug in BROAD_TAGS:
        if slug in by_slug:
            return by_slug[slug], f"tag:{slug}"
    if cleaned:
        slug = str(cleaned[0]["slug"])
        return str(cleaned[0].get("label") or slug), f"tag:{slug}"
    return "untagged", "none"


def assign_legs(values: list[float]) -> list[str]:
    """Winsorize, then Low / Middle / High at the 30th and 70th percentiles."""
    if not values:
        return []
    clipped = winsorize(values)
    ordered = sorted(clipped)
    p30 = percentile(ordered, 0.30)
    p70 = percentile(ordered, 0.70)
    legs: list[str] = []
    for value in clipped:
        if value <= p30:
            legs.append("low")
        elif value >= p70:
            legs.append("high")
        else:
            legs.append("middle")
    return legs


def oi_weighted_mean(rows: list[dict[str, float]]) -> float | None:
    weight = sum(row["oi"] for row in rows)
    if weight <= 0:
        return None
    return sum(row["oi"] * row["r"] for row in rows) / weight


def category_portfolios(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Eqs. (3) and (4) for one formation date and one characteristic.

    ``rows`` already have a numeric ``x`` (the characteristic), ``oi``, ``r``,
    and ``category``. Membership uses the winsorized characteristic. Weights
    use raw open interest, not the characteristic.
    """
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    leg_returns: dict[str, list[tuple[float, float]]] = {"low": [], "middle": [], "high": []}
    n_contracts = 0
    for category, members in by_category.items():
        if len(members) < 3:
            continue
        legs = assign_legs([float(member["x"]) for member in members])
        grouped: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
        for member, leg in zip(members, legs):
            grouped[leg].append(member)
        if not grouped["low"] or not grouped["middle"] or not grouped["high"]:
            continue
        presort = sum(float(member["oi"]) for member in members)
        if presort <= 0:
            continue
        ready = True
        returns: dict[str, float] = {}
        for leg, bucket in grouped.items():
            mean = oi_weighted_mean(
                [{"oi": float(item["oi"]), "r": float(item["r"])} for item in bucket]
            )
            if mean is None:
                ready = False
                break
            returns[leg] = mean
        if not ready:
            continue
        n_contracts += len(members)
        for leg in ("low", "middle", "high"):
            leg_returns[leg].append((presort, returns[leg]))
    if not leg_returns["low"]:
        return None

    def aggregate(pairs: list[tuple[float, float]]) -> float:
        weight = sum(item[0] for item in pairs)
        return sum(item[0] * item[1] for item in pairs) / weight

    low = aggregate(leg_returns["low"])
    middle = aggregate(leg_returns["middle"])
    high = aggregate(leg_returns["high"])
    return {
        "n_categories": len(leg_returns["low"]),
        "n_contracts": n_contracts,
        "low": low,
        "middle": middle,
        "high": high,
        "high_minus_low": high - low,
    }


def newey_west_t(values: list[float], lags: int = NW_LAGS) -> float | None:
    """t-statistic for the mean, Bartlett kernel, ``lags`` Newey-West lags."""
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    errors = [value - mean for value in values]

    def gamma(lag: int) -> float:
        return sum(errors[index] * errors[index - lag] for index in range(lag, count)) / count

    variance = gamma(0)
    usable = min(lags, count - 1)
    for lag in range(1, usable + 1):
        variance += 2.0 * (1.0 - lag / (usable + 1)) * gamma(lag)
    variance /= count
    if variance <= 0:
        return None
    return mean / math.sqrt(variance)


def summarize_spreads(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily:
        grouped[row["characteristic"]].append(row)
    summary: list[dict[str, Any]] = []
    for characteristic in CHARACTERISTICS:
        rows = grouped.get(characteristic, [])
        if not rows:
            continue
        count = len(rows)

        def avg(key: str) -> float:
            return sum(float(row[key]) for row in rows) / count

        spreads = [float(row["high_minus_low"]) for row in rows]
        t_stat = newey_west_t(spreads, NW_LAGS)
        summary.append(
            {
                "characteristic": characteristic,
                "n_dates": count,
                "mean_low_cents": avg("low") * 100.0,
                "mean_middle_cents": avg("middle") * 100.0,
                "mean_high_cents": avg("high") * 100.0,
                "mean_high_minus_low_cents": avg("high_minus_low") * 100.0,
                "newey_west_lags": NW_LAGS if count >= 2 else "",
                "t_newey_west": "" if t_stat is None else f"{t_stat:.4f}",
                "mean_categories": avg("n_categories"),
                "mean_contracts": avg("n_contracts"),
            }
        )
    return summary


def build_daily_portfolios(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One High/Middle/Low record per date and characteristic."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in panel:
        if row.get("in_portfolio_sample") != "true":
            continue
        by_date[row["date"]].append(row)
    daily: list[dict[str, Any]] = []
    for day in sorted(by_date):
        members = by_date[day]
        for characteristic in CHARACTERISTICS:
            usable = []
            for row in members:
                value = as_float(row.get(characteristic))
                oi = as_float(row.get("oi_shares"))
                payoff = as_float(row.get("r_pp"))
                if value is None or oi is None or oi <= 0 or payoff is None:
                    continue
                usable.append(
                    {
                        "category": row["category"],
                        "x": value,
                        "oi": oi,
                        "r": payoff,
                    }
                )
            result = category_portfolios(usable)
            if result is None:
                continue
            daily.append(
                {
                    "date": day,
                    "characteristic": characteristic,
                    "n_categories": result["n_categories"],
                    "n_contracts": result["n_contracts"],
                    "low": result["low"],
                    "middle": result["middle"],
                    "high": result["high"],
                    "high_minus_low": result["high_minus_low"],
                    "low_cents": result["low"] * 100.0,
                    "middle_cents": result["middle"] * 100.0,
                    "high_cents": result["high"] * 100.0,
                    "high_minus_low_cents": result["high_minus_low"] * 100.0,
                }
            )
    return daily


def latest_closed_formation(start: date, end: date, now_epoch: int) -> date | None:
    """Latest formation date whose next 4:00 p.m. Eastern mark is already observable."""
    day = end
    while day >= start:
        if formation_epoch(day + timedelta(days=1)) <= now_epoch:
            return day
        day -= timedelta(days=1)
    return None


def iter_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def price_chunks(start_epoch: int, end_epoch: int) -> list[tuple[int, int]]:
    if end_epoch <= start_epoch:
        return []
    chunks: list[tuple[int, int]] = []
    cursor = start_epoch
    while cursor < end_epoch:
        nxt = min(cursor + PRICE_CHUNK_SECONDS, end_epoch)
        chunks.append((cursor, nxt))
        cursor = nxt
    return chunks


def fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def get_json(url: str, limiter: RateLimiter, timeout: int = 45) -> Any:
    delay = 1.0
    last: Exception | None = None
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
            code = exc.code
            exc.close()
            last = RuntimeError(f"HTTP {code} for {url}: {detail}")
            if code in {400, 404} and "too long" not in detail:
                raise last
            if code in {429, 500, 502, 503, 504} and attempt < 4:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry_after) if retry_after and str(retry_after).isdigit() else delay
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            raise last from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt >= 4:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"request failed: {url}") from last


def load_universe(path: Path, start: date, end: date, closed_mode: str) -> list[dict[str, str]]:
    """Step 1 contracts with a YES token whose life overlaps the window."""
    window_start = formation_time(start)
    window_end = formation_time(end)
    selected: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            token = (row.get("yes_token") or "").strip()
            if not token:
                continue
            closed = (row.get("closed") or "").strip().lower()
            if closed_mode == "open" and closed != "false":
                continue
            if closed_mode == "closed" and closed != "true":
                continue
            opened = parse_dt(row.get("open_date"))
            expiry = parse_dt(row.get("expiry"))
            if opened is None or expiry is None:
                continue
            if opened > window_end or expiry < window_start:
                continue
            selected.append(row)
    return selected


def slim_gamma(market: dict[str, Any]) -> dict[str, Any]:
    tags = []
    for tag in market.get("tags") or []:
        if isinstance(tag, dict) and tag.get("slug"):
            tags.append({"slug": tag.get("slug"), "label": tag.get("label")})
    return {
        "id": str(market.get("id") or ""),
        "conditionId": market.get("conditionId") or "",
        "closed": market.get("closed"),
        "closedTime": market.get("closedTime"),
        "outcomes": market.get("outcomes"),
        "outcomePrices": market.get("outcomePrices"),
        "tags": tags,
    }


def fetch_gamma_batch(market_ids: list[str], limiter: RateLimiter) -> list[dict[str, Any]]:
    params: list[tuple[str, str]] = [("id", market_id) for market_id in market_ids]
    params.append(("include_tag", "true"))
    url = f"{pm.GAMMA_API}/markets?{urllib.parse.urlencode(params)}"
    payload = get_json(url, limiter)
    if not isinstance(payload, list):
        raise RuntimeError("Gamma /markets did not return a list")
    return [slim_gamma(row) for row in payload if isinstance(row, dict)]


def fetch_gamma(market_ids: list[str], cache_dir: Path, limiter: RateLimiter, workers: int) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for market_id in market_ids:
        path = cache_dir / "gamma" / f"{market_id}.json"
        if path.exists():
            found[market_id] = json.loads(path.read_text(encoding="utf-8"))
        else:
            missing.append(market_id)
    batches = [missing[index : index + 20] for index in range(0, len(missing), 20)]
    print(f"gamma cache {len(found)} fetch_batches {len(batches)}", flush=True)

    def run(batch: list[str]) -> list[dict[str, Any]]:
        return fetch_gamma_batch(batch, limiter)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(run, batch): batch for batch in batches}
        done = 0
        for future in as_completed(futures):
            rows = future.result()
            for row in rows:
                market_id = row["id"]
                if not market_id:
                    continue
                path = cache_dir / "gamma" / f"{market_id}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(row), encoding="utf-8")
                found[market_id] = row
            done += 1
            if done % 25 == 0 or done == len(batches):
                print(f"gamma batches {done}/{len(batches)}", flush=True)
    return found


def fetch_oi(condition_ids: list[str], limiter: RateLimiter, workers: int) -> dict[str, float]:
    unique = [item for item in dict.fromkeys(condition_ids) if item]
    batches = [unique[index : index + 20] for index in range(0, len(unique), 20)]
    found: dict[str, float] = {}

    def run(batch: list[str]) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"condition": ",".join(batch)})
        url = f"{pm.DATA_API}/v2/oi?{query}"
        payload = get_json(url, limiter)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("Data API /v2/oi did not return data")
        return [row for row in rows if isinstance(row, dict)]

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = [pool.submit(run, batch) for batch in batches]
        done = 0
        for future in as_completed(futures):
            for row in future.result():
                condition = str(row.get("condition_id") or "")
                value = as_float(row.get("value"))
                if condition and value is not None:
                    found[condition.lower()] = value
            done += 1
            if done % 25 == 0 or done == len(batches):
                print(f"oi batches {done}/{len(batches)}", flush=True)
    return found


def fetch_price_range(token: str, start_epoch: int, end_epoch: int, limiter: RateLimiter) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for chunk_start, chunk_end in price_chunks(start_epoch, end_epoch):
        params = {
            "market": token,
            "startTs": chunk_start,
            "endTs": chunk_end,
            "fidelity": 60,
        }
        url = f"{pm.CLOB_HOST}/prices-history?{urllib.parse.urlencode(params)}"
        try:
            payload = get_json(url, limiter)
        except RuntimeError as exc:
            text = str(exc)
            if "HTTP 400" in text or "HTTP 404" in text:
                continue
            raise
        history = payload.get("history") if isinstance(payload, dict) else None
        if not isinstance(history, list):
            continue
        for point in history:
            if not isinstance(point, dict):
                continue
            epoch = as_float(point.get("t"))
            price = as_float(point.get("p"))
            if epoch is None or price is None:
                continue
            points.append((int(epoch), price))
    return normalize_history(points)


def load_prices(
    tokens: list[str],
    start_epoch: int,
    end_epoch: int,
    cache_dir: Path,
    limiter: RateLimiter,
    workers: int,
    refresh: bool,
) -> dict[str, list[tuple[int, float]]]:
    found: dict[str, list[tuple[int, float]]] = {}
    missing: list[str] = []
    for token in tokens:
        path = cache_dir / "prices" / f"{token}.json"
        if path.exists() and not refresh:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and int(cached.get("start", 0)) <= start_epoch
                and int(cached.get("end", 0)) >= end_epoch
                and isinstance(cached.get("history"), list)
            ):
                found[token] = normalize_history(
                    (int(item[0]), float(item[1])) for item in cached["history"] if len(item) == 2
                )
                continue
        missing.append(token)
    print(f"prices cache {len(found)} fetch {len(missing)}", flush=True)

    def run(token: str) -> tuple[str, list[tuple[int, float]]]:
        history = fetch_price_range(token, start_epoch, end_epoch, limiter)
        path = cache_dir / "prices" / f"{token}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"start": start_epoch, "end": end_epoch, "history": history}),
            encoding="utf-8",
        )
        return token, history

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(run, token): token for token in missing}
        done = 0
        for future in as_completed(futures):
            token = futures[future]
            done += 1
            try:
                key, history = future.result()
                found[key] = history
            except Exception as exc:  # noqa: BLE001 — keep going, then fail the pull if any remain
                failures.append(f"{token}: {exc}")
            if done % 200 == 0 or done == len(missing):
                print(f"prices {done}/{len(missing)} failures {len(failures)}", flush=True)
    if failures:
        preview = "; ".join(failures[:3])
        raise SystemExit(f"{len(failures)} price histories failed. {preview}")
    return found


def yes_settlement(meta: dict[str, Any]) -> tuple[float | None, int | None]:
    if meta.get("closed") is not True and str(meta.get("closed")).lower() != "true":
        return None, None
    closed_at = parse_dt(meta.get("closedTime"))
    if closed_at is None:
        return None, None
    outcomes = [str(item).strip().lower() for item in parse_json_list(meta.get("outcomes"))]
    prices = parse_json_list(meta.get("outcomePrices"))
    if "yes" not in outcomes:
        return None, None
    index = outcomes.index("yes")
    if index >= len(prices):
        return None, None
    value = as_float(prices[index])
    if value is None or not (value <= 0.001 or value >= 0.999):
        return None, None
    settled = 1.0 if value >= 0.999 else 0.0
    return settled, int(closed_at.timestamp())


def contract_panel_rows(
    contract: dict[str, str],
    meta: dict[str, Any] | None,
    history: list[tuple[int, float]],
    oi_usdc: float | None,
    oi_anchor: date | None,
    days: list[date],
) -> list[dict[str, str]]:
    tags = meta.get("tags") if isinstance(meta, dict) else None
    category, category_source = choose_category(tags if isinstance(tags, list) else [])
    condition = str((meta or {}).get("conditionId") or "")
    settlement_value, settlement_epoch = yes_settlement(meta or {})
    opened = parse_dt(contract.get("open_date"))
    expiry = parse_dt(contract.get("expiry"))
    # Formation prices for LOR lags and for the next-day endpoint sit outside ``days``.
    needed = set(days)
    for day in list(days):
        for lag in LOR_HORIZONS:
            needed.add(day - timedelta(days=lag))
        needed.add(day + timedelta(days=1))
    formed: dict[date, tuple[float | None, int | None, float | None]] = {
        day: price_at_formation(history, day) for day in needed
    }
    rows: list[dict[str, str]] = []
    for day in days:
        form_ts = formation_time(day)
        if opened is None or expiry is None or opened > form_ts or expiry < form_ts:
            continue
        price, obs_epoch, age = formed[day]
        fresh = age is not None and age <= PRICE_FRESH_HOURS
        traded = traded_preceding_week(history, day)
        use_oi = oi_anchor is not None and day == oi_anchor and oi_usdc is not None and oi_usdc > 0
        shares = yes_share_proxy(oi_usdc if use_oi else None, price)
        yesmv = price * shares if price is not None and shares is not None else None
        lors = {
            horizon: lor_value(price, formed[day - timedelta(days=horizon)][0])
            for horizon in LOR_HORIZONS
        }
        end_price: float | None = None
        end_source = ""
        end_age: float | None = None
        next_epoch = formation_epoch(day + timedelta(days=1))
        if settlement_epoch is not None and settlement_value is not None and settlement_epoch <= next_epoch:
            end_price = settlement_value
            end_source = "settlement"
            end_age = 0.0
        else:
            next_price, next_obs, next_age = formed[day + timedelta(days=1)]
            if next_price is not None and next_age is not None and next_age <= PRICE_FRESH_HOURS:
                end_price = next_price
                end_source = "next_formation"
                end_age = next_age
            elif next_price is not None:
                end_source = "stale"
                end_age = next_age
        r_pp = end_price - price if end_price is not None and price is not None else None
        in_sample = (
            fresh
            and traded
            and shares is not None
            and shares > 0
            and r_pp is not None
            and price is not None
        )
        rows.append(
            {
                "date": day.isoformat(),
                "market_id": contract["market_id"],
                "question": contract.get("question") or "",
                "event_id": contract.get("event_id") or "",
                "event_title": contract.get("event_title") or "",
                "category": category,
                "category_source": category_source,
                "yes_token": contract.get("yes_token") or "",
                "condition_id": condition,
                "p_form": fmt(price),
                "p_form_obs": "" if obs_epoch is None else iso_z(datetime.fromtimestamp(obs_epoch, tz=timezone.utc)),
                "p_form_age_hours": fmt(age, 4),
                "price_fresh": "true" if fresh else "false",
                "traded_prior_7d": "true" if traded else "false",
                "oi_usdc": fmt(oi_usdc if use_oi else None, 4),
                "oi_shares": fmt(shares, 4),
                "oi_timing": "snapshot_after_formation_single_date" if use_oi else "",
                "yesmv": fmt(yesmv, 4),
                "lor_1": fmt(lors[1]),
                "lor_2": fmt(lors[2]),
                "lor_3": fmt(lors[3]),
                "lor_4": fmt(lors[4]),
                "lor_5": fmt(lors[5]),
                "lor_6": fmt(lors[6]),
                "p_end": fmt(end_price),
                "p_end_source": end_source,
                "p_end_age_hours": fmt(end_age, 4),
                "r_pp": fmt(r_pp),
                "in_portfolio_sample": "true" if in_sample else "false",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def render_summary(meta: dict[str, Any]) -> str:
    spreads = {row["characteristic"]: row for row in meta["spreads"]}
    yes = spreads.get("yesmv")
    lor = spreads.get("lor_1")

    def spread_line(row: dict[str, Any] | None) -> str:
        if row is None:
            return "not formed"
        t_stat = row["t_newey_west"] or "n/a (fewer than two dates)"
        return (
            f"{float(row['mean_high_minus_low_cents']):.4f} cents "
            f"over {row['n_dates']} date(s), Newey-West t = {t_stat}"
        )

    lines = [
        "# HLZ Step 2 / YESMV and log odds ratio",
        "",
        f"Window / 窗口: **{meta['start_date']}** through **{meta['end_date']}** (formation dates, 4:00 p.m. Eastern).",
        f"OI anchor date / 使用公开 OI 快照的形成日: **{meta['oi_anchor_date'] or 'none'}**.",
        f"OI snapshot taken / 快照时间: {meta['oi_observed_at']}.",
        f"Hours from that formation to the snapshot / 形成时点到快照的小时数: {meta['oi_lag_hours']}.",
        "",
        "## Paper definitions / 论文定义",
        "",
        "Formation, from the paper:",
        "",
        "> We set a common formation time of 4:00 p.m. Eastern Time and account for daylight saving time. "
        "The formation price is the most recent valid hourly observation at or before that time. "
        "We use its closing transaction price when available and the midpoint of a valid two-sided quote otherwise. "
        "All lookbacks end at the formation time, so no post-formation observation enters a characteristic.",
        "",
        "Portfolio sample, from the paper:",
        "",
        "> The portfolio sample imposes two further requirements. The price source must be no more than two hours old, "
        "and the contract must have traded on at least one day during the preceding seven calendar days. "
        "These restrictions limit measurement error from stale prices and prolonged nontrading. "
        "Open interest is the latest observation available at or before formation and is never filled backward from future data. "
        "The two-hour limit applies only to execution prices, not to this stock variable.",
        "",
        "Equations:",
        "",
        "> (1) YESMV_{i,t} = P^form_{i,t} × OI_{i,t}",
        "",
        "> (2) R^{pp}_{i,t+1} = P^end_{i,t+1} − P^form_{i,t}",
        "",
        "> For each contract-day, the holding period ends at settlement or at 4:00 p.m. on the following Eastern calendar day, whichever occurs first.",
        "",
        "> (5) LOR_{i,t}(h) = logit(P^form_{i,t}) − logit(P^form_{i,t−h}), logit(p) = log[p/(1−p)], h = 1,...,6",
        "",
        "> We winsorize each continuous characteristic at the first and 99th percentiles of its formation-date–category cross-section "
        "and assign contracts to Low, Middle, and High portfolios using the 30th and 70th percentiles.",
        "",
        "Within a category, contract price changes are weighted by formation-time raw open interest (Eq. 3). "
        "Category portfolios are aggregated with the matched category set and presort category open interest (Eq. 4). "
        "High−Low is reported in cents per YES claim. Newey–West uses seven lags when at least two dates exist.",
        "",
        "## Polymarket mapping / 映射",
        "",
        "Universe: Step 1 `paper_sample_markets.csv` (cumulative volume ≥ 10,000 USD notional, scheduled life ≥ 2 days, "
        f"opening date on or before the Step 1 sample end). This run keeps YES-token contracts with `closed_mode={meta['closed_mode']}`. "
        f"Markets in the run: {meta['n_markets']}. The paper's Polymarket appendix uses cumulative volume above 2,000 and a chain-reconstructed open-interest path. "
        "This Step 2 file does not replace the Step 1 screen with that 2,000 cutoff.",
        "",
        "Formation price: CLOB `GET /prices-history` for the YES token, `fidelity=60` (about one point per hour). "
        "P^form is the latest point at or before 4:00 p.m. America/New_York. "
        "The feed has a single price, not a separate closing trade and a two-sided quote, so there is no trade-then-midpoint fallback. "
        "The portfolio sample keeps a price only when that point is at most two hours old.",
        "",
        "Traded in the preceding seven Eastern calendar dates: at least one `prices-history` point falls on one of those dates. "
        "The feed does not flag a print as a trade, so a carried hourly price can satisfy the screen. That is wider than the paper's transaction test.",
        "",
        "Endpoint: recorded YES settlement if Gamma `closedTime` is at or before the next 4:00 p.m. Eastern and the YES outcome price is 0 or 1. "
        "Otherwise the next calendar day's 4:00 p.m. price, under the same two-hour rule.",
        "",
        "Category: one Gamma tag per contract. A slug in a fixed broad list (sports, politics, crypto, business, and the rest in the script) wins when several tags are present. "
        "Otherwise the first tag is the category. This is not Kalshi's official category field.",
        "",
        "### Open interest / 未平仓量",
        "",
        "The paper's Polymarket appendix says open interest at 4:00 p.m. Eastern is reconstructed from Polygon CTF and negative-risk lifecycle events. "
        "Gamma and CLOB do not publish that history. Data API `GET /v2/oi` returns the current priced gross open interest in USDC:",
        "",
        "> Σ ((shares − fee_receiver_shares) / 1e6 · outcome_price) across outcomes, with no netting.",
        "",
        "It is one snapshot for the whole life of the request, not a value as of 4:00 p.m. on each formation date. "
        "Copying it backward would put later position changes into earlier characteristics, which the paper rules out. "
        "This run attaches the snapshot only on the latest formation date whose next 4:00 p.m. mark is already in the price history. "
        "The snapshot is still after that 4:00 p.m. The lag in hours is above. "
        "Share proxy: oi_shares = oi_usdc / (P^form + (1 − P^form)) = oi_usdc, using the complementary NO price because the NO print is not in the YES history. "
        "YESMV = P^form × oi_shares. The price is not used by itself as the size measure.",
        "",
        "How this can differ from the paper: ranks and weights move if open interest changed between 4:00 p.m. and the snapshot; "
        "priced-gross USDC equals the raw contract count only when YES and NO prices sum to one; "
        "the High−Low mean is a one-date cross-section when only one formation date receives OI, so it is not the paper's multi-year Newey–West mean.",
        "",
        "未平仓量只有当前快照，没有每个形成日 16:00 的历史。快照只挂在最近一个已经能观察到下一交易日 16:00 价格的形成日上，不回填到更早的日期。YESMV 仍是形成价乘以份额代理，而不是单独用价格。",
        "",
        "## This run / 本次结果",
        "",
        f"- Factor rows / 因子行数: {meta['n_factor_rows']}",
        f"- Portfolio-sample rows / 进入组合的行数: {meta['n_portfolio_rows']}",
        f"- Formation dates in the panel / 面板中的形成日数: {meta['n_formation_dates']}",
        f"- Dates with a High−Low portfolio / 能算出多空组合的日期数: {meta['n_spread_dates']}",
        f"- Mean High−Low YESMV: {spread_line(yes)}",
        f"- Mean High−Low LOR(1): {spread_line(lor)}",
        "",
        "Cents are R^{pp} times 100. A negative High−Low means the high characteristic has the lower subsequent price change.",
        "",
        "### Spreads / 价差（美分）",
        "",
        "| Characteristic | Dates | Low | Middle | High | High−Low | NW t |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for characteristic in CHARACTERISTICS:
        row = spreads.get(characteristic)
        if row is None:
            lines.append(f"| {characteristic} | 0 |  |  |  |  |  |")
            continue
        lines.append(
            "| {characteristic} | {n_dates} | {low:.4f} | {mid:.4f} | {high:.4f} | {hl:.4f} | {t} |".format(
                characteristic=characteristic,
                n_dates=row["n_dates"],
                low=float(row["mean_low_cents"]),
                mid=float(row["mean_middle_cents"]),
                high=float(row["mean_high_cents"]),
                hl=float(row["mean_high_minus_low_cents"]),
                t=row["t_newey_west"] or "",
            )
        )
    lines.extend(
        [
            "",
            "Category counts in the portfolio sample:",
            "",
        ]
    )
    for name, count in meta["category_counts"][:12]:
        lines.append(f"- {name}: {count}")
    lines.extend(
        [
            "",
            "Rebuild / 重跑:",
            "",
            "```bash",
            "python3 scripts/strategy/hlz_cross_section/build_factors.py --self-test",
            "python3 scripts/strategy/hlz_cross_section/build_factors.py --start-date 2026-11-01 --end-date 2026-11-06",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_factors(args: argparse.Namespace) -> int:
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise SystemExit("--end-date is before --start-date")
    now = datetime.now(timezone.utc)
    now_epoch = int(now.timestamp())
    anchor = latest_closed_formation(start, end, now_epoch)
    contracts = load_universe(args.universe, start, end, args.closed_mode)
    if args.max_markets > 0:
        contracts = contracts[: args.max_markets]
    if not contracts:
        raise SystemExit("no Step 1 contracts matched the window and YES-token filter")
    print(
        f"contracts {len(contracts)} window {start.isoformat()}..{end.isoformat()} "
        f"oi_anchor {anchor.isoformat() if anchor else None}",
        flush=True,
    )
    limiter = RateLimiter(REQUESTS_PER_SECOND)
    gamma = fetch_gamma([row["market_id"] for row in contracts], args.cache_dir, limiter, args.workers)
    conditions = []
    for row in contracts:
        meta = gamma.get(row["market_id"]) or {}
        condition = str(meta.get("conditionId") or "")
        if condition:
            conditions.append(condition)
    oi_observed_at = datetime.now(timezone.utc)
    oi_by_condition = fetch_oi(conditions, limiter, args.workers)
    fetch_start = formation_epoch(start - timedelta(days=TRADE_LOOKBACK_DAYS))
    histories = load_prices(
        [(row.get("yes_token") or "").strip() for row in contracts],
        fetch_start,
        now_epoch,
        args.cache_dir,
        limiter,
        args.workers,
        args.refresh,
    )
    days = iter_days(start, end)
    panel: list[dict[str, str]] = []
    for row in contracts:
        token = (row.get("yes_token") or "").strip()
        meta = gamma.get(row["market_id"])
        condition = str((meta or {}).get("conditionId") or "").lower()
        panel.extend(
            contract_panel_rows(
                row,
                meta,
                histories.get(token, []),
                oi_by_condition.get(condition),
                anchor,
                days,
            )
        )
    panel.sort(key=lambda item: (item["date"], item["category"], item["market_id"]))
    daily = build_daily_portfolios(panel)
    spreads = summarize_spreads(daily)
    for row in spreads:
        row["mean_low_cents"] = f"{row['mean_low_cents']:.6f}"
        row["mean_middle_cents"] = f"{row['mean_middle_cents']:.6f}"
        row["mean_high_cents"] = f"{row['mean_high_cents']:.6f}"
        row["mean_high_minus_low_cents"] = f"{row['mean_high_minus_low_cents']:.6f}"
        row["mean_categories"] = f"{row['mean_categories']:.4f}"
        row["mean_contracts"] = f"{row['mean_contracts']:.4f}"
    daily_out = []
    for row in daily:
        daily_out.append(
            {
                "date": row["date"],
                "characteristic": row["characteristic"],
                "n_categories": row["n_categories"],
                "n_contracts": row["n_contracts"],
                "low_cents": f"{row['low_cents']:.6f}",
                "middle_cents": f"{row['middle_cents']:.6f}",
                "high_cents": f"{row['high_cents']:.6f}",
                "high_minus_low_cents": f"{row['high_minus_low_cents']:.6f}",
            }
        )
    category_counts: dict[str, int] = defaultdict(int)
    portfolio_rows = 0
    for row in panel:
        if row["in_portfolio_sample"] == "true":
            portfolio_rows += 1
            category_counts[row["category"]] += 1
    lag_hours = ""
    if anchor is not None:
        lag_hours = f"{(oi_observed_at - formation_time(anchor)).total_seconds() / 3600.0:.2f}"
    meta_out = {
        "generated_at": iso_z(now),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "closed_mode": args.closed_mode,
        "n_markets": len(contracts),
        "n_factor_rows": len(panel),
        "n_portfolio_rows": portfolio_rows,
        "n_formation_dates": len({row["date"] for row in panel}),
        "n_spread_dates": len({row["date"] for row in daily_out}),
        "oi_anchor_date": anchor.isoformat() if anchor else None,
        "oi_observed_at": iso_z(oi_observed_at),
        "oi_lag_hours": lag_hours,
        "oi_markets": len(oi_by_condition),
        "spreads": spreads,
        "category_counts": sorted(category_counts.items(), key=lambda item: -item[1]),
    }
    write_csv(args.factors, panel, FACTOR_COLUMNS)
    write_csv(args.spreads, spreads, SPREAD_COLUMNS)
    write_csv(args.daily, daily_out, DAILY_COLUMNS)
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(meta_out, indent=2) + "\n", encoding="utf-8")
    summary = render_summary(meta_out)
    args.summary.write_text(summary, encoding="utf-8")
    yes = next((row for row in spreads if row["characteristic"] == "yesmv"), None)
    lor = next((row for row in spreads if row["characteristic"] == "lor_1"), None)
    print(
        f"rows {len(panel)} portfolio_rows {portfolio_rows} "
        f"YESMV {None if yes is None else yes['mean_high_minus_low_cents']} "
        f"LOR1 {None if lor is None else lor['mean_high_minus_low_cents']}",
        flush=True,
    )
    print(f"wrote {args.factors}", flush=True)
    print(f"wrote {args.summary}", flush=True)
    return 0


def _self_test() -> None:
    assert formation_epoch(date(2026, 11, 6)) == int(
        datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc).timestamp()
    )
    assert formation_epoch(date(2026, 7, 15)) == int(
        datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc).timestamp()
    )
    assert abs((logit(0.2) or 0) - math.log(0.2 / 0.8)) < 1e-12
    assert logit(0.0) is None and logit(1.0) is None

    day = date(2026, 11, 6)
    epoch = formation_epoch(day)
    history = normalize_history(
        [
            (epoch - 3 * 3600, 0.40),
            (epoch - 30 * 60, 0.42),
            (epoch + 10 * 60, 0.99),
        ]
    )
    price, obs, age = price_at_formation(history, day)
    assert price == 0.42
    assert obs == epoch - 30 * 60
    assert age is not None and age <= 2
    stale_history = normalize_history([(epoch - 5 * 3600, 0.10)])
    stale_price, _obs, stale_age = price_at_formation(stale_history, day)
    assert stale_price == 0.10
    assert stale_age is not None and stale_age > 2

    # A print on Nov 5 counts. A print only on Nov 6 does not: that day is not "preceding".
    prior = normalize_history([(formation_epoch(date(2026, 11, 5)) - 3600, 0.2)])
    assert traded_preceding_week(prior, day)
    only_today = normalize_history([(epoch - 3600, 0.2)])
    assert not traded_preceding_week(only_today, day)

    assert lor_value(0.6, 0.4) == logit(0.6) - logit(0.4)
    shares = yes_share_proxy(1000.0, 0.25)
    assert shares == 1000.0
    assert abs((0.25 * shares) - 250.0) < 1e-9
    assert yes_share_proxy(None, 0.25) is None

    politics, source = choose_category(
        [
            {"slug": "trump-iran", "label": "U.S. x Iran"},
            {"slug": "politics", "label": "Politics"},
        ]
    )
    assert politics == "Politics" and source == "tag:politics"
    narrow, narrow_source = choose_category([{"slug": "nfl", "label": "NFL"}])
    assert narrow == "NFL" and narrow_source == "tag:nfl"

    # Five contracts, one category. Hand-computed 30/70 legs and Eq. (3).
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert assign_legs(values) == ["low", "low", "middle", "high", "high"]
    rows = [
        {"category": "Politics", "x": values[i], "oi": oi, "r": r}
        for i, (oi, r) in enumerate(
            [(10.0, 0.01), (10.0, 0.02), (10.0, 0.03), (30.0, 0.04), (10.0, 0.05)]
        )
    ]
    result = category_portfolios(rows)
    assert result is not None
    assert abs(result["low"] - 0.015) < 1e-12
    assert abs(result["high"] - 0.0425) < 1e-12
    assert abs(result["high_minus_low"] - 0.0275) < 1e-12
    # A second category with the same shape and half the open interest.
    # Eq. (4) then puts weight 70/105 on the first category.
    other = []
    for row in rows:
        other.append({**row, "category": "Sports", "oi": row["oi"] / 2.0})
    both = category_portfolios(rows + other)
    assert both is not None and both["n_categories"] == 2
    assert abs(both["high_minus_low"] - 0.0275) < 1e-12

    # Snapshot OI is not attached before the anchor date.
    anchor = date(2026, 11, 6)
    contract = {
        "market_id": "1",
        "question": "Example",
        "event_id": "9",
        "event_title": "Example",
        "yes_token": "yes",
        "open_date": "2026-01-01T00:00:00Z",
        "expiry": "2026-12-01T00:00:00Z",
    }
    meta = {
        "conditionId": "0xabc",
        "closed": False,
        "tags": [{"slug": "politics", "label": "Politics"}],
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.4", "0.6"],
    }
    points = []
    for offset in range(0, 10):
        stamp = date(2026, 11, 6) - timedelta(days=offset)
        points.append((formation_epoch(stamp) - 20 * 60, 0.40 + offset * 0.01))
    points.append((formation_epoch(date(2026, 11, 7)) - 15 * 60, 0.55))
    panel = contract_panel_rows(
        contract,
        meta,
        normalize_history(points),
        5000.0,
        anchor,
        [date(2026, 11, 5), date(2026, 11, 6)],
    )
    by_day = {row["date"]: row for row in panel}
    assert by_day["2026-11-05"]["oi_shares"] == ""
    assert by_day["2026-11-05"]["yesmv"] == ""
    assert by_day["2026-11-05"]["in_portfolio_sample"] == "false"
    assert by_day["2026-11-06"]["p_form"] == "0.400000"
    assert float(by_day["2026-11-06"]["oi_shares"]) == 5000.0
    assert abs(float(by_day["2026-11-06"]["yesmv"]) - 2000.0) < 1e-6
    assert by_day["2026-11-06"]["p_end_source"] == "next_formation"
    assert abs(float(by_day["2026-11-06"]["r_pp"]) - (0.55 - 0.40)) < 1e-9
    assert by_day["2026-11-06"]["in_portfolio_sample"] == "true"
    # The post-formation 0.99 print must not be the formation price.
    assert float(by_day["2026-11-06"]["p_form"]) != 0.99

    settled_meta = {
        **meta,
        "closed": True,
        "closedTime": "2026-11-07T12:00:00Z",
        "outcomePrices": ["1", "0"],
    }
    settled_rows = contract_panel_rows(
        contract,
        settled_meta,
        normalize_history(points),
        5000.0,
        anchor,
        [date(2026, 11, 6)],
    )
    assert settled_rows[0]["p_end_source"] == "settlement"
    assert settled_rows[0]["p_end"] == "1.000000"
    assert abs(float(settled_rows[0]["r_pp"]) - 0.60) < 1e-9

    late_settlement = {
        **settled_meta,
        "closedTime": "2026-11-08T18:00:00Z",
    }
    late_rows = contract_panel_rows(
        contract,
        late_settlement,
        normalize_history(points),
        5000.0,
        anchor,
        [date(2026, 11, 6)],
    )
    assert late_rows[0]["p_end_source"] == "next_formation"

    chunks = price_chunks(0, PRICE_CHUNK_SECONDS + 10)
    assert chunks == [(0, PRICE_CHUNK_SECONDS), (PRICE_CHUNK_SECONDS, PRICE_CHUNK_SECONDS + 10)]
    assert latest_closed_formation(
        date(2026, 11, 1),
        date(2026, 11, 7),
        formation_epoch(date(2026, 11, 7)) + 3600,
    ) == date(2026, 11, 6)

    daily = [
        {"characteristic": "yesmv", "low": 0.001, "middle": 0.0, "high": -0.001, "high_minus_low": -0.002, "n_categories": 2, "n_contracts": 10},
        {"characteristic": "yesmv", "low": 0.003, "middle": 0.0, "high": 0.001, "high_minus_low": -0.002, "n_categories": 2, "n_contracts": 12},
    ]
    summary = summarize_spreads(daily)
    assert summary[0]["characteristic"] == "yesmv"
    assert abs(summary[0]["mean_high_minus_low_cents"] - (-0.2)) < 1e-9
    assert summary[0]["t_newey_west"] == ""
    print("self-test ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the HLZ Step 2 YESMV and LOR portfolios.")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start-date", default="2026-11-01")
    parser.add_argument("--end-date", default="2026-11-06")
    parser.add_argument(
        "--closed-mode",
        choices=("open", "closed", "all"),
        default="open",
        help="Which Step 1 contracts to read. Default open keeps the CLOB pull workable.",
    )
    parser.add_argument("--max-markets", type=int, default=0, help="Debug cap. 0 means every matched contract.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    parser.add_argument("--spreads", type=Path, default=DEFAULT_SPREADS)
    parser.add_argument("--daily", type=Path, default=DEFAULT_DAILY)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    return build_factors(args)


if __name__ == "__main__":
    raise SystemExit(main())
