from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.mvp2_scanner.match_opportunity_evaluator import (
    AlignedOutcome,
    DEFAULT_HL_QUESTION_NAME,
    DEFAULT_OUTCOMES,
    MatchEvaluation,
    evaluate_match,
)
from src.strategies.pm_hl.mvp2_scanner.pm_sports_match_discovery import discover_moneyline


@dataclass(frozen=True)
class Op1DryRunConfig:
    pm_event_slug: str = "fifwc-arg-aut-2026-06-22"
    hl_question_name: str = DEFAULT_HL_QUESTION_NAME
    duration_minutes: float = 10.0
    interval_seconds: int = 30
    execution_enabled: bool = False
    s1_shares: float = 20.0
    s2_shares: float = 20.0
    max_active_outcomes: int = 1
    rule_match_threshold: float = 0.90
    entry_min_best_book_depth_shares: float = 40.0
    s2_exit_min_best_bid_depth_shares: float = 20.0
    entry_net_edge_bps_threshold: float = 10.0
    entry_expected_profit_threshold_usd: float = 0.03
    s2_exit_realized_net_pnl_all_in_threshold_usd: float = 0.03
    s2_exit_net_edge_bps_all_in_threshold: float = 10.0
    s2_exit_exit_vs_hold_usd_threshold: float = 0.0
    pre_match_cutoff_minutes: float = 10.0
    consecutive_signal_count: int = 1

    @property
    def total_planned_shares(self) -> float:
        return self.s1_shares + self.s2_shares


DRY_RUN_CSV_FIELDS = [
    "timestamp",
    "iteration",
    "outcome",
    "best_side",
    "entry_cost",
    "entry_gross_edge",
    "entry_fee",
    "entry_net",
    "entry_net_bps",
    "expected_profit_s1_20",
    "expected_profit_s1s2_40",
    "depth",
    "rule_match_score",
    "rank_score",
    "rank",
    "top1_flag",
    "s1_entry_eligible",
    "s2_entry_eligible",
    "depth_ok",
    "entry_leg1_depth",
    "entry_leg2_depth",
    "s2_exit_depth_ok",
    "s2_exit_leg1_bid_depth",
    "s2_exit_leg2_bid_depth",
    "net_bps_ok",
    "expected_profit_ok",
    "rule_match_ok",
    "pre_match_cutoff_ok",
    "activation_allowed",
    "block_reason",
    "would_place_orders",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pre_match_cutoff_ok(timestamp: str, start_time: str | None, cutoff_minutes: float) -> bool:
    start = _parse_iso(start_time)
    now = _parse_iso(timestamp)
    if not start or not now:
        return True
    seconds_to_start = (start - now).total_seconds()
    return seconds_to_start > cutoff_minutes * 60


def _print_table(title: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    print(title)
    if not rows:
        print("  no rows")
        return
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in rows))
        for col in columns
    }
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))


def _best_op1_by_outcome(evaluation: MatchEvaluation) -> dict[str, dict[str, Any]]:
    group = evaluation.opportunity_groups.get("cross_venue_direct_no_complete_set", [])
    best: dict[str, dict[str, Any]] = {}
    expected_outcomes = tuple(row.outcome for row in evaluation.aligned_outcomes) or DEFAULT_OUTCOMES
    for outcome in expected_outcomes:
        candidates = [row for row in group if row.get("outcome") == outcome]
        if not candidates:
            continue
        best[outcome] = max(
            candidates,
            key=lambda row: row.get("net") if row.get("net") is not None else -999.0,
        )
    return best


def _aligned_by_outcome(evaluation: MatchEvaluation) -> dict[str, AlignedOutcome]:
    return {row.outcome: row for row in evaluation.aligned_outcomes}


def _entry_leg_depths(outcome: str, side: str, aligned: dict[str, AlignedOutcome]) -> tuple[float | None, float | None]:
    row = aligned[outcome]
    if side.startswith("buy_pm_"):
        return (
            row.pm_yes_book.ask_size if row.pm_yes_book else None,
            row.hl_no_book.ask_size if row.hl_no_book else None,
        )
    if side.startswith("buy_hl_"):
        return (
            row.hl_yes_book.ask_size if row.hl_yes_book else None,
            row.pm_no_book.ask_size if row.pm_no_book else None,
        )
    return None, None


def _s2_exit_leg_bid_depths(outcome: str, side: str, aligned: dict[str, AlignedOutcome]) -> tuple[float | None, float | None]:
    row = aligned[outcome]
    if side.startswith("buy_pm_"):
        return (
            row.pm_yes_book.bid_size if row.pm_yes_book else None,
            row.hl_no_book.bid_size if row.hl_no_book else None,
        )
    if side.startswith("buy_hl_"):
        return (
            row.hl_yes_book.bid_size if row.hl_yes_book else None,
            row.pm_no_book.bid_size if row.pm_no_book else None,
        )
    return None, None


def _failure_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not row["depth_ok"]:
        reasons.append("entry_depth")
    if not row["s2_exit_depth_ok"]:
        reasons.append("s2_exit_depth")
    if not row["net_bps_ok"]:
        reasons.append("net_edge_bps")
    if not row["expected_profit_ok"]:
        reasons.append("expected_profit")
    if not row["rule_match_ok"]:
        reasons.append("rule_match")
    if not row["pre_match_cutoff_ok"]:
        reasons.append("pre_match_cutoff")
    if not row["activation_allowed"]:
        reasons.append("not_top1")
    if row["would_place_orders"] is False and row["s1_entry_eligible"] and row["s2_entry_eligible"]:
        reasons.append("execution_disabled")
    return reasons


def build_strategy_snapshot(
    evaluation: MatchEvaluation,
    config: Op1DryRunConfig,
    timestamp: str,
    iteration: int,
    match_start_time: str | None = None,
) -> dict[str, Any]:
    best_by_outcome = _best_op1_by_outcome(evaluation)
    aligned = _aligned_by_outcome(evaluation)
    pre_match_cutoff_ok = _pre_match_cutoff_ok(
        timestamp,
        match_start_time,
        config.pre_match_cutoff_minutes,
    )
    ranking_rows: list[dict[str, Any]] = []
    expected_outcomes = tuple(row.outcome for row in evaluation.aligned_outcomes) or DEFAULT_OUTCOMES
    for outcome in expected_outcomes:
        candidate = best_by_outcome.get(outcome, {})
        side = str(candidate.get("side") or "unavailable")
        entry_leg1_depth, entry_leg2_depth = _entry_leg_depths(outcome, side, aligned)
        s2_exit_leg1_bid_depth, s2_exit_leg2_bid_depth = _s2_exit_leg_bid_depths(outcome, side, aligned)
        entry_cost = candidate.get("sum_ask")
        entry_net = candidate.get("net")
        entry_net_bps = (
            entry_net / entry_cost * 10000
            if entry_net is not None and entry_cost and entry_cost > 0
            else None
        )
        expected_profit_s1 = entry_net * config.s1_shares if entry_net is not None else None
        expected_profit_full = (
            entry_net * config.total_planned_shares if entry_net is not None else None
        )
        row = {
            "timestamp": timestamp,
            "iteration": iteration,
            "outcome": outcome,
            "best_side": side,
            "entry_cost": entry_cost,
            "entry_gross_edge": candidate.get("gross"),
            "entry_fee": candidate.get("estimated_fee"),
            "entry_net": entry_net,
            "entry_net_bps": entry_net_bps,
            "expected_profit_s1_20": expected_profit_s1,
            "expected_profit_s1s2_40": expected_profit_full,
            "depth": candidate.get("depth"),
            "entry_leg1_depth": entry_leg1_depth,
            "entry_leg2_depth": entry_leg2_depth,
            "s2_exit_leg1_bid_depth": s2_exit_leg1_bid_depth,
            "s2_exit_leg2_bid_depth": s2_exit_leg2_bid_depth,
            "rule_match_score": candidate.get("rule_match_score", 0.0),
            "rank_score": expected_profit_full if expected_profit_full is not None else -999.0,
        }
        ranking_rows.append(row)

    ranking_rows = sorted(
        ranking_rows,
        key=lambda row: (
            row["rank_score"] if row["rank_score"] is not None else -999.0,
            row["entry_net_bps"] if row["entry_net_bps"] is not None else -999.0,
            row["depth"] if row["depth"] is not None else -999.0,
            row["rule_match_score"] if row["rule_match_score"] is not None else -999.0,
        ),
        reverse=True,
    )
    for index, row in enumerate(ranking_rows, start=1):
        row["rank"] = index
        row["top1_flag"] = index == 1

    gate_rows: list[dict[str, Any]] = []
    for row in ranking_rows:
        entry_leg1_depth = row.get("entry_leg1_depth") or 0.0
        entry_leg2_depth = row.get("entry_leg2_depth") or 0.0
        s2_exit_leg1_bid_depth = row.get("s2_exit_leg1_bid_depth") or 0.0
        s2_exit_leg2_bid_depth = row.get("s2_exit_leg2_bid_depth") or 0.0
        depth_ok = (
            entry_leg1_depth >= config.entry_min_best_book_depth_shares
            and entry_leg2_depth >= config.entry_min_best_book_depth_shares
        )
        s2_exit_depth_ok = (
            s2_exit_leg1_bid_depth >= config.s2_exit_min_best_bid_depth_shares
            and s2_exit_leg2_bid_depth >= config.s2_exit_min_best_bid_depth_shares
        )
        net_bps_ok = (row.get("entry_net_bps") or -999.0) >= config.entry_net_edge_bps_threshold
        expected_profit_ok = (
            row.get("expected_profit_s1_20") or -999.0
        ) >= config.entry_expected_profit_threshold_usd
        rule_match_ok = (row.get("rule_match_score") or 0.0) >= config.rule_match_threshold
        activation_allowed = bool(row["top1_flag"]) and row["rank"] <= config.max_active_outcomes
        eligible = (
            depth_ok
            and net_bps_ok
            and expected_profit_ok
            and rule_match_ok
            and pre_match_cutoff_ok
            and activation_allowed
        )
        gate = {
            "timestamp": timestamp,
            "iteration": iteration,
            "outcome": row["outcome"],
            "s1_entry_eligible": eligible,
            "s2_entry_eligible": eligible,
            "depth_ok": depth_ok,
            "entry_leg1_depth": row.get("entry_leg1_depth"),
            "entry_leg2_depth": row.get("entry_leg2_depth"),
            "s2_exit_depth_ok": s2_exit_depth_ok,
            "s2_exit_leg1_bid_depth": row.get("s2_exit_leg1_bid_depth"),
            "s2_exit_leg2_bid_depth": row.get("s2_exit_leg2_bid_depth"),
            "net_bps_ok": net_bps_ok,
            "expected_profit_ok": expected_profit_ok,
            "rule_match_ok": rule_match_ok,
            "pre_match_cutoff_ok": pre_match_cutoff_ok,
            "activation_allowed": activation_allowed,
            "would_place_orders": bool(eligible and config.execution_enabled),
        }
        gate["block_reason"] = ",".join(_failure_reasons({**row, **gate})) or "pass_dry_run_only"
        gate_rows.append(gate)

    top1_rank = next(row for row in ranking_rows if row["top1_flag"])
    top1_gate = next(row for row in gate_rows if row["outcome"] == top1_rank["outcome"])
    top1_decision = {
        "timestamp": timestamp,
        "iteration": iteration,
        "top1_outcome": top1_rank["outcome"],
        "selected_side": top1_rank["best_side"],
        "s1_plan_shares": config.s1_shares,
        "s2_plan_shares": config.s2_shares,
        "s1_decision": "dry_run_plan_only" if top1_gate["s1_entry_eligible"] else "blocked",
        "s2_decision": "dry_run_plan_only" if top1_gate["s2_entry_eligible"] else "blocked",
        "s2_exit_decision": (
            "not_applicable_no_assumed_position"
            if top1_gate["s2_exit_depth_ok"]
            else "not_applicable_no_assumed_position_exit_depth_would_block"
        ),
        "would_place_orders": bool(top1_gate["would_place_orders"]),
        "reason": top1_gate["block_reason"],
        "execution_enabled": config.execution_enabled,
        "live_order_submission_implemented": False,
    }
    return {
        "timestamp": timestamp,
        "iteration": iteration,
        "ranking_rows": ranking_rows,
        "gate_rows": gate_rows,
        "top1_decision": top1_decision,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _init_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=DRY_RUN_CSV_FIELDS).writeheader()


def _append_csv(path: Path, rows: list[dict[str, Any]], gate_rows: list[dict[str, Any]]) -> None:
    gates = {row["outcome"]: row for row in gate_rows}
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DRY_RUN_CSV_FIELDS)
        for row in rows:
            gate = gates[row["outcome"]]
            csv_row = {field: row.get(field) for field in DRY_RUN_CSV_FIELDS}
            for field in (
                "s1_entry_eligible",
                "s2_entry_eligible",
                "depth_ok",
                "entry_leg1_depth",
                "entry_leg2_depth",
                "s2_exit_depth_ok",
                "s2_exit_leg1_bid_depth",
                "s2_exit_leg2_bid_depth",
                "net_bps_ok",
                "expected_profit_ok",
                "rule_match_ok",
                "pre_match_cutoff_ok",
                "activation_allowed",
                "block_reason",
                "would_place_orders",
            ):
                csv_row[field] = gate.get(field)
            writer.writerow(csv_row)


def monitor_op1_strategy_dry_run(
    *,
    output_dir: Path,
    config: Op1DryRunConfig,
) -> Path:
    if config.interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    planned_iterations = max(
        1,
        int((config.duration_minutes * 60 + config.interval_seconds - 1) // config.interval_seconds),
    )
    started_at = _now_iso()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"pm_hl_op1_strategy_dry_run_{config.pm_event_slug}_{stamp}.json"
    csv_path = output_dir / f"pm_hl_op1_strategy_dry_run_{config.pm_event_slug}_{stamp}.csv"
    payload: dict[str, Any] = {
        "started_at": started_at,
        "completed_at": None,
        "config": config.__dict__,
        "planned_iterations": planned_iterations,
        "completed_iterations": 0,
        "warnings": [],
        "snapshots": [],
    }
    _write_json(json_path, payload)
    _init_csv(csv_path)
    match_start_time = discover_moneyline(config.pm_event_slug).parent_event.start_time

    print("PM-HL op1 strategy dry-run monitor (NO EXECUTION)")
    print(
        f"test_start_time={started_at} duration_minutes={config.duration_minutes} "
        f"interval_seconds={config.interval_seconds} planned_iterations={planned_iterations}"
    )
    print(
        f"pm_event_slug={config.pm_event_slug} hl_question_name={config.hl_question_name} "
        f"execution_enabled={config.execution_enabled} live_order_submission_implemented=False "
        f"match_start_time={match_start_time}"
    )
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    sys.stdout.flush()

    ranking_columns = [
        "outcome",
        "best_side",
        "entry_net",
        "entry_net_bps",
        "expected_profit_s1_20",
        "expected_profit_s1s2_40",
        "depth",
        "entry_leg1_depth",
        "entry_leg2_depth",
        "rank_score",
        "rank",
        "top1_flag",
    ]
    gate_columns = [
        "outcome",
        "s1_entry_eligible",
        "s2_entry_eligible",
        "depth_ok",
        "s2_exit_depth_ok",
        "net_bps_ok",
        "expected_profit_ok",
        "rule_match_ok",
        "pre_match_cutoff_ok",
        "activation_allowed",
        "block_reason",
    ]
    decision_columns = [
        "top1_outcome",
        "selected_side",
        "s1_plan_shares",
        "s2_plan_shares",
        "s1_decision",
        "s2_decision",
        "s2_exit_decision",
        "would_place_orders",
        "reason",
    ]

    for iteration in range(1, planned_iterations + 1):
        timestamp = _now_iso()
        print(f"\n=== op1 dry-run iteration {iteration}/{planned_iterations} timestamp={timestamp} ===")
        try:
            evaluation = evaluate_match(config.pm_event_slug, config.hl_question_name)
            snapshot = build_strategy_snapshot(
                evaluation,
                config,
                timestamp,
                iteration,
                match_start_time,
            )
            _print_table("op1 strategy ranking table", ranking_columns, snapshot["ranking_rows"])
            print()
            _print_table("op1 strategy gate table", gate_columns, snapshot["gate_rows"])
            print()
            _print_table(
                "top1 dry-run decision summary",
                decision_columns,
                [snapshot["top1_decision"]],
            )
            _append_csv(csv_path, snapshot["ranking_rows"], snapshot["gate_rows"])
            payload["snapshots"].append(
                {
                    **snapshot,
                    "status": "ok",
                    "raw_opportunity_snapshot": evaluation.to_dict(),
                }
            )
            payload["completed_iterations"] = iteration
        except Exception as exc:
            warning = f"iteration={iteration} timestamp={timestamp} warning={str(exc)[:300]}"
            print(f"WARN: {warning}")
            payload["warnings"].append(warning)
            payload["snapshots"].append(
                {
                    "timestamp": timestamp,
                    "iteration": iteration,
                    "status": "warning",
                    "error": str(exc)[:500],
                }
            )
        _write_json(json_path, payload)
        sys.stdout.flush()
        if iteration < planned_iterations:
            time.sleep(config.interval_seconds)

    payload["completed_at"] = _now_iso()
    _write_json(json_path, payload)
    print(
        f"\nop1 dry-run completed completed_at={payload['completed_at']} "
        f"completed_iterations={payload['completed_iterations']} warnings={len(payload['warnings'])}"
    )
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    sys.stdout.flush()
    return json_path

