from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"
DOC_PATH = PROJECT_ROOT / "docs" / "pm_hl_mvp2_arg_aut_core_profit_review.md"

CSV_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv"
JSON_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json"
LOG_PATH = OUTPUT_DIR / "pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log"

OPPORTUNITY_STATS_CSV = OUTPUT_DIR / "review_arg_aut_core_opportunity_stats.csv"
STRATEGY_RETURN_CSV = OUTPUT_DIR / "review_arg_aut_core_strategy_return.csv"

UTC8 = timezone(timedelta(hours=8))
OP_GROUPS = (
    "cross_venue_direct_no_complete_set",
    "cross_venue_single_outcome",
    "cross_venue_complement_basket",
)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_utc8(value: str) -> str:
    return parse_ts(value).astimezone(UTC8).strftime("%Y-%m-%d %H:%M:%S UTC+8")


def ffloat(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def read_csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json_payload() -> dict[str, Any]:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_num(value: Any, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt_num(row.get(col)) for col in columns) + " |")
    return "\n".join(lines)


def positive_net_stats(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("op_group") not in OP_GROUPS:
            continue
        net = ffloat(row.get("net"))
        gross = ffloat(row.get("gross"))
        if net is None:
            continue
        groups[(row["op_group"], row["key"], row["side"])].append(
            {
                "timestamp": row["timestamp"],
                "net": net,
                "gross": gross,
            }
        )

    out: list[dict[str, Any]] = []
    for (op_group, outcome, side), items in sorted(groups.items()):
        positives = [row for row in items if row["net"] > 0]
        best = max(positives, key=lambda row: row["net"], default=None)
        out.append(
            {
                "op_group": op_group,
                "outcome": outcome,
                "side": side,
                "total_rows": len(items),
                "positive_net_rows": len(positives),
                "positive_net_pct": len(positives) / len(items) if items else 0.0,
                "mean_positive_net": mean([row["net"] for row in positives]),
                "max_positive_net": best["net"] if best else None,
                "best_timestamp_utc8": fmt_utc8(best["timestamp"]) if best else "",
            }
        )
    return out


def diagnostic_stats(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    diagnostics = [
        ("polymarket", "PM sum_ask_minus_1 < 0", "sum_ask", lambda ask, bid: None if ask is None else 1.0 - ask),
        ("polymarket", "PM sum_bid_minus_1 > 0", "sum_bid", lambda ask, bid: None if bid is None else bid - 1.0),
        ("hyperliquid", "HL sum_ask_minus_1 < 0", "sum_ask", lambda ask, bid: None if ask is None else 1.0 - ask),
        ("hyperliquid", "HL sum_bid_minus_1 > 0", "sum_bid", lambda ask, bid: None if bid is None else bid - 1.0),
    ]
    diag_rows = [
        row
        for row in rows
        if row.get("op_group") == "single_venue_three_way_sum_diagnostic"
    ]
    out: list[dict[str, Any]] = []
    for venue, condition, field, edge_fn in diagnostics:
        venue_rows = [row for row in diag_rows if row.get("key") == venue]
        edges: list[float] = []
        valid_count = 0
        for row in venue_rows:
            ask = ffloat(row.get("sum_ask"))
            bid = ffloat(row.get("sum_bid"))
            value = ask if field == "sum_ask" else bid
            if value is None:
                continue
            valid_count += 1
            edge = edge_fn(ask, bid)
            if edge is not None and edge > 0:
                edges.append(edge)
        out.append(
            {
                "venue": venue,
                "condition": condition,
                "total_rows": valid_count,
                "true_rows": len(edges),
                "true_pct": len(edges) / valid_count if valid_count else 0.0,
                "mean_edge_when_true": mean(edges),
                "max_edge_when_true": max(edges) if edges else None,
                "min_edge_when_true": min(edges) if edges else None,
            }
        )
    return out


def strategy_return_rows(opportunity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    op1_arg = [
        row
        for row in opportunity_rows
        if row["op_group"] == "cross_venue_direct_no_complete_set"
        and row["outcome"] == "Argentina"
        and row["positive_net_rows"] > 0
    ]
    best_arg = max(op1_arg, key=lambda row: row["max_positive_net"], default=None)
    max_net = float(best_arg["max_positive_net"]) if best_arg else 0.0
    one_slot_profit = max_net * 20
    two_slot_profit = max_net * 40
    one_slot_capital_low = 18.0
    one_slot_capital_high = 20.0
    six_slot_capital_low = 6 * one_slot_capital_low
    six_slot_capital_high = 6 * one_slot_capital_high
    return [
        {
            "scenario": "Argentina one 20-share slot caught at max net",
            "max_net_per_share": max_net,
            "gross_profit_usd": one_slot_profit,
            "capital_used_low_usd": one_slot_capital_low,
            "capital_used_high_usd": one_slot_capital_high,
            "trade_return_low_capital": one_slot_profit / one_slot_capital_low if one_slot_capital_low else None,
            "trade_return_high_capital": one_slot_profit / one_slot_capital_high if one_slot_capital_high else None,
            "portfolio_capital_low_usd": six_slot_capital_low,
            "portfolio_capital_high_usd": six_slot_capital_high,
            "portfolio_return_low_capital": one_slot_profit / six_slot_capital_low,
            "portfolio_return_high_capital": one_slot_profit / six_slot_capital_high,
            "notes": "Uses top-of-book max monitor net; not VWAP/execution verified.",
        },
        {
            "scenario": "Argentina S1+S2 both 20-share slots caught at max net",
            "max_net_per_share": max_net,
            "gross_profit_usd": two_slot_profit,
            "capital_used_low_usd": 2 * one_slot_capital_low,
            "capital_used_high_usd": 2 * one_slot_capital_high,
            "trade_return_low_capital": two_slot_profit / (2 * one_slot_capital_low),
            "trade_return_high_capital": two_slot_profit / (2 * one_slot_capital_high),
            "portfolio_capital_low_usd": six_slot_capital_low,
            "portfolio_capital_high_usd": six_slot_capital_high,
            "portfolio_return_low_capital": two_slot_profit / six_slot_capital_low,
            "portfolio_return_high_capital": two_slot_profit / six_slot_capital_high,
            "notes": "Assumes both slots fill at same best observed net; optimistic MVP rough calculation.",
        },
        {
            "scenario": "single-leg naked exposure estimate: one 20-share slot",
            "max_net_per_share": None,
            "gross_profit_usd": None,
            "capital_used_low_usd": one_slot_capital_low,
            "capital_used_high_usd": one_slot_capital_high,
            "trade_return_low_capital": None,
            "trade_return_high_capital": None,
            "portfolio_capital_low_usd": six_slot_capital_low,
            "portfolio_capital_high_usd": six_slot_capital_high,
            "portfolio_return_low_capital": None,
            "portfolio_return_high_capital": None,
            "notes": "If only one leg fills, rough naked downside can approach the 20-share leg notional, about $18-$20.",
        },
        {
            "scenario": "single-leg naked exposure estimate: S1+S2 40 shares",
            "max_net_per_share": None,
            "gross_profit_usd": None,
            "capital_used_low_usd": 2 * one_slot_capital_low,
            "capital_used_high_usd": 2 * one_slot_capital_high,
            "trade_return_low_capital": None,
            "trade_return_high_capital": None,
            "portfolio_capital_low_usd": six_slot_capital_low,
            "portfolio_capital_high_usd": six_slot_capital_high,
            "portfolio_return_low_capital": None,
            "portfolio_return_high_capital": None,
            "notes": "If S1+S2 both suffer one-leg-only fill, rough naked downside can approach $36-$40.",
        },
    ]


def write_report(
    opp_stats: list[dict[str, Any]],
    diag_stats: list[dict[str, Any]],
    returns: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    op1_stats = [row for row in opp_stats if row["op_group"] == "cross_venue_direct_no_complete_set"]
    op2_stats = [row for row in opp_stats if row["op_group"] == "cross_venue_single_outcome"]
    op3_stats = [row for row in opp_stats if row["op_group"] == "cross_venue_complement_basket"]
    best = max(opp_stats, key=lambda row: row["max_positive_net"] or -999)
    arg_best = max(
        [row for row in op1_stats if row["outcome"] == "Argentina"],
        key=lambda row: row["max_positive_net"] or -999,
        default=None,
    )
    report = f"""# PM-HL MVP2 Arg/Aus Core Profit Review

## Conclusions First

- Best observed positive net across op1/op2/op3 was **{best['max_positive_net']:.6f}** from `{best['op_group']}` / `{best['outcome']}` / `{best['side']}` at **{best['best_timestamp_utc8']}**.
- For op1 specifically, Argentina had the largest max net. This supports continuing MVP execution research, but only with strict fill/leg-risk controls because this is top-of-book monitoring, not execution-verified VWAP.
- A single 20-share Argentina slot at max observed op1 net would have made roughly **${returns[0]['gross_profit_usd']:.2f}** before operational slippage; S1+S2 together would be roughly **${returns[1]['gross_profit_usd']:.2f}**.
- Main downside is not rule-complete-set payout if both legs fill and rules match; the practical MVP risk is one-leg-only exposure, roughly **$18-$20** for one 20-share slot or **$36-$40** for S1+S2.

## 1. op1 / op2 / op3 Positive Net Statistics

### op1: direct No-token complete-set

{md_table(op1_stats, ['op_group', 'outcome', 'side', 'total_rows', 'positive_net_rows', 'positive_net_pct', 'mean_positive_net', 'max_positive_net', 'best_timestamp_utc8'])}

### op2: single outcome cross-venue

{md_table(op2_stats, ['op_group', 'outcome', 'side', 'total_rows', 'positive_net_rows', 'positive_net_pct', 'mean_positive_net', 'max_positive_net', 'best_timestamp_utc8'])}

### op3: complement basket

{md_table(op3_stats, ['op_group', 'outcome', 'side', 'total_rows', 'positive_net_rows', 'positive_net_pct', 'mean_positive_net', 'max_positive_net', 'best_timestamp_utc8'])}

## 2. op4 Diagnostic Opportunity Statistics

{md_table(diag_stats, ['venue', 'condition', 'total_rows', 'true_rows', 'true_pct', 'mean_edge_when_true', 'max_edge_when_true', 'min_edge_when_true'])}

## 3. op1 Rough Return Math

{md_table(returns, ['scenario', 'max_net_per_share', 'gross_profit_usd', 'capital_used_low_usd', 'capital_used_high_usd', 'trade_return_low_capital', 'trade_return_high_capital', 'portfolio_capital_low_usd', 'portfolio_capital_high_usd', 'portfolio_return_low_capital', 'portfolio_return_high_capital', 'notes'])}

## 4. Max Loss Rough Estimate

- If both legs fill and PM/HL rule matching holds, the position is intended as a complete set. The main residual risks are fee/slippage, rule mismatch, venue settlement/funding issues, and operational mistakes.
- If only one leg fills for a 20-share slot, rough naked downside can approach the funded leg notional, about **$18-$20** under the simple capital assumption.
- If S1+S2 both get one-leg-only exposure, rough naked downside can approach **$36-$40**.

## MVP Decision

This match supports continuing op1 MVP execution-layer work, but not because every signal was tradable. The reason is that the data produced real positive top-of-book net windows, especially Argentina. However, the edge is episodic and execution-sensitive, so the next layer should focus narrowly on atomic/controlled two-leg execution, fill confirmation, kill switch, and one-leg exposure handling. Do not broaden to op2/op3/op4 execution yet.

## Source Files

- CSV: `{CSV_PATH}`
- JSON: `{JSON_PATH}`
- LOG: `{LOG_PATH}`
- JSON completed iterations: `{payload.get('completed_iterations')}`
- JSON warnings: `{len(payload.get('warnings', []))}`
"""
    DOC_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    rows = read_csv_rows()
    payload = read_json_payload()
    _ = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    opp_stats = positive_net_stats(rows)
    diag_stats = diagnostic_stats(rows)
    returns = strategy_return_rows(opp_stats)
    write_csv(
        OPPORTUNITY_STATS_CSV,
        opp_stats + diag_stats,
        [
            "op_group",
            "outcome",
            "side",
            "total_rows",
            "positive_net_rows",
            "positive_net_pct",
            "mean_positive_net",
            "max_positive_net",
            "best_timestamp_utc8",
            "venue",
            "condition",
            "true_rows",
            "true_pct",
            "mean_edge_when_true",
            "max_edge_when_true",
            "min_edge_when_true",
        ],
    )
    write_csv(
        STRATEGY_RETURN_CSV,
        returns,
        [
            "scenario",
            "max_net_per_share",
            "gross_profit_usd",
            "capital_used_low_usd",
            "capital_used_high_usd",
            "trade_return_low_capital",
            "trade_return_high_capital",
            "portfolio_capital_low_usd",
            "portfolio_capital_high_usd",
            "portfolio_return_low_capital",
            "portfolio_return_high_capital",
            "notes",
        ],
    )
    write_report(opp_stats, diag_stats, returns, payload)
    print(f"Markdown: {DOC_PATH}")
    print(f"Opportunity stats CSV: {OPPORTUNITY_STATS_CSV}")
    print(f"Strategy return CSV: {STRATEGY_RETURN_CSV}")


if __name__ == "__main__":
    main()

