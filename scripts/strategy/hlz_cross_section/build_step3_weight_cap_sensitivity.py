#!/usr/bin/env python3
"""Step 3 weight-cap sensitivity on the fixed min-N=5 portfolio.

A name's weight is its share of that day's High portfolio, or separately
of that day's Low portfolio. Weight above the cap is cash earning zero.
Remaining weights are not scaled back up to one. Official Step 3 files
and the min-N tables are not rewritten.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_step3 import CHARACTERISTICS, newey_west_t  # noqa: E402
from build_step3_min_n_sensitivity import load_panel, portfolios_min_bucket  # noqa: E402
from hlz_paper import assign_legs  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
MIN_N_TABLE = OUT / "step3_min_n_sensitivity.csv"
TABLE = OUT / "step3_weight_cap_sensitivity.csv"
YEAR_TABLE = OUT / "step3_weight_cap_yesmv_by_year.csv"
REPORT = OUT / "STEP3_WEIGHT_CAP_SENSITIVITY.md"
MINIMUM = 5
CAPS = (
    ("n5_no_cap", None),
    ("n5_cap_50", 0.50),
    ("n5_cap_30", 0.30),
    ("n5_cap_20", 0.20),
    ("n5_cap_10", 0.10),
    ("n5_cap_5", 0.05),
)
PAPER_YESMV = {"low": 0.084, "high": -0.171, "hl": -0.255, "t": -5.81}


def leg_names(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """N=5 membership, with each name's weight in the day's High and Low."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["category"]), []).append(row)
    matched: list[tuple[float, dict[str, list[dict[str, Any]]]]] = []
    for members in grouped.values():
        if len(members) < 3:
            continue
        legs = assign_legs([float(member["x"]) for member in members])
        buckets: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
        for member, leg in zip(members, legs):
            buckets[leg].append(member)
        if not all(buckets[name] for name in ("low", "middle", "high")):
            continue
        if len(buckets["high"]) < MINIMUM or len(buckets["low"]) < MINIMUM:
            continue
        presort = sum(float(member["oi"]) for member in members)
        if presort <= 0:
            continue
        if any(sum(float(item["oi"]) for item in buckets[name]) <= 0 for name in ("low", "middle", "high")):
            continue
        matched.append((presort, buckets))
    if not matched:
        return None
    total = sum(item[0] for item in matched)
    names: dict[str, list[tuple[float, float]]] = {"low": [], "high": []}
    for presort, buckets in matched:
        category_weight = presort / total
        for leg in ("low", "high"):
            leg_oi = sum(float(item["oi"]) for item in buckets[leg])
            for item in buckets[leg]:
                names[leg].append((category_weight * float(item["oi"]) / leg_oi, float(item["r"])))
    return {"n_categories": len(matched), "names": names}


def apply_cap(pairs: list[tuple[float, float]], cap: float | None) -> tuple[float, float]:
    """Return the leg return and the cash weight. Cash earns zero."""
    cash = 0.0
    total = 0.0
    for weight, payoff in pairs:
        kept = weight if cap is None else min(weight, cap)
        cash += weight - kept
        total += kept * payoff
    return total, cash


def run(grouped: dict[Any, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """One daily record per characteristic. Caps are applied later."""
    out: dict[str, list[dict[str, Any]]] = {label: [] for _key, label in CHARACTERISTICS}
    for day in sorted(grouped):
        members = grouped[day]
        for key, label in CHARACTERISTICS:
            usable = [
                {
                    "category": member["category"],
                    "x": float(member[key]),
                    "oi": member["oi"],
                    "r": member["r"],
                }
                for member in members
                if member[key] is not None
            ]
            detail = leg_names(usable)
            reference = portfolios_min_bucket(usable, MINIMUM)
            if (detail is None) != (reference is None):
                raise SystemExit(f"{label} {day} membership disagrees with the min-N builder")
            if detail is None or reference is None:
                continue
            for leg in ("low", "high"):
                uncapped, _cash = apply_cap(detail["names"][leg], None)
                target = reference[leg]
                if abs(uncapped - target) > 1e-9:
                    raise SystemExit(
                        f"{label} {day} {leg} weight sum {uncapped} != min-N return {target}"
                    )
            out[label].append({"date": day, "n_categories": detail["n_categories"], "names": detail["names"]})
    return out


def series_for(days: list[dict[str, Any]], cap: float | None) -> list[dict[str, Any]]:
    points = []
    for day in days:
        low, low_cash = apply_cap(day["names"]["low"], cap)
        high, high_cash = apply_cap(day["names"]["high"], cap)
        points.append(
            {
                "date": day["date"],
                "n_categories": day["n_categories"],
                "low": low * 100,
                "high": high * 100,
                "high_minus_low": (high - low) * 100,
                "low_cash": low_cash,
                "high_cash": high_cash,
            }
        )
    return points


def check_baseline(stats: dict[str, Any], prior: dict[str, str], label: str) -> None:
    pairs = (
        ("n_dates", stats["n_dates"], int(prior["n_dates"]), 0),
        ("n_category_days", stats["n_category_days"], int(prior["n_category_days"]), 0),
        ("mean_low_cents", stats["mean_low_cents"], float(prior["mean_low_cents"]), 1e-4),
        ("mean_high_cents", stats["mean_high_cents"], float(prior["mean_high_cents"]), 1e-4),
        (
            "mean_high_minus_low_cents",
            stats["mean_high_minus_low_cents"],
            float(prior["mean_high_minus_low_cents"]),
            1e-4,
        ),
    )
    for name, got, expected, tol in pairs:
        if abs(got - expected) > tol:
            raise SystemExit(
                f"N=5 baseline {label} {name} is {got} but the min-N table has {expected}. "
                "No files were overwritten."
            )
    got_t = stats["newey_west_t_lag7"]
    expected_t = float(prior["newey_west_t_lag7"])
    if got_t is None or abs(got_t - expected_t) > 1e-3:
        raise SystemExit(
            f"N=5 baseline {label} t is {got_t} but the min-N table has {expected_t}. "
            "No files were overwritten."
        )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def render(rows: list[dict[str, Any]], years: list[dict[str, Any]]) -> str:
    lines = [
        "# Step 3 weight-cap sensitivity at min N = 5",
        "",
        "High and Low must each contain at least 5 contracts, the same rule as the main min-N row. "
        "A name's weight is its share of that day's High portfolio, or separately of that day's Low portfolio, "
        "after the usual within-category open-interest weights and the presort category weights. "
        "Weight above the cap is cash earning zero. The other names keep their original weights. Nothing is scaled back up to one.",
        "",
        "The no-cap row matches `step3_min_n_sensitivity.csv`. Official Step 3 files and the min-N files were not rewritten. "
        "Paper Table IA.15 YESMV is Low +0.084, High −0.171, High−Low −0.255 (t = −5.81).",
        "",
        "## YESMV",
        "",
        "| Scheme | Cap | Dates | Category-days | Low | High | High−Low | NW(7) t | Mean High cash |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        if row["characteristic"] != "YESMV":
            continue
        lines.append(
            f"| {row['scheme']} | {row['cap']} | {row['n_dates']} | {row['n_category_days']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {float(row['newey_west_t_lag7']):.2f} | "
            f"{float(row['mean_high_cash']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## All characteristics",
            "",
            "| Scheme | Characteristic | Dates | Category-days | Low | High | High−Low | NW(7) t |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['scheme']} | {row['characteristic']} | {row['n_dates']} | {row['n_category_days']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {float(row['newey_west_t_lag7']):.2f} |"
        )
    lines.extend(
        [
            "",
            "## YESMV by year",
            "",
            "| Scheme | Years | Dates | Low | High | High−Low | NW(7) t |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in years:
        t_text = "" if row["newey_west_t_lag7"] == "" else f"{float(row['newey_west_t_lag7']):.2f}"
        lines.append(
            f"| {row['scheme']} | {row['years']} | {row['n_dates']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {t_text} |"
        )
    lines.extend(
        [
            "",
            "中文：分组仍是 N=5。只把当天 High 或 Low 里单个名字的权重截到上限，多出来的部分当天收益记为 0，其余名字的权重不放大。无上限那一行与已有的 N=5 结果一致。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if not MIN_N_TABLE.exists():
        raise SystemExit(f"missing {MIN_N_TABLE}")
    with MIN_N_TABLE.open(encoding="utf-8") as handle:
        prior = {
            row["characteristic"]: row
            for row in csv.DictReader(handle)
            if row["scheme"] == "min_high_low_5"
        }
    grouped = load_panel()
    print("build N=5 membership", flush=True)
    books = run(grouped)
    baseline = {label: summarize_points(series_for(books[label], None)) for _key, label in CHARACTERISTICS}
    for _key, label in CHARACTERISTICS:
        check_baseline(baseline[label], prior[label], label)
    print("N=5 no-cap row matches the min-N table", flush=True)
    rows: list[dict[str, Any]] = []
    capped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, cap in CAPS:
        capped[name] = {}
        for _key, label in CHARACTERISTICS:
            points = series_for(books[label], cap)
            capped[name][label] = points
            stats = summarize_points(points)
            t_stat = stats["newey_west_t_lag7"]
            rows.append(
                {
                    "scheme": name,
                    "min_high_low_n": str(MINIMUM),
                    "cap": "none" if cap is None else f"{cap:.2f}",
                    "characteristic": label,
                    "n_dates": stats["n_dates"],
                    "n_category_days": stats["n_category_days"],
                    "mean_low_cents": f"{stats['mean_low_cents']:.6f}",
                    "mean_high_cents": f"{stats['mean_high_cents']:.6f}",
                    "mean_high_minus_low_cents": f"{stats['mean_high_minus_low_cents']:.6f}",
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                    "mean_low_cash": f"{stats['mean_low_cash']:.6f}",
                    "mean_high_cash": f"{stats['mean_high_cash']:.6f}",
                    "paper_yesmv_low": f"{PAPER_YESMV['low']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_high": f"{PAPER_YESMV['high']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_high_minus_low": f"{PAPER_YESMV['hl']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_t": f"{PAPER_YESMV['t']:.2f}" if label == "YESMV" else "",
                }
            )
    years: list[dict[str, Any]] = []
    for name, _cap in CAPS:
        buckets: dict[str, list[dict[str, Any]]] = {"2023": [], "2024": [], "2025-2026": []}
        for point in capped[name]["YESMV"]:
            buckets[year_of(point["date"])].append(point)
        for bucket_name in ("2023", "2024", "2025-2026"):
            series = buckets[bucket_name]
            if len(series) < 2:
                continue
            stats = summarize_points(series)
            t_stat = stats["newey_west_t_lag7"]
            years.append(
                {
                    "scheme": name,
                    "years": bucket_name,
                    "n_dates": stats["n_dates"],
                    "mean_low_cents": f"{stats['mean_low_cents']:.6f}",
                    "mean_high_cents": f"{stats['mean_high_cents']:.6f}",
                    "mean_high_minus_low_cents": f"{stats['mean_high_minus_low_cents']:.6f}",
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                }
            )
    write_csv(TABLE, rows)
    write_csv(YEAR_TABLE, years)
    REPORT.write_text(render(rows, years), encoding="utf-8")
    print(f"wrote {REPORT}", flush=True)
    return 0


def summarize_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(points)
    hl = [row["high_minus_low"] for row in points]
    return {
        "n_dates": count,
        "n_category_days": sum(row["n_categories"] for row in points),
        "mean_low_cents": sum(row["low"] for row in points) / count,
        "mean_high_cents": sum(row["high"] for row in points) / count,
        "mean_high_minus_low_cents": sum(hl) / count,
        "newey_west_t_lag7": newey_west_t(hl, 7),
        "mean_low_cash": sum(row["low_cash"] for row in points) / count,
        "mean_high_cash": sum(row["high_cash"] for row in points) / count,
    }


def year_of(day: Any) -> str:
    year = day.year
    if year <= 2023:
        return "2023"
    if year == 2024:
        return "2024"
    return "2025-2026"


if __name__ == "__main__":
    raise SystemExit(main())
