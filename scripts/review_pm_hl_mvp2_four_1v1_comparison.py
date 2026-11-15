from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"
DOC_PATH = PROJECT_ROOT / "docs" / "pm_hl_mvp2_four_1v1_opportunity_comparison.md"
MATCH_SUMMARY_CSV = OUTPUT_DIR / "mvp2_four_1v1_match_summary.csv"
OPPORTUNITY_CSV = OUTPUT_DIR / "mvp2_four_1v1_opportunity_comparison.csv"

UTC8 = timezone(timedelta(hours=8))
SHARES = 20.0
PORTFOLIO_LOW = 108.0
PORTFOLIO_HIGH = 120.0


MATCHES = [
    {
        "match": "Argentina vs Austria",
        "csv": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv",
        "json": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json",
    },
    {
        "match": "Portugal vs Uzbekistan",
        "csv": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv",
        "json": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.json",
    },
    {
        "match": "Switzerland vs Canada",
        "csv": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_sui-can_20260624_165140.csv",
        "json": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_sui-can_20260624_165140.json",
    },
    {
        "match": "Bosnia and Herzegovina vs Qatar",
        "csv": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_bih-qat_20260624_165144.csv",
        "json": OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_bih-qat_20260624_165144.json",
    },
]

MATCH_SUMMARY_FIELDS = [
    "match",
    "completed_iterations",
    "warning_count",
    "first_warning_time_utc8",
    "op1_max_net",
    "op1_positive_rows",
    "op1_positive_pct",
    "op1_best_outcome",
    "op1_best_side",
    "op1_est_profit_20",
    "op1_portfolio_return_range",
    "op3_max_net",
    "op3_positive_rows",
    "op3_positive_pct",
    "op4_best_condition",
    "short_conclusion",
]

OPPORTUNITY_FIELDS = [
    "match",
    "op_group",
    "total_rows",
    "positive_rows",
    "positive_pct",
    "max_net_or_edge",
    "mean_positive_net_or_edge",
    "best_outcome_or_condition",
    "best_side",
    "est_profit_20",
    "portfolio_return_low_pct",
    "portfolio_return_high_pct",
    "execution_suitability",
]


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc8(value: str) -> str:
    return parse_ts(value).astimezone(UTC8).strftime("%Y-%m-%d %H:%M:%S UTC+8")


def ffloat(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def row_key(row: dict[str, str]) -> str:
    return row.get("outcome_or_condition") or row.get("key") or ""


def row_edge(row: dict[str, str]) -> float | None:
    op_group = row.get("op_group")
    if op_group in {
        "cross_venue_direct_no_complete_set",
        "cross_venue_single_outcome",
        "cross_venue_complement_basket",
    }:
        return ffloat(row.get("net"))
    if op_group == "single_venue_three_way_sum_diagnostic":
        if row.get("edge") not in (None, ""):
            return ffloat(row.get("edge"))
        key = row_key(row)
        sum_ask = ffloat(row.get("sum_ask"))
        sum_bid = ffloat(row.get("sum_bid"))
        if key in {"polymarket", "hyperliquid"}:
            return None
        if "sum_ask_minus_1 < 0" in key:
            return None if sum_ask is None else 1.0 - sum_ask
        if "sum_bid_minus_1 > 0" in key:
            return None if sum_bid is None else sum_bid - 1.0
    return None


def expand_old_diag(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    expanded: list[dict[str, str]] = []
    for row in rows:
        if row.get("op_group") != "single_venue_three_way_sum_diagnostic":
            expanded.append(row)
            continue
        key = row_key(row)
        if key not in {"polymarket", "hyperliquid"}:
            expanded.append(row)
            continue
        for suffix in ("sum_ask_minus_1 < 0", "sum_bid_minus_1 > 0"):
            copy = dict(row)
            label = "PM" if key == "polymarket" else "HL"
            copy["outcome_or_condition"] = f"{label} {suffix}"
            copy["side"] = key
            expanded.append(copy)
    return expanded


def profit(edge: float | None) -> dict[str, Any]:
    if edge is None:
        return {
            "est_profit_20": None,
            "portfolio_return_low_pct": None,
            "portfolio_return_high_pct": None,
        }
    p = edge * SHARES
    return {
        "est_profit_20": p,
        "portfolio_return_low_pct": p / PORTFOLIO_LOW * 100,
        "portfolio_return_high_pct": p / PORTFOLIO_HIGH * 100,
    }


def suitability(op_group: str) -> str:
    if op_group == "cross_venue_direct_no_complete_set":
        return "include_v1_execution"
    if op_group == "cross_venue_single_outcome":
        return "monitor_only_reference"
    if op_group == "cross_venue_complement_basket":
        return "future_research"
    return "diagnostic_only"


def summarize_match_op_group(match: str, rows: list[dict[str, str]], op_group: str) -> dict[str, Any]:
    group_rows = [row for row in rows if row.get("op_group") == op_group]
    edges = [(row, row_edge(row)) for row in group_rows]
    edges = [(row, edge) for row, edge in edges if edge is not None]
    positives = [(row, edge) for row, edge in edges if edge > 0]
    best_row, best_edge = max(positives, key=lambda item: item[1], default=(None, None))
    result = {
        "match": match,
        "op_group": op_group,
        "total_rows": len(edges),
        "positive_rows": len(positives),
        "positive_pct": len(positives) / len(edges) if edges else 0.0,
        "max_net_or_edge": best_edge,
        "mean_positive_net_or_edge": mean([edge for _, edge in positives]),
        "best_outcome_or_condition": row_key(best_row) if best_row else "",
        "best_side": best_row.get("side", "") if best_row else "",
        "execution_suitability": suitability(op_group),
    }
    result.update(profit(best_edge))
    return result


def json_summary(payload: dict[str, Any]) -> tuple[int, int, str]:
    warnings = payload.get("warnings", [])
    first_warning = ""
    for snap in payload.get("snapshots", []):
        if snap.get("status") == "warning":
            first_warning = utc8(snap["timestamp"])
            break
    return int(payload.get("completed_iterations") or 0), len(warnings), first_warning


def match_conclusion(op1: dict[str, Any], op3: dict[str, Any]) -> str:
    if (op1.get("max_net_or_edge") or 0) > 0.02:
        return "strong op1 spike; best execution-layer evidence"
    if (op1.get("max_net_or_edge") or 0) > 0.005:
        return "positive but modest op1; useful validation sample"
    if (op3.get("max_net_or_edge") or 0) > (op1.get("max_net_or_edge") or 0):
        return "op3 better than op1 but remains future research"
    return "weak opportunity; monitor only"


def build_tables() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    match_summary: list[dict[str, Any]] = []
    opportunity_rows: list[dict[str, Any]] = []
    loaded_files: list[dict[str, Any]] = []
    for spec in MATCHES:
        rows = expand_old_diag(read_csv(spec["csv"]))
        payload = read_json(spec["json"])
        completed, warning_count, first_warning = json_summary(payload)
        loaded_files.append({"match": spec["match"], "csv": str(spec["csv"]), "json": str(spec["json"])})
        summaries = {
            op_group: summarize_match_op_group(spec["match"], rows, op_group)
            for op_group in (
                "cross_venue_direct_no_complete_set",
                "cross_venue_single_outcome",
                "cross_venue_complement_basket",
                "single_venue_three_way_sum_diagnostic",
            )
        }
        opportunity_rows.extend(summaries.values())
        op1 = summaries["cross_venue_direct_no_complete_set"]
        op3 = summaries["cross_venue_complement_basket"]
        op4 = summaries["single_venue_three_way_sum_diagnostic"]
        match_summary.append(
            {
                "match": spec["match"],
                "completed_iterations": completed,
                "warning_count": warning_count,
                "first_warning_time_utc8": first_warning,
                "op1_max_net": op1["max_net_or_edge"],
                "op1_positive_rows": op1["positive_rows"],
                "op1_positive_pct": op1["positive_pct"],
                "op1_best_outcome": op1["best_outcome_or_condition"],
                "op1_best_side": op1["best_side"],
                "op1_est_profit_20": op1["est_profit_20"],
                "op1_portfolio_return_range": (
                    f"{op1['portfolio_return_high_pct']:.3f}% - {op1['portfolio_return_low_pct']:.3f}%"
                    if op1["portfolio_return_low_pct"] is not None
                    else ""
                ),
                "op3_max_net": op3["max_net_or_edge"],
                "op3_positive_rows": op3["positive_rows"],
                "op3_positive_pct": op3["positive_pct"],
                "op4_best_condition": op4["best_outcome_or_condition"],
                "short_conclusion": match_conclusion(op1, op3),
            }
        )
    decision_rows = execution_decision_table(opportunity_rows)
    ranking_rows = final_ranking_table(opportunity_rows)
    return match_summary, opportunity_rows, decision_rows, ranking_rows


def aggregate_by_group(rows: list[dict[str, Any]], op_group: str) -> dict[str, Any]:
    selected = [row for row in rows if row["op_group"] == op_group]
    total = sum(int(row["total_rows"]) for row in selected)
    positive = sum(int(row["positive_rows"]) for row in selected)
    best = max(selected, key=lambda row: row["max_net_or_edge"] or -999)
    matches_positive = sum(1 for row in selected if (row["max_net_or_edge"] or 0) > 0)
    return {
        "total": total,
        "positive": positive,
        "positive_pct": positive / total if total else 0.0,
        "best": best,
        "matches_positive": matches_positive,
    }


def execution_decision_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    specs = [
        ("cross_venue_direct_no_complete_set", "yes", "yes", "moderate: strong Argentina spike plus modest positives in other matches", "seen in all 4 matches, but concentrated in spikes", "medium", "include_v1_execution", "Only buy-only candidate family; strongest risk/reward evidence."),
        ("cross_venue_single_outcome", "no", "no", "mirrors op1 price discrepancies", "frequent but not independent", "medium/high due to sell/inventory assumptions", "monitor_only", "Do not double count op1-like edge."),
        ("cross_venue_complement_basket", "yes but 3-leg", "yes", "small positives, weaker than op1", "sporadic", "high, three-leg execution", "future_research", "Independent alpha exists but not v1 execution."),
        ("single_venue_three_way_sum_diagnostic", "no", "no", "diagnostic signals present", "varies by venue", "not an execution strategy", "diagnostic_only", "Useful sanity/future research only."),
    ]
    for op_group, buy_only, independent, strength, frequency, complexity, decision, reason in specs:
        agg = aggregate_by_group(rows, op_group)
        out.append(
            {
                "opportunity": op_group,
                "buy_only_executable": buy_only,
                "independent_alpha": independent,
                "observed_strength": f"{strength}; max={agg['best']['max_net_or_edge']:.6f}",
                "frequency": f"{frequency}; positive_rows={agg['positive']}/{agg['total']}",
                "complexity": complexity,
                "execution_layer_decision": decision,
                "reason": reason,
            }
        )
    return out


def final_ranking_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "opportunity": "cross_venue_direct_no_complete_set",
            "evidence_from_4_matches": "Best max edge and only scoped buy-only candidate; Argentina spike plus smaller positives elsewhere.",
            "estimated_value": "highest MVP value; best observed 20-share profit about $1.39",
            "implementation_cost": "medium",
            "decision": "include_v1_execution",
        },
        {
            "rank": 2,
            "opportunity": "cross_venue_complement_basket",
            "evidence_from_4_matches": "Independent positives exist, but max and frequency weaker; three-leg execution.",
            "estimated_value": "supplemental alpha",
            "implementation_cost": "high",
            "decision": "future_research",
        },
        {
            "rank": 3,
            "opportunity": "cross_venue_single_outcome",
            "evidence_from_4_matches": "Useful reference but overlaps op1 economics and requires sell/inventory assumptions.",
            "estimated_value": "monitoring signal",
            "implementation_cost": "medium/high",
            "decision": "monitor_only",
        },
        {
            "rank": 4,
            "opportunity": "single_venue_three_way_sum_diagnostic",
            "evidence_from_4_matches": "Shows structure changes and diagnostic opportunities, not MVP2 execution scope.",
            "estimated_value": "diagnostic/future MVP3",
            "implementation_cost": "n/a",
            "decision": "diagnostic_only",
        },
    ]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def md_table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt(row.get(field)) for field in fields) + " |")
    return "\n".join(lines)


def write_report(match_summary: list[dict[str, Any]], opportunity_rows: list[dict[str, Any]], decision_rows: list[dict[str, Any]], ranking_rows: list[dict[str, Any]]) -> None:
    best_match = max(match_summary, key=lambda row: row["op1_max_net"] or -999)
    report = f"""# PM-HL MVP2 Four 1v1 Opportunity Comparison

## Conclusions First

- Best execution-layer candidate: **op1 / cross_venue_direct_no_complete_set**.
- Strongest evidence still comes from **{best_match['match']}**, with op1 max net `{fmt(best_match['op1_max_net'])}` and 20-share profit `{fmt(best_match['op1_est_profit_20'])}`.
- op3 has independent supplemental alpha, but it is weaker and more complex because it needs three legs.
- op2 is useful as a reference/mirror but should not be double-counted as independent buy-only execution alpha.
- op4 remains diagnostic only.

## Table 1: Match-level Summary

{md_table(match_summary, MATCH_SUMMARY_FIELDS)}

## Table 2: op-group Comparison

{md_table(opportunity_rows, OPPORTUNITY_FIELDS)}

## Table 3: Execution Decision Table

{md_table(decision_rows, ['opportunity', 'buy_only_executable', 'independent_alpha', 'observed_strength', 'frequency', 'complexity', 'execution_layer_decision', 'reason'])}

## Table 4: Final Ranking

{md_table(ranking_rows, ['rank', 'opportunity', 'evidence_from_4_matches', 'estimated_value', 'implementation_cost', 'decision'])}

## Notes

- Returns are MVP rough calculations: `max_net_or_edge * 20 shares`.
- Portfolio denominator is `$108-$120` for six 20-share slots.
- Positive rows are monitoring observations, not independent executable trades.
- No monitor was started by this review.
"""
    DOC_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    match_summary, opportunity_rows, decision_rows, ranking_rows = build_tables()
    write_csv(MATCH_SUMMARY_CSV, match_summary, MATCH_SUMMARY_FIELDS)
    write_csv(OPPORTUNITY_CSV, opportunity_rows, OPPORTUNITY_FIELDS)
    write_report(match_summary, opportunity_rows, decision_rows, ranking_rows)
    print(f"Markdown: {DOC_PATH}")
    print(f"Match summary CSV: {MATCH_SUMMARY_CSV}")
    print(f"Opportunity comparison CSV: {OPPORTUNITY_CSV}")


if __name__ == "__main__":
    main()

