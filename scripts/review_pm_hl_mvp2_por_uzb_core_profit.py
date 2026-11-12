from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"
DOC_PATH = PROJECT_ROOT / "docs" / "pm_hl_mvp2_por_uzb_core_profit_review.md"
OUT_CSV = OUTPUT_DIR / "review_por_uzb_core_profit_table.csv"

CSV_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv"
JSON_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.json"
LOG_PATH = OUTPUT_DIR / "pm_hl_mvp2_overnight_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.log"

UTC8 = timezone(timedelta(hours=8))
SHARES = 20.0
PORTFOLIO_LOW = 108.0
PORTFOLIO_HIGH = 120.0


FIELDS = [
    "op_group",
    "outcome_or_condition",
    "side",
    "total_rows",
    "positive_rows",
    "positive_pct",
    "max_net",
    "mean_positive_net",
    "best_timestamp_utc8",
    "est_profit_20_shares",
    "portfolio_return_low_pct",
    "portfolio_return_high_pct",
    "mvp_decision",
    "comment",
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


def read_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json() -> dict[str, Any]:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def profit_fields(edge: float | None) -> dict[str, Any]:
    if edge is None:
        return {
            "est_profit_20_shares": None,
            "portfolio_return_low_pct": None,
            "portfolio_return_high_pct": None,
        }
    profit = edge * SHARES
    return {
        "est_profit_20_shares": profit,
        "portfolio_return_low_pct": profit / PORTFOLIO_LOW * 100,
        "portfolio_return_high_pct": profit / PORTFOLIO_HIGH * 100,
    }


def decision(op_group: str, max_edge: float | None) -> tuple[str, str]:
    if op_group == "cross_venue_direct_no_complete_set":
        return (
            "continue_op1_execution_mvp_research" if max_edge and max_edge > 0 else "monitor_only",
            "op1 is the only MVP2 execution candidate family; requires execution/VWAP validation.",
        )
    if op_group == "cross_venue_complement_basket":
        return (
            "paper_alpha_only" if max_edge and max_edge > 0 else "monitor_only",
            "op3 can be independent supplemental alpha, but not in MVP2 execution scope.",
        )
    if op_group == "cross_venue_single_outcome":
        return (
            "reference_only",
            "op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope.",
        )
    return (
        "diagnostic_only",
        "op4 is single-venue structure diagnostic only, not a trade trigger.",
    )


def summarize_group(rows: list[dict[str, str]], op_group: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("op_group") != op_group:
            continue
        edge = ffloat(row.get("net") or row.get("edge"))
        if edge is None:
            continue
        key = (row["outcome_or_condition"], row["side"])
        groups.setdefault(key, []).append({"timestamp": row["timestamp"], "edge": edge})
    out = []
    for (outcome, side), items in sorted(groups.items()):
        positives = [row for row in items if row["edge"] > 0]
        best = max(positives, key=lambda row: row["edge"], default=None)
        max_edge = best["edge"] if best else None
        mvp_decision, comment = decision(op_group, max_edge)
        result = {
            "op_group": op_group,
            "outcome_or_condition": outcome,
            "side": side,
            "total_rows": len(items),
            "positive_rows": len(positives),
            "positive_pct": len(positives) / len(items) if items else 0,
            "max_net": max_edge,
            "mean_positive_net": mean([row["edge"] for row in positives]),
            "best_timestamp_utc8": utc8(best["timestamp"]) if best else "",
            "mvp_decision": mvp_decision,
            "comment": comment,
        }
        result.update(profit_fields(max_edge))
        out.append(result)
    return out


def summarize_op4(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    wanted = {
        "polymarket sum_ask_minus_1 < 0": "PM sum_ask_minus_1 < 0",
        "polymarket sum_bid_minus_1 > 0": "PM sum_bid_minus_1 > 0",
        "hyperliquid sum_ask_minus_1 < 0": "HL sum_ask_minus_1 < 0",
        "hyperliquid sum_bid_minus_1 > 0": "HL sum_bid_minus_1 > 0",
    }
    out = []
    for condition_key, label in wanted.items():
        items = []
        for row in rows:
            if row.get("op_group") == "single_venue_three_way_sum_diagnostic" and row.get("outcome_or_condition") == condition_key:
                edge = ffloat(row.get("edge"))
                if edge is not None:
                    items.append({"timestamp": row["timestamp"], "edge": edge})
        positives = [row for row in items if row["edge"] > 0]
        best = max(positives, key=lambda row: row["edge"], default=None)
        max_edge = best["edge"] if best else None
        mvp_decision, comment = decision("single_venue_three_way_sum_diagnostic", max_edge)
        result = {
            "op_group": "single_venue_three_way_sum_diagnostic",
            "outcome_or_condition": label,
            "side": label.split()[0],
            "total_rows": len(items),
            "positive_rows": len(positives),
            "positive_pct": len(positives) / len(items) if items else 0,
            "max_net": max_edge,
            "mean_positive_net": mean([row["edge"] for row in positives]),
            "best_timestamp_utc8": utc8(best["timestamp"]) if best else "",
            "mvp_decision": mvp_decision,
            "comment": comment,
        }
        result.update(profit_fields(max_edge))
        out.append(result)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
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


def scan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    warnings = payload.get("warnings", [])
    snapshots = payload.get("snapshots", [])
    warning_snaps = [row for row in snapshots if row.get("status") == "warning"]
    first = warning_snaps[0] if warning_snaps else None
    return {
        "planned_iterations": payload.get("planned_iterations"),
        "completed_iterations": payload.get("completed_iterations"),
        "warnings": len(warnings),
        "first_warning_time_utc8": utc8(first["timestamp"]) if first else "",
        "data_reviewable": bool(payload.get("completed_iterations", 0) > 0),
    }


def write_markdown(rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    summary = scan_summary(payload)
    op1 = [row for row in rows if row["op_group"] == "cross_venue_direct_no_complete_set"]
    op3 = [row for row in rows if row["op_group"] == "cross_venue_complement_basket"]
    op2 = [row for row in rows if row["op_group"] == "cross_venue_single_outcome"]
    op4 = [row for row in rows if row["op_group"] == "single_venue_three_way_sum_diagnostic"]
    best_op1 = max(op1, key=lambda row: row["max_net"] or -999)
    best_op3 = max(op3, key=lambda row: row["max_net"] or -999)
    best_op2 = max(op2, key=lambda row: row["max_net"] or -999)
    report = f"""# PM-HL MVP2 Portugal vs Uzbekistan Core Profit Review

## Conclusions First

- Scan is reviewable: `{summary['completed_iterations']}` successful iterations, `{summary['warnings']}` warnings.
- Best op1 row: `{best_op1['outcome_or_condition']}` / `{best_op1['side']}` with max net `{fmt(best_op1['max_net'])}` and 20-share profit `{fmt(best_op1['est_profit_20_shares'])}`.
- Best op3 row: `{best_op3['outcome_or_condition']}` / `{best_op3['side']}` with max net `{fmt(best_op3['max_net'])}`; keep as paper alpha only.
- Compared with Argentina vs Austria, this match is weaker: no Argentina-style large op1 spike; current max op1 profit is only about `${fmt(best_op1['est_profit_20_shares'])}` per 20-share slot.

## 1. Scan Completeness

{md_table([summary], ['planned_iterations', 'completed_iterations', 'warnings', 'first_warning_time_utc8', 'data_reviewable'])}

## 2. op1: direct No-token complete-set

{md_table(op1, FIELDS)}

## 3. op3: complement basket

{md_table(op3, FIELDS)}

## 4. op2 Reference

Best op2 row: `{best_op2['outcome_or_condition']}` / `{best_op2['side']}` with max net `{fmt(best_op2['max_net'])}`. op2 remains reference-only and is not counted as independent buy-only execution alpha.

{md_table(op2, FIELDS)}

## 5. op4 Diagnostics

{md_table(op4, FIELDS)}

## Decision

This match supports continuing to monitor op1, but it is weaker than Argentina vs Austria for execution MVP evidence. It does not add a strong new case for immediate execution beyond the prior Argentina result. If execution work continues, use Argentina-style stronger op1 windows as the motivating case and keep Portugal vs Uzbekistan as a lower-edge validation sample.

## Source Files

- CSV: `{CSV_PATH}`
- JSON: `{JSON_PATH}`
- LOG: `{LOG_PATH}`
"""
    DOC_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    rows = read_rows()
    payload = read_json()
    _ = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    summary_rows = []
    summary_rows.extend(summarize_group(rows, "cross_venue_direct_no_complete_set"))
    summary_rows.extend(summarize_group(rows, "cross_venue_single_outcome"))
    summary_rows.extend(summarize_group(rows, "cross_venue_complement_basket"))
    summary_rows.extend(summarize_op4(rows))
    write_csv(OUT_CSV, summary_rows)
    write_markdown(summary_rows, payload)
    print(f"Markdown: {DOC_PATH}")
    print(f"CSV: {OUT_CSV}")
    print("Scan:", scan_summary(payload))


if __name__ == "__main__":
    main()

