"""Paper definitions for HLZ Step 2. No network and no proxy inputs.

Formation is 4:00 p.m. America/New_York. A stock variable may use only
records whose own timestamp is at or before that instant. Missing inputs
stay missing.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
USDC_COLLATERAL = {
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # native USDC
}
ZERO_PARENT = "0x" + "0" * 64
FULL_SET = frozenset({"1", "2"})
FRESH_SECONDS = 2 * 3600


def formation_time(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 16, 0, tzinfo=EASTERN)


def formation_epoch(day: date) -> int:
    return int(formation_time(day).timestamp())


def eastern_date(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, tz=EASTERN).date()


def logit(price: float) -> float | None:
    if price <= 0.0 or price >= 1.0:
        return None
    return math.log(price / (1.0 - price))


def lor(price_now: float | None, price_then: float | None) -> float | None:
    if price_now is None or price_then is None:
        return None
    now = logit(price_now)
    then = logit(price_then)
    if now is None or then is None:
        return None
    return now - then


def percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("empty")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * probability
    low = int(math.floor(rank))
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def winsorize(values: list[float]) -> list[float]:
    ordered = sorted(values)
    floor = percentile(ordered, 0.01)
    cap = percentile(ordered, 0.99)
    if cap < floor:
        floor, cap = cap, floor
    return [min(max(value, floor), cap) for value in values]


def assign_legs(values: list[float]) -> list[str]:
    clipped = winsorize(values)
    ordered = sorted(clipped)
    low_cut = percentile(ordered, 0.30)
    high_cut = percentile(ordered, 0.70)
    legs: list[str] = []
    for value in clipped:
        if value <= low_cut:
            legs.append("low")
        elif value >= high_cut:
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
    """Eqs. (3) and (4). Weights are raw open interest, not the characteristic."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["category"]), []).append(row)
    leg_returns: dict[str, list[tuple[float, float]]] = {"low": [], "middle": [], "high": []}
    n_contracts = 0
    for members in grouped.values():
        if len(members) < 3:
            continue
        legs = assign_legs([float(member["x"]) for member in members])
        buckets: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
        for member, leg in zip(members, legs):
            buckets[leg].append(member)
        if not all(buckets[name] for name in ("low", "middle", "high")):
            continue
        presort = sum(float(member["oi"]) for member in members)
        if presort <= 0:
            continue
        returns: dict[str, float] = {}
        ok = True
        for name, bucket in buckets.items():
            mean = oi_weighted_mean(
                [{"oi": float(item["oi"]), "r": float(item["r"])} for item in bucket]
            )
            if mean is None:
                ok = False
                break
            returns[name] = mean
        if not ok:
            continue
        n_contracts += len(members)
        for name in ("low", "middle", "high"):
            leg_returns[name].append((presort, returns[name]))
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


def parse_block_id(record_id: str) -> int | None:
    parts = str(record_id).split("_")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def normalize_partition(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        text = value.strip().strip("[]")
        items = [part.strip().strip("'\"") for part in text.split(",") if part.strip()]
        return frozenset(items)
    try:
        return frozenset(str(item).strip() for item in value)
    except TypeError:
        return frozenset()


def event_counts_as_complete_set(event: dict[str, Any]) -> bool:
    """Root USDC complete-set split, merge, or redemption.

    A full binary set is partition or index set {1, 2}. Anything else is
    left out of the open-interest sum and counted by the caller.
    """
    collateral = str(event.get("collateral") or "").lower()
    parent = str(event.get("parent") or "").lower()
    if collateral not in USDC_COLLATERAL or parent != ZERO_PARENT:
        return False
    return normalize_partition(event.get("partition")) == FULL_SET


def replay_open_interest(events: Iterable[dict[str, Any]], asof: int) -> tuple[float | None, str]:
    """Net complete sets with timestamp <= asof.

    Returns (None, reason) when the history is not usable. A present history
    that nets to zero is zero, not a fabricated positive number. Events after
    `asof` are ignored.
    """
    total = 0.0
    seen = 0
    for event in events:
        timestamp = event.get("timestamp")
        if timestamp is None:
            return None, "event_missing_timestamp"
        if int(timestamp) > asof:
            continue
        if not event_counts_as_complete_set(event):
            continue
        amount = event.get("amount")
        if amount is None or float(amount) < 0:
            return None, "event_bad_amount"
        seen += 1
        kind = event["kind"]
        if kind == "split":
            total += float(amount)
        elif kind in {"merge", "redemption"}:
            total -= float(amount)
        else:
            return None, "event_unknown_kind"
    if seen == 0:
        return None, "no_complete_set_events"
    return total, "ok"


def last_trade_at_or_before(
    trades: Iterable[dict[str, Any]],
    asof: int,
    *,
    max_age: int = FRESH_SECONDS,
) -> dict[str, Any] | None:
    """Latest trade at or before asof, if it is not older than max_age.

    This does not accept a price-history sample. The caller must pass fills.
    """
    chosen: dict[str, Any] | None = None
    for trade in trades:
        timestamp = trade.get("timestamp")
        price = trade.get("price")
        if timestamp is None or price is None:
            continue
        stamp = int(timestamp)
        if stamp > asof:
            continue
        if chosen is None or stamp > int(chosen["timestamp"]):
            chosen = trade
    if chosen is None:
        return None
    if asof - int(chosen["timestamp"]) > max_age:
        return None
    if not 0.0 < float(chosen["price"]) < 1.0:
        return None
    return chosen


def traded_on_preceding_days(trade_timestamps: Iterable[int], day: date, lookback: int = 7) -> bool:
    wanted = {day - timedelta(days=offset) for offset in range(1, lookback + 1)}
    for timestamp in trade_timestamps:
        if eastern_date(int(timestamp)) in wanted:
            return True
    return False


def yes_payout(numerators: Any) -> float | None:
    """Map a binary ConditionResolution payout onto the reference outcome.

    TimeSeventeen documents ['1','0'] as the first outcome (YES on Yes/No
    markets; outcome_seq 1) and ['0','1'] as the second outcome.
    """
    parts = normalize_partition(numerators)
    # order matters; normalize_partition drops it. Parse directly.
    if isinstance(numerators, str):
        text = numerators.strip().strip("[]")
        values = [part.strip().strip("'\"") for part in text.split(",") if part.strip()]
    else:
        try:
            values = [str(item).strip() for item in numerators]
        except TypeError:
            return None
    if values == ["1", "0"]:
        return 1.0
    if values == ["0", "1"]:
        return 0.0
    return None


def endpoint_price(
    *,
    next_epoch: int,
    settlement_time: int | None,
    settlement_value: float | None,
    next_trade: dict[str, Any] | None,
) -> tuple[float | None, str]:
    """Settlement if it is at or before the next 4:00 p.m., else that print."""
    if (
        settlement_time is not None
        and settlement_value is not None
        and int(settlement_time) <= next_epoch
    ):
        return float(settlement_value), "settlement"
    if next_trade is None:
        return None, "missing_next_trade"
    return float(next_trade["price"]), "next_trade"


def self_test() -> None:
    assert formation_epoch(date(2026, 11, 6)) == int(
        datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc).timestamp()
    )
    assert formation_epoch(date(2026, 7, 15)) == int(
        datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc).timestamp()
    )
    assert yes_payout(["1", "0"]) == 1.0
    assert yes_payout(["0", "1"]) == 0.0
    assert yes_payout(["1", "1"]) is None

    asof = 1_000_000
    base = {
        "collateral": "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
        "parent": ZERO_PARENT,
        "partition": ["1", "2"],
    }
    events = [
        {**base, "kind": "split", "timestamp": asof - 10, "amount": 100.0},
        {**base, "kind": "merge", "timestamp": asof - 5, "amount": 40.0},
        {**base, "kind": "split", "timestamp": asof + 1, "amount": 999.0},
        {**base, "kind": "redemption", "timestamp": asof + 50, "amount": 60.0},
    ]
    oi, reason = replay_open_interest(events, asof)
    assert reason == "ok" and oi == 60.0
    later, later_reason = replay_open_interest(
        [event for event in events if event["amount"] != 999.0],
        asof + 100,
    )
    assert later_reason == "ok" and later == 0.0
    missing, missing_reason = replay_open_interest(
        [{**base, "kind": "split", "timestamp": None, "amount": 1.0}],
        asof,
    )
    assert missing is None and missing_reason == "event_missing_timestamp"

    trades = [
        {"timestamp": asof - 3 * 3600, "price": 0.2, "id": "old"},
        {"timestamp": asof - 30 * 60, "price": 0.4, "id": "ok"},
        {"timestamp": asof + 60, "price": 0.9, "id": "future"},
    ]
    chosen = last_trade_at_or_before(trades, asof)
    assert chosen is not None and chosen["id"] == "ok"
    assert last_trade_at_or_before([trades[0]], asof) is None
    day = eastern_date(asof)
    assert traded_on_preceding_days([asof - 86400], day)
    assert not traded_on_preceding_days([asof - 100], day)

    price, source = endpoint_price(
        next_epoch=asof + 86400,
        settlement_time=asof + 1000,
        settlement_value=1.0,
        next_trade={"timestamp": asof + 86400 - 10, "price": 0.3},
    )
    assert source == "settlement" and price == 1.0
    price, source = endpoint_price(
        next_epoch=asof + 86400,
        settlement_time=asof + 90000,
        settlement_value=1.0,
        next_trade={"timestamp": asof + 86400 - 10, "price": 0.3},
    )
    assert source == "next_trade" and price == 0.3

    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert assign_legs(values) == ["low", "low", "middle", "high", "high"]
    rows = [
        {"category": "Politics", "x": values[index], "oi": oi, "r": payoff}
        for index, (oi, payoff) in enumerate(
            [(10.0, 0.01), (10.0, 0.02), (10.0, 0.03), (30.0, 0.04), (10.0, 0.05)]
        )
    ]
    result = category_portfolios(rows)
    assert result is not None
    assert abs(result["low"] - 0.015) < 1e-12
    assert abs(result["high"] - 0.0425) < 1e-12
    assert abs(result["high_minus_low"] - 0.0275) < 1e-12
    print("self-test ok")


if __name__ == "__main__":
    self_test()
