from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"

FINAL_REPORT = PROJECT_ROOT / "docs" / "pm_hl_mvp2_final_report.md"
HANDOFF = PROJECT_ROOT / "docs" / "pm_hl_execution_layer_v1_handoff.md"

FINAL_SUMMARY_CSV = OUTPUT_DIR / "mvp2_four_match_final_summary.csv"
GROUP_SUMMARY_CSV = OUTPUT_DIR / "mvp2_opportunity_group_summary.csv"
WINDOWS_CSV = OUTPUT_DIR / "mvp2_positive_windows_detail.csv"
HANDOFF_DECISION_CSV = OUTPUT_DIR / "mvp2_execution_handoff_decision.csv"

UTC8 = timezone(timedelta(hours=8))
SHARES = 20.0
PORTFOLIO_LOW = 108.0
PORTFOLIO_HIGH = 120.0
WINDOW_GAP_SECONDS = 90

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

OP_GROUPS = (
    "cross_venue_direct_no_complete_set",
    "cross_venue_single_outcome",
    "cross_venue_complement_basket",
    "single_venue_three_way_sum_diagnostic",
)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_utc8(value: str | datetime | None) -> str:
    if value is None:
        return ""
    dt = parse_ts(value) if isinstance(value, str) else value
    return dt.astimezone(UTC8).strftime("%Y-%m-%d %H:%M:%S UTC+8")


def ffloat(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def row_key(row: dict[str, str]) -> str:
    return row.get("outcome_or_condition") or row.get("key") or ""


def row_side(row: dict[str, str]) -> str:
    return row.get("side") or ""


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
        ask = ffloat(row.get("sum_ask"))
        bid = ffloat(row.get("sum_bid"))
        if key in {"polymarket", "hyperliquid"}:
            return None
        if "sum_ask_minus_1 < 0" in key:
            return None if ask is None else 1.0 - ask
        if "sum_bid_minus_1 > 0" in key:
            return None if bid is None else bid - 1.0
    return None


def expand_diag(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    expanded: list[dict[str, str]] = []
    for row in rows:
        if row.get("op_group") != "single_venue_three_way_sum_diagnostic":
            expanded.append(row)
            continue
        key = row_key(row)
        if key not in {"polymarket", "hyperliquid"}:
            expanded.append(row)
            continue
        prefix = "PM" if key == "polymarket" else "HL"
        for suffix in ("sum_ask_minus_1 < 0", "sum_bid_minus_1 > 0"):
            new_row = dict(row)
            new_row["outcome_or_condition"] = f"{prefix} {suffix}"
            new_row["side"] = key
            expanded.append(new_row)
    return expanded


def profit(edge: float | None) -> dict[str, Any]:
    if edge is None:
        return {
            "est_profit_20_shares": None,
            "portfolio_return_low_pct": None,
            "portfolio_return_high_pct": None,
        }
    p = edge * SHARES
    return {
        "est_profit_20_shares": p,
        "portfolio_return_low_pct": p / PORTFOLIO_LOW * 100,
        "portfolio_return_high_pct": p / PORTFOLIO_HIGH * 100,
    }


def summarize_op_group(match: str, rows: list[dict[str, str]], op_group: str) -> dict[str, Any]:
    group_rows = [row for row in rows if row.get("op_group") == op_group]
    edge_rows = [(row, row_edge(row)) for row in group_rows]
    edge_rows = [(row, edge) for row, edge in edge_rows if edge is not None]
    positive = [(row, edge) for row, edge in edge_rows if edge > 0]
    best_row, best_edge = max(positive, key=lambda item: item[1], default=(None, None))
    result = {
        "match": match,
        "op_group": op_group,
        "total_rows": len(edge_rows),
        "positive_rows": len(positive),
        "positive_pct": len(positive) / len(edge_rows) if edge_rows else 0.0,
        "positive_windows": len(positive_windows(match, rows, op_group)),
        "max_net_or_edge": best_edge,
        "mean_positive_net_or_edge": mean([edge for _, edge in positive]),
        "best_outcome_or_condition": row_key(best_row) if best_row else "",
        "best_side": row_side(best_row) if best_row else "",
    }
    result.update(profit(best_edge))
    result["execution_decision"] = execution_decision(op_group)
    return result


def positive_windows(match: str, rows: list[dict[str, str]], op_group: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("op_group") != op_group:
            continue
        edge = row_edge(row)
        if edge is None or edge <= 0:
            continue
        grouped[(row_key(row), row_side(row))].append(
            {
                "match": match,
                "op_group": op_group,
                "outcome_or_condition": row_key(row),
                "side": row_side(row),
                "timestamp": parse_ts(row["timestamp"]),
                "edge": edge,
            }
        )
    windows: list[dict[str, Any]] = []
    for (key, side), items in grouped.items():
        items = sorted(items, key=lambda row: row["timestamp"])
        current: list[dict[str, Any]] = []
        for item in items:
            if not current or (item["timestamp"] - current[-1]["timestamp"]).total_seconds() <= WINDOW_GAP_SECONDS:
                current.append(item)
            else:
                windows.append(window_row(match, op_group, key, side, current))
                current = [item]
        if current:
            windows.append(window_row(match, op_group, key, side, current))
    return windows


def window_row(match: str, op_group: str, key: str, side: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    start = items[0]["timestamp"]
    end = items[-1]["timestamp"]
    best = max(items, key=lambda row: row["edge"])
    max_edge = best["edge"]
    result = {
        "match": match,
        "op_group": op_group,
        "outcome_or_condition": key,
        "side": side,
        "window_start_utc8": fmt_utc8(start),
        "window_end_utc8": fmt_utc8(end),
        "duration_seconds": (end - start).total_seconds(),
        "positive_rows_in_window": len(items),
        "max_net_or_edge": max_edge,
        "mean_net_or_edge": mean([row["edge"] for row in items]),
        "best_timestamp_utc8": fmt_utc8(best["timestamp"]),
    }
    result.update(profit(max_edge))
    return result


def json_stats(payload: dict[str, Any]) -> tuple[int, int, str]:
    warnings = payload.get("warnings", [])
    first_warning = ""
    for snap in payload.get("snapshots", []):
        if snap.get("status") == "warning":
            first_warning = fmt_utc8(snap["timestamp"])
            break
    return int(payload.get("completed_iterations") or 0), len(warnings), first_warning


def execution_decision(op_group: str) -> str:
    return {
        "cross_venue_direct_no_complete_set": "include_v1_execution",
        "cross_venue_single_outcome": "monitor_only",
        "cross_venue_complement_basket": "future_research",
        "single_venue_three_way_sum_diagnostic": "diagnostic_only",
    }[op_group]


def load_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    final_summary: list[dict[str, Any]] = []
    group_summary: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    for spec in MATCHES:
        rows = expand_diag(read_csv(spec["csv"]))
        payload = read_json(spec["json"])
        completed, warning_count, first_warning = json_stats(payload)
        summaries = {op: summarize_op_group(spec["match"], rows, op) for op in OP_GROUPS}
        group_summary.extend(summaries.values())
        for op in OP_GROUPS:
            windows.extend(positive_windows(spec["match"], rows, op))
        op1 = summaries["cross_venue_direct_no_complete_set"]
        op3 = summaries["cross_venue_complement_basket"]
        op4 = summaries["single_venue_three_way_sum_diagnostic"]
        final_summary.append(
            {
                "match": spec["match"],
                "completed_iterations": completed,
                "warning_count": warning_count,
                "first_warning_time_utc8": first_warning,
                "op1_max_net": op1["max_net_or_edge"],
                "op1_positive_rows": op1["positive_rows"],
                "op1_positive_windows": op1["positive_windows"],
                "op1_best_outcome": op1["best_outcome_or_condition"],
                "op1_best_side": op1["best_side"],
                "op1_best_profit_20_shares": op1["est_profit_20_shares"],
                "op1_portfolio_return_range": return_range(op1),
                "op3_max_net": op3["max_net_or_edge"],
                "op3_positive_rows": op3["positive_rows"],
                "op3_positive_windows": op3["positive_windows"],
                "op3_best_outcome": op3["best_outcome_or_condition"],
                "op3_best_side": op3["best_side"],
                "op4_best_condition": op4["best_outcome_or_condition"],
                "final_conclusion": match_conclusion(op1, op3),
            }
        )
    return final_summary, group_summary, windows


def return_range(row: dict[str, Any]) -> str:
    if row.get("portfolio_return_low_pct") is None:
        return ""
    return f"{row['portfolio_return_high_pct']:.3f}% - {row['portfolio_return_low_pct']:.3f}%"


def match_conclusion(op1: dict[str, Any], op3: dict[str, Any]) -> str:
    if (op1.get("max_net_or_edge") or 0) > 0.02:
        return "strong op1 evidence"
    if (op3.get("max_net_or_edge") or 0) > (op1.get("max_net_or_edge") or 0):
        return "op3 stronger but future research"
    if (op1.get("max_net_or_edge") or 0) > 0:
        return "modest op1 validation"
    return "weak monitor-only evidence"


def handoff_decision_rows(group_summary: list[dict[str, Any]], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "opportunity": "op1 cross_venue_direct_no_complete_set",
            "buy_only_executable": "yes",
            "independent_alpha": "yes",
            "observed_strength": "Strongest evidence across four matches; best 20-share profit about $1.39",
            "positive_window_evidence": window_evidence(windows, "cross_venue_direct_no_complete_set"),
            "implementation_complexity": "medium",
            "execution_layer_decision": "include_v1_execution",
            "reason": "Only scoped two-leg buy-only candidate; positive windows across all four matches.",
        },
        {
            "opportunity": "op2 cross_venue_single_outcome",
            "buy_only_executable": "no",
            "independent_alpha": "no",
            "observed_strength": "Overlaps op1 pricing evidence",
            "positive_window_evidence": window_evidence(windows, "cross_venue_single_outcome"),
            "implementation_complexity": "medium/high",
            "execution_layer_decision": "monitor_only",
            "reason": "Reference signal, not independent buy-only execution.",
        },
        {
            "opportunity": "op3 cross_venue_complement_basket",
            "buy_only_executable": "yes but three-leg",
            "independent_alpha": "yes",
            "observed_strength": "Independent positives exist, notably Switzerland and Bosnia/Qatar",
            "positive_window_evidence": window_evidence(windows, "cross_venue_complement_basket"),
            "implementation_complexity": "high",
            "execution_layer_decision": "future_research",
            "reason": "Three-leg execution is too complex for v1.",
        },
        {
            "opportunity": "op4 single_venue_three_way_sum_diagnostic",
            "buy_only_executable": "no",
            "independent_alpha": "no",
            "observed_strength": "Useful structure/quality signal only",
            "positive_window_evidence": window_evidence(windows, "single_venue_three_way_sum_diagnostic"),
            "implementation_complexity": "n/a",
            "execution_layer_decision": "diagnostic_only",
            "reason": "Not a PM-HL cross-venue execution candidate.",
        },
    ]


def window_evidence(windows: list[dict[str, Any]], op_group: str) -> str:
    selected = [row for row in windows if row["op_group"] == op_group]
    if not selected:
        return "0 positive windows"
    best = max(selected, key=lambda row: row["max_net_or_edge"])
    return f"{len(selected)} windows; best={best['max_net_or_edge']:.6f} in {best['match']}"


def final_ranking_rows() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "opportunity": "op1 cross_venue_direct_no_complete_set",
            "evidence_from_4_matches": "Positive windows in all four matches; strongest max edge in Argentina and Switzerland.",
            "estimated_value": "Best v1 value; max observed 20-share profit about $1.39",
            "implementation_cost": "medium",
            "decision": "include_v1_execution",
        },
        {
            "rank": 2,
            "opportunity": "op3 cross_venue_complement_basket",
            "evidence_from_4_matches": "Independent alpha but weaker/sporadic and three-leg.",
            "estimated_value": "supplemental future alpha",
            "implementation_cost": "high",
            "decision": "future_research",
        },
        {
            "rank": 3,
            "opportunity": "op2 cross_venue_single_outcome",
            "evidence_from_4_matches": "Useful mirror/reference of cross-venue pricing.",
            "estimated_value": "monitoring signal",
            "implementation_cost": "medium/high",
            "decision": "monitor_only",
        },
        {
            "rank": 4,
            "opportunity": "op4 single_venue_three_way_sum_diagnostic",
            "evidence_from_4_matches": "Good structural diagnostic, not execution signal.",
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


FINAL_SUMMARY_FIELDS = [
    "match",
    "completed_iterations",
    "warning_count",
    "first_warning_time_utc8",
    "op1_max_net",
    "op1_positive_rows",
    "op1_positive_windows",
    "op1_best_outcome",
    "op1_best_side",
    "op1_best_profit_20_shares",
    "op1_portfolio_return_range",
    "op3_max_net",
    "op3_positive_rows",
    "op3_positive_windows",
    "op3_best_outcome",
    "op3_best_side",
    "op4_best_condition",
    "final_conclusion",
]

GROUP_SUMMARY_FIELDS = [
    "match",
    "op_group",
    "total_rows",
    "positive_rows",
    "positive_pct",
    "positive_windows",
    "max_net_or_edge",
    "mean_positive_net_or_edge",
    "best_outcome_or_condition",
    "best_side",
    "est_profit_20_shares",
    "portfolio_return_low_pct",
    "portfolio_return_high_pct",
    "execution_decision",
]

WINDOW_FIELDS = [
    "match",
    "op_group",
    "outcome_or_condition",
    "side",
    "window_start_utc8",
    "window_end_utc8",
    "duration_seconds",
    "positive_rows_in_window",
    "max_net_or_edge",
    "mean_net_or_edge",
    "best_timestamp_utc8",
    "est_profit_20_shares",
    "portfolio_return_low_pct",
    "portfolio_return_high_pct",
]

HANDOFF_FIELDS = [
    "opportunity",
    "buy_only_executable",
    "independent_alpha",
    "observed_strength",
    "positive_window_evidence",
    "implementation_complexity",
    "execution_layer_decision",
    "reason",
]


def write_reports(final_summary: list[dict[str, Any]], group_summary: list[dict[str, Any]], windows: list[dict[str, Any]], handoff: list[dict[str, Any]]) -> None:
    ranking = final_ranking_rows()
    best = max(final_summary, key=lambda row: row["op1_max_net"] or -999)
    report = f"""# PM-HL MVP2 Final Report

## 1. Executive Summary

MVP2 scanner research can close. Across four 1v1 Moneyline matches, the only opportunity family that should move into execution layer v1 is **op1: cross_venue_direct_no_complete_set**.

Strongest match evidence: **{best['match']}**, op1 max net `{fmt(best['op1_max_net'])}`, estimated 20-share profit `{fmt(best['op1_best_profit_20_shares'])}`.

## 2. Four-match Evidence

{md_table(final_summary, FINAL_SUMMARY_FIELDS)}

## 3. Positive Window Analysis

Positive window rule: consecutive positive rows are grouped if gaps are <= 90 seconds.

{md_table(windows[:40], WINDOW_FIELDS)}

Full window detail is in `outputs/pm_hl_mvp2_scanner/mvp2_positive_windows_detail.csv`.

## 4. Opportunity Decision

{md_table(handoff, HANDOFF_FIELDS)}

## 5. Expected MVP Return Rough Range

Returns are MVP rough estimates: `max_net_or_edge * 20 shares`, portfolio denominator `$108-$120`.

{md_table(group_summary, GROUP_SUMMARY_FIELDS)}

## 6. Main Risks

- Single-leg exposure if only one venue fills.
- Stale quote between signal and execution.
- Rule/revalidation mismatch between PM and HL.
- Top-of-book monitor rows are not VWAP/fill-verified.
- Fee/slippage can erase small gross edges.

## 7. Execution Layer Handoff

Execution layer v1 should take only op1 signals, paper first, then tiny live. It must revalidate both legs, require manual approval, record fills, compute PnL, and include kill switch plus no retry/chase.

## 8. MVP3 Backlog

- op3 complement basket execution research.
- op4 single-venue structural diagnostics.
- deeper book/VWAP simulation.
- multi-match portfolio allocator.
"""
    FINAL_REPORT.write_text(report, encoding="utf-8")

    handoff_note = f"""# PM-HL Execution Layer v1 Handoff

## Scope

- Strategy: op1 `cross_venue_direct_no_complete_set` only
- Market: 1v1 Moneyline first
- Mode: paper first, then tiny live
- Size: 20 shares per slot

## Flow

1. Scanner signal
2. Manual approve
3. Revalidate both legs
4. Paper or tiny execution
5. Record fills
6. Compute PnL

## Must-have Risk Controls

- Kill switch
- No auto retry/chase
- Single-leg exposure handling
- Max one active trade per match/outcome
- Fresh quote revalidation immediately before action

## Not in v1

- op2
- op3
- op4
- WC Winner
- Portfolio allocator
- Automatic re-entry
- S1/S2 live state machine reuse from MVP1

## Evidence

Four-match MVP2 scanner research supports op1-only execution v1. See `{FINAL_REPORT}`.
"""
    HANDOFF.write_text(handoff_note, encoding="utf-8")


def main() -> None:
    final_summary, group_summary, windows = load_all()
    handoff = handoff_decision_rows(group_summary, windows)
    write_csv(FINAL_SUMMARY_CSV, final_summary, FINAL_SUMMARY_FIELDS)
    write_csv(GROUP_SUMMARY_CSV, group_summary, GROUP_SUMMARY_FIELDS)
    write_csv(WINDOWS_CSV, windows, WINDOW_FIELDS)
    write_csv(HANDOFF_DECISION_CSV, handoff, HANDOFF_FIELDS)
    write_reports(final_summary, group_summary, windows, handoff)
    print(f"Final report: {FINAL_REPORT}")
    print(f"Handoff: {HANDOFF}")
    print(f"Final summary CSV: {FINAL_SUMMARY_CSV}")
    print(f"Group summary CSV: {GROUP_SUMMARY_CSV}")
    print(f"Windows CSV: {WINDOWS_CSV}")
    print(f"Handoff decision CSV: {HANDOFF_DECISION_CSV}")


if __name__ == "__main__":
    main()

