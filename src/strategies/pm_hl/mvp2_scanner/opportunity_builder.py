from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.mvp2_scanner.risk_scoring import (
    execution_risk_score,
    match_recommendation,
    recommendation,
    rule_match_score,
    rule_match_note,
)
from src.strategies.pm_hl.mvp2_scanner.schemas import (
    BookTop,
    ChampionMarket,
    ChampionUniverseOutcome,
    MatchMarket,
    OpportunityRow,
)
from src.strategies.pm_hl.opportunity_model import pm_fee


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hl_taker_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def _top(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> BookTop:
    bid, bid_size = bids[0] if bids else (None, None)
    ask, ask_size = asks[0] if asks else (None, None)
    return BookTop(bid=bid, bid_size=bid_size, ask=ask, ask_size=ask_size)


def _safe_pm_book(token: str) -> tuple[BookTop, dict[str, Any] | None, str | None]:
    try:
        bids, asks, raw = pm.book(token)
        return _top(bids, asks), raw, None
    except Exception as exc:
        return BookTop(), None, f"pm_book_error:{str(exc)[:120]}"


def _safe_hl_book(coin: str) -> tuple[BookTop, str | None]:
    try:
        bids, asks = hl.coin_book(coin)
        return _top(bids, asks), None
    except Exception as exc:
        return BookTop(), f"hl_book_error:{str(exc)[:120]}"


def _missing_count(*books: BookTop) -> int:
    values = []
    for book in books:
        values.extend([book.bid, book.ask])
    return sum(1 for value in values if value is None)


def _sum_present(values: list[float | None]) -> float | None:
    return sum(value for value in values if value is not None) if any(value is not None for value in values) else None


def _deviation(value: float | None, target: float) -> float | None:
    return None if value is None else value - target


def _build_direction(
    *,
    pm_book: BookTop,
    hl_book: BookTop,
    direction: str,
) -> dict[str, Any]:
    if pm_book.ask is None or hl_book.ask is None:
        return {"direction": direction, "net_edge": None}
    depth = min(pm_book.ask_size or 0.0, hl_book.ask_size or 0.0)
    gross_edge = 1.0 - pm_book.ask - hl_book.ask
    estimated_fee = pm_fee(pm_book.ask) + _hl_taker_fee()
    net_edge = gross_edge - estimated_fee
    return {
        "direction": direction,
        "gross_edge": gross_edge,
        "estimated_fee": estimated_fee,
        "net_edge": net_edge,
        "depth": depth,
        "capacity_usd": depth * (pm_book.ask + hl_book.ask),
        "pm_ask": pm_book.ask,
        "hl_ask": hl_book.ask,
    }


def build_champion_row(market: ChampionMarket) -> tuple[OpportunityRow, list[str]]:
    warnings: list[str] = []
    pm_yes, pm_yes_raw, error = _safe_pm_book(market.pm_yes_token)
    if error:
        warnings.append(error)
    pm_no, pm_no_raw, error = _safe_pm_book(market.pm_no_token)
    if error:
        warnings.append(error)
    hl_yes, error = _safe_hl_book(market.hl_yes_coin)
    if error:
        warnings.append(error)
    hl_no, error = _safe_hl_book(market.hl_no_coin)
    if error:
        warnings.append(error)

    dir_pm_yes_hl_no = _build_direction(
        pm_book=pm_yes,
        hl_book=hl_no,
        direction="buy_pm_yes_buy_hl_no",
    )
    dir_pm_no_hl_yes = _build_direction(
        pm_book=pm_no,
        hl_book=hl_yes,
        direction="buy_pm_no_buy_hl_yes",
    )
    directions = [dir_pm_yes_hl_no, dir_pm_no_hl_yes]
    selected = max(directions, key=lambda row: row.get("net_edge") or -999.0)
    missing = _missing_count(pm_yes, pm_no, hl_yes, hl_no)
    risk = execution_risk_score(
        strategy_type="champion_cross_venue",
        depth=selected.get("depth"),
        capacity_usd=selected.get("capacity_usd"),
        missing_price_count=missing,
    )
    rec = recommendation(selected.get("net_edge"), selected.get("capacity_usd"), risk)
    net_edge = selected.get("net_edge")
    row = OpportunityRow(
        timestamp=now_iso(),
        strategy_type="champion_cross_venue",
        venue_a="polymarket",
        venue_b="hyperliquid",
        market_key=market.market_key,
        market_title=market.market_title,
        outcome=market.outcome,
        price_a_bid=pm_yes.bid,
        price_a_ask=pm_yes.ask,
        price_b_bid=hl_yes.bid,
        price_b_ask=hl_yes.ask,
        gross_edge=selected.get("gross_edge"),
        estimated_fee=selected.get("estimated_fee"),
        net_edge=net_edge,
        net_edge_bps=net_edge * 10_000 if net_edge is not None else None,
        depth=selected.get("depth"),
        capacity_usd=selected.get("capacity_usd"),
        rule_match_score=rule_match_score("champion_cross_venue", True),
        execution_risk_score=risk,
        recommendation=rec,
        raw={
            "pm_slug": market.pm_slug,
            "pm_market_id": market.pm_market_id,
            "pm_yes_token": market.pm_yes_token,
            "pm_no_token": market.pm_no_token,
            "hl_yes_coin": market.hl_yes_coin,
            "hl_no_coin": market.hl_no_coin,
            "pm_yes_top": pm_yes.__dict__,
            "pm_no_top": pm_no.__dict__,
            "hl_yes_top": hl_yes.__dict__,
            "hl_no_top": hl_no.__dict__,
            "selected_direction": selected.get("direction"),
            "directions": directions,
            "fee_note": "PM fee uses existing 3%*p*(1-p); HL fee from HL_TAKER_FEE env, default 0.",
            "rule_match_note": rule_match_note("champion_cross_venue", True),
            "diagnostic_note": "Single-venue all-yes/all-no deviations are diagnostic only, not MVP2 strategy signals.",
            "pm_tick_size": (pm_yes_raw or pm_no_raw or {}).get("tick_size"),
            "warnings": warnings,
        },
    )
    return row, warnings


def _venue_full_diagnostic(
    venue: str,
    universe: list[ChampionUniverseOutcome],
) -> dict[str, Any]:
    yes_values: list[float | None] = []
    no_values: list[float | None] = []
    warnings: list[str] = []
    for outcome in universe:
        if venue == "polymarket":
            yes_book, _, error = _safe_pm_book(str(outcome.yes_token or ""))
            if error:
                warnings.append(f"{outcome.outcome}:yes:{error}")
            no_book, _, error = _safe_pm_book(str(outcome.no_token or ""))
            if error:
                warnings.append(f"{outcome.outcome}:no:{error}")
        else:
            yes_book, error = _safe_hl_book(str(outcome.yes_coin or ""))
            if error:
                warnings.append(f"{outcome.outcome}:yes:{error}")
            no_book, error = _safe_hl_book(str(outcome.no_coin or ""))
            if error:
                warnings.append(f"{outcome.outcome}:no:{error}")
        yes_values.append(yes_book.ask)
        no_values.append(no_book.ask)

    count = len(universe)
    sum_yes = _sum_present(yes_values)
    sum_no = _sum_present(no_values)
    missing_yes = sum(1 for value in yes_values if value is None)
    missing_no = sum(1 for value in no_values if value is None)
    other_labels = [outcome.outcome for outcome in universe if outcome.is_other]
    placeholder_count = sum(1 for outcome in universe if outcome.is_placeholder)
    completeness_flag = "complete" if count and missing_yes == 0 and missing_no == 0 else "partial"
    if not count:
        completeness_flag = "missing"
    completeness_note = (
        f"{venue} full champion universe outcomes={count}; "
        f"missing_yes={missing_yes}; missing_no={missing_no}; "
        f"other_labels={other_labels or 'none'}; placeholder_count={placeholder_count}"
    )
    return {
        "outcome_count": count,
        "sum_yes": sum_yes,
        "sum_yes_deviation_from_1": _deviation(sum_yes, 1.0),
        "sum_no": sum_no,
        "sum_no_deviation_from_n_minus_1": _deviation(sum_no, count - 1),
        "has_other": bool(other_labels),
        "other_labels": other_labels,
        "placeholder_count": placeholder_count,
        "completeness_flag": completeness_flag,
        "completeness_note": completeness_note,
        "warnings": warnings,
    }


def build_champion_full_diagnostic(
    pm_universe: list[ChampionUniverseOutcome],
    hl_universe: list[ChampionUniverseOutcome],
) -> dict[str, Any]:
    return {
        "pm": _venue_full_diagnostic("polymarket", pm_universe),
        "hl": _venue_full_diagnostic("hyperliquid", hl_universe),
        "scope_note": "Full-market diagnostic uses each venue's full discovered World Cup Champion universe, not the current scanned subset.",
    }


def add_champion_diagnostics(
    rows: list[OpportunityRow],
    full_diagnostic: dict[str, Any] | None = None,
) -> list[OpportunityRow]:
    champion_rows = [row for row in rows if row.strategy_type == "champion_cross_venue"]
    if not champion_rows:
        return rows

    pm_yes_values = [row.price_a_ask for row in champion_rows]
    hl_yes_values = [row.price_b_ask for row in champion_rows]
    pm_no_values = [
        (row.raw.get("pm_no_top") or {}).get("ask")
        for row in champion_rows
    ]
    hl_no_values = [
        (row.raw.get("hl_no_top") or {}).get("ask")
        for row in champion_rows
    ]
    n = len(champion_rows)
    pm_sum_yes = _sum_present(pm_yes_values)
    hl_sum_yes = _sum_present(hl_yes_values)
    pm_sum_no = _sum_present(pm_no_values)
    hl_sum_no = _sum_present(hl_no_values)
    missing_counts = {
        "pm_yes_missing": sum(1 for value in pm_yes_values if value is None),
        "pm_no_missing": sum(1 for value in pm_no_values if value is None),
        "hl_yes_missing": sum(1 for value in hl_yes_values if value is None),
        "hl_no_missing": sum(1 for value in hl_no_values if value is None),
    }
    is_complete = all(value == 0 for value in missing_counts.values())
    completeness_flag = "complete" if is_complete else "partial"
    completeness_note = (
        f"champion diagnostics over {n} matched PM/HL outcomes; "
        + ", ".join(f"{key}={value}" for key, value in missing_counts.items())
    )

    enriched: list[OpportunityRow] = []
    for row in rows:
        if row.strategy_type != "champion_cross_venue":
            enriched.append(row)
            continue
        raw = dict(row.raw)
        pm_full = (full_diagnostic or {}).get("pm", {})
        hl_full = (full_diagnostic or {}).get("hl", {})
        raw["champion_subset_diagnostic"] = {
            "pm_subset_sum_yes": pm_sum_yes,
            "pm_subset_sum_yes_deviation_from_1": _deviation(pm_sum_yes, 1.0),
            "pm_subset_sum_no": pm_sum_no,
            "pm_subset_sum_no_deviation_from_n_minus_1": _deviation(pm_sum_no, n - 1),
            "hl_subset_sum_yes": hl_sum_yes,
            "hl_subset_sum_yes_deviation_from_1": _deviation(hl_sum_yes, 1.0),
            "hl_subset_sum_no": hl_sum_no,
            "hl_subset_sum_no_deviation_from_n_minus_1": _deviation(hl_sum_no, n - 1),
            "completeness_flag": completeness_flag,
            "completeness_note": completeness_note,
            "scope_note": "Diagnostic only; not used for MVP2 recommendation.",
        }
        raw["champion_full_market_diagnostic"] = full_diagnostic or {}
        enriched.append(
            replace(
                row,
                pm_subset_sum_yes=pm_sum_yes,
                pm_subset_sum_yes_deviation_from_1=_deviation(pm_sum_yes, 1.0),
                pm_subset_sum_no=pm_sum_no,
                pm_subset_sum_no_deviation_from_n_minus_1=_deviation(pm_sum_no, n - 1),
                hl_subset_sum_yes=hl_sum_yes,
                hl_subset_sum_yes_deviation_from_1=_deviation(hl_sum_yes, 1.0),
                hl_subset_sum_no=hl_sum_no,
                hl_subset_sum_no_deviation_from_n_minus_1=_deviation(hl_sum_no, n - 1),
                pm_full_outcome_count=pm_full.get("outcome_count"),
                pm_full_sum_yes=pm_full.get("sum_yes"),
                pm_full_sum_yes_deviation_from_1=pm_full.get("sum_yes_deviation_from_1"),
                pm_full_sum_no=pm_full.get("sum_no"),
                pm_full_sum_no_deviation_from_n_minus_1=pm_full.get("sum_no_deviation_from_n_minus_1"),
                pm_full_has_other=pm_full.get("has_other"),
                pm_full_other_labels=list(pm_full.get("other_labels") or []),
                pm_full_placeholder_count=pm_full.get("placeholder_count"),
                pm_full_completeness_flag=str(pm_full.get("completeness_flag") or "unknown"),
                pm_full_completeness_note=str(pm_full.get("completeness_note") or ""),
                hl_full_outcome_count=hl_full.get("outcome_count"),
                hl_full_sum_yes=hl_full.get("sum_yes"),
                hl_full_sum_yes_deviation_from_1=hl_full.get("sum_yes_deviation_from_1"),
                hl_full_sum_no=hl_full.get("sum_no"),
                hl_full_sum_no_deviation_from_n_minus_1=hl_full.get("sum_no_deviation_from_n_minus_1"),
                hl_full_has_other=hl_full.get("has_other"),
                hl_full_other_labels=list(hl_full.get("other_labels") or []),
                hl_full_placeholder_count=hl_full.get("placeholder_count"),
                hl_full_completeness_flag=str(hl_full.get("completeness_flag") or "unknown"),
                hl_full_completeness_note=str(hl_full.get("completeness_note") or ""),
                pm_sum_yes=pm_sum_yes,
                pm_sum_yes_deviation_from_1=_deviation(pm_sum_yes, 1.0),
                pm_sum_no=pm_sum_no,
                pm_sum_no_deviation_from_n_minus_1=_deviation(pm_sum_no, n - 1),
                hl_sum_yes=hl_sum_yes,
                hl_sum_yes_deviation_from_1=_deviation(hl_sum_yes, 1.0),
                hl_sum_no=hl_sum_no,
                hl_sum_no_deviation_from_n_minus_1=_deviation(hl_sum_no, n - 1),
                completeness_flag=completeness_flag,
                completeness_note=completeness_note,
                raw=raw,
            )
        )
    return enriched


def _mid(book: BookTop) -> float | None:
    if book.bid is not None and book.ask is not None:
        return (book.bid + book.ask) / 2.0
    return book.bid if book.bid is not None else book.ask


def build_match_rows(market: MatchMarket) -> tuple[list[OpportunityRow], list[str]]:
    warnings: list[str] = []
    timestamp = now_iso()
    hl_books: dict[str, BookTop] = {}
    pm_books: dict[str, BookTop] = {}

    for outcome, outcome_id in zip(market.outcomes, market.hl_outcome_ids):
        book, error = _safe_hl_book(f"#{outcome_id * 10}")
        hl_books[outcome] = book
        if error:
            warnings.append(f"{outcome}:{error}")
        token = market.pm_outcome_tokens.get(outcome)
        if token:
            pm_book, _, error = _safe_pm_book(token)
            pm_books[outcome] = pm_book
            if error:
                warnings.append(f"{outcome}:{error}")
        else:
            pm_books[outcome] = BookTop()

    pm_ask_sum = (
        sum(book.ask or 0.0 for book in pm_books.values())
        if market.mapping_status == "matched"
        else None
    )
    hl_ask_sum = sum(book.ask or 0.0 for book in hl_books.values())
    completeness_flag = "complete" if market.mapping_status == "matched" else "partial"
    completeness_note = (
        f"1v1 mapping_status={market.mapping_status}; "
        f"missing_pm_outcomes={','.join(market.missing_pm_outcomes) or 'none'}"
    )
    rows: list[OpportunityRow] = []
    for outcome in market.outcomes:
        pm_book = pm_books[outcome]
        hl_book = hl_books[outcome]
        pm_mid = _mid(pm_book)
        hl_mid = _mid(hl_book)
        discrepancy = None if pm_mid is None or hl_mid is None else hl_mid - pm_mid
        missing = _missing_count(pm_book, hl_book)
        depth = min(
            value
            for value in (pm_book.ask_size, hl_book.ask_size)
            if value is not None
        ) if pm_book.ask_size is not None and hl_book.ask_size is not None else None
        risk = execution_risk_score(
            strategy_type="match_3way",
            depth=depth,
            capacity_usd=None,
            missing_price_count=missing,
        )
        rec = (
            match_recommendation(discrepancy, risk)
            if market.mapping_status == "matched"
            else "observe"
        )
        rows.append(
            OpportunityRow(
                timestamp=timestamp,
                strategy_type="match_3way",
                venue_a="polymarket",
                venue_b="hyperliquid",
                market_key=market.market_key,
                market_title=market.market_title,
                outcome=outcome,
                price_a_bid=pm_book.bid,
                price_a_ask=pm_book.ask,
                price_b_bid=hl_book.bid,
                price_b_ask=hl_book.ask,
                gross_edge=discrepancy,
                estimated_fee=None,
                net_edge=discrepancy,
                net_edge_bps=discrepancy * 10_000 if discrepancy is not None else None,
                depth=depth,
                capacity_usd=None,
                rule_match_score=rule_match_score("match_3way", market.mapping_status == "matched"),
                execution_risk_score=risk,
                recommendation=rec,
                pm_sum_three_way=pm_ask_sum,
                pm_sum_three_way_deviation_from_1=None if pm_ask_sum is None else pm_ask_sum - 1.0,
                hl_sum_three_way=hl_ask_sum,
                hl_sum_three_way_deviation_from_1=hl_ask_sum - 1.0,
                completeness_flag=completeness_flag,
                completeness_note=completeness_note,
                raw={
                    "team_a": market.team_a,
                    "draw": "Draw",
                    "team_b": market.team_b,
                    "parse_status": market.parse_status,
                    "mapping_status": market.mapping_status,
                    "failure_reason": market.failure_reason,
                    "missing_pm_outcomes": list(market.missing_pm_outcomes),
                    "pm_token": market.pm_outcome_tokens.get(outcome),
                    "hl_yes_coin": f"#{market.hl_outcome_ids[market.outcomes.index(outcome)] * 10}",
                    "pm_ask_sum": pm_ask_sum,
                    "hl_ask_sum": hl_ask_sum,
                    "pm_sum_to_one_error": None if pm_ask_sum is None else pm_ask_sum - 1.0,
                    "hl_sum_to_one_error": hl_ask_sum - 1.0,
                    "cross_market_discrepancy": discrepancy,
                    "rule_match_note": rule_match_note("match_3way", market.mapping_status == "matched"),
                    "future_strategy_hook": "Reserved for single outcome vs complement basket research; no trade intent generated.",
                    "diagnostic_note": "3-way sum deviation is diagnostic only, not an MVP2 strategy signal.",
                    "warnings": warnings,
                },
            )
        )
    if market.failure_reason:
        warnings.append(f"{market.market_key}:{market.failure_reason}")
    return rows, warnings

