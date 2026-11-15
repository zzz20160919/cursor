from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"
DOC_PATH = PROJECT_ROOT / "docs" / "pm_hl_mvp2_arg_aut_core_profit_table.md"
OUT_CSV = OUTPUT_DIR / "review_arg_aut_core_profit_table.csv"

CSV_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv"
JSON_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json"
LOG_PATH = OUTPUT_DIR / "pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log"

UTC8 = timezone(timedelta(hours=8))
SLOT_SHARES = 20.0
PORTFOLIO_LOW = 108.0
PORTFOLIO_HIGH = 120.0


FIELDS = [
    "op_group",
    "outcome_or_condition",
    "side",
    "total_rows",
    "positive_rows",
    "positive_pct",
    "max_positive_net_or_edge",
    "mean_positive_net_or_edge",
    "best_timestamp_utc8",
    "est_profit_20_shares",
    "est_portfolio_return_low_pct",
    "est_portfolio_return_high_pct",
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


def decision(op_group: str, max_edge: float | None) -> tuple[str, str]:
    if op_group == "cross_venue_direct_no_complete_set":
        if max_edge and max_edge > 0:
            return (
                "continue_op1_execution_mvp_research",
                "Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation.",
            )
        return ("monitor_only", "No positive op1 edge observed.")
    if op_group in {"cross_venue_single_outcome", "cross_venue_complement_basket"}:
        return ("paper_monitor_only", "Keep monitoring/research; do not enter MVP2 execution scope.")
    return ("diagnostic_only", "Single-venue structural signal only; do not use as MVP2 execution trigger.")


def profit_fields(edge: float | None) -> dict[str, Any]:
    profit = (edge or 0.0) * SLOT_SHARES
    return {
        "est_profit_20_shares": profit if edge is not None else None,
        "est_portfolio_return_low_pct": profit / PORTFOLIO_LOW * 100 if edge is not None else None,
        "est_portfolio_return_high_pct": profit / PORTFOLIO_HIGH * 100 if edge is not None else None,
    }


def summarize_opportunities(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        op_group = row.get("op_group", "")
        if op_group not in {
            "cross_venue_direct_no_complete_set",
            "cross_venue_single_outcome",
            "cross_venue_complement_basket",
        }:
            continue
        net = ffloat(row.get("net"))
        if net is None:
            continue
        key = (op_group, row.get("key", ""), row.get("side", ""))
        groups.setdefault(key, []).append(
            {
                "timestamp": row["timestamp"],
                "net": net,
            }
        )

    out: list[dict[str, Any]] = []
    for (op_group, outcome, side), items in sorted(groups.items()):
        positives = [row for row in items if row["net"] > 0]
        best = max(positives, key=lambda row: row["net"], default=None)
        max_edge = best["net"] if best else None
        mvp_decision, comment = decision(op_group, max_edge)
        result = {
            "op_group": op_group,
            "outcome_or_condition": outcome,
            "side": side,
            "total_rows": len(items),
            "positive_rows": len(positives),
            "positive_pct": len(positives) / len(items) if items else 0.0,
            "max_positive_net_or_edge": max_edge,
            "mean_positive_net_or_edge": mean([row["net"] for row in positives]),
            "best_timestamp_utc8": utc8(best["timestamp"]) if best else "",
            "mvp_decision": mvp_decision,
            "comment": comment,
        }
        result.update(profit_fields(max_edge))
        out.append(result)
    return out


def summarize_diagnostics(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    diag_rows = [row for row in rows if row.get("op_group") == "single_venue_three_way_sum_diagnostic"]
    specs = [
        ("polymarket", "PM sum_ask_minus_1 < 0", "sum_ask", lambda ask, bid: None if ask is None else 1.0 - ask),
        ("polymarket", "PM sum_bid_minus_1 > 0", "sum_bid", lambda ask, bid: None if bid is None else bid - 1.0),
        ("hyperliquid", "HL sum_ask_minus_1 < 0", "sum_ask", lambda ask, bid: None if ask is None else 1.0 - ask),
        ("hyperliquid", "HL sum_bid_minus_1 > 0", "sum_bid", lambda ask, bid: None if bid is None else bid - 1.0),
    ]
    out: list[dict[str, Any]] = []
    for venue, condition, required_field, edge_fn in specs:
        items = [row for row in diag_rows if row.get("key") == venue]
        valid = []
        positives = []
        for row in items:
            ask = ffloat(row.get("sum_ask"))
            bid = ffloat(row.get("sum_bid"))
            value = ask if required_field == "sum_ask" else bid
            if value is None:
                continue
            valid.append(row)
            edge = edge_fn(ask, bid)
            if edge is not None and edge > 0:
                positives.append({"timestamp": row["timestamp"], "edge": edge})
        best = max(positives, key=lambda row: row["edge"], default=None)
        max_edge = best["edge"] if best else None
        mvp_decision, comment = decision("single_venue_three_way_sum_diagnostic", max_edge)
        result = {
            "op_group": "single_venue_three_way_sum_diagnostic",
            "outcome_or_condition": condition,
            "side": venue,
            "total_rows": len(valid),
            "positive_rows": len(positives),
            "positive_pct": len(positives) / len(valid) if valid else 0.0,
            "max_positive_net_or_edge": max_edge,
            "mean_positive_net_or_edge": mean([row["edge"] for row in positives]),
            "best_timestamp_utc8": utc8(best["timestamp"]) if best else "",
            "mvp_decision": mvp_decision,
            "comment": comment,
        }
        result.update(profit_fields(max_edge))
        out.append(result)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def md_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt(row.get(field)) for field in FIELDS) + " |")
    return "\n".join(lines)


def write_markdown(path: Path, rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    best = max(rows, key=lambda row: row.get("max_positive_net_or_edge") or -999)
    op1_rows = [row for row in rows if row["op_group"] == "cross_venue_direct_no_complete_set"]
    best_op1 = max(op1_rows, key=lambda row: row.get("max_positive_net_or_edge") or -999)
    report = f"""# PM-HL MVP2 Arg/Aus Core Profit Table

## Conclusions First

- Best observed edge: `{best['op_group']}` / `{best['outcome_or_condition']}` / `{best['side']}` with max edge `{fmt(best['max_positive_net_or_edge'])}` at `{best['best_timestamp_utc8']}`.
- Best MVP2 execution candidate remains op1: `{best_op1['outcome_or_condition']}` / `{best_op1['side']}` with max net `{fmt(best_op1['max_positive_net_or_edge'])}`.
- A 20-share slot at that best op1 net is roughly `${fmt(best_op1['est_profit_20_shares'])}` profit, or `{fmt(best_op1['est_portfolio_return_low_pct'])}% - {fmt(best_op1['est_portfolio_return_high_pct'])}%` on a $108-$120 six-slot portfolio.
- op2/op3 stay paper monitor only; op4 stays diagnostic only.

## Core Profit Table

{md_table(rows)}

## Notes

- Uses existing overnight monitor data only; no new scan was started.
- Return math is MVP rough math: `max_positive_net_or_edge * 20 shares`.
- Portfolio denominator uses `$108-$120` for six 20-share slots.
- Positive diagnostic op4 rows are not execution recommendations.

## Source Files

- CSV: `{CSV_PATH}`
- JSON: `{JSON_PATH}`
- LOG: `{LOG_PATH}`
- JSON completed iterations: `{payload.get('completed_iterations')}`
- JSON warnings: `{len(payload.get('warnings', []))}`
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    rows = read_rows()
    payload = read_json()
    _ = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    group_order = {
        "cross_venue_direct_no_complete_set": 1,
        "cross_venue_single_outcome": 2,
        "cross_venue_complement_basket": 3,
        "single_venue_three_way_sum_diagnostic": 4,
    }
    summary = summarize_opportunities(rows) + summarize_diagnostics(rows)
    summary = sorted(
        summary,
        key=lambda row: (
            group_order.get(row["op_group"], 99),
            row["outcome_or_condition"],
            row["side"],
        ),
    )
    write_csv(OUT_CSV, summary)
    write_markdown(DOC_PATH, summary, payload)
    print(f"Markdown: {DOC_PATH}")
    print(f"CSV: {OUT_CSV}")
    best = max(summary, key=lambda row: row.get("max_positive_net_or_edge") or -999)
    print("Best:", best["op_group"], best["outcome_or_condition"], best["side"], best["max_positive_net_or_edge"])


if __name__ == "__main__":
    main()

