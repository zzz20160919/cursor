#!/usr/bin/env python3
"""Dissect the YESMV High leg on the existing Step 3 panel.

Uses the same 30/70 membership, raw open-interest weights, and presort
category aggregation as build_step3.py. Does not change prices or the universe.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from hlz_paper import assign_legs, percentile  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
SLICES = OUT / "diagnostic_yesmv_high_slices.csv"
TOP = OUT / "diagnostic_yesmv_high_top.csv"
NAMED = ("253591", "253597")  # 2024 Trump and Harris winner markets
EXPECTED = {"high": 0.282845, "low": 0.073974}


def load_rows() -> dict[Any, list[dict[str, Any]]]:
    con = duckdb.connect()
    fetched = con.execute(
        f"""
        SELECT formation_date, market_id, question, category, p_form, oi_shares,
               yesmv, r_pp, p_end_source
        FROM read_parquet('{FACTOR}')
        WHERE in_portfolio_sample
          AND category <> ''
          AND oi_shares > 0
          AND r_pp IS NOT NULL
          AND yesmv IS NOT NULL
        """
    ).fetchall()
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for day, market_id, question, category, price, oi, yesmv, payoff, source in fetched:
        grouped[day].append(
            {
                "date": day.isoformat(),
                "market_id": market_id,
                "question": question,
                "category": category,
                "p_form": float(price),
                "oi": float(oi),
                "yesmv": float(yesmv),
                "r": float(payoff),
                "p_end_source": source or "",
            }
        )
    return grouped


def assign(grouped: dict[Any, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], int]:
    """Return High and Low membership with the weight used in the leg mean."""
    dated: list[tuple[Any, list[dict[str, Any]]]] = []
    for day, members in grouped.items():
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for member in members:
            by_category[member["category"]].append(member)
        matched = []
        for category, rows in by_category.items():
            if len(rows) < 3:
                continue
            legs = assign_legs([row["yesmv"] for row in rows])
            buckets: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
            for row, leg in zip(rows, legs):
                buckets[leg].append(row)
            if not all(buckets[name] for name in ("low", "middle", "high")):
                continue
            presort = sum(row["oi"] for row in rows)
            if presort <= 0:
                continue
            matched.append((presort, buckets))
        if not matched:
            continue
        total = sum(item[0] for item in matched)
        held: list[dict[str, Any]] = []
        for presort, buckets in matched:
            category_weight = presort / total
            for leg in ("low", "high"):
                leg_oi = sum(row["oi"] for row in buckets[leg])
                if leg_oi <= 0:
                    continue
                for row in buckets[leg]:
                    held.append(
                        {
                            **row,
                            "leg": leg,
                            "day_weight": category_weight * row["oi"] / leg_oi,
                        }
                    )
        dated.append((day, held))
    count = len(dated)
    assigned = []
    for _day, held in dated:
        for row in held:
            assigned.append({**row, "mean_weight": row["day_weight"] / count})
    return assigned, count


def slice_table(rows: list[dict[str, Any]], leg: str, oi_p99: float) -> list[dict[str, Any]]:
    chosen = [row for row in rows if row["leg"] == leg]
    total_n = len(chosen)

    def pack(name: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        weight = sum(row["mean_weight"] for row in subset)
        contribution = sum(row["mean_weight"] * row["r"] * 100 for row in subset)
        return {
            "leg": leg,
            "slice": name,
            "contract_days": len(subset),
            "share_of_leg_days": f"{(len(subset) / total_n) if total_n else 0:.6f}",
            "share_of_leg_weight": f"{weight:.6f}",
            "contribution_to_leg_mean_cents": f"{contribution:.6f}",
            "slice_weighted_mean_cents": "" if weight <= 0 else f"{contribution / weight:.6f}",
        }

    near = [row for row in chosen if row["p_form"] <= 0.05 or row["p_form"] >= 0.95]
    low_price = [row for row in chosen if row["p_form"] <= 0.05]
    high_price = [row for row in chosen if row["p_form"] >= 0.95]
    interior = [row for row in chosen if 0.05 < row["p_form"] < 0.95]
    extreme_oi = [row for row in chosen if row["oi"] >= oi_p99]
    named = [row for row in chosen if row["market_id"] in NAMED]
    trump = [row for row in chosen if row["market_id"] == "253591"]
    harris = [row for row in chosen if row["market_id"] == "253597"]
    settlement = [row for row in chosen if row["p_end_source"] == "settlement"]
    nxt = [row for row in chosen if row["p_end_source"] == "next_close"]
    other = [row for row in chosen if row["p_end_source"] not in {"settlement", "next_close"}]
    return [
        pack("all", chosen),
        pack("next_close", nxt),
        pack("settlement", settlement),
        pack("other_endpoint", other),
        pack("price_le_0.05", low_price),
        pack("price_ge_0.95", high_price),
        pack("price_near_0_or_1", near),
        pack("price_between_0.05_and_0.95", interior),
        pack("oi_at_or_above_leg_p99", extreme_oi),
        pack("trump_253591", trump),
        pack("harris_253597", harris),
        pack("trump_or_harris", named),
    ]


def top_rows(rows: list[dict[str, Any]], leg: str, limit: int = 20) -> list[dict[str, Any]]:
    chosen = [row for row in rows if row["leg"] == leg]
    ordered = sorted(chosen, key=lambda row: row["mean_weight"] * row["r"], reverse=True)
    out = []
    for row in ordered[:limit]:
        out.append(
            {
                "leg": leg,
                "rank_by_contribution": len(out) + 1,
                "date": row["date"],
                "market_id": row["market_id"],
                "question": row["question"],
                "category": row["category"],
                "p_form": f"{row['p_form']:.6f}",
                "oi_shares": f"{row['oi']:.4f}",
                "yesmv": f"{row['yesmv']:.4f}",
                "p_end_source": row["p_end_source"],
                "return_cents": f"{row['r'] * 100:.6f}",
                "mean_weight": f"{row['mean_weight']:.8f}",
                "contribution_to_leg_mean_cents": f"{row['mean_weight'] * row['r'] * 100:.6f}",
            }
        )
    return out


def main() -> int:
    grouped = load_rows()
    assigned, n_dates = assign(grouped)
    for leg, expected in EXPECTED.items():
        got = sum(row["mean_weight"] * row["r"] * 100 for row in assigned if row["leg"] == leg)
        if abs(got - expected) > 5e-4:
            raise SystemExit(f"{leg} reconstructed mean {got:.6f} vs Step 3 {expected:.6f}")
        print(f"{leg} mean {got:.6f} cents over {n_dates} dates", flush=True)
    oi_values = sorted(row["oi"] for row in assigned if row["leg"] == "high")
    oi_p99 = percentile(oi_values, 0.99)
    print(f"high-leg OI p99 {oi_p99:.4f}", flush=True)
    slices = slice_table(assigned, "high", oi_p99) + slice_table(assigned, "low", oi_p99)
    # The Low-leg p99 is a different threshold. Recompute that slice with the Low p99.
    low_p99 = percentile(sorted(row["oi"] for row in assigned if row["leg"] == "low"), 0.99)
    for row in slices:
        if row["leg"] == "low" and row["slice"] == "oi_at_or_above_leg_p99":
            subset = [item for item in assigned if item["leg"] == "low" and item["oi"] >= low_p99]
            weight = sum(item["mean_weight"] for item in subset)
            contribution = sum(item["mean_weight"] * item["r"] * 100 for item in subset)
            total_n = sum(1 for item in assigned if item["leg"] == "low")
            row["contract_days"] = len(subset)
            row["share_of_leg_days"] = f"{len(subset) / total_n:.6f}"
            row["share_of_leg_weight"] = f"{weight:.6f}"
            row["contribution_to_leg_mean_cents"] = f"{contribution:.6f}"
            row["slice_weighted_mean_cents"] = "" if weight <= 0 else f"{contribution / weight:.6f}"
    tops = top_rows(assigned, "high") + top_rows(assigned, "low")
    for path, table in ((SLICES, slices), (TOP, tops)):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(table[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
    meta = OUT / "diagnostic_yesmv_high_meta.csv"
    with meta.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["stat", "value"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            [
                {"stat": "yesmv_dates", "value": str(n_dates)},
                {"stat": "high_contract_days", "value": str(sum(1 for row in assigned if row["leg"] == "high"))},
                {"stat": "low_contract_days", "value": str(sum(1 for row in assigned if row["leg"] == "low"))},
                {"stat": "high_oi_p99", "value": f"{oi_p99:.6f}"},
                {"stat": "low_oi_p99", "value": f"{low_p99:.6f}"},
            ]
        )
    print(f"wrote {SLICES}", flush=True)
    write_day_stats(assigned, n_dates)
    return 0


def write_day_stats(rows: list[dict[str, Any]], n_dates: int) -> None:
    by_leg: dict[str, dict[str, float]] = {"high": defaultdict(float), "low": defaultdict(float)}
    for row in rows:
        by_leg[row["leg"]][row["date"]] += row["day_weight"] * row["r"] * 100
    path = OUT / "diagnostic_yesmv_high_days.csv"
    records = []
    for leg, series in by_leg.items():
        values = [series[day] for day in sorted(series)]
        ordered = sorted(values)
        mean = sum(values) / len(values)
        median = ordered[len(ordered) // 2] if len(ordered) % 2 == 1 else (
            ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]
        ) / 2
        for threshold in (5.0, 10.0):
            kept = [value for value in values if value >= threshold]
            records.append(
                {
                    "leg": leg,
                    "stat": f"dates_with_return_ge_{threshold:.0f}c",
                    "value": str(len(kept)),
                }
            )
            records.append(
                {
                    "leg": leg,
                    "stat": f"contribution_of_dates_ge_{threshold:.0f}c",
                    "value": f"{sum(kept) / n_dates:.6f}",
                }
            )
        records.extend(
            [
                {"leg": leg, "stat": "n_dates", "value": str(len(values))},
                {"leg": leg, "stat": "mean_cents", "value": f"{mean:.6f}"},
                {"leg": leg, "stat": "median_cents", "value": f"{median:.6f}"},
                {
                    "leg": leg,
                    "stat": "share_of_dates_positive",
                    "value": f"{sum(1 for value in values if value > 0) / len(values):.6f}",
                },
            ]
        )
    for leg in ("high", "low"):
        chosen = [row for row in rows if row["leg"] == leg]
        contribution = sum(row["mean_weight"] * row["r"] * 100 for row in chosen)
        top20 = sorted(chosen, key=lambda row: row["mean_weight"] * row["r"], reverse=True)[:20]
        top_sum = sum(row["mean_weight"] * row["r"] * 100 for row in top20)
        records.append(
            {
                "leg": leg,
                "stat": "top20_contract_contribution_cents",
                "value": f"{top_sum:.6f}",
            }
        )
        records.append(
            {
                "leg": leg,
                "stat": "rest_after_top20_contribution_cents",
                "value": f"{contribution - top_sum:.6f}",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["leg", "stat", "value"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
