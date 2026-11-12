from __future__ import annotations

import json
import os
import re
import sys
import time
import csv
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.mvp2_scanner.pm_sports_match_discovery import (
    MoneylineMarket,
    TokenBookTop,
    discover_moneyline,
)
from src.strategies.pm_hl.mvp2_scanner.risk_scoring import execution_risk_score
from src.strategies.pm_hl.opportunity_model import pm_fee


DEFAULT_OUTCOMES = ("Argentina", "Draw", "Austria")
DEFAULT_HL_QUESTION_NAME = "World Cup: Argentina vs Austria"


def _norm_label(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    compact = re.sub(r"[^a-z0-9]+", "", text)
    aliases = {
        "bosniaherzegovina": "bosniaandherzegovina",
    }
    return aliases.get(compact, compact)


@dataclass(frozen=True)
class HLBookTop:
    coin: str
    bid: float | None = None
    bid_size: float | None = None
    ask: float | None = None
    ask_size: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class AlignedOutcome:
    outcome: str
    pm_market_id: str
    pm_market_slug: str
    pm_yes_token: str
    pm_no_token: str
    pm_yes_book: TokenBookTop | None
    pm_no_book: TokenBookTop | None
    pm_rule_text: str
    hl_outcome_id: int
    hl_yes_coin: str
    hl_no_coin: str
    hl_yes_book: HLBookTop | None
    hl_no_book: HLBookTop | None
    hl_rule_text: str


@dataclass(frozen=True)
class EvaluationRow:
    sample_match_key: str
    pm_event_slug: str
    hl_question_name: str
    outcome: str
    pm_yes_bid: float | None
    pm_yes_ask: float | None
    hl_yes_bid: float | None
    hl_yes_ask: float | None
    single_outcome_side: str
    single_outcome_gross_edge: float | None
    single_outcome_estimated_fee: float | None
    single_outcome_net_edge: float | None
    single_outcome_depth: float | None
    single_outcome_capacity_usd: float | None
    complement_side: str
    complement_sum_ask: float | None
    complement_gross_edge: float | None
    complement_estimated_fee: float | None
    complement_net_edge: float | None
    complement_depth: float | None
    complement_capacity_usd: float | None
    rule_match_score: float
    rule_match_note: str
    execution_risk_score: float
    recommendation: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchEvaluation:
    evaluated_at: str
    sample_match_key: str
    pm_event_slug: str
    hl_question_name: str
    aligned_outcomes: list[AlignedOutcome]
    rows: list[EvaluationRow]
    opportunity_groups: dict[str, list[dict[str, Any]]]
    single_venue_diagnostics: list[dict[str, Any]]
    formula_reference: dict[str, Any]
    coverage_scope: dict[str, Any]
    sanity_checks: dict[str, Any]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hl_taker_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def _hl_top(coin: str) -> HLBookTop:
    try:
        bids, asks = hl.coin_book(coin)
        bid, bid_size = bids[0] if bids else (None, None)
        ask, ask_size = asks[0] if asks else (None, None)
        return HLBookTop(
            coin=coin,
            bid=bid,
            bid_size=bid_size,
            ask=ask,
            ask_size=ask_size,
        )
    except Exception as exc:
        return HLBookTop(coin=coin, error=str(exc)[:200])


def _hl_question(question_name: str) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    meta = hl.info({"type": "outcomeMeta"})
    outcomes = {
        int(row["outcome"]): row
        for row in meta.get("outcomes", [])
        if isinstance(row, dict) and row.get("outcome") is not None
    }
    for question in meta.get("questions", []):
        if str(question.get("name") or "") == question_name:
            return question, outcomes
    raise ValueError(f"HL question not found: {question_name}")


def _market_by_label(markets: list[MoneylineMarket]) -> dict[str, MoneylineMarket]:
    return {market.label: market for market in markets}


def _build_alignment(pm_event_slug: str, hl_question_name: str) -> list[AlignedOutcome]:
    pm_discovery = discover_moneyline(pm_event_slug)
    pm_markets = _market_by_label(pm_discovery.moneyline_markets)
    expected_outcomes = tuple(market.label for market in pm_discovery.moneyline_markets) or DEFAULT_OUTCOMES
    question, hl_outcomes = _hl_question(hl_question_name)
    hl_ids_by_label: dict[str, int] = {}
    hl_ids_by_norm_label: dict[str, int] = {}
    for outcome_id in question.get("namedOutcomes", []):
        outcome = hl_outcomes.get(int(outcome_id), {})
        label = str(outcome.get("name") or "")
        hl_ids_by_label[label] = int(outcome_id)
        hl_ids_by_norm_label[_norm_label(label)] = int(outcome_id)

    aligned: list[AlignedOutcome] = []
    for label in expected_outcomes:
        pm_market = pm_markets[label]
        outcome_id = hl_ids_by_label.get(label) or hl_ids_by_norm_label[_norm_label(label)]
        hl_outcome = hl_outcomes[outcome_id]
        yes_coin = f"#{outcome_id * 10}"
        no_coin = f"#{outcome_id * 10 + 1}"
        aligned.append(
            AlignedOutcome(
                outcome=label,
                pm_market_id=pm_market.market_id,
                pm_market_slug=pm_market.market_slug,
                pm_yes_token=pm_market.clob_token_ids[0] if len(pm_market.clob_token_ids) >= 1 else "",
                pm_no_token=pm_market.clob_token_ids[1] if len(pm_market.clob_token_ids) >= 2 else "",
                pm_yes_book=pm_market.yes_book_top,
                pm_no_book=pm_market.no_book_top,
                pm_rule_text=pm_market.description,
                hl_outcome_id=outcome_id,
                hl_yes_coin=yes_coin,
                hl_no_coin=no_coin,
                hl_yes_book=_hl_top(yes_coin),
                hl_no_book=_hl_top(no_coin),
                hl_rule_text=str(hl_outcome.get("description") or question.get("description") or ""),
            )
        )
    return aligned


def _expected_outcomes(aligned_by_label: dict[str, AlignedOutcome]) -> tuple[str, ...]:
    return tuple(aligned_by_label.keys()) or DEFAULT_OUTCOMES


def _sample_match_key(aligned: list[AlignedOutcome]) -> str:
    if len(aligned) >= 3:
        return f"{aligned[0].outcome} vs {aligned[2].outcome}"
    return " vs ".join(row.outcome for row in aligned)


def _single_candidates(pm_book: TokenBookTop | None, hl_book: HLBookTop | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if pm_book and hl_book and pm_book.ask is not None and hl_book.bid is not None:
        gross = hl_book.bid - pm_book.ask
        fee = pm_fee(pm_book.ask) + _hl_taker_fee()
        depth = min(pm_book.ask_size or 0.0, hl_book.bid_size or 0.0)
        candidates.append(
            {
                "side": "buy_pm_yes_sell_hl_yes",
                "gross_edge": gross,
                "estimated_fee": fee,
                "net_edge": gross - fee,
                "depth": depth,
                "capacity_usd": depth * pm_book.ask,
            }
        )
    if pm_book and hl_book and hl_book.ask is not None and pm_book.bid is not None:
        gross = pm_book.bid - hl_book.ask
        fee = pm_fee(pm_book.bid) + _hl_taker_fee()
        depth = min(hl_book.ask_size or 0.0, pm_book.bid_size or 0.0)
        candidates.append(
            {
                "side": "buy_hl_yes_sell_pm_yes",
                "gross_edge": gross,
                "estimated_fee": fee,
                "net_edge": gross - fee,
                "depth": depth,
                "capacity_usd": depth * hl_book.ask,
            }
        )
    return candidates


def _gross_single(pm_book: TokenBookTop | None, hl_book: HLBookTop | None) -> dict[str, Any]:
    candidates = _single_candidates(pm_book, hl_book)
    if not candidates:
        return {
            "side": "unavailable",
            "gross_edge": None,
            "estimated_fee": None,
            "net_edge": None,
            "depth": None,
            "capacity_usd": None,
        }
    return max(candidates, key=lambda row: row["net_edge"])


def _ask(book: TokenBookTop | HLBookTop | None) -> float | None:
    return book.ask if book else None


def _ask_size(book: TokenBookTop | HLBookTop | None) -> float | None:
    return book.ask_size if book else None


def _complement_for_outcome(
    outcome: str,
    aligned_by_label: dict[str, AlignedOutcome],
) -> dict[str, Any]:
    candidates = _complement_candidates(outcome, aligned_by_label)
    if not candidates:
        return {
            "side": "unavailable",
            "sum_ask": None,
            "gross_edge": None,
            "estimated_fee": None,
            "net_edge": None,
            "depth": None,
            "capacity_usd": None,
        }
    return max(candidates, key=lambda row: row["net_edge"])


def _complement_candidates(
    outcome: str,
    aligned_by_label: dict[str, AlignedOutcome],
) -> list[dict[str, Any]]:
    others = [label for label in _expected_outcomes(aligned_by_label) if label != outcome]
    current = aligned_by_label[outcome]

    candidates: list[dict[str, Any]] = []
    pm_single = _ask(current.pm_yes_book)
    hl_other_asks = [_ask(aligned_by_label[label].hl_yes_book) for label in others]
    if pm_single is not None and all(value is not None for value in hl_other_asks):
        ask_sum = pm_single + sum(value for value in hl_other_asks if value is not None)
        fee = pm_fee(pm_single) + 2 * _hl_taker_fee()
        sizes = [_ask_size(current.pm_yes_book)] + [
            _ask_size(aligned_by_label[label].hl_yes_book) for label in others
        ]
        depth = min(value or 0.0 for value in sizes)
        candidates.append(
            {
                "side": f"buy_pm_{outcome}_yes_buy_hl_{'+'.join(others)}_yes",
                "sum_ask": ask_sum,
                "gross_edge": 1.0 - ask_sum,
                "estimated_fee": fee,
                "net_edge": 1.0 - ask_sum - fee,
                "depth": depth,
                "capacity_usd": depth * ask_sum,
            }
        )

    hl_single = _ask(current.hl_yes_book)
    pm_other_asks = [_ask(aligned_by_label[label].pm_yes_book) for label in others]
    if hl_single is not None and all(value is not None for value in pm_other_asks):
        ask_sum = hl_single + sum(value for value in pm_other_asks if value is not None)
        fee = sum(pm_fee(value) for value in pm_other_asks if value is not None) + _hl_taker_fee()
        sizes = [_ask_size(current.hl_yes_book)] + [
            _ask_size(aligned_by_label[label].pm_yes_book) for label in others
        ]
        depth = min(value or 0.0 for value in sizes)
        candidates.append(
            {
                "side": f"buy_hl_{outcome}_yes_buy_pm_{'+'.join(others)}_yes",
                "sum_ask": ask_sum,
                "gross_edge": 1.0 - ask_sum,
                "estimated_fee": fee,
                "net_edge": 1.0 - ask_sum - fee,
                "depth": depth,
                "capacity_usd": depth * ask_sum,
            }
        )

    return candidates


def _recommend(single_net_edge: float | None, complement_net_edge: float | None, risk: float) -> str:
    best = max(single_net_edge or 0.0, complement_net_edge or 0.0)
    if best <= 0:
        return "ignore"
    if best < 0.002:
        return "observe"
    if best < 0.006 or risk >= 0.7:
        return "paper"
    return "manual_review"


def _recommend_value(net_edge: float | None, risk: float) -> str:
    edge = net_edge or 0.0
    if edge <= 0:
        return "ignore"
    if edge < 0.002:
        return "observe"
    if edge < 0.006 or risk >= 0.7:
        return "paper"
    return "manual_review"


def _risk_for_candidate(candidate: dict[str, Any]) -> float:
    return execution_risk_score(
        strategy_type="match_3way",
        depth=candidate.get("depth"),
        capacity_usd=candidate.get("capacity_usd"),
        missing_price_count=0 if candidate.get("net_edge") is not None else 1,
    )


def _opportunity_row(
    *,
    opportunity_type: str,
    outcome: str,
    candidate: dict[str, Any],
    formula: str,
    fee_formula: str,
    unit: str,
    required_books: list[str],
    rule_match_score: float,
    notes: str,
) -> dict[str, Any]:
    risk = _risk_for_candidate(candidate)
    return {
        "opportunity_type": opportunity_type,
        "outcome": outcome,
        "side": candidate.get("side"),
        "formula": formula,
        "fee_formula": fee_formula,
        "unit": unit,
        "required_books": required_books,
        "gross": candidate.get("gross_edge"),
        "estimated_fee": candidate.get("estimated_fee"),
        "net": candidate.get("net_edge"),
        "depth": candidate.get("depth"),
        "rough_capacity_usd": candidate.get("capacity_usd"),
        "sum_ask": candidate.get("sum_ask"),
        "rule_match_score": rule_match_score,
        "execution_risk_score": risk,
        "recommendation": _recommend_value(candidate.get("net_edge"), risk),
        "notes": notes,
    }


def _direct_no_candidates(
    outcome: str,
    aligned_by_label: dict[str, AlignedOutcome],
) -> list[dict[str, Any]]:
    current = aligned_by_label[outcome]
    candidates: list[dict[str, Any]] = []
    pm_yes = _ask(current.pm_yes_book)
    hl_no = _ask(current.hl_no_book)
    if pm_yes is not None and hl_no is not None:
        sum_ask = pm_yes + hl_no
        fee = pm_fee(pm_yes) + _hl_taker_fee()
        depth = min(_ask_size(current.pm_yes_book) or 0.0, _ask_size(current.hl_no_book) or 0.0)
        candidates.append(
            {
                "side": f"buy_pm_{outcome}_yes_buy_hl_{outcome}_no",
                "sum_ask": sum_ask,
                "gross_edge": 1.0 - sum_ask,
                "estimated_fee": fee,
                "net_edge": 1.0 - sum_ask - fee,
                "depth": depth,
                "capacity_usd": depth * sum_ask,
            }
        )
    hl_yes = _ask(current.hl_yes_book)
    pm_no = _ask(current.pm_no_book)
    if hl_yes is not None and pm_no is not None:
        sum_ask = hl_yes + pm_no
        fee = _hl_taker_fee() + pm_fee(pm_no)
        depth = min(_ask_size(current.hl_yes_book) or 0.0, _ask_size(current.pm_no_book) or 0.0)
        candidates.append(
            {
                "side": f"buy_hl_{outcome}_yes_buy_pm_{outcome}_no",
                "sum_ask": sum_ask,
                "gross_edge": 1.0 - sum_ask,
                "estimated_fee": fee,
                "net_edge": 1.0 - sum_ask - fee,
                "depth": depth,
                "capacity_usd": depth * sum_ask,
            }
        )
    return candidates


def _single_venue_diagnostics(aligned: list[AlignedOutcome]) -> list[dict[str, Any]]:
    pm_asks = [_ask(row.pm_yes_book) for row in aligned]
    pm_bids = [row.pm_yes_book.bid if row.pm_yes_book else None for row in aligned]
    hl_asks = [_ask(row.hl_yes_book) for row in aligned]
    hl_bids = [row.hl_yes_book.bid if row.hl_yes_book else None for row in aligned]

    diagnostics: list[dict[str, Any]] = []
    for venue, asks, bids in (
        ("polymarket", pm_asks, pm_bids),
        ("hyperliquid", hl_asks, hl_bids),
    ):
        sum_ask = sum(value for value in asks if value is not None) if all(value is not None for value in asks) else None
        sum_bid = sum(value for value in bids if value is not None) if all(value is not None for value in bids) else None
        diagnostics.append(
            {
                "opportunity_type": "single_venue_three_way_sum_diagnostic",
                "venue": venue,
                "formula": "sum_ask = Argentina_yes_ask + Draw_yes_ask + Austria_yes_ask; deviation_from_1 = sum_ask - 1",
                "bid_formula": "sum_bid = Argentina_yes_bid + Draw_yes_bid + Austria_yes_bid; bid_deviation_from_1 = sum_bid - 1",
                "unit": "USD per 1 three-way complete set diagnostic",
                "sum_ask": sum_ask,
                "deviation_from_1": None if sum_ask is None else sum_ask - 1.0,
                "sum_bid": sum_bid,
                "bid_deviation_from_1": None if sum_bid is None else sum_bid - 1.0,
                "recommendation": "diagnostic_only",
                "notes": "Single-venue three-way sum is monitoring only and not an MVP2 trade recommendation.",
            }
        )
    return diagnostics


def _formula_reference() -> dict[str, Any]:
    return {
        "fee": {
            "pm_fee": "0.03 * price * (1 - price), estimated taker fee",
            "hl_fee": "HL_TAKER_FEE env var, defaults to 0",
        },
        "cross_venue_single_outcome": {
            "unit": "USD per 1 yes share price-comparison unit",
            "buy_pm_yes_sell_hl_yes": "gross = hl_yes_bid - pm_yes_ask; net = gross - pm_fee(pm_yes_ask) - hl_fee",
            "buy_hl_yes_sell_pm_yes": "gross = pm_yes_bid - hl_yes_ask; net = gross - pm_fee(pm_yes_bid) - hl_fee",
            "sell_note": "sell labels are bid-crossing price comparisons, not execution instructions.",
        },
        "cross_venue_direct_no_complete_set": {
            "unit": "USD per 1 cross-venue complete set",
            "pm_yes_hl_no": "gross = 1 - (pm_X_yes_ask + hl_X_no_ask); net = gross - pm_fee(pm_X_yes_ask) - hl_fee",
            "hl_yes_pm_no": "gross = 1 - (hl_X_yes_ask + pm_X_no_ask); net = gross - pm_fee(pm_X_no_ask) - hl_fee",
        },
        "cross_venue_complement_basket": {
            "unit": "USD per 1 three-leg complete set",
            "pm_single_hl_complement": "gross = 1 - (pm_X_yes_ask + hl_Y_yes_ask + hl_Z_yes_ask); net = gross - pm_fee(pm_X_yes_ask) - 2*hl_fee",
            "hl_single_pm_complement": "gross = 1 - (hl_X_yes_ask + pm_Y_yes_ask + pm_Z_yes_ask); net = gross - pm_fee(pm_Y_yes_ask) - pm_fee(pm_Z_yes_ask) - hl_fee",
        },
        "single_venue_three_way_sum_diagnostic": {
            "unit": "USD per 1 venue-local three-way complete set diagnostic",
            "ask": "sum_ask = Argentina_yes_ask + Draw_yes_ask + Austria_yes_ask; deviation = sum_ask - 1",
            "bid": "sum_bid = Argentina_yes_bid + Draw_yes_bid + Austria_yes_bid; deviation = sum_bid - 1",
        },
    }


def evaluate_match(
    pm_event_slug: str = "fifwc-arg-aut-2026-06-22",
    hl_question_name: str = DEFAULT_HL_QUESTION_NAME,
) -> MatchEvaluation:
    aligned = _build_alignment(pm_event_slug, hl_question_name)
    aligned_by_label = {row.outcome: row for row in aligned}
    sample_match_key = _sample_match_key(aligned)
    rows: list[EvaluationRow] = []
    opportunity_groups: dict[str, list[dict[str, Any]]] = {
        "cross_venue_single_outcome": [],
        "cross_venue_direct_no_complete_set": [],
        "cross_venue_complement_basket": [],
    }
    for row in aligned:
        single_candidates = _single_candidates(row.pm_yes_book, row.hl_yes_book)
        single = _gross_single(row.pm_yes_book, row.hl_yes_book)
        direct_no_candidates = _direct_no_candidates(row.outcome, aligned_by_label)
        complement_candidates = _complement_candidates(row.outcome, aligned_by_label)
        complement = _complement_for_outcome(row.outcome, aligned_by_label)
        missing_prices = sum(
            1
            for value in (
                row.pm_yes_book.bid if row.pm_yes_book else None,
                row.pm_yes_book.ask if row.pm_yes_book else None,
                row.hl_yes_book.bid if row.hl_yes_book else None,
                row.hl_yes_book.ask if row.hl_yes_book else None,
            )
            if value is None
        )
        depth = single.get("depth")
        capacity = single.get("capacity_usd")
        risk = execution_risk_score(
            strategy_type="match_3way",
            depth=depth,
            capacity_usd=capacity,
            missing_price_count=missing_prices,
        )
        for candidate in single_candidates:
            formula = (
                "gross = hl_yes_bid - pm_yes_ask; net = gross - pm_fee(pm_yes_ask) - hl_fee"
                if candidate.get("side") == "buy_pm_yes_sell_hl_yes"
                else "gross = pm_yes_bid - hl_yes_ask; net = gross - pm_fee(pm_yes_bid) - hl_fee"
            )
            opportunity_groups["cross_venue_single_outcome"].append(
                _opportunity_row(
                    opportunity_type="cross_venue_single_outcome",
                    outcome=row.outcome,
                    candidate=candidate,
                    formula=formula,
                    fee_formula="PM fee estimated by 0.03*p*(1-p); HL fee from HL_TAKER_FEE env, default 0.",
                    unit="USD per 1 yes share price-comparison unit",
                    required_books=["pm_yes_bid/ask", "hl_yes_bid/ask"],
                    rule_match_score=0.90,
                    notes="Top-of-book taker-style spread monitor. sell_* is a price label, not execution instruction.",
                )
            )
        for candidate in direct_no_candidates:
            formula = (
                "gross = 1 - (pm_X_yes_ask + hl_X_no_ask); net = gross - pm_fee(pm_X_yes_ask) - hl_fee"
                if candidate.get("side", "").startswith("buy_pm_")
                else "gross = 1 - (hl_X_yes_ask + pm_X_no_ask); net = gross - pm_fee(pm_X_no_ask) - hl_fee"
            )
            opportunity_groups["cross_venue_direct_no_complete_set"].append(
                _opportunity_row(
                    opportunity_type="cross_venue_direct_no_complete_set",
                    outcome=row.outcome,
                    candidate=candidate,
                    formula=formula,
                    fee_formula="Fee applies to the PM leg with PM fee estimate; HL leg uses HL_TAKER_FEE env, default 0.",
                    unit="USD per 1 cross-venue complete set",
                    required_books=["pm_yes/no ask", "hl_yes/no ask"],
                    rule_match_score=0.90,
                    notes="Price-based complete-set evaluator only; no execution sequencing or inventory checks.",
                )
            )
        for candidate in complement_candidates:
            formula = (
                "gross = 1 - (pm_X_yes_ask + hl_Y_yes_ask + hl_Z_yes_ask); net = gross - pm_fee(pm_X_yes_ask) - 2*hl_fee"
                if candidate.get("side", "").startswith("buy_pm_")
                else "gross = 1 - (hl_X_yes_ask + pm_Y_yes_ask + pm_Z_yes_ask); net = gross - pm_fee(pm_Y_yes_ask) - pm_fee(pm_Z_yes_ask) - hl_fee"
            )
            opportunity_groups["cross_venue_complement_basket"].append(
                _opportunity_row(
                    opportunity_type="cross_venue_complement_basket",
                    outcome=row.outcome,
                    candidate=candidate,
                    formula=formula,
                    fee_formula="PM fee estimate applies to PM legs; HL fee uses HL_TAKER_FEE env, default 0.",
                    unit="USD per 1 three-leg complete set",
                    required_books=["single outcome yes ask", "other two outcomes yes asks"],
                    rule_match_score=0.90,
                    notes="Buy-only cross-venue complement basket evaluator; no multi-leg execution logic.",
                )
            )
        rows.append(
            EvaluationRow(
                sample_match_key=sample_match_key,
                pm_event_slug=pm_event_slug,
                hl_question_name=hl_question_name,
                outcome=row.outcome,
                pm_yes_bid=row.pm_yes_book.bid if row.pm_yes_book else None,
                pm_yes_ask=row.pm_yes_book.ask if row.pm_yes_book else None,
                hl_yes_bid=row.hl_yes_book.bid if row.hl_yes_book else None,
                hl_yes_ask=row.hl_yes_book.ask if row.hl_yes_book else None,
                single_outcome_side=str(single.get("side")),
                single_outcome_gross_edge=single.get("gross_edge"),
                single_outcome_estimated_fee=single.get("estimated_fee"),
                single_outcome_net_edge=single.get("net_edge"),
                single_outcome_depth=single.get("depth"),
                single_outcome_capacity_usd=single.get("capacity_usd"),
                complement_side=str(complement.get("side")),
                complement_sum_ask=complement.get("sum_ask"),
                complement_gross_edge=complement.get("gross_edge"),
                complement_estimated_fee=complement.get("estimated_fee"),
                complement_net_edge=complement.get("net_edge"),
                complement_depth=complement.get("depth"),
                complement_capacity_usd=complement.get("capacity_usd"),
                rule_match_score=0.90,
                rule_match_note=(
                    "PM Moneyline and HL 3-way both resolve on regular 90 minutes plus stoppage time; "
                    "cancellation/fallback wording differs slightly, so not marked 1.00."
                ),
                execution_risk_score=risk,
                recommendation=_recommend(
                    single.get("net_edge"),
                    complement.get("net_edge"),
                    risk,
                ),
                raw={
                    "pm_market_id": row.pm_market_id,
                    "pm_market_slug": row.pm_market_slug,
                    "pm_yes_token": row.pm_yes_token,
                    "pm_no_token": row.pm_no_token,
                    "hl_outcome_id": row.hl_outcome_id,
                    "hl_yes_coin": row.hl_yes_coin,
                    "hl_no_coin": row.hl_no_coin,
                    "fee_note": "PM fee estimated with existing 0.03*p*(1-p); HL fee uses HL_TAKER_FEE env and defaults to 0.",
                    "single_outcome_formula": {
                        "buy_pm_yes_sell_hl_yes": "gross_edge = hl_yes_bid - pm_yes_ask; net_edge = gross_edge - pm_fee(pm_yes_ask) - hl_taker_fee",
                        "buy_hl_yes_sell_pm_yes": "gross_edge = pm_yes_bid - hl_yes_ask; net_edge = gross_edge - pm_fee(pm_yes_bid) - hl_taker_fee",
                        "sell_note": "The sell leg is a price-comparison label for crossing the displayed bid. It is not an execution instruction and may require inventory or venue-specific short/No mechanics.",
                    },
                    "single_outcome_candidates": single_candidates,
                    "single_outcome_best_side_reason": "Selected candidate with maximum net_edge among available single-outcome cross-venue directions.",
                    "direct_no_formula": {
                        "definition": "For each outcome X, direct No complete-set pairs X yes on one venue with X no on the other venue.",
                        "pm_yes_hl_no": "gross_edge = 1 - (pm_X_yes_ask + hl_X_no_ask); net_edge = gross_edge - pm_fee(pm_X_yes_ask) - hl_taker_fee",
                        "hl_yes_pm_no": "gross_edge = 1 - (hl_X_yes_ask + pm_X_no_ask); net_edge = gross_edge - pm_fee(pm_X_no_ask) - hl_taker_fee",
                    },
                    "direct_no_candidates": direct_no_candidates,
                    "complement_formula": {
                        "definition": "For each outcome X, complement is the other two Moneyline outcomes.",
                        "pm_single_hl_complement": "gross_edge = 1 - (pm_X_yes_ask + hl_Y_yes_ask + hl_Z_yes_ask); net_edge = gross_edge - pm_fee(pm_X_yes_ask) - 2*hl_taker_fee",
                        "hl_single_pm_complement": "gross_edge = 1 - (hl_X_yes_ask + pm_Y_yes_ask + pm_Z_yes_ask); net_edge = gross_edge - pm_fee(pm_Y_yes_ask) - pm_fee(pm_Z_yes_ask) - hl_taker_fee",
                    },
                    "complement_candidates": complement_candidates,
                    "complement_best_side_reason": "Selected complement basket with maximum net_edge among the two buy-only cross-venue complete-set candidates.",
                    "pm_rule_text": row.pm_rule_text,
                    "hl_rule_text": row.hl_rule_text,
                },
            )
        )

    sanity = {
        "aligned_outcome_count": len(aligned),
        "contains_expected_outcomes": set(_expected_outcomes(aligned_by_label)).issubset({row.outcome for row in aligned}),
        "all_pm_tokens_present": all(row.pm_yes_token and row.pm_no_token for row in aligned),
        "all_hl_coins_present": all(row.hl_yes_coin and row.hl_no_coin for row in aligned),
        "all_yes_orderbooks_present": all(
            row.pm_yes_book
            and row.hl_yes_book
            and not row.pm_yes_book.error
            and not row.hl_yes_book.error
            for row in aligned
        ),
        "execution_enabled": False,
    }
    return MatchEvaluation(
        evaluated_at=_now_iso(),
        sample_match_key=sample_match_key,
        pm_event_slug=pm_event_slug,
        hl_question_name=hl_question_name,
        aligned_outcomes=aligned,
        rows=rows,
        opportunity_groups=opportunity_groups,
        single_venue_diagnostics=_single_venue_diagnostics(aligned),
        formula_reference=_formula_reference(),
        coverage_scope={
            "stage": "opportunity_evaluation_only",
            "included": [
                f"{sample_match_key} single sample",
                "Moneyline only",
                "top-of-book only",
                "taker-style static opportunity monitor",
                "cross-venue single outcome spreads",
                "cross-venue direct No-token complete sets",
                "cross-venue complement baskets",
                "single-venue three-way sum diagnostics",
            ],
            "excluded": [
                "execution",
                "trade intents",
                "entry/exit rules",
                "S1/S2 state machine",
                "full universe batch scanning",
                "Exact Score/Totals/Spread/Halves",
                "maker orders",
                "deeper book walking",
                "sequencing/inventory/short feasibility checks",
                "single-venue strategy recommendations",
            ],
        },
        sanity_checks=sanity,
        notes=[
            "Single-sample evaluator only; no batch scanning and no execution.",
            "All opportunity rows are monitoring/evaluation rows and do not generate trade intents.",
            "Single-outcome 'sell' directions are price-comparison labels, not execution instructions.",
            "Coverage: Moneyline only, top-of-book only, taker-style static evaluator only.",
            "Single-venue three-way sums are diagnostic only and do not drive recommendations.",
        ],
    )


def write_evaluation_json(output_dir: Path, evaluation: MatchEvaluation) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"pm_hl_1v1_moneyline_{evaluation.pm_event_slug}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_rows(title: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    print(_render_rows(title, columns, rows))


def _render_rows(title: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
    lines = [title]
    if not rows:
        lines.append("  no rows")
        return "\n".join(lines)
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in rows))
        for col in columns
    }
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        lines.append(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))
    return "\n".join(lines)


def _best_group_rows(evaluation: MatchEvaluation, timestamp: str, iteration: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    expected_outcomes = tuple(row.outcome for row in evaluation.aligned_outcomes) or DEFAULT_OUTCOMES
    for group_name, group_rows in evaluation.opportunity_groups.items():
        for outcome in expected_outcomes:
            candidates = [row for row in group_rows if row.get("outcome") == outcome]
            if not candidates:
                continue
            best = max(candidates, key=lambda row: row.get("net") if row.get("net") is not None else -999)
            rows.append(
                {
                    "timestamp": timestamp,
                    "iteration": iteration,
                    "outcome": outcome,
                    "opportunity_type": group_name,
                    "best_side": best.get("side"),
                    "gross": best.get("gross"),
                    "fee": best.get("estimated_fee"),
                    "net": best.get("net"),
                    "rough_capacity_usd": best.get("rough_capacity_usd"),
                    "recommendation": best.get("recommendation"),
                }
            )
    return rows


def _best_monitor_rows(
    evaluation: MatchEvaluation,
    group_name: str,
    timestamp: str,
    iteration: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    expected_outcomes = tuple(row.outcome for row in evaluation.aligned_outcomes) or DEFAULT_OUTCOMES
    for outcome in expected_outcomes:
        candidates = [
            row
            for row in evaluation.opportunity_groups.get(group_name, [])
            if row.get("outcome") == outcome
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda row: row.get("net") if row.get("net") is not None else -999)
        rows.append(
            {
                "timestamp": timestamp,
                "iteration": iteration,
                "outcome": outcome,
                "side": best.get("side"),
                "gross": best.get("gross"),
                "fee": best.get("estimated_fee"),
                "net": best.get("net"),
                "depth": best.get("depth"),
                "capacity_usd": best.get("rough_capacity_usd"),
                "rec": best.get("recommendation"),
                "op_group": group_name,
                "note": best.get("notes"),
            }
        )
    return rows


def _all_monitor_rows(
    evaluation: MatchEvaluation,
    group_name: str,
    timestamp: str,
    iteration: int,
) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": timestamp,
            "iteration": iteration,
            "outcome": row.get("outcome"),
            "side": row.get("side"),
            "sum_ask": row.get("sum_ask"),
            "gross": row.get("gross"),
            "fee": row.get("estimated_fee"),
            "net": row.get("net"),
            "depth": row.get("depth"),
            "capacity_usd": row.get("rough_capacity_usd"),
            "rec": row.get("recommendation"),
            "op_group": group_name,
            "note": row.get("notes"),
        }
        for row in evaluation.opportunity_groups.get(group_name, [])
    ]


def _diagnostic_rows(evaluation: MatchEvaluation, timestamp: str, iteration: int) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": timestamp,
            "iteration": iteration,
            "venue": row.get("venue"),
            "sum_ask": row.get("sum_ask"),
            "sum_bid": row.get("sum_bid"),
            "sum_ask_minus_1": row.get("deviation_from_1"),
            "sum_bid_minus_1": row.get("bid_deviation_from_1"),
            "note": row.get("notes"),
        }
        for row in evaluation.single_venue_diagnostics
    ]


def _write_monitor_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_monitor_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


MONITOR_CSV_FIELDS = [
    "timestamp",
    "timestamp_utc8",
    "iteration",
    "op_group",
    "outcome_or_condition",
    "side",
    "gross",
    "fee",
    "net",
    "edge",
    "positive_flag",
    "depth",
    "capacity_usd",
    "sum_ask",
    "sum_bid",
    "rec",
    "est_profit_20_shares",
    "est_portfolio_return_low_pct",
    "est_portfolio_return_high_pct",
    "note",
]


def _init_monitor_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MONITOR_CSV_FIELDS)
        writer.writeheader()


def _timestamp_utc8(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
    except ValueError:
        return ""


def _review_profit_fields(edge: float | None) -> dict[str, Any]:
    if edge is None:
        return {
            "edge": None,
            "positive_flag": False,
            "est_profit_20_shares": None,
            "est_portfolio_return_low_pct": None,
            "est_portfolio_return_high_pct": None,
        }
    profit = edge * 20.0
    return {
        "edge": edge,
        "positive_flag": edge > 0,
        "est_profit_20_shares": profit,
        "est_portfolio_return_low_pct": profit / 108.0 * 100.0,
        "est_portfolio_return_high_pct": profit / 120.0 * 100.0,
    }


def _csv_opportunity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        edge = row.get("net")
        out.append({
            "timestamp": row.get("timestamp"),
            "timestamp_utc8": _timestamp_utc8(row.get("timestamp")),
            "iteration": row.get("iteration"),
            "op_group": row.get("op_group"),
            "outcome_or_condition": row.get("outcome"),
            "side": row.get("side"),
            "gross": row.get("gross"),
            "fee": row.get("fee"),
            "net": row.get("net"),
            **_review_profit_fields(edge),
            "depth": row.get("depth"),
            "capacity_usd": row.get("capacity_usd"),
            "sum_ask": row.get("sum_ask"),
            "sum_bid": None,
            "rec": row.get("rec"),
            "note": row.get("note"),
        })
    return out


def _csv_diagnostic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        for condition, edge in (
            ("sum_ask_minus_1 < 0", None if row.get("sum_ask") is None else 1.0 - row.get("sum_ask")),
            ("sum_bid_minus_1 > 0", None if row.get("sum_bid") is None else row.get("sum_bid") - 1.0),
        ):
            out.append({
                "timestamp": row.get("timestamp"),
                "timestamp_utc8": _timestamp_utc8(row.get("timestamp")),
                "iteration": row.get("iteration"),
                "op_group": "single_venue_three_way_sum_diagnostic",
                "outcome_or_condition": f"{row.get('venue')} {condition}",
                "side": row.get("venue"),
                "gross": None,
                "fee": None,
                "net": None,
                **_review_profit_fields(edge),
                "depth": None,
                "capacity_usd": None,
                "sum_ask": row.get("sum_ask"),
                "sum_bid": row.get("sum_bid"),
                "rec": "diagnostic_only",
                "note": row.get("note"),
            })
    return out


def _append_monitor_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MONITOR_CSV_FIELDS)
        writer.writerows(rows)


def monitor_match(
    *,
    output_dir: Path,
    pm_event_slug: str = "fifwc-arg-aut-2026-06-22",
    hl_question_name: str = DEFAULT_HL_QUESTION_NAME,
    duration_minutes: float = 10.0,
    interval_seconds: int = 30,
    output_label: str | None = None,
) -> Path:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    planned_iterations = max(1, int((duration_minutes * 60 + interval_seconds - 1) // interval_seconds))
    started_at = _now_iso()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_stem = output_label or pm_event_slug
    output_path = output_dir / f"pm_hl_1v1_moneyline_monitor_{output_stem}_{stamp}.json"
    csv_path = output_dir / f"pm_hl_1v1_moneyline_monitor_{output_stem}_{stamp}.csv"
    text_log_path = output_dir / f"pm_hl_mvp2_overnight_monitor_{output_stem}_{stamp}.log"
    payload: dict[str, Any] = {
        "started_at": started_at,
        "completed_at": None,
        "pm_event_slug": pm_event_slug,
        "hl_question_name": hl_question_name,
        "duration_minutes": duration_minutes,
        "interval_seconds": interval_seconds,
        "planned_iterations": planned_iterations,
        "completed_iterations": 0,
        "snapshots": [],
        "warnings": [],
        "execution_enabled": False,
        "csv_path": str(csv_path),
        "text_log_path": str(text_log_path),
    }
    _write_monitor_json(output_path, payload)
    _init_monitor_csv(csv_path)

    start_text = "\n".join(
        [
            "PM-HL 1v1 Moneyline monitor smoke test (READ ONLY)",
            f"test_start_time={started_at} duration_minutes={duration_minutes} "
            f"interval_seconds={interval_seconds} planned_iterations={planned_iterations}",
            f"pm_event_slug={pm_event_slug} hl_question_name={hl_question_name}",
            f"JSON: {output_path}",
            f"CSV: {csv_path}",
            f"TEXT_LOG: {text_log_path}",
        ]
    )
    print(start_text)
    _append_monitor_text(text_log_path, start_text)
    sys.stdout.flush()

    op_columns = [
        "outcome",
        "side",
        "gross",
        "fee",
        "net",
        "depth",
        "capacity_usd",
        "rec",
    ]
    complement_columns = ["outcome", "side", "sum_ask", "gross", "fee", "net", "depth", "capacity_usd", "rec"]
    diagnostic_columns = [
        "venue",
        "sum_ask",
        "sum_ask_minus_1",
        "sum_bid",
        "sum_bid_minus_1",
        "note",
    ]

    for iteration in range(1, planned_iterations + 1):
        ts = _now_iso()
        header = f"=== iteration {iteration}/{planned_iterations} timestamp={ts} ==="
        try:
            evaluation = evaluate_match(pm_event_slug, hl_question_name)
            op1_rows = _best_monitor_rows(evaluation, "cross_venue_direct_no_complete_set", ts, iteration)
            op2_rows = _best_monitor_rows(evaluation, "cross_venue_single_outcome", ts, iteration)
            op3_rows = _all_monitor_rows(evaluation, "cross_venue_complement_basket", ts, iteration)
            diagnostics = _diagnostic_rows(evaluation, ts, iteration)
            opportunity_rows = op1_rows + op2_rows + op3_rows
            iteration_text = "\n\n".join(
                [
                    header,
                    _render_rows("op1 = cross_venue_direct_no_complete_set", op_columns, op1_rows),
                    _render_rows("op2 = cross_venue_single_outcome", op_columns, op2_rows),
                    _render_rows("op3 = cross_venue_complement_basket", complement_columns, op3_rows),
                    _render_rows("op4 = single_venue_three_way_sum_diagnostic", diagnostic_columns, diagnostics),
                ]
            )
            print("\n" + iteration_text)
            _append_monitor_text(text_log_path, "\n" + iteration_text)
            _append_monitor_csv(
                csv_path,
                _csv_opportunity_rows(opportunity_rows) + _csv_diagnostic_rows(diagnostics),
            )
            payload["snapshots"].append(
                {
                    "timestamp": ts,
                    "iteration": iteration,
                    "status": "ok",
                    "opportunity_rows": opportunity_rows,
                    "op1_direct_no_complete_set": op1_rows,
                    "op2_single_outcome": op2_rows,
                    "op3_complement_basket": op3_rows,
                    "single_venue_diagnostics": diagnostics,
                    "evaluation": evaluation.to_dict(),
                }
            )
            payload["completed_iterations"] = iteration
        except Exception as exc:
            warning = f"iteration={iteration} timestamp={ts} warning={str(exc)[:300]}"
            print(f"WARN: {warning}")
            _append_monitor_text(text_log_path, f"\n{header}\nWARN: {warning}")
            payload["warnings"].append(warning)
            payload["snapshots"].append(
                {
                    "timestamp": ts,
                    "iteration": iteration,
                    "status": "warning",
                    "error": str(exc)[:500],
                }
            )
        _write_monitor_json(output_path, payload)
        sys.stdout.flush()
        if iteration < planned_iterations:
            time.sleep(interval_seconds)

    completed_at = _now_iso()
    payload["completed_at"] = completed_at
    _write_monitor_json(output_path, payload)
    completed_text = (
        f"\nmonitor completed completed_at={completed_at} "
        f"completed_iterations={payload['completed_iterations']} warnings={len(payload['warnings'])}"
    )
    print(completed_text)
    print(f"JSON: {output_path}")
    print(f"CSV: {csv_path}")
    print(f"TEXT_LOG: {text_log_path}")
    _append_monitor_text(
        text_log_path,
        f"{completed_text}\nJSON: {output_path}\nCSV: {csv_path}\nTEXT_LOG: {text_log_path}",
    )
    sys.stdout.flush()
    return output_path


def print_evaluation(evaluation: MatchEvaluation) -> None:
    print("PM-HL 1v1 Moneyline evaluator (READ ONLY)")
    print(f"evaluated_at={evaluation.evaluated_at}")
    print(
        f"sample_match_key={evaluation.sample_match_key} "
        f"pm_event_slug={evaluation.pm_event_slug} "
        f"hl_question_name={evaluation.hl_question_name}"
    )
    print(f"stage={evaluation.coverage_scope.get('stage')}")
    print(f"sanity={evaluation.sanity_checks}")
    columns = [
        "outcome",
        "pm_yes_bid",
        "pm_yes_ask",
        "hl_yes_bid",
        "hl_yes_ask",
        "single_outcome_side",
        "single_outcome_net_edge",
        "single_outcome_depth",
        "complement_side",
        "complement_sum_ask",
        "complement_net_edge",
        "rule_match_score",
        "execution_risk_score",
        "recommendation",
    ]
    dict_rows = [asdict(row) for row in evaluation.rows]
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in dict_rows))
        for col in columns
    }
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    print(header)
    print("-" * len(header))
    for row in dict_rows:
        print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))
    print("\nTransparent details:")
    for row in evaluation.rows:
        print(f"\n{row.outcome}")
        print("  single outcome candidates:")
        for candidate in row.raw.get("single_outcome_candidates", []):
            print(
                "   - "
                f"{candidate.get('side')}: gross={_fmt(candidate.get('gross_edge'))} "
                f"fee={_fmt(candidate.get('estimated_fee'))} "
                f"net={_fmt(candidate.get('net_edge'))} "
                f"depth={_fmt(candidate.get('depth'))}"
            )
        print(f"    best side: {row.single_outcome_side} ({row.raw.get('single_outcome_best_side_reason')})")
        print("  complement candidates:")
        for candidate in row.raw.get("complement_candidates", []):
            print(
                "   - "
                f"{candidate.get('side')}: sum_ask={_fmt(candidate.get('sum_ask'))} "
                f"gross={_fmt(candidate.get('gross_edge'))} "
                f"fee={_fmt(candidate.get('estimated_fee'))} "
                f"net={_fmt(candidate.get('net_edge'))} "
                f"depth={_fmt(candidate.get('depth'))}"
            )
        print(f"    best complement: {row.complement_side} ({row.raw.get('complement_best_side_reason')})")
        best_net = max(row.single_outcome_net_edge or 0.0, row.complement_net_edge or 0.0)
        print(
            "  recommendation reason: "
            f"best_net={_fmt(best_net)}, risk={_fmt(row.execution_risk_score)}, "
            f"recommendation={row.recommendation}"
        )

    print("\nOpportunity groups:")
    group_columns = [
        "outcome",
        "side",
        "gross",
        "estimated_fee",
        "net",
        "depth",
        "rough_capacity_usd",
        "recommendation",
    ]
    for group_name, opportunities in evaluation.opportunity_groups.items():
        print(f"\n[{group_name}]")
        if not opportunities:
            print("  no rows")
            continue
        widths = {
            col: max(len(col), *(len(_fmt(row.get(col))) for row in opportunities))
            for col in group_columns
        }
        header = " | ".join(col.ljust(widths[col]) for col in group_columns)
        print(header)
        print("-" * len(header))
        for row in opportunities:
            print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in group_columns))

    print("\nSingle-venue three-way sum diagnostics:")
    diagnostic_columns = [
        "venue",
        "sum_ask",
        "deviation_from_1",
        "sum_bid",
        "bid_deviation_from_1",
        "recommendation",
    ]
    diagnostics = evaluation.single_venue_diagnostics
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in diagnostics))
        for col in diagnostic_columns
    }
    header = " | ".join(col.ljust(widths[col]) for col in diagnostic_columns)
    print(header)
    print("-" * len(header))
    for row in diagnostics:
        print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in diagnostic_columns))

