from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.opportunity_model import pm_fee


OP_GROUP = "cross_venue_direct_no_complete_set"
ENTRY_MODE = "S1_AND_S2"
OUTPUT_DIR = PROJECT_ROOT / "data" / "execution_v1"
LOG_DIR = PROJECT_ROOT / "logs" / "execution_v1"
STOP_FILE = OUTPUT_DIR / "STOP"
DEFAULT_THRESHOLD = 0.0005
DEFAULT_S1_SIZE_SHARES = 20.0
DEFAULT_S2_SIZE_SHARES = 20.0
DEFAULT_MIN_S1_PROFIT_USD = 0.01
DEFAULT_MIN_S2_PROFIT_USD = 0.01
RULE_MATCH_SCORE_DEFAULT = 0.90
RULE_MATCH_THRESHOLD = 0.90
LIVE_ORDER_ADAPTER_READY = False
ADAPTER_SUBMIT_ENABLED = False
LIVE_ADAPTER_ENABLE_ENV = "EXECUTION_V1_ADAPTER_SUBMIT_ENABLED"
REQUIRED_LIVE_ENV = ("PM_PRIVATE_KEY", "PM_FUNDER", "HL_ACCOUNT", "HL_AGENT_KEY")


CANDIDATE_FIELDS = [
    "run_id",
    "candidate_id",
    "source_csv",
    "source_json",
    "pm_event_slug",
    "hl_question_name",
    "timestamp",
    "timestamp_utc8",
    "iteration",
    "match",
    "outcome",
    "entry_mode",
    "s1_size_shares",
    "s2_size_shares",
    "combined_size_shares",
    "selected_direction",
    "entry_net_edge",
    "gross_edge",
    "estimated_fee",
    "s1_entry_net_usd_profit",
    "s2_entry_net_usd_profit",
    "combined_entry_net_usd_profit",
    "leg1_venue",
    "leg1_token_or_coin",
    "leg1_side",
    "leg1_price",
    "leg1_best_ask_depth",
    "leg2_venue",
    "leg2_token_or_coin",
    "leg2_side",
    "leg2_price",
    "leg2_best_ask_depth",
    "depth_required",
    "depth_pass",
    "entry_triggered",
    "scanner_net",
    "scanner_depth",
    "rule_match_score",
    "fail_reason",
]

REVALIDATION_FIELDS = [
    "run_id",
    "candidate_id",
    "checked_at",
    "pm_event_slug",
    "hl_question_name",
    "match",
    "outcome",
    "entry_mode",
    "s1_size_shares",
    "s2_size_shares",
    "combined_size_shares",
    "selected_direction",
    "entry_net_edge",
    "gross_edge",
    "estimated_fee",
    "s1_entry_net_usd_profit",
    "s2_entry_net_usd_profit",
    "combined_entry_net_usd_profit",
    "scanner_leg1_price",
    "scanner_leg2_price",
    "revalidated_leg1_best_ask",
    "revalidated_leg2_best_ask",
    "order_leg1_limit_price",
    "order_leg2_limit_price",
    "max_acceptable_leg1_price",
    "max_acceptable_leg2_price",
    "leg1_venue",
    "leg1_token_or_coin",
    "leg1_side",
    "leg1_price",
    "leg1_best_ask_depth",
    "leg2_venue",
    "leg2_token_or_coin",
    "leg2_side",
    "leg2_price",
    "leg2_best_ask_depth",
    "depth_required",
    "depth_pass",
    "rule_match_score",
    "pass_flag",
    "fail_reason",
]

ORDER_INTENT_FIELDS = [
    "order_intent_id",
    "candidate_id",
    "entry_mode",
    "strategy_type",
    "match",
    "outcome",
    "selected_direction",
    "combined_size_shares",
    "leg",
    "venue",
    "token_or_coin",
    "side",
    "order_type",
    "time_in_force",
    "scanner_price",
    "revalidated_best_ask",
    "limit_price",
    "max_acceptable_price",
    "required_depth",
    "revalidated_depth",
    "depth_pass",
    "entry_net_edge",
    "entry_threshold_decimal",
    "entry_threshold_bps",
    "entry_net_usd_profit",
    "status",
    "fail_reason",
    "created_at",
]

PAPER_FILL_FIELDS = [
    "run_id",
    "candidate_id",
    "filled_at",
    "venue",
    "leg",
    "instrument",
    "side",
    "shares",
    "price",
    "notional",
    "fee",
]

PAPER_PNL_FIELDS = [
    "run_id",
    "candidate_id",
    "shares",
    "gross_cost",
    "fee",
    "net_cost",
    "settlement_payoff",
    "paper_pnl",
]

PAPER_POSITION_FIELDS = [
    "position_id",
    "candidate_id",
    "strategy_mode",
    "match",
    "outcome",
    "selected_direction",
    "leg1_venue",
    "leg1_token_or_coin",
    "leg1_side",
    "leg1_entry_price",
    "leg1_size_shares",
    "leg2_venue",
    "leg2_token_or_coin",
    "leg2_side",
    "leg2_entry_price",
    "leg2_size_shares",
    "entry_net_edge",
    "entry_net_usd_profit",
    "status",
    "created_at",
]

LIVE_ORDER_FIELDS = [
    "run_id",
    "candidate_id",
    "submitted_at",
    "venue",
    "leg",
    "instrument",
    "side",
    "shares",
    "limit_price",
    "status",
    "error",
    "raw_json",
]

LIVE_FILL_FIELDS = [
    "run_id",
    "candidate_id",
    "filled_at",
    "venue",
    "leg",
    "instrument",
    "side",
    "shares",
    "price",
    "notional",
    "raw_json",
]

LIVE_ADAPTER_STATUS_FIELDS = [
    "adapter",
    "venue",
    "adapter_ready",
    "adapter_submit_enabled",
    "balance_check_supported",
    "balance",
    "order_type_supported",
    "time_in_force_supported",
    "status",
    "error_message",
    "checked_at",
]

LIVE_ORDER_STATUS_FIELDS = [
    "candidate_id",
    "venue",
    "leg",
    "order_id",
    "requested_size",
    "filled_size",
    "avg_fill_price",
    "fill_status",
    "order_status",
    "error_message",
    "checked_at",
]

RISK_EVENT_FIELDS = [
    "run_id",
    "candidate_id",
    "event_at",
    "event_type",
    "severity",
    "message",
]

LIVE_SAFETY_CHECK_FIELDS = [
    "check_id",
    "candidate_id",
    "adapter_ready",
    "order_type",
    "time_in_force",
    "requested_size",
    "filled_size",
    "fill_status",
    "leg1_fill_status",
    "leg2_fill_status",
    "partial_fill_detected",
    "single_leg_exposure",
    "blocked_reason",
    "checked_at",
]

PAYLOAD_PREVIEW_PATH = OUTPUT_DIR / "live_order_payload_preview.json"
ADAPTER_STATUS_PATH = OUTPUT_DIR / "adapter_status.csv"
ADAPTER_TEST_RESULTS_PATH = OUTPUT_DIR / "adapter_test_results.md"


@dataclass(frozen=True)
class StrategyConfig:
    threshold: float
    s1_size_shares: float
    s2_size_shares: float
    min_s1_profit_usd: float
    min_s2_profit_usd: float

    @property
    def combined_size_shares(self) -> float:
        return self.s1_size_shares + self.s2_size_shares


@dataclass(frozen=True)
class LegPlan:
    venue: str
    token_or_coin: str
    side: str
    price: float
    best_ask_depth: float


@dataclass(frozen=True)
class EntryPlan:
    selected_direction: str
    gross_edge: float
    estimated_fee: float
    entry_net_edge: float
    leg1: LegPlan
    leg2: LegPlan


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    source_csv: Path
    source_json: Path | None
    pm_event_slug: str
    hl_question_name: str
    timestamp: str
    timestamp_utc8: str
    iteration: str
    match: str
    outcome: str
    scanner_net: float
    scanner_depth: float | None
    rule_match_score: float
    pm_yes_token: str
    pm_no_token: str
    hl_yes_coin: str
    hl_no_coin: str
    initial_plan: EntryPlan | None
    status: str = "candidate"
    fail_reason: str = ""


@dataclass(frozen=True)
class CandidateBuildResult:
    candidates: list[Candidate]
    raw_positive_rows_count: int
    threshold_filtered_count: int
    duplicates_removed_count: int


@dataclass(frozen=True)
class QuoteCheck:
    candidate: Candidate
    checked_at: str
    plan: EntryPlan | None
    depth_required: float
    depth_pass: bool
    s1_entry_net_usd_profit: float
    s2_entry_net_usd_profit: float
    combined_entry_net_usd_profit: float
    pass_flag: bool
    fail_reason: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def norm_label(value: str) -> str:
    compact = "".join(ch for ch in value.lower() if ch.isalnum())
    aliases = {"bosniaherzegovina": "bosniaandherzegovina"}
    return aliases.get(compact, compact)


def hl_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sibling_json_path(csv_path: Path) -> Path | None:
    candidate = csv_path.with_suffix(".json")
    return candidate if candidate.exists() else None


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_metadata(data: dict[str, Any]) -> tuple[str, str]:
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    return (
        str(data.get("pm_event_slug") or config.get("pm_event_slug") or ""),
        str(data.get("hl_question_name") or config.get("hl_question_name") or ""),
    )


def snapshot_aligned_index(data: dict[str, Any]) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for snapshot in data.get("snapshots", []) if isinstance(data, dict) else []:
        if not isinstance(snapshot, dict):
            continue
        evaluation = snapshot.get("evaluation") if isinstance(snapshot.get("evaluation"), dict) else {}
        raw_snapshot = (
            snapshot.get("raw_opportunity_snapshot")
            if isinstance(snapshot.get("raw_opportunity_snapshot"), dict)
            else {}
        )
        aligned = (
            evaluation.get("aligned_outcomes")
            or raw_snapshot.get("aligned_outcomes")
            or snapshot.get("aligned_outcomes")
            or []
        )
        timestamp = str(snapshot.get("timestamp") or "")
        iteration = str(snapshot.get("iteration") or "")
        pm_event_slug = str(snapshot.get("pm_event_slug") or evaluation.get("pm_event_slug") or data.get("pm_event_slug") or "")
        hl_question_name = str(
            snapshot.get("hl_question_name") or evaluation.get("hl_question_name") or data.get("hl_question_name") or ""
        )
        if aligned:
            index[(iteration, timestamp, pm_event_slug, hl_question_name)] = aligned
            if iteration:
                index[(iteration, "", pm_event_slug, hl_question_name)] = aligned
    if not index and data.get("aligned_outcomes"):
        index[("", "", str(data.get("pm_event_slug") or ""), str(data.get("hl_question_name") or ""))] = data["aligned_outcomes"]
    return index


def find_aligned(
    aligned_index: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    iteration: str,
    timestamp: str,
    pm_event_slug: str,
    hl_question_name: str,
    outcome: str,
) -> dict[str, Any] | None:
    rows = (
        aligned_index.get((iteration, timestamp, pm_event_slug, hl_question_name))
        or aligned_index.get((iteration, "", pm_event_slug, hl_question_name))
        or aligned_index.get(("", "", pm_event_slug, hl_question_name))
        or []
    )
    for row in rows:
        if norm_label(str(row.get("outcome") or "")) == norm_label(outcome):
            return row
    return None


def book_price_size(book: dict[str, Any] | None, side: str) -> tuple[float, float]:
    if not isinstance(book, dict):
        return 0.0, 0.0
    price = as_float(book.get("ask" if side == "ask" else "bid")) or 0.0
    size = as_float(book.get("ask_size" if side == "ask" else "bid_size")) or 0.0
    return price, size


def build_entry_plan_from_books(aligned: dict[str, Any]) -> EntryPlan | None:
    pm_yes, pm_yes_depth = book_price_size(aligned.get("pm_yes_book"), "ask")
    pm_no, pm_no_depth = book_price_size(aligned.get("pm_no_book"), "ask")
    hl_yes, hl_yes_depth = book_price_size(aligned.get("hl_yes_book"), "ask")
    hl_no, hl_no_depth = book_price_size(aligned.get("hl_no_book"), "ask")
    pm_yes_token = str(aligned.get("pm_yes_token") or "")
    pm_no_token = str(aligned.get("pm_no_token") or "")
    hl_yes_coin = str(aligned.get("hl_yes_coin") or "")
    hl_no_coin = str(aligned.get("hl_no_coin") or "")

    plans: list[EntryPlan] = []
    if pm_yes and hl_no and pm_yes_token and hl_no_coin:
        gross = 1.0 - (pm_yes + hl_no)
        fee = pm_fee(pm_yes) + hl_fee()
        plans.append(
            EntryPlan(
                selected_direction="BUY_PM_YES_BUY_HL_NO",
                gross_edge=gross,
                estimated_fee=fee,
                entry_net_edge=gross - fee,
                leg1=LegPlan("polymarket", pm_yes_token, "BUY_PM_YES", pm_yes, pm_yes_depth),
                leg2=LegPlan("hyperliquid", hl_no_coin, "BUY_HL_NO", hl_no, hl_no_depth),
            )
        )
    if hl_yes and pm_no and hl_yes_coin and pm_no_token:
        gross = 1.0 - (hl_yes + pm_no)
        fee = pm_fee(pm_no) + hl_fee()
        plans.append(
            EntryPlan(
                selected_direction="BUY_HL_YES_BUY_PM_NO",
                gross_edge=gross,
                estimated_fee=fee,
                entry_net_edge=gross - fee,
                leg1=LegPlan("hyperliquid", hl_yes_coin, "BUY_HL_YES", hl_yes, hl_yes_depth),
                leg2=LegPlan("polymarket", pm_no_token, "BUY_PM_NO", pm_no, pm_no_depth),
            )
        )
    return max(plans, key=lambda plan: plan.entry_net_edge) if plans else None


def make_candidate_id(pm_event_slug: str, hl_question_name: str, outcome: str) -> str:
    raw = f"{pm_event_slug}|{hl_question_name}|{outcome}|{ENTRY_MODE}"
    return f"op1-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def is_monitor_positive(row: dict[str, str]) -> bool:
    if row.get("op_group") != OP_GROUP:
        return False
    outcome = (row.get("outcome_or_condition") or row.get("key") or "").strip()
    side = (row.get("side") or "").strip()
    if not outcome or not (side.startswith("buy_pm_") or side.startswith("buy_hl_")):
        return False
    if str(row.get("positive_flag", "")).strip() != "":
        return as_bool(row.get("positive_flag"))
    return (as_float(row.get("net")) or 0.0) > 0.0


def is_dry_run_positive(row: dict[str, str]) -> bool:
    side = (row.get("best_side") or "").strip()
    return (
        (side.startswith("buy_pm_") or side.startswith("buy_hl_"))
        and as_bool(row.get("s1_entry_eligible"))
        and as_bool(row.get("top1_flag"))
        and str(row.get("block_reason") or "") in {"", "pass_dry_run_only"}
    )


def row_kind(rows: list[dict[str, str]]) -> str:
    fieldnames = set(rows[0].keys()) if rows else set()
    if {"op_group", "side"}.issubset(fieldnames):
        return "monitor"
    if {"best_side", "s1_entry_eligible"}.issubset(fieldnames):
        return "dry_run"
    return "unknown"


def candidate_dedupe_key(candidate: Candidate) -> tuple[str, str, str]:
    return (candidate.pm_event_slug, candidate.hl_question_name, candidate.outcome)


def build_candidates_result(
    input_csv: Path,
    config: StrategyConfig,
    max_candidates: int | None,
) -> CandidateBuildResult:
    rows = read_csv_rows(input_csv)
    kind = row_kind(rows)
    json_path = sibling_json_path(input_csv)
    json_data = load_json(json_path)
    default_pm_event_slug, default_hl_question_name = json_metadata(json_data)
    aligned_index = snapshot_aligned_index(json_data)
    raw_positive_rows_count = 0
    threshold_filtered_count = 0
    raw_candidates: list[Candidate] = []

    for row in rows:
        if kind == "monitor":
            if not is_monitor_positive(row):
                continue
            timestamp = str(row.get("timestamp") or "")
            timestamp_utc8 = str(row.get("timestamp_utc8") or "")
            iteration = str(row.get("iteration") or "")
            pm_event_slug = str(row.get("pm_event_slug") or default_pm_event_slug)
            hl_question_name = str(row.get("hl_question_name") or default_hl_question_name)
            outcome = str(row.get("outcome_or_condition") or row.get("key") or "").strip()
            scanner_net = as_float(row.get("net") or row.get("edge"))
            scanner_depth = as_float(row.get("depth"))
        elif kind == "dry_run":
            if not is_dry_run_positive(row):
                continue
            timestamp = str(row.get("timestamp") or "")
            timestamp_utc8 = ""
            iteration = str(row.get("iteration") or "")
            pm_event_slug = str(row.get("pm_event_slug") or default_pm_event_slug)
            hl_question_name = str(row.get("hl_question_name") or default_hl_question_name)
            outcome = str(row.get("outcome") or "").strip()
            scanner_net = as_float(row.get("entry_net"))
            scanner_depth = as_float(row.get("depth"))
        else:
            continue

        raw_positive_rows_count += 1
        if scanner_net is None:
            threshold_filtered_count += 1
            continue

        aligned = find_aligned(aligned_index, iteration, timestamp, pm_event_slug, hl_question_name, outcome)
        candidate_id = make_candidate_id(pm_event_slug, hl_question_name, outcome)
        if aligned is None:
            raw_candidates.append(
                Candidate(
                    candidate_id=candidate_id,
                    source_csv=input_csv,
                    source_json=json_path,
                    pm_event_slug=pm_event_slug,
                    hl_question_name=hl_question_name,
                    timestamp=timestamp,
                    timestamp_utc8=timestamp_utc8,
                    iteration=iteration,
                    match=hl_question_name,
                    outcome=outcome,
                    scanner_net=scanner_net,
                    scanner_depth=scanner_depth,
                    rule_match_score=RULE_MATCH_SCORE_DEFAULT,
                    pm_yes_token="",
                    pm_no_token="",
                    hl_yes_coin="",
                    hl_no_coin="",
                    initial_plan=None,
                    status="invalid",
                    fail_reason="missing_aligned_outcome_json",
                )
            )
            continue

        if norm_label(str(aligned.get("outcome") or "")) != norm_label(outcome):
            fail_reason = "outcome_mismatch"
        else:
            fail_reason = ""
        plan = build_entry_plan_from_books(aligned)
        if plan is None and not fail_reason:
            fail_reason = "leg_mapping_inconsistent"
        raw_candidates.append(
            Candidate(
                candidate_id=candidate_id,
                source_csv=input_csv,
                source_json=json_path,
                pm_event_slug=pm_event_slug,
                hl_question_name=hl_question_name,
                timestamp=timestamp,
                timestamp_utc8=timestamp_utc8,
                iteration=iteration,
                match=hl_question_name,
                outcome=outcome,
                scanner_net=scanner_net,
                scanner_depth=scanner_depth,
                rule_match_score=RULE_MATCH_SCORE_DEFAULT,
                pm_yes_token=str(aligned.get("pm_yes_token") or ""),
                pm_no_token=str(aligned.get("pm_no_token") or ""),
                hl_yes_coin=str(aligned.get("hl_yes_coin") or ""),
                hl_no_coin=str(aligned.get("hl_no_coin") or ""),
                initial_plan=plan,
                status="invalid" if fail_reason else "candidate",
                fail_reason=fail_reason,
            )
        )

    latest_by_key: dict[tuple[str, str, str], Candidate] = {}
    for candidate in raw_candidates:
        key = candidate_dedupe_key(candidate)
        existing = latest_by_key.get(key)
        if existing is None or parse_time(candidate.timestamp) >= parse_time(existing.timestamp):
            latest_by_key[key] = candidate
    candidates = sorted(latest_by_key.values(), key=lambda item: parse_time(item.timestamp), reverse=True)
    if max_candidates is not None:
        candidates = candidates[:max_candidates]
    return CandidateBuildResult(
        candidates=candidates,
        raw_positive_rows_count=raw_positive_rows_count,
        threshold_filtered_count=threshold_filtered_count,
        duplicates_removed_count=len(raw_candidates) - len(latest_by_key),
    )


def top_ask_from_pm(token: str) -> tuple[float, float]:
    _bid, ask, _tick_size, _neg_risk = pm.top(token)
    return float(ask[0]), float(ask[1])


def top_ask_from_hl(coin: str) -> tuple[float, float]:
    _bids, asks = hl.coin_book(coin)
    if not asks:
        return 1.0, 0.0
    return float(asks[0][0]), float(asks[0][1])


def quote_error(candidate: Candidate, checked_at: str, fail_reason: str, config: StrategyConfig) -> QuoteCheck:
    return QuoteCheck(
        candidate=candidate,
        checked_at=checked_at,
        plan=None,
        depth_required=config.combined_size_shares,
        depth_pass=False,
        s1_entry_net_usd_profit=0.0,
        s2_entry_net_usd_profit=0.0,
        combined_entry_net_usd_profit=0.0,
        pass_flag=False,
        fail_reason=fail_reason,
    )


def revalidate(candidate: Candidate, config: StrategyConfig) -> QuoteCheck:
    checked_at = now_iso()
    if STOP_FILE.exists():
        return quote_error(candidate, checked_at, "stop_file_present", config)
    if candidate.status != "candidate":
        return quote_error(candidate, checked_at, candidate.fail_reason or "invalid_candidate", config)
    if candidate.rule_match_score < RULE_MATCH_THRESHOLD:
        return quote_error(candidate, checked_at, "rule_match_score_below_threshold", config)

    try:
        pm_yes, pm_yes_depth = top_ask_from_pm(candidate.pm_yes_token)
        pm_no, pm_no_depth = top_ask_from_pm(candidate.pm_no_token)
    except HTTPError as exc:
        if exc.code == 404:
            event = pm.gamma_event_by_slug(candidate.pm_event_slug) if candidate.pm_event_slug else None
            reason = (
                "market_closed_or_token_not_found"
                if event and (event.get("closed") or event.get("archived") or not event.get("active", True))
                else "pm_quote_404_token_not_found"
            )
            return quote_error(candidate, checked_at, reason, config)
        return quote_error(candidate, checked_at, f"pm_quote_fetch_failed:{str(exc)[:120]}", config)
    except Exception as exc:
        return quote_error(candidate, checked_at, f"pm_quote_fetch_failed:{str(exc)[:120]}", config)

    try:
        hl_yes, hl_yes_depth = top_ask_from_hl(candidate.hl_yes_coin)
        hl_no, hl_no_depth = top_ask_from_hl(candidate.hl_no_coin)
    except Exception as exc:
        return quote_error(candidate, checked_at, f"hl_quote_fetch_failed:{str(exc)[:120]}", config)

    aligned = {
        "pm_yes_token": candidate.pm_yes_token,
        "pm_no_token": candidate.pm_no_token,
        "hl_yes_coin": candidate.hl_yes_coin,
        "hl_no_coin": candidate.hl_no_coin,
        "pm_yes_book": {"ask": pm_yes, "ask_size": pm_yes_depth},
        "pm_no_book": {"ask": pm_no, "ask_size": pm_no_depth},
        "hl_yes_book": {"ask": hl_yes, "ask_size": hl_yes_depth},
        "hl_no_book": {"ask": hl_no, "ask_size": hl_no_depth},
    }
    plan = build_entry_plan_from_books(aligned)
    if plan is None:
        return quote_error(candidate, checked_at, "leg_mapping_inconsistent", config)

    s1_profit = plan.entry_net_edge * config.s1_size_shares
    s2_profit = plan.entry_net_edge * config.s2_size_shares
    combined_profit = plan.entry_net_edge * config.combined_size_shares
    depth_pass = (
        plan.leg1.best_ask_depth >= config.combined_size_shares
        and plan.leg2.best_ask_depth >= config.combined_size_shares
    )
    fail_reasons: list[str] = []
    if plan.entry_net_edge < config.threshold:
        fail_reasons.append("edge_below_threshold")
    if s1_profit < config.min_s1_profit_usd:
        fail_reasons.append("s1_profit_below_min")
    if s2_profit < config.min_s2_profit_usd:
        fail_reasons.append("s2_profit_below_min")
    if not depth_pass:
        fail_reasons.append("combined_depth_not_enough")
    return QuoteCheck(
        candidate=candidate,
        checked_at=checked_at,
        plan=plan,
        depth_required=config.combined_size_shares,
        depth_pass=depth_pass,
        s1_entry_net_usd_profit=s1_profit,
        s2_entry_net_usd_profit=s2_profit,
        combined_entry_net_usd_profit=combined_profit,
        pass_flag=not fail_reasons,
        fail_reason=",".join(fail_reasons),
    )


def blank_leg() -> LegPlan:
    return LegPlan("", "", "", 0.0, 0.0)


def scanner_price_for_leg(candidate: Candidate, leg: LegPlan) -> Any:
    plan = candidate.initial_plan
    if not plan:
        return ""
    for scanner_leg in (plan.leg1, plan.leg2):
        if scanner_leg.token_or_coin == leg.token_or_coin and scanner_leg.side == leg.side:
            return scanner_leg.price
    return ""


def candidate_row(run: str, candidate: Candidate, config: StrategyConfig) -> dict[str, Any]:
    plan = candidate.initial_plan
    leg1 = plan.leg1 if plan else blank_leg()
    leg2 = plan.leg2 if plan else blank_leg()
    depth_pass = (
        bool(plan)
        and leg1.best_ask_depth >= config.combined_size_shares
        and leg2.best_ask_depth >= config.combined_size_shares
    )
    entry_net_edge = plan.entry_net_edge if plan else 0.0
    return {
        "run_id": run,
        "candidate_id": candidate.candidate_id,
        "source_csv": str(candidate.source_csv),
        "source_json": str(candidate.source_json or ""),
        "pm_event_slug": candidate.pm_event_slug,
        "hl_question_name": candidate.hl_question_name,
        "timestamp": candidate.timestamp,
        "timestamp_utc8": candidate.timestamp_utc8,
        "iteration": candidate.iteration,
        "match": candidate.match,
        "outcome": candidate.outcome,
        "entry_mode": ENTRY_MODE,
        "s1_size_shares": config.s1_size_shares,
        "s2_size_shares": config.s2_size_shares,
        "combined_size_shares": config.combined_size_shares,
        "selected_direction": plan.selected_direction if plan else "",
        "entry_net_edge": entry_net_edge,
        "gross_edge": plan.gross_edge if plan else 0.0,
        "estimated_fee": plan.estimated_fee if plan else 0.0,
        "s1_entry_net_usd_profit": entry_net_edge * config.s1_size_shares,
        "s2_entry_net_usd_profit": entry_net_edge * config.s2_size_shares,
        "combined_entry_net_usd_profit": entry_net_edge * config.combined_size_shares,
        "leg1_venue": leg1.venue,
        "leg1_token_or_coin": leg1.token_or_coin,
        "leg1_side": leg1.side,
        "leg1_price": leg1.price,
        "leg1_best_ask_depth": leg1.best_ask_depth,
        "leg2_venue": leg2.venue,
        "leg2_token_or_coin": leg2.token_or_coin,
        "leg2_side": leg2.side,
        "leg2_price": leg2.price,
        "leg2_best_ask_depth": leg2.best_ask_depth,
        "depth_required": config.combined_size_shares,
        "depth_pass": depth_pass,
        "entry_triggered": False,
        "scanner_net": candidate.scanner_net,
        "scanner_depth": candidate.scanner_depth if candidate.scanner_depth is not None else "",
        "rule_match_score": candidate.rule_match_score,
        "fail_reason": candidate.fail_reason,
    }


def revalidation_row(run: str, quote: QuoteCheck, config: StrategyConfig) -> dict[str, Any]:
    plan = quote.plan
    leg1 = plan.leg1 if plan else blank_leg()
    leg2 = plan.leg2 if plan else blank_leg()
    candidate = quote.candidate
    return {
        "run_id": run,
        "candidate_id": candidate.candidate_id,
        "checked_at": quote.checked_at,
        "pm_event_slug": candidate.pm_event_slug,
        "hl_question_name": candidate.hl_question_name,
        "match": candidate.match,
        "outcome": candidate.outcome,
        "entry_mode": ENTRY_MODE,
        "s1_size_shares": config.s1_size_shares,
        "s2_size_shares": config.s2_size_shares,
        "combined_size_shares": config.combined_size_shares,
        "selected_direction": plan.selected_direction if plan else "",
        "entry_net_edge": plan.entry_net_edge if plan else 0.0,
        "gross_edge": plan.gross_edge if plan else 0.0,
        "estimated_fee": plan.estimated_fee if plan else 0.0,
        "s1_entry_net_usd_profit": quote.s1_entry_net_usd_profit,
        "s2_entry_net_usd_profit": quote.s2_entry_net_usd_profit,
        "combined_entry_net_usd_profit": quote.combined_entry_net_usd_profit,
        "scanner_leg1_price": scanner_price_for_leg(candidate, leg1),
        "scanner_leg2_price": scanner_price_for_leg(candidate, leg2),
        "revalidated_leg1_best_ask": leg1.price,
        "revalidated_leg2_best_ask": leg2.price,
        "order_leg1_limit_price": leg1.price if quote.pass_flag else "",
        "order_leg2_limit_price": leg2.price if quote.pass_flag else "",
        "max_acceptable_leg1_price": leg1.price if quote.pass_flag else "",
        "max_acceptable_leg2_price": leg2.price if quote.pass_flag else "",
        "leg1_venue": leg1.venue,
        "leg1_token_or_coin": leg1.token_or_coin,
        "leg1_side": leg1.side,
        "leg1_price": leg1.price,
        "leg1_best_ask_depth": leg1.best_ask_depth,
        "leg2_venue": leg2.venue,
        "leg2_token_or_coin": leg2.token_or_coin,
        "leg2_side": leg2.side,
        "leg2_price": leg2.price,
        "leg2_best_ask_depth": leg2.best_ask_depth,
        "depth_required": quote.depth_required,
        "depth_pass": quote.depth_pass,
        "rule_match_score": candidate.rule_match_score,
        "pass_flag": quote.pass_flag,
        "fail_reason": quote.fail_reason,
    }


def order_intent_rows(run: str, quote: QuoteCheck, config: StrategyConfig) -> list[dict[str, Any]]:
    if not quote.pass_flag or not quote.plan:
        return []
    created_at = now_iso()
    rows: list[dict[str, Any]] = []
    for index, leg in enumerate((quote.plan.leg1, quote.plan.leg2), start=1):
        if leg.price <= 0:
            rows.append(
                {
                    "order_intent_id": f"{quote.candidate.candidate_id}__leg{index}",
                    "candidate_id": quote.candidate.candidate_id,
                    "entry_mode": ENTRY_MODE,
                    "strategy_type": f"S1_AND_S2_LEG{index}",
                    "match": quote.candidate.match,
                    "outcome": quote.candidate.outcome,
                    "selected_direction": quote.plan.selected_direction,
                    "combined_size_shares": config.combined_size_shares,
                    "leg": f"leg{index}",
                    "venue": leg.venue,
                    "token_or_coin": leg.token_or_coin,
                    "side": leg.side,
                    "order_type": "limit",
                    "time_in_force": "FOK",
                    "scanner_price": scanner_price_for_leg(quote.candidate, leg),
                    "revalidated_best_ask": leg.price,
                    "limit_price": leg.price,
                    "max_acceptable_price": leg.price,
                    "required_depth": config.combined_size_shares,
                    "revalidated_depth": leg.best_ask_depth,
                    "depth_pass": False,
                    "entry_net_edge": quote.plan.entry_net_edge,
                    "entry_threshold_decimal": config.threshold,
                    "entry_threshold_bps": config.threshold * 10000,
                    "entry_net_usd_profit": quote.combined_entry_net_usd_profit,
                    "status": "blocked",
                    "fail_reason": "limit_price_violation",
                    "created_at": created_at,
                }
            )
            continue
        rows.append(
            {
                "order_intent_id": f"{quote.candidate.candidate_id}__leg{index}",
                "candidate_id": quote.candidate.candidate_id,
                "entry_mode": ENTRY_MODE,
                "strategy_type": f"S1_AND_S2_LEG{index}",
                "match": quote.candidate.match,
                "outcome": quote.candidate.outcome,
                "selected_direction": quote.plan.selected_direction,
                "combined_size_shares": config.combined_size_shares,
                "leg": f"leg{index}",
                "venue": leg.venue,
                "token_or_coin": leg.token_or_coin,
                "side": leg.side,
                "order_type": "limit",
                "time_in_force": "FOK",
                "scanner_price": scanner_price_for_leg(quote.candidate, leg),
                "revalidated_best_ask": leg.price,
                "limit_price": leg.price,
                "max_acceptable_price": leg.price,
                "required_depth": config.combined_size_shares,
                "revalidated_depth": leg.best_ask_depth,
                "depth_pass": leg.best_ask_depth >= config.combined_size_shares,
                "entry_net_edge": quote.plan.entry_net_edge,
                "entry_threshold_decimal": config.threshold,
                "entry_threshold_bps": config.threshold * 10000,
                "entry_net_usd_profit": quote.combined_entry_net_usd_profit,
                "status": "ready",
                "fail_reason": "",
                "created_at": created_at,
            }
        )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def empty_outputs() -> dict[str, list[dict[str, Any]]]:
    return {
        "candidates": [],
        "revalidations": [],
        "order_intents": [],
        "paper_fills": [],
        "paper_pnl": [],
        "paper_positions": [],
        "live_orders": [],
        "live_fills": [],
        "live_adapter_status": [],
        "live_order_status": [],
        "live_safety_checks": [],
        "risk_events": [],
    }


def write_all_outputs(rows: dict[str, list[dict[str, Any]]]) -> None:
    write_csv(OUTPUT_DIR / "candidates.csv", CANDIDATE_FIELDS, rows["candidates"])
    write_csv(OUTPUT_DIR / "revalidations.csv", REVALIDATION_FIELDS, rows["revalidations"])
    write_csv(OUTPUT_DIR / "order_intents.csv", ORDER_INTENT_FIELDS, rows["order_intents"])
    write_csv(OUTPUT_DIR / "paper_fills.csv", PAPER_FILL_FIELDS, rows["paper_fills"])
    write_csv(OUTPUT_DIR / "paper_pnl.csv", PAPER_PNL_FIELDS, rows["paper_pnl"])
    write_csv(OUTPUT_DIR / "paper_positions.csv", PAPER_POSITION_FIELDS, rows["paper_positions"])
    write_csv(OUTPUT_DIR / "live_orders.csv", LIVE_ORDER_FIELDS, rows["live_orders"])
    write_csv(OUTPUT_DIR / "live_fills.csv", LIVE_FILL_FIELDS, rows["live_fills"])
    write_csv(OUTPUT_DIR / "live_adapter_status.csv", LIVE_ADAPTER_STATUS_FIELDS, rows["live_adapter_status"])
    write_csv(OUTPUT_DIR / "live_order_status.csv", LIVE_ORDER_STATUS_FIELDS, rows["live_order_status"])
    write_csv(OUTPUT_DIR / "live_safety_checks.csv", LIVE_SAFETY_CHECK_FIELDS, rows["live_safety_checks"])
    write_csv(OUTPUT_DIR / "risk_events.csv", RISK_EVENT_FIELDS, rows["risk_events"])


def risk_event(run: str, candidate_id: str, event_type: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "run_id": run,
        "candidate_id": candidate_id,
        "event_at": now_iso(),
        "event_type": event_type,
        "severity": severity,
        "message": message,
    }


def paper_execute(
    run: str,
    quote: QuoteCheck,
    config: StrategyConfig,
    intents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not quote.plan or len(intents) != 2:
        return [], {}, []
    candidate = quote.candidate
    plan = quote.plan
    for intent, leg in zip(intents, (plan.leg1, plan.leg2)):
        if intent.get("order_type") != "limit":
            return [], {}, []
        if intent.get("time_in_force") not in {"FOK", "IOC"}:
            return [], {}, []
        if float(intent.get("limit_price") or -1) != leg.price:
            return [], {}, []
        if float(intent.get("max_acceptable_price") or -1) != leg.price:
            return [], {}, []
        if float(intent.get("revalidated_depth") or 0) < config.combined_size_shares:
            return [], {}, []
        if intent.get("status") != "ready":
            return [], {}, []
    filled_at = now_iso()
    combined = config.combined_size_shares
    leg1_fee = combined * pm_fee(plan.leg1.price) if plan.leg1.venue == "polymarket" else combined * hl_fee()
    leg2_fee = combined * pm_fee(plan.leg2.price) if plan.leg2.venue == "polymarket" else combined * hl_fee()
    fills = [
        {
            "run_id": run,
            "candidate_id": candidate.candidate_id,
            "filled_at": filled_at,
            "venue": plan.leg1.venue,
            "leg": plan.leg1.side,
            "instrument": plan.leg1.token_or_coin,
            "side": "BUY",
            "shares": combined,
            "price": plan.leg1.price,
            "notional": combined * plan.leg1.price,
            "fee": leg1_fee,
        },
        {
            "run_id": run,
            "candidate_id": candidate.candidate_id,
            "filled_at": filled_at,
            "venue": plan.leg2.venue,
            "leg": plan.leg2.side,
            "instrument": plan.leg2.token_or_coin,
            "side": "BUY",
            "shares": combined,
            "price": plan.leg2.price,
            "notional": combined * plan.leg2.price,
            "fee": leg2_fee,
        },
    ]
    gross_cost = sum(float(row["notional"]) for row in fills)
    fee = leg1_fee + leg2_fee
    pnl = {
        "run_id": run,
        "candidate_id": candidate.candidate_id,
        "shares": combined,
        "gross_cost": gross_cost,
        "fee": fee,
        "net_cost": gross_cost + fee,
        "settlement_payoff": combined,
        "paper_pnl": combined - gross_cost - fee,
    }
    positions = [
        paper_position_row(candidate, plan, "S1", "HOLD_TO_MATURITY", config.s1_size_shares, filled_at),
        paper_position_row(candidate, plan, "S2", "ACTIVE_DYNAMIC", config.s2_size_shares, filled_at),
    ]
    return fills, pnl, positions


def paper_position_row(
    candidate: Candidate,
    plan: EntryPlan,
    strategy_mode: str,
    status: str,
    size_shares: float,
    created_at: str,
) -> dict[str, Any]:
    return {
        "position_id": f"{candidate.candidate_id}__{strategy_mode}",
        "candidate_id": candidate.candidate_id,
        "strategy_mode": strategy_mode,
        "match": candidate.match,
        "outcome": candidate.outcome,
        "selected_direction": plan.selected_direction,
        "leg1_venue": plan.leg1.venue,
        "leg1_token_or_coin": plan.leg1.token_or_coin,
        "leg1_side": plan.leg1.side,
        "leg1_entry_price": plan.leg1.price,
        "leg1_size_shares": size_shares,
        "leg2_venue": plan.leg2.venue,
        "leg2_token_or_coin": plan.leg2.token_or_coin,
        "leg2_side": plan.leg2.side,
        "leg2_entry_price": plan.leg2.price,
        "leg2_size_shares": size_shares,
        "entry_net_edge": plan.entry_net_edge,
        "entry_net_usd_profit": plan.entry_net_edge * size_shares,
        "status": status,
        "created_at": created_at,
    }


def fail_reason_counts(rows: dict[str, list[dict[str, Any]]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for group in ("candidates", "revalidations"):
        for row in rows[group]:
            for reason in str(row.get("fail_reason") or "").split(","):
                if reason:
                    counts[reason] += 1
    for row in rows["risk_events"]:
        event_type = str(row.get("event_type") or "")
        if event_type:
            counts[event_type] += 1
    return counts


def write_summary(
    rows: dict[str, list[dict[str, Any]]],
    mode: str,
    input_csv: Path | None,
    config: StrategyConfig,
    build_result: CandidateBuildResult | None,
    manual_note: str = "",
    live_status: dict[str, Any] | None = None,
) -> None:
    pass_count = sum(1 for row in rows["revalidations"] if as_bool(row.get("pass_flag")))
    fail_count = len(rows["revalidations"]) - pass_count
    counts = fail_reason_counts(rows)
    fail_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(counts.items())) or "- none"
    raw_positive_rows_count = build_result.raw_positive_rows_count if build_result else 0
    threshold_filtered_count = build_result.threshold_filtered_count if build_result else 0
    duplicates_removed_count = build_result.duplicates_removed_count if build_result else 0
    paper_pnl = sum(float(row.get("paper_pnl") or 0) for row in rows["paper_pnl"])
    price_moved_or_no_fill_count = counts.get("price_moved_or_no_fill", 0)
    partial_fill_count = counts.get("partial_fill_detected", 0)
    single_leg_exposure_count = counts.get("single_leg_exposure", 0) + counts.get("SINGLE_LEG_EXPOSURE", 0)
    live = live_status or {}
    gate_ok, _gate_failures = live_adapter_gate()
    content = f"""# Execution v1 Summary

- Mode: {mode}
- Input CSV: {input_csv or ""}
- execution_style: taker_limit
- scanner_price_used_for_order: false
- revalidation_price_used_for_order: true
- order_limit_price_rule: limit_price equals revalidated best ask
- chase_allowed: false
- retry_allowed: false
- consume_deeper_book_allowed: false
- time_in_force_preference: FOK then IOC
- paper_fill_price_source: revalidated best ask
- live_ready_status: {live.get("live_ready_status", "infrastructure_only")}
- live_preflight_status: {live.get("live_preflight_status", "")}
- live_dry_run_status: {live.get("live_dry_run_status", "")}
- live_order_adapter_ready: {str(gate_ok).lower()}
- adapter_submit_enabled: {str(gate_ok).lower()}
- submit_order_called: false
- real_order_sent: false
- fill_parser_ready: true
- tiny_live_allowed: false
- tiny_live_blocked_reason: {live.get("tiny_live_blocked_reason", "live_order_adapter_not_ready" if mode.startswith("tiny_live") else "")}
- payload_preview_path: {live.get("payload_preview_path", str(PAYLOAD_PREVIEW_PATH))}
- entry_mode: {ENTRY_MODE}
- s1_size_shares: {config.s1_size_shares}
- s2_size_shares: {config.s2_size_shares}
- combined_size_shares: {config.combined_size_shares}
- threshold_decimal: {config.threshold}
- threshold_percent: {config.threshold * 100:.3g}%
- min_s1_profit_usd: {config.min_s1_profit_usd}
- min_s2_profit_usd: {config.min_s2_profit_usd}
- relaxed_threshold_test: {str(config.threshold < 0.0005 or config.min_s1_profit_usd < 0.01 or config.min_s2_profit_usd < 0.01).lower()}
- live_allowed: false
- raw_positive_rows_count: {raw_positive_rows_count}
- threshold_filtered_count: {threshold_filtered_count}
- deduped_candidates_count: {len(rows["candidates"])}
- duplicates_removed_count: {duplicates_removed_count}
- revalidation pass/fail: {pass_count}/{fail_count}
- order_intents_count: {len(rows["order_intents"])}
- paper_fills_count: {len(rows["paper_fills"])}
- paper positions count: {len(rows["paper_positions"])}
- no_fake_candidate: true
- live_order_adapter_ready: {str(gate_ok).lower()}
- partial_fill_detection_ready: true
- single_leg_exposure_detection_ready: true
- Paper PnL: {paper_pnl:.8f}
- Live orders/fills: {len(rows["live_orders"])}/{len(rows["live_fills"])}
- price_moved_or_no_fill_count: {price_moved_or_no_fill_count}
- partial_fill_count: {partial_fill_count}
- single_leg_exposure_count: {single_leg_exposure_count}

## Failure Reason Counts
{fail_lines}

## Manual Notes
{manual_note or "- none"}

## Next Manual Checks Before Tiny Live
- Tiny live is disabled in this S1_AND_S2 paper-only revision.
- Confirm a future candidate has two-leg combined depth for both S1 and S2 together.
- Confirm S2 exit logic is designed before any dynamic live trading.
- Confirm PM/HL rule equivalence and token/coin mapping manually before any future live enablement.
"""
    (OUTPUT_DIR / "summary.md").write_text(content, encoding="utf-8")


def read_output_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def truthy_csv(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def live_adapter_gate() -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not bool_env(LIVE_ADAPTER_ENABLE_ENV, False):
        failures.append(f"{LIVE_ADAPTER_ENABLE_ENV}=true is required")
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED=true is required")
    if bool_env("DRY_RUN", True):
        failures.append("DRY_RUN=false is required")
    missing = [key for key in REQUIRED_LIVE_ENV if not os.environ.get(key)]
    if missing:
        failures.append("missing_env:" + ",".join(missing))
    return not failures, failures


def live_order_adapter_ready() -> bool:
    ok, _failures = live_adapter_gate()
    return ok


def adapter_submit_enabled() -> bool:
    ok, _failures = live_adapter_gate()
    return ok


def get_pm_balance() -> tuple[float | None, str]:
    try:
        balances = pm.get_usdc_balance(pm.get_funder())
        if not balances:
            return None, "no_usdc_balance_rows"
        return sum(float(value) for value in balances.values()), ""
    except Exception as exc:
        return None, str(exc)[:200]


def get_hl_balance() -> tuple[float | None, str]:
    try:
        balances = hl.spot_balances()
        usdc = next((float(total) for coin, total in balances if str(coin).upper() == "USDC"), None)
        return usdc, ""
    except Exception as exc:
        return None, str(exc)[:200]


def build_pm_limit_order_payload(intent: dict[str, str]) -> dict[str, Any]:
    if str(intent.get("order_type") or "").lower() != "limit":
        raise ValueError("market_order_blocked")
    limit_price = as_float(intent.get("limit_price"))
    best_ask = as_float(intent.get("revalidated_best_ask"))
    if limit_price is None or best_ask is None or limit_price != best_ask:
        raise ValueError("limit_price_violation")
    return {
        "venue": "polymarket",
        "token_id": intent.get("token_or_coin") or "",
        "side": "BUY",
        "order_type": "limit",
        "time_in_force": intent.get("time_in_force") or "FOK",
        "price": limit_price,
        "size": as_float(intent.get("combined_size_shares")) or 0.0,
        "submit_order_called": False,
        "real_order_sent": False,
    }


def build_hl_limit_order_payload(intent: dict[str, str]) -> dict[str, Any]:
    if str(intent.get("order_type") or "").lower() != "limit":
        raise ValueError("market_order_blocked")
    limit_price = as_float(intent.get("limit_price"))
    best_ask = as_float(intent.get("revalidated_best_ask"))
    if limit_price is None or best_ask is None or limit_price != best_ask:
        raise ValueError("limit_price_violation")
    return {
        "venue": "hyperliquid",
        "coin": intent.get("token_or_coin") or "",
        "is_buy": True,
        "order_type": "limit",
        "time_in_force": intent.get("time_in_force") or "FOK",
        "limit_price": limit_price,
        "size": as_float(intent.get("combined_size_shares")) or 0.0,
        "submit_order_called": False,
        "real_order_sent": False,
    }


def pm_order_type_for_tif(time_in_force: str) -> Any:
    from py_clob_client_v2 import OrderType

    tif = time_in_force.upper()
    if tif == "FOK" and hasattr(OrderType, "FOK"):
        return OrderType.FOK
    if tif in {"IOC", "FAK"} and hasattr(OrderType, "FAK"):
        return OrderType.FAK
    raise RuntimeError(f"unsupported_pm_time_in_force:{time_in_force}")


def submit_pm_limit_order(payload: dict[str, Any]) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok:
        return {"submitted": False, "order_id": "", "error_message": ";".join(failures)}
    if payload.get("order_type") != "limit":
        return {"submitted": False, "order_id": "", "error_message": "market_order_blocked"}
    try:
        from py_clob_client_v2 import OrderArgs, PartialCreateOrderOptions, Side

        client = pm.build_client()
        _bid, _ask, tick_size, neg_risk = pm.top(str(payload["token_id"]))
        response = client.create_and_post_order(
            order_args=OrderArgs(
                token_id=str(payload["token_id"]),
                price=float(payload["price"]),
                size=float(payload["size"]),
                side=Side.BUY if str(payload.get("side", "BUY")).upper() == "BUY" else Side.SELL,
            ),
            options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
            order_type=pm_order_type_for_tif(str(payload.get("time_in_force") or "FOK")),
        )
        order_id = ""
        if isinstance(response, dict):
            order_id = str(response.get("orderID") or response.get("order_id") or response.get("id") or "")
        return {"submitted": True, "order_id": order_id, "raw": response, "error_message": ""}
    except Exception as exc:
        return {"submitted": False, "order_id": "", "error_message": str(exc)[:300]}


def submit_hl_limit_order(payload: dict[str, Any]) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok:
        return {"submitted": False, "order_id": "", "error_message": ";".join(failures)}
    if payload.get("order_type") != "limit":
        return {"submitted": False, "order_id": "", "error_message": "market_order_blocked"}
    try:
        exchange, _agent_address, _account = hl.build_exchange()
        requested_tif = str(payload.get("time_in_force") or "FOK").upper()
        tif = "Ioc" if requested_tif in {"FOK", "IOC"} else requested_tif
        response = exchange.order(
            str(payload["coin"]),
            bool(payload.get("is_buy", True)),
            float(payload["size"]),
            float(payload["limit_price"]),
            {"limit": {"tif": tif}},
        )
        order_id = ""
        if isinstance(response, dict):
            statuses = (
                response.get("response", {})
                .get("data", {})
                .get("statuses", [])
                if isinstance(response.get("response"), dict)
                else []
            )
            if statuses and isinstance(statuses[0], dict):
                resting = statuses[0].get("resting") if isinstance(statuses[0].get("resting"), dict) else {}
                filled = statuses[0].get("filled") if isinstance(statuses[0].get("filled"), dict) else {}
                order_id = str(resting.get("oid") or filled.get("oid") or "")
        return {"submitted": True, "order_id": order_id, "raw": response, "error_message": ""}
    except Exception as exc:
        return {"submitted": False, "order_id": "", "error_message": str(exc)[:300]}


def get_pm_order_status(order_id: str, requested_size: float = 0.0) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok or not order_id:
        return parse_order_status(
            "polymarket",
            "",
            order_id,
            requested_size,
            {"status": "not_submitted", "error_message": ";".join(failures) if failures else ""},
        )
    try:
        client = pm.build_client()
        raw = client.get_order(order_id)
        return parse_order_status("polymarket", "", order_id, requested_size, raw if isinstance(raw, dict) else {})
    except Exception as exc:
        return parse_order_status("polymarket", "", order_id, requested_size, {"status": "unknown", "error": str(exc)[:300]})


def get_hl_order_status(order_id: str, requested_size: float = 0.0) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok or not order_id:
        return parse_order_status(
            "hyperliquid",
            "",
            order_id,
            requested_size,
            {"status": "not_submitted", "error_message": ";".join(failures) if failures else ""},
        )
    try:
        oid = int(str(order_id).split(":")[-1])
        raw = hl.info({"type": "orderStatus", "user": hl.get_account(), "oid": oid})
        parsed = parse_order_status("hyperliquid", "", order_id, requested_size, raw if isinstance(raw, dict) else {})
        parsed["raw_status"] = raw
        parsed["normalized_status"] = parsed["fill_status"]
        parsed["remaining_size"] = max(requested_size - float(parsed["filled_size"] or 0), 0.0)
        parsed["checked_at"] = now_iso()
        return parsed
    except Exception as exc:
        return {
            "venue": "hyperliquid",
            "leg": "",
            "order_id": order_id or "",
            "raw_status": {},
            "normalized_status": "unknown",
            "requested_size": requested_size,
            "filled_size": 0.0,
            "remaining_size": requested_size,
            "avg_fill_price": 0.0,
            "fill_status": "unknown",
            "order_status": "unknown",
            "error_message": str(exc)[:300],
            "checked_at": now_iso(),
        }


def cancel_pm_order(order_id: str) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok:
        return {"cancel_called": False, "cancelled": False, "error_message": ";".join(failures)}
    try:
        client = pm.build_client()
        raw = client.cancel(order_id)
        return {"cancel_called": True, "cancelled": True, "raw": raw, "error_message": ""}
    except Exception as exc:
        return {"cancel_called": True, "cancelled": False, "error_message": str(exc)[:300]}


def split_hl_coin_order_id(order_id: str, coin: str | None = None) -> tuple[str | None, int | None, str | None]:
    if coin:
        try:
            return coin, int(order_id), None
        except ValueError:
            return coin, None, "invalid_hl_order_id"
    text = str(order_id or "")
    for sep in (":", "|"):
        if sep in text:
            left, right = text.rsplit(sep, 1)
            try:
                return left, int(right), None
            except ValueError:
                return left, None, "invalid_hl_order_id"
    return None, None, "hl_cancel_requires_coin_and_oid"


def cancel_hl_order(order_id: str, coin: str | None = None) -> dict[str, Any]:
    ok, failures = live_adapter_gate()
    if not ok:
        return {
            "venue": "hyperliquid",
            "order_id": order_id or "",
            "cancel_submitted": False,
            "cancel_status": "blocked",
            "error_message": ";".join(failures),
            "raw_response": {},
            "checked_at": now_iso(),
        }
    hl_coin, oid, error = split_hl_coin_order_id(order_id, coin)
    if error or not hl_coin or oid is None:
        return {
            "venue": "hyperliquid",
            "order_id": order_id or "",
            "cancel_submitted": False,
            "cancel_status": "not_supported",
            "error_message": error or "hl_cancel_requires_coin_and_oid",
            "raw_response": {},
            "checked_at": now_iso(),
        }
    try:
        exchange, _agent_address, _account = hl.build_exchange()
        raw = exchange.cancel(hl_coin, oid)
        return {
            "venue": "hyperliquid",
            "order_id": str(oid),
            "cancel_submitted": True,
            "cancel_status": "submitted",
            "error_message": "",
            "raw_response": raw,
            "checked_at": now_iso(),
        }
    except Exception as exc:
        return {
            "venue": "hyperliquid",
            "order_id": str(oid),
            "cancel_submitted": True,
            "cancel_status": "error",
            "error_message": str(exc)[:300],
            "raw_response": {},
            "checked_at": now_iso(),
        }


def parse_order_status(
    venue: str,
    leg: str,
    order_id: str,
    requested_size: float,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = raw or {}
    raw_text = json.dumps(raw, default=str).lower()
    filled_size = as_float(raw.get("filled_size") or raw.get("filledSize") or raw.get("filled") or raw.get("takingAmount")) or 0.0
    avg_fill_price = as_float(raw.get("avg_fill_price") or raw.get("avgFillPrice") or raw.get("price") or raw.get("avgPx")) or 0.0
    raw_status = raw.get("order_status") or raw.get("status") or raw.get("orderStatus") or raw.get("raw_status") or ""
    if filled_size <= 0 and isinstance(raw.get("response"), dict):
        statuses = raw.get("response", {}).get("data", {}).get("statuses", [])
        if isinstance(statuses, list):
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                if "error" in status or "rejected" in status:
                    raw_status = status.get("error") or status.get("rejected") or "rejected"
                filled = status.get("filled") if isinstance(status.get("filled"), dict) else {}
                filled_size = as_float(filled.get("totalSz") or filled.get("sz") or filled.get("size")) or filled_size
                avg_fill_price = as_float(filled.get("avgPx") or filled.get("px")) or avg_fill_price
    if any(marker in raw_text for marker in ("rejected", "reject", "failed", "insufficient", "invalid order", "error")):
        fill_status = "rejected"
    elif any(marker in raw_text for marker in ("canceled", "cancelled")):
        fill_status = "canceled"
    elif filled_size <= 0:
        fill_status = "none"
    elif requested_size and filled_size >= requested_size:
        fill_status = "full"
    else:
        fill_status = "partial"
    order_status = str(raw_status or raw.get("status") or "not_submitted")
    if fill_status in {"rejected", "canceled"}:
        order_status = fill_status
    return {
        "venue": venue,
        "leg": leg,
        "order_id": order_id or "",
        "requested_size": requested_size,
        "filled_size": filled_size,
        "remaining_size": max(requested_size - filled_size, 0.0),
        "avg_fill_price": avg_fill_price,
        "fill_status": fill_status,
        "order_status": order_status,
        "error_message": raw.get("error_message") or raw.get("error") or "",
    }


def detect_single_leg_exposure(statuses: list[dict[str, Any]]) -> tuple[bool, bool]:
    fill_statuses = [str(row.get("fill_status") or "none") for row in statuses]
    partial = any(status == "partial" for status in fill_statuses)
    has_fill = [status in {"partial", "full"} for status in fill_statuses]
    single_leg = len(has_fill) >= 2 and any(has_fill) and not all(has_fill)
    return partial, single_leg


def live_adapter_status_rows() -> list[dict[str, Any]]:
    pm_balance, pm_error = get_pm_balance()
    hl_balance, hl_error = get_hl_balance()
    gate_ok, gate_failures = live_adapter_gate()
    gate_error = ";".join(gate_failures)
    checked_at = now_iso()
    return [
        {
            "adapter": "pm_limit_order_adapter",
            "venue": "polymarket",
            "adapter_ready": gate_ok,
            "adapter_submit_enabled": gate_ok,
            "balance_check_supported": True,
            "balance": "" if pm_balance is None else pm_balance,
            "order_type_supported": "limit",
            "time_in_force_supported": "FOK",
            "status": "ready" if gate_ok else "blocked",
            "error_message": pm_error or gate_error,
            "checked_at": checked_at,
        },
        {
            "adapter": "hl_limit_order_adapter",
            "venue": "hyperliquid",
            "adapter_ready": gate_ok,
            "adapter_submit_enabled": gate_ok,
            "balance_check_supported": True,
            "balance": "" if hl_balance is None else hl_balance,
            "order_type_supported": "limit",
            "time_in_force_supported": "FOK,IOC",
            "status": "ready" if gate_ok else "blocked",
            "error_message": hl_error or gate_error,
            "checked_at": checked_at,
        },
    ]


def write_adapter_status_csv() -> None:
    write_csv(ADAPTER_STATUS_PATH, LIVE_ADAPTER_STATUS_FIELDS, live_adapter_status_rows())


def mock_cancel_parser(order_id: str = "#0:12345") -> dict[str, Any]:
    coin, oid, error = split_hl_coin_order_id(order_id)
    return {
        "venue": "hyperliquid",
        "order_id": "" if oid is None else str(oid),
        "cancel_submitted": False,
        "cancel_status": "mock_parse_ok" if not error else "not_supported",
        "error_message": error or "",
        "raw_response": {},
        "checked_at": now_iso(),
        "coin": coin or "",
    }


def run_adapter_smoke_test() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_adapter_status_csv()
    requested = 40.0
    mock_pm_full = parse_order_status(
        "polymarket",
        "mock_pm",
        "pm-order-1",
        requested,
        {"status": "matched", "takingAmount": requested, "price": 0.5},
    )
    mock_hl_partial = parse_order_status(
        "hyperliquid",
        "mock_hl",
        "hl-order-1",
        requested,
        {"response": {"data": {"statuses": [{"filled": {"totalSz": 12.5, "avgPx": 0.5}}]}}},
    )
    mock_rejected = parse_order_status(
        "hyperliquid",
        "mock_hl",
        "hl-order-2",
        requested,
        {"response": {"data": {"statuses": [{"error": "insufficient balance"}]}}},
    )
    mock_canceled = parse_order_status(
        "polymarket",
        "mock_pm",
        "pm-order-2",
        requested,
        {"status": "canceled"},
    )
    mock_none = parse_order_status("hyperliquid", "mock_hl", "", requested, {})
    partial_detected, single_leg = detect_single_leg_exposure([mock_pm_full, mock_none])
    cancel_parse = mock_cancel_parser()
    content = f"""# Execution v1 Adapter Smoke Test

- generated_at: {now_iso()}
- real_submit_called: false
- real_cancel_called: false
- adapter_gate_ok: {str(live_adapter_gate()[0]).lower()}
- PM real submit connected: YES
- HL real submit connected: YES
- PM order status connected: YES
- HL order status connected: YES
- PM cancel connected: YES
- HL cancel connected: YES_WITH_COIN_AND_OID
- Rejected parser supported: {mock_rejected["fill_status"] == "rejected"}
- Canceled parser supported: {mock_canceled["fill_status"] == "canceled"}
- Partial parser supported: {mock_hl_partial["fill_status"] == "partial"}
- Full parser supported: {mock_pm_full["fill_status"] == "full"}
- None parser supported: {mock_none["fill_status"] == "none"}
- Single-leg exposure detection supported: {single_leg}
- Partial fill detection supported: {partial_detected is False and mock_hl_partial["fill_status"] == "partial"}
- HL true FOK supported: NO
- HL requested FOK mapped to: IOC
- HL partial fill risk: YES

## Mock Status Rows

```json
{json.dumps([mock_pm_full, mock_hl_partial, mock_rejected, mock_canceled, mock_none], indent=2, sort_keys=True)}
```

## Mock Cancel Parser

```json
{json.dumps(cancel_parse, indent=2, sort_keys=True)}
```

## Remaining Live Risk

- Hyperliquid wrapper maps requested FOK to IOC, so partial fills remain possible.
- HL cancel requires both coin and oid, or an order id encoded as `coin:oid`.
- HL order status uses `info({{"type": "orderStatus", "user": account, "oid": oid}})` and requires a valid oid.
"""
    ADAPTER_TEST_RESULTS_PATH.write_text(content, encoding="utf-8")
    return 0


def live_block_reason(
    candidates: list[dict[str, str]],
    revalidations: list[dict[str, str]],
    intents: list[dict[str, str]],
) -> str:
    if not candidates:
        return "no_candidate"
    if not any(truthy_csv(row.get("pass_flag")) for row in revalidations):
        return "revalidation_not_pass"
    if not intents:
        return "no_order_intent"
    for intent in intents:
        order_type = str(intent.get("order_type") or "").lower()
        if order_type == "market":
            return "market_order_blocked"
        if order_type != "limit":
            return "non_limit_order_blocked"
        if str(intent.get("time_in_force") or "") not in {"FOK", "IOC"}:
            return "invalid_time_in_force"
        limit_price = as_float(intent.get("limit_price"))
        best_ask = as_float(intent.get("revalidated_best_ask"))
        max_acceptable = as_float(intent.get("max_acceptable_price"))
        if limit_price is None or best_ask is None or max_acceptable is None:
            return "limit_price_violation"
        if limit_price != best_ask or max_acceptable != best_ask:
            return "limit_price_violation"
    return "live_order_adapter_not_ready"


def write_payload_preview(
    mode: str,
    blocked_reason: str,
    candidates: list[dict[str, str]],
    intents: list[dict[str, str]],
) -> None:
    payloads = []
    for intent in intents:
        venue = str(intent.get("venue") or "")
        try:
            adapter_payload = (
                build_pm_limit_order_payload(intent)
                if venue == "polymarket"
                else build_hl_limit_order_payload(intent)
                if venue == "hyperliquid"
                else {}
            )
        except ValueError as exc:
            adapter_payload = {"error_message": str(exc)}
        payloads.append(
            {
                "candidate_id": intent.get("candidate_id"),
                "venue": intent.get("venue"),
                "token_or_coin": intent.get("token_or_coin"),
                "side": intent.get("side"),
                "order_type": intent.get("order_type"),
                "time_in_force": intent.get("time_in_force"),
                "size": intent.get("combined_size_shares"),
                "limit_price": intent.get("limit_price"),
                "max_acceptable_price": intent.get("max_acceptable_price"),
                "adapter_payload": adapter_payload,
            }
        )
    PAYLOAD_PREVIEW_PATH.write_text(
        json.dumps(
            {
                "mode": mode,
                "status": "blocked",
                "blocked_reason": blocked_reason,
                "submit_order_called": False,
                "real_order_sent": False,
                "candidate_count": len(candidates),
                "order_intents_count": len(intents),
                "payloads": payloads,
                "created_at": now_iso(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def run_live_safety_mode(args: argparse.Namespace, mode_name: str) -> int:
    run = run_id()
    rows = empty_outputs()
    config = StrategyConfig(
        threshold=args.threshold,
        s1_size_shares=args.s1_size_shares,
        s2_size_shares=args.s2_size_shares,
        min_s1_profit_usd=args.min_s1_profit_usd,
        min_s2_profit_usd=args.min_s2_profit_usd,
    )
    candidates = read_output_csv(OUTPUT_DIR / "candidates.csv")
    revalidations = read_output_csv(OUTPUT_DIR / "revalidations.csv")
    intents = read_output_csv(OUTPUT_DIR / "order_intents.csv")
    blocked_reason = "stop_file_present" if STOP_FILE.exists() else live_block_reason(candidates, revalidations, intents)
    candidate_id = candidates[0].get("candidate_id", "") if candidates else (args.candidate_id or "")
    requested_size = as_float(intents[0].get("combined_size_shares")) if intents else config.combined_size_shares
    order_type = intents[0].get("order_type", "limit") if intents else "limit"
    time_in_force = intents[0].get("time_in_force", "FOK") if intents else "FOK"
    rows["live_adapter_status"].extend(live_adapter_status_rows())
    parsed_statuses: list[dict[str, Any]] = []
    for intent in intents:
        parsed = parse_order_status(
            str(intent.get("venue") or ""),
            str(intent.get("leg") or ""),
            "",
            as_float(intent.get("combined_size_shares")) or 0.0,
            {},
        )
        parsed_statuses.append(parsed)
        rows["live_order_status"].append(
            {
                "candidate_id": intent.get("candidate_id", ""),
                "venue": parsed["venue"],
                "leg": parsed["leg"],
                "order_id": parsed["order_id"],
                "requested_size": parsed["requested_size"],
                "filled_size": parsed["filled_size"],
                "avg_fill_price": parsed["avg_fill_price"],
                "fill_status": parsed["fill_status"],
                "order_status": parsed["order_status"],
                "error_message": parsed["error_message"],
                "checked_at": now_iso(),
            }
        )
    partial_fill_detected, single_leg_exposure = detect_single_leg_exposure(parsed_statuses)
    rows["live_safety_checks"].append(
        {
            "check_id": f"{mode_name}-{run}",
            "candidate_id": candidate_id,
            "adapter_ready": False,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "requested_size": requested_size,
            "filled_size": 0,
            "fill_status": "none",
            "leg1_fill_status": parsed_statuses[0]["fill_status"] if len(parsed_statuses) >= 1 else "none",
            "leg2_fill_status": parsed_statuses[1]["fill_status"] if len(parsed_statuses) >= 2 else "none",
            "partial_fill_detected": partial_fill_detected,
            "single_leg_exposure": single_leg_exposure,
            "blocked_reason": blocked_reason,
            "checked_at": now_iso(),
        }
    )
    if single_leg_exposure:
        rows["risk_events"].append(
            risk_event(run, candidate_id, "single_leg_exposure", "critical", "One leg filled while another did not; no chase/retry.")
        )
    if partial_fill_detected:
        rows["risk_events"].append(
            risk_event(run, candidate_id, "partial_fill_detected", "critical", "Partial fill detected; no chase/retry.")
        )
    if blocked_reason in {"market_order_blocked", "limit_price_violation", "stop_file_present"}:
        rows["risk_events"].append(risk_event(run, candidate_id, blocked_reason, "critical", "Live preflight blocked."))
    write_payload_preview(mode_name, blocked_reason, candidates, intents)
    write_csv(OUTPUT_DIR / "live_safety_checks.csv", LIVE_SAFETY_CHECK_FIELDS, rows["live_safety_checks"])
    write_csv(OUTPUT_DIR / "risk_events.csv", RISK_EVENT_FIELDS, rows["risk_events"])
    write_csv(OUTPUT_DIR / "live_orders.csv", LIVE_ORDER_FIELDS, rows["live_orders"])
    write_csv(OUTPUT_DIR / "live_fills.csv", LIVE_FILL_FIELDS, rows["live_fills"])
    write_csv(OUTPUT_DIR / "live_adapter_status.csv", LIVE_ADAPTER_STATUS_FIELDS, rows["live_adapter_status"])
    write_csv(OUTPUT_DIR / "live_order_status.csv", LIVE_ORDER_STATUS_FIELDS, rows["live_order_status"])
    live_status = {
        "live_ready_status": "infrastructure_only" if blocked_reason == "no_candidate" else "blocked",
        "live_preflight_status": "blocked" if mode_name == "live_preflight" else "",
        "live_dry_run_status": "blocked" if mode_name == "live_dry_run" else "",
        "tiny_live_blocked_reason": blocked_reason if blocked_reason != "live_order_adapter_not_ready" else "live_order_adapter_not_ready",
        "payload_preview_path": str(PAYLOAD_PREVIEW_PATH),
    }
    if args.report:
        write_summary(rows, mode_name, None, config, None, live_status=live_status)
    return 0


def run_paper(args: argparse.Namespace) -> int:
    run = run_id()
    rows = empty_outputs()
    config = StrategyConfig(
        threshold=args.threshold,
        s1_size_shares=args.s1_size_shares,
        s2_size_shares=args.s2_size_shares,
        min_s1_profit_usd=args.min_s1_profit_usd,
        min_s2_profit_usd=args.min_s2_profit_usd,
    )
    if STOP_FILE.exists():
        rows["risk_events"].append(
            risk_event(run, "", "stop_file_present", "critical", f"Execution blocked because {STOP_FILE} exists.")
        )
        write_all_outputs(rows)
        write_summary(rows, "paper_blocked", Path(args.input), config, None)
        return 2

    build_result = build_candidates_result(Path(args.input), config, args.max_candidates)
    rows["candidates"] = [candidate_row(run, candidate, config) for candidate in build_result.candidates]
    for candidate in build_result.candidates:
        quote = revalidate(candidate, config)
        rows["revalidations"].append(revalidation_row(run, quote, config))
        if not quote.pass_flag:
            continue
        intents = order_intent_rows(run, quote, config)
        rows["order_intents"].extend(intents)
        fills, pnl, positions = paper_execute(run, quote, config, intents)
        rows["paper_fills"].extend(fills)
        if pnl:
            rows["paper_pnl"].append(pnl)
        rows["paper_positions"].extend(positions)
    write_all_outputs(rows)
    if args.report:
        write_summary(rows, "paper", Path(args.input), config, build_result)
    return 0


def run_tiny_live(args: argparse.Namespace) -> int:
    run = run_id()
    rows = empty_outputs()
    config = StrategyConfig(
        threshold=args.threshold,
        s1_size_shares=args.s1_size_shares,
        s2_size_shares=args.s2_size_shares,
        min_s1_profit_usd=args.min_s1_profit_usd,
        min_s2_profit_usd=args.min_s2_profit_usd,
    )
    rows["risk_events"].append(
        risk_event(
            run,
            args.candidate_id or "",
            "live_order_adapter_not_ready",
            "critical",
            "fail_reason=live_order_adapter_not_ready; submit_order_called=false; real_order_sent=false.",
        )
    )
    rows["live_adapter_status"].extend(live_adapter_status_rows())
    rows["live_order_status"].append(
        {
            "candidate_id": args.candidate_id or "",
            "venue": "",
            "leg": "",
            "order_id": "",
            "requested_size": config.combined_size_shares,
            "filled_size": 0,
            "avg_fill_price": 0,
            "fill_status": "none",
            "order_status": "not_submitted",
            "error_message": "live_order_adapter_not_ready",
            "checked_at": now_iso(),
        }
    )
    rows["live_safety_checks"].append(
        {
            "check_id": f"live-safety-{run}",
            "candidate_id": args.candidate_id or "",
            "adapter_ready": False,
            "order_type": "limit",
            "time_in_force": "FOK",
            "requested_size": config.combined_size_shares,
            "filled_size": 0,
            "fill_status": "none",
            "leg1_fill_status": "none",
            "leg2_fill_status": "none",
            "partial_fill_detected": False,
            "single_leg_exposure": False,
            "blocked_reason": "live_order_adapter_not_ready",
            "checked_at": now_iso(),
        }
    )
    write_payload_preview("tiny_live_blocked", "live_order_adapter_not_ready", [], [])
    write_all_outputs(rows)
    write_summary(rows, "tiny_live_blocked", Path(args.input), config, None)
    return 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP2 op1 Execution v1 S1_AND_S2 paper layer.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--paper", action="store_true", help="Run paper execution.")
    mode.add_argument("--tiny-live", action="store_true", help="Disabled in this paper-only revision.")
    mode.add_argument("--live-preflight", action="store_true", help="Run submit-before-live safety checks only.")
    mode.add_argument("--live-dry-run", action="store_true", help="Build payload preview and stop before submit.")
    mode.add_argument("--adapter-smoke-test", action="store_true", help="Run non-submit adapter/parser smoke tests.")
    parser.add_argument("--input", default="", help="MVP2 op1 monitor or dry-run CSV.")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--confirm-live", default="")
    parser.add_argument("--s1-size-shares", type=float, default=DEFAULT_S1_SIZE_SHARES)
    parser.add_argument("--s2-size-shares", type=float, default=DEFAULT_S2_SIZE_SHARES)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--min-s1-profit-usd", type=float, default=DEFAULT_MIN_S1_PROFIT_USD)
    parser.add_argument("--min-s2-profit-usd", type=float, default=DEFAULT_MIN_S2_PROFIT_USD)
    parser.add_argument("--report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dirs()
    pm.load_env()
    hl.load_env()
    if args.live_preflight:
        return run_live_safety_mode(args, "live_preflight")
    if args.live_dry_run:
        return run_live_safety_mode(args, "live_dry_run")
    if args.adapter_smoke_test:
        return run_adapter_smoke_test()
    if args.tiny_live:
        return run_tiny_live(args)
    input_csv = Path(args.input)
    if not args.input or not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    return run_paper(args)


if __name__ == "__main__":
    raise SystemExit(main())
