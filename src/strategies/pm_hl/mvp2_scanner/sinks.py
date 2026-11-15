from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.mvp2_scanner.schemas import OpportunityRow, ScanSummary


DISPLAY_COLUMNS = (
    "strategy_type",
    "market_key",
    "outcome",
    "price_a_bid",
    "price_a_ask",
    "price_b_bid",
    "price_b_ask",
    "net_edge_bps",
    "depth",
    "capacity_usd",
    "rule_match_score",
    "execution_risk_score",
    "recommendation",
    "completeness_flag",
    "pm_subset_sum_yes_deviation_from_1",
    "hl_subset_sum_yes_deviation_from_1",
    "pm_full_outcome_count",
    "pm_full_sum_yes_deviation_from_1",
    "pm_full_sum_no_deviation_from_n_minus_1",
    "hl_full_outcome_count",
    "hl_full_sum_yes_deviation_from_1",
    "hl_full_sum_no_deviation_from_n_minus_1",
    "pm_sum_three_way_deviation_from_1",
    "hl_sum_three_way_deviation_from_1",
)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if abs(value) >= 100:
            return f"{value:.1f}"
        if abs(value) >= 1:
            return f"{value:.3f}"
        return f"{value:.4f}"
    return str(value)


def print_summary(summary: ScanSummary, extra: dict[str, Any]) -> None:
    print("PM-HL MVP2 scanner v0 (READ ONLY, no orders)")
    print(
        "Champion: "
        f"candidates={summary.champion_candidates} "
        f"matched_outcomes={summary.champion_matched_outcomes} "
        f"unmatched_outcomes={summary.champion_unmatched_outcomes} "
        f"scanned={summary.champion_scanned} "
        f"failed={summary.champion_failed}"
    )
    print(
        "1v1: "
        f"candidates={summary.match_candidates} "
        f"parsed={summary.match_parsed} "
        f"matched={summary.match_matched} "
        f"failed={summary.match_failed}"
    )
    if summary.failure_reasons:
        reasons = ", ".join(f"{key}={value}" for key, value in sorted(summary.failure_reasons.items()))
        print(f"1v1 failure reasons: {reasons}")
    if extra:
        details = ", ".join(f"{key}={value}" for key, value in extra.items())
        print(f"Discovery: {details}")


def print_table(rows: list[OpportunityRow], limit: int | None = None) -> None:
    selected = rows[:limit] if limit else rows
    if not selected:
        print("No rows to display.")
        return
    dict_rows = [row.to_flat_dict() for row in selected]
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in dict_rows))
        for col in DISPLAY_COLUMNS
    }
    header = " | ".join(col.ljust(widths[col]) for col in DISPLAY_COLUMNS)
    print(header)
    print("-" * len(header))
    for row in dict_rows:
        print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in DISPLAY_COLUMNS))
    if limit and len(rows) > limit:
        print(f"... {len(rows) - limit} more rows not shown")


def write_csv(path: Path, rows: list[OpportunityRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat_rows = [row.to_flat_dict() for row in rows]
    fieldnames = list(flat_rows[0].keys()) if flat_rows else list(OpportunityRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in flat_rows:
            writable = dict(row)
            writable["raw"] = json.dumps(writable.get("raw") or {}, sort_keys=True)
            writer.writerow(writable)
    return path


def write_json(path: Path, rows: list[OpportunityRow], summary: ScanSummary) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": asdict(summary),
        "rows": [row.to_flat_dict() for row in rows],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path

