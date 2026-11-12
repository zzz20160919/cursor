"""Compute MVP3-B v0 S1/S2 snapshot entry edges from the latest A3 CSV.

This script is intentionally offline-only:
- reads the existing A3 winner price comparison CSV
- does not call APIs
- does not place orders
- does not emit trade candidates
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "outputs" / "mvp3_pm_predictfun" / "mvp3_a3_winner_price_compare.csv"
OUTPUT_DIR = ROOT / "outputs" / "mvp3_pm_predictfun"
OUTPUT_CSV = OUTPUT_DIR / "winner_snapshot_s1s2_entry_edges_20countries.csv"
OUTPUT_TABLE_MD = OUTPUT_DIR / "winner_snapshot_s1s2_entry_edges_20countries.md"
OUTPUT_SUMMARY_MD = OUTPUT_DIR / "winner_snapshot_s1s2_entry_edges_summary.md"

REQUIRED_PRICE_FIELDS = (
    "pm_yes_bid1",
    "pm_yes_ask1",
    "pm_no_bid1",
    "pm_no_ask1",
    "pd_yes_bid1",
    "pd_yes_ask1",
    "pd_no_bid1",
    "pd_no_ask1",
)

PM_FEE_RATE = Decimal("0.03")
PD_FEE_RATE = Decimal("0.02")
PD_FEE_DISCOUNT_MULTIPLIER = Decimal("1.0")
S1_SIZE_SHARES = Decimal("20")
S2_SIZE_SHARES = Decimal("20")
COMBINED_SIZE_SHARES = S1_SIZE_SHARES + S2_SIZE_SHARES
POSITIVE_EDGE_THRESHOLD = Decimal("0.0005")
POSITIVE_PROFIT_THRESHOLD = Decimal("0.01")

CSV_COLUMNS = (
    "timestamp",
    "team",
    "mapping_status",
    "pm_yes_bid1",
    "pm_yes_ask1",
    "pm_no_bid1",
    "pm_no_ask1",
    "pd_yes_bid1",
    "pd_yes_ask1",
    "pd_no_bid1",
    "pd_no_ask1",
    "gross_edge_pm_yes_pd_no",
    "pm_fee_pm_yes",
    "pd_fee_pd_no",
    "total_fee_pm_yes_pd_no",
    "net_edge_pm_yes_pd_no",
    "net_edge_pct_pm_yes_pd_no",
    "net_edge_bps_pm_yes_pd_no",
    "s1_net_usd_profit_pm_yes_pd_no",
    "s2_net_usd_profit_pm_yes_pd_no",
    "combined_s1s2_net_usd_profit_pm_yes_pd_no",
    "gross_edge_pd_yes_pm_no",
    "pd_fee_pd_yes",
    "pm_fee_pm_no",
    "total_fee_pd_yes_pm_no",
    "net_edge_pd_yes_pm_no",
    "net_edge_pct_pd_yes_pm_no",
    "net_edge_bps_pd_yes_pm_no",
    "s1_net_usd_profit_pd_yes_pm_no",
    "s2_net_usd_profit_pd_yes_pm_no",
    "combined_s1s2_net_usd_profit_pd_yes_pm_no",
    "best_direction_by_net_edge",
    "best_net_edge",
    "best_net_edge_pct",
    "best_net_edge_bps",
    "best_s1_net_usd_profit",
    "best_s2_net_usd_profit",
    "best_combined_s1s2_net_usd_profit",
    "status",
    "notes",
)


@dataclass(frozen=True)
class FilterResult:
    total_rows: int
    matched_rows: list[dict[str, str]]
    complete_rows: list[dict[str, str]]
    incomplete_matched_rows: list[dict[str, str]]
    non_matched_rows: list[dict[str, str]]


def to_decimal(value: str) -> Decimal:
    return Decimal(value.strip())


def q(value: Decimal, places: str = "0.000001") -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def q_price(value: str) -> str:
    return q(to_decimal(value), "0.000")


def fmt_pct(value: Decimal) -> str:
    return f"{q(value * Decimal('100'), '0.001')}%"


def fmt_usd(value: Decimal) -> str:
    return q(value, "0.0001")


def has_all_prices(row: dict[str, str]) -> bool:
    return all(row.get(field, "").strip() for field in REQUIRED_PRICE_FIELDS)


def missing_price_reason(row: dict[str, str]) -> str:
    missing = [field for field in REQUIRED_PRICE_FIELDS if not row.get(field, "").strip()]
    return "missing " + ", ".join(missing)


def pm_taker_fee(price: Decimal) -> Decimal:
    return PM_FEE_RATE * price * (Decimal("1") - price)


def pd_taker_fee(price: Decimal) -> Decimal:
    return PD_FEE_RATE * PD_FEE_DISCOUNT_MULTIPLIER * min(price, Decimal("1") - price)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def filter_universe(rows: list[dict[str, str]]) -> FilterResult:
    matched_rows = [row for row in rows if row.get("mapping_status") == "matched"]
    complete_rows = [row for row in matched_rows if has_all_prices(row)]
    incomplete_matched_rows = [row for row in matched_rows if not has_all_prices(row)]
    non_matched_rows = [row for row in rows if row.get("mapping_status") != "matched"]
    return FilterResult(
        total_rows=len(rows),
        matched_rows=matched_rows,
        complete_rows=complete_rows,
        incomplete_matched_rows=incomplete_matched_rows,
        non_matched_rows=non_matched_rows,
    )


def compute_edge_row(row: dict[str, str]) -> dict[str, str]:
    pm_yes_ask = to_decimal(row["pm_yes_ask1"])
    pm_no_ask = to_decimal(row["pm_no_ask1"])
    pd_yes_ask = to_decimal(row["pd_yes_ask1"])
    pd_no_ask = to_decimal(row["pd_no_ask1"])

    gross_a = Decimal("1") - pm_yes_ask - pd_no_ask
    pm_fee_a = pm_taker_fee(pm_yes_ask)
    pd_fee_a = pd_taker_fee(pd_no_ask)
    total_fee_a = pm_fee_a + pd_fee_a
    net_a = gross_a - total_fee_a

    gross_b = Decimal("1") - pd_yes_ask - pm_no_ask
    pd_fee_b = pd_taker_fee(pd_yes_ask)
    pm_fee_b = pm_taker_fee(pm_no_ask)
    total_fee_b = pd_fee_b + pm_fee_b
    net_b = gross_b - total_fee_b

    s1_profit_a = net_a * S1_SIZE_SHARES
    s2_profit_a = net_a * S2_SIZE_SHARES
    combined_profit_a = net_a * COMBINED_SIZE_SHARES
    s1_profit_b = net_b * S1_SIZE_SHARES
    s2_profit_b = net_b * S2_SIZE_SHARES
    combined_profit_b = net_b * COMBINED_SIZE_SHARES

    if net_a >= net_b:
        best_direction = "pm_yes_pd_no"
        best_net = net_a
        best_s1_profit = s1_profit_a
        best_s2_profit = s2_profit_a
        best_combined_profit = combined_profit_a
    else:
        best_direction = "pd_yes_pm_no"
        best_net = net_b
        best_s1_profit = s1_profit_b
        best_s2_profit = s2_profit_b
        best_combined_profit = combined_profit_b

    positive_a = (
        net_a >= POSITIVE_EDGE_THRESHOLD
        and s1_profit_a >= POSITIVE_PROFIT_THRESHOLD
        and s2_profit_a >= POSITIVE_PROFIT_THRESHOLD
    )
    positive_b = (
        net_b >= POSITIVE_EDGE_THRESHOLD
        and s1_profit_b >= POSITIVE_PROFIT_THRESHOLD
        and s2_profit_b >= POSITIVE_PROFIT_THRESHOLD
    )

    if positive_a or positive_b:
        status = "positive_review_signal"
        notes = "review_only_not_tradeable; depth/fee/freshness/settlement still need verification"
    else:
        status = "negative_or_zero_after_fee"
        notes = "review_only_not_tradeable; no direction clears net edge/profit thresholds after fees"

    return {
        "timestamp": row["timestamp"],
        "team": row["team"],
        "mapping_status": row["mapping_status"],
        "pm_yes_bid1": q_price(row["pm_yes_bid1"]),
        "pm_yes_ask1": q_price(row["pm_yes_ask1"]),
        "pm_no_bid1": q_price(row["pm_no_bid1"]),
        "pm_no_ask1": q_price(row["pm_no_ask1"]),
        "pd_yes_bid1": q_price(row["pd_yes_bid1"]),
        "pd_yes_ask1": q_price(row["pd_yes_ask1"]),
        "pd_no_bid1": q_price(row["pd_no_bid1"]),
        "pd_no_ask1": q_price(row["pd_no_ask1"]),
        "gross_edge_pm_yes_pd_no": q(gross_a),
        "pm_fee_pm_yes": q(pm_fee_a),
        "pd_fee_pd_no": q(pd_fee_a),
        "total_fee_pm_yes_pd_no": q(total_fee_a),
        "net_edge_pm_yes_pd_no": q(net_a),
        "net_edge_pct_pm_yes_pd_no": q(net_a * Decimal("100")),
        "net_edge_bps_pm_yes_pd_no": q(net_a * Decimal("10000"), "0.01"),
        "s1_net_usd_profit_pm_yes_pd_no": fmt_usd(s1_profit_a),
        "s2_net_usd_profit_pm_yes_pd_no": fmt_usd(s2_profit_a),
        "combined_s1s2_net_usd_profit_pm_yes_pd_no": fmt_usd(combined_profit_a),
        "gross_edge_pd_yes_pm_no": q(gross_b),
        "pd_fee_pd_yes": q(pd_fee_b),
        "pm_fee_pm_no": q(pm_fee_b),
        "total_fee_pd_yes_pm_no": q(total_fee_b),
        "net_edge_pd_yes_pm_no": q(net_b),
        "net_edge_pct_pd_yes_pm_no": q(net_b * Decimal("100")),
        "net_edge_bps_pd_yes_pm_no": q(net_b * Decimal("10000"), "0.01"),
        "s1_net_usd_profit_pd_yes_pm_no": fmt_usd(s1_profit_b),
        "s2_net_usd_profit_pd_yes_pm_no": fmt_usd(s2_profit_b),
        "combined_s1s2_net_usd_profit_pd_yes_pm_no": fmt_usd(combined_profit_b),
        "best_direction_by_net_edge": best_direction,
        "best_net_edge": q(best_net),
        "best_net_edge_pct": q(best_net * Decimal("100")),
        "best_net_edge_bps": q(best_net * Decimal("10000"), "0.01"),
        "best_s1_net_usd_profit": fmt_usd(best_s1_profit),
        "best_s2_net_usd_profit": fmt_usd(best_s2_profit),
        "best_combined_s1s2_net_usd_profit": fmt_usd(best_combined_profit),
        "status": status,
        "notes": notes,
    }


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def bid_ask(row: dict[str, str], bid_field: str, ask_field: str) -> str:
    return f"{row[bid_field]} / {row[ask_field]}"


def write_table_md(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# MVP3-B v0 Winner Snapshot S1/S2 Entry Edges",
        "",
        "Review-only table from the latest A3 CSV. No API refresh, no live trading, no orders, no trade candidates.",
        "",
        "| team | pm_yes_bid/ask | pm_no_bid/ask | pd_yes_bid/ask | pd_no_bid/ask | gross_edge_A | net_edge_A | net_edge_pct_A | s1_profit_A | s2_profit_A | gross_edge_B | net_edge_B | net_edge_pct_B | s1_profit_B | s2_profit_B | best_direction | best_combined_profit | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["team"],
                    bid_ask(row, "pm_yes_bid1", "pm_yes_ask1"),
                    bid_ask(row, "pm_no_bid1", "pm_no_ask1"),
                    bid_ask(row, "pd_yes_bid1", "pd_yes_ask1"),
                    bid_ask(row, "pd_no_bid1", "pd_no_ask1"),
                    row["gross_edge_pm_yes_pd_no"],
                    row["net_edge_pm_yes_pd_no"],
                    fmt_pct(to_decimal(row["net_edge_pm_yes_pd_no"])),
                    row["s1_net_usd_profit_pm_yes_pd_no"],
                    row["s2_net_usd_profit_pm_yes_pd_no"],
                    row["gross_edge_pd_yes_pm_no"],
                    row["net_edge_pd_yes_pm_no"],
                    fmt_pct(to_decimal(row["net_edge_pd_yes_pm_no"])),
                    row["s1_net_usd_profit_pd_yes_pm_no"],
                    row["s2_net_usd_profit_pd_yes_pm_no"],
                    row["best_direction_by_net_edge"],
                    row["best_combined_s1s2_net_usd_profit"],
                    row["status"],
                ]
            )
            + " |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def excluded_lines(filter_result: FilterResult) -> list[str]:
    lines: list[str] = []
    if filter_result.incomplete_matched_rows:
        lines.append("Incomplete matched rows excluded by missing price fields:")
        for row in filter_result.incomplete_matched_rows:
            lines.append(f"- {row['team']}: {missing_price_reason(row)}")
    else:
        lines.append("Incomplete matched rows excluded by missing price fields: none")

    if filter_result.non_matched_rows:
        lines.append("")
        lines.append("Rows excluded before price completeness because mapping_status != matched:")
        for row in filter_result.non_matched_rows:
            notes = row.get("notes", "").strip() or "mapping_status != matched"
            lines.append(f"- {row['team']}: mapping_status={row.get('mapping_status', '')}; {notes}")
    return lines


def write_summary_md(path: Path, filter_result: FilterResult, rows: list[dict[str, str]]) -> None:
    positive_rows = [row for row in rows if row["status"] == "positive_review_signal"]
    best_row = max(rows, key=lambda row: to_decimal(row["best_net_edge"]))
    focus_teams = ["France", "Argentina", "Spain", "England", "Brazil", "Portugal"]
    focus_by_team = {row["team"]: row for row in rows if row["team"] in focus_teams}

    lines = [
        "# MVP3-B v0 Winner Snapshot S1/S2 Entry Edge Summary",
        "",
        "## Inputs And Filters",
        "",
        f"- Input CSV: `{INPUT_CSV.relative_to(ROOT)}`",
        f"- Filter-before row count: {filter_result.total_rows}",
        f"- `mapping_status = matched` row count: {len(filter_result.matched_rows)}",
        f"- Complete price country count: {len(filter_result.complete_rows)}",
        "",
        "## Exclusions",
        "",
        *excluded_lines(filter_result),
        "",
        "## Fee And Size Assumptions",
        "",
        f"- PM fee rate: {PM_FEE_RATE}",
        "- PM fee uses default sports fee rate 0.03 and still needs market-level verification.",
        f"- PD fee rate: {PD_FEE_RATE}",
        f"- PD fee discount multiplier: {PD_FEE_DISCOUNT_MULTIPLIER}",
        f"- S1 size: {S1_SIZE_SHARES} shares",
        f"- S2 size: {S2_SIZE_SHARES} shares",
        f"- Combined size: {COMBINED_SIZE_SHARES} shares",
        "",
        "## Review Signals",
        "",
        f"- `positive_review_signal` countries: {len(positive_rows)}",
        f"- Max net edge: {best_row['team']} / {best_row['best_direction_by_net_edge']} / {best_row['best_net_edge']} ({fmt_pct(to_decimal(best_row['best_net_edge']))})",
        f"- Max combined S1+S2 profit: {best_row['best_combined_s1s2_net_usd_profit']}",
        "",
        "## Focus Countries",
        "",
        "| team | best_direction | best_net_edge | best_net_edge_pct | best_s1_profit | best_s2_profit | best_combined_profit |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    for team in focus_teams:
        row = focus_by_team[team]
        lines.append(
            f"| {team} | {row['best_direction_by_net_edge']} | {row['best_net_edge']} | "
            f"{fmt_pct(to_decimal(row['best_net_edge']))} | {row['best_s1_net_usd_profit']} | "
            f"{row['best_s2_net_usd_profit']} | {row['best_combined_s1s2_net_usd_profit']} |"
        )

    lines.extend(
        [
            "",
            "## Readiness",
            "",
            "- MVP3-B v1 fresh scanner: recommended as the next read-only step, with fresh revalidation, depth checks, quote freshness, settlement verification, and explicit fee metadata checks.",
            "- Live trade readiness: NOT_READY",
            "- Reason: this is only snapshot entry-edge review; no fresh revalidation, no depth confirmation, no quote freshness, no settlement verification, no live adapter.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = load_rows(INPUT_CSV)
    filter_result = filter_universe(rows)
    computed_rows = [compute_edge_row(row) for row in filter_result.complete_rows]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_CSV, computed_rows)
    write_table_md(OUTPUT_TABLE_MD, computed_rows)
    write_summary_md(OUTPUT_SUMMARY_MD, filter_result, computed_rows)

    positive_count = sum(1 for row in computed_rows if row["status"] == "positive_review_signal")
    best_row = max(computed_rows, key=lambda row: to_decimal(row["best_net_edge"]))
    print(f"input_csv={INPUT_CSV}")
    print(f"total_rows={filter_result.total_rows}")
    print(f"matched_rows={len(filter_result.matched_rows)}")
    print(f"complete_price_countries={len(computed_rows)}")
    print(f"positive_review_signal={positive_count}")
    print(
        "max_net_edge="
        f"{best_row['team']} {best_row['best_direction_by_net_edge']} {best_row['best_net_edge']}"
    )
    print(f"wrote={OUTPUT_CSV}")
    print(f"wrote={OUTPUT_TABLE_MD}")
    print(f"wrote={OUTPUT_SUMMARY_MD}")


if __name__ == "__main__":
    main()
