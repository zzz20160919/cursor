#!/usr/bin/env python3
"""Sensitivity of Step 3 to a minimum High and Low bucket size.

The official Step 3 table is now the N=5 sort written by build_step3.py.
The row named official in this file is the older sort with no minimum.
This script does not rewrite the official Step 3 files. A category-day
is dropped when its High or Low bucket is thinner than the minimum.
Weights, winsorization, and the 30/70 split are otherwise the same.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_step3 import CHARACTERISTICS, newey_west_t  # noqa: E402
from hlz_paper import assign_legs, category_portfolios, oi_weighted_mean  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
TABLE = OUT / "step3_min_n_sensitivity.csv"
YEAR_TABLE = OUT / "step3_min_n_yesmv_by_year.csv"
REPORT = OUT / "STEP3_MIN_N_SENSITIVITY.md"

SCHEMES = (
    ("official", None),
    ("min_high_low_2", 2),
    ("min_high_low_5", 5),
    ("min_high_low_10", 10),
    ("min_high_low_20", 20),
    ("min_high_low_30", 30),
)
PAPER_YESMV = {"low": 0.084, "high": -0.171, "hl": -0.255, "t": -5.81}


def load_panel() -> dict[Any, list[dict[str, Any]]]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT formation_date, category, yesmv, oi_shares, p_form,
               lor_1, lor_2, lor_3, lor_4, lor_5, lor_6, r_pp
        FROM read_parquet('{FACTOR}')
        WHERE in_portfolio_sample
          AND category <> ''
          AND oi_shares > 0
          AND r_pp IS NOT NULL
        """
    ).fetchall()
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for formation_date, category, yesmv, oi, price, l1, l2, l3, l4, l5, l6, payoff in rows:
        grouped.setdefault(formation_date, []).append(
            {
                "category": category,
                "yesmv": yesmv,
                "oi_shares": oi,
                "p_form": price,
                "lor_1": l1,
                "lor_2": l2,
                "lor_3": l3,
                "lor_4": l4,
                "lor_5": l5,
                "lor_6": l6,
                "oi": float(oi),
                "r": float(payoff),
            }
        )
    return grouped


def portfolios_min_bucket(rows: list[dict[str, Any]], minimum: int) -> dict[str, Any] | None:
    """Same as category_portfolios, plus a minimum size on High and on Low."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["category"]), []).append(row)
    leg_returns: dict[str, list[tuple[float, float]]] = {"low": [], "middle": [], "high": []}
    n_contracts = 0
    for members in grouped.values():
        if len(members) < 3:
            continue
        legs = assign_legs([float(member["x"]) for member in members])
        buckets: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
        for member, leg in zip(members, legs):
            buckets[leg].append(member)
        if not all(buckets[name] for name in ("low", "middle", "high")):
            continue
        if len(buckets["high"]) < minimum or len(buckets["low"]) < minimum:
            continue
        presort = sum(float(member["oi"]) for member in members)
        if presort <= 0:
            continue
        returns: dict[str, float] = {}
        ok = True
        for name, bucket in buckets.items():
            mean = oi_weighted_mean(
                [{"oi": float(item["oi"]), "r": float(item["r"])} for item in bucket]
            )
            if mean is None:
                ok = False
                break
            returns[name] = mean
        if not ok:
            continue
        n_contracts += len(members)
        for name in ("low", "middle", "high"):
            leg_returns[name].append((presort, returns[name]))
    if not leg_returns["low"]:
        return None

    def aggregate(pairs: list[tuple[float, float]]) -> float:
        weight = sum(item[0] for item in pairs)
        return sum(item[0] * item[1] for item in pairs) / weight

    low = aggregate(leg_returns["low"])
    middle = aggregate(leg_returns["middle"])
    high = aggregate(leg_returns["high"])
    return {
        "n_categories": len(leg_returns["low"]),
        "n_contracts": n_contracts,
        "low": low,
        "middle": middle,
        "high": high,
        "high_minus_low": high - low,
    }


def run_scheme(
    grouped: dict[Any, list[dict[str, Any]]],
    minimum: int | None,
) -> dict[str, list[dict[str, Any]]]:
    """Daily portfolio results keyed by characteristic label."""
    out: dict[str, list[dict[str, Any]]] = {label: [] for _key, label in CHARACTERISTICS}
    for day in sorted(grouped):
        members = grouped[day]
        for key, label in CHARACTERISTICS:
            usable = []
            for member in members:
                value = member[key]
                if value is None:
                    continue
                usable.append(
                    {
                        "category": member["category"],
                        "x": float(value),
                        "oi": member["oi"],
                        "r": member["r"],
                    }
                )
            if minimum is None:
                result = category_portfolios(usable)
            else:
                result = portfolios_min_bucket(usable, minimum)
            if result is None:
                continue
            out[label].append(
                {
                    "date": day,
                    "n_categories": result["n_categories"],
                    "low": result["low"] * 100,
                    "high": result["high"] * 100,
                    "high_minus_low": result["high_minus_low"] * 100,
                }
            )
    return out


def summarize(series: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(series)
    hl = [row["high_minus_low"] for row in series]
    return {
        "n_dates": count,
        "n_category_days": sum(row["n_categories"] for row in series),
        "mean_low_cents": sum(row["low"] for row in series) / count,
        "mean_high_cents": sum(row["high"] for row in series) / count,
        "mean_high_minus_low_cents": sum(hl) / count,
        "newey_west_t_lag7": newey_west_t(hl, 7),
    }


# The unrestricted sort, frozen when the official table still had no minimum.
OLD_UNRESTRICTED = {
    "YESMV": (884, 0.073974, 0.282845, 0.208871, 1.2140),
    "Open interest": (884, 0.288748, 0.276170, -0.012579, -0.0709),
    "Formation price": (880, -0.076225, 0.221801, 0.298026, 1.4591),
    "LOR(1)": (755, 0.249958, 0.163820, -0.086138, -0.3991),
    "LOR(2)": (729, 0.192687, -0.036119, -0.228806, -1.0363),
    "LOR(3)": (730, 0.093831, 0.088509, -0.005322, -0.0408),
    "LOR(4)": (722, 0.026324, 0.116589, 0.090265, 0.5100),
    "LOR(5)": (717, -0.024112, -0.013373, 0.010740, 0.0890),
    "LOR(6)": (710, 0.040182, 0.029148, -0.011034, -0.0806),
}


def check_unrestricted(summary: dict[str, Any], label: str) -> None:
    n_dates, low, high, spread, t_stat = OLD_UNRESTRICTED[label]
    checks = {
        "n_dates": (summary["n_dates"], n_dates, 0),
        "mean_low_cents": (summary["mean_low_cents"], low, 1e-4),
        "mean_high_cents": (summary["mean_high_cents"], high, 1e-4),
        "mean_high_minus_low_cents": (summary["mean_high_minus_low_cents"], spread, 1e-4),
    }
    for name, (got, expected, tol) in checks.items():
        if abs(got - expected) > tol:
            raise SystemExit(f"unrestricted {label} {name} is {got}, expected {expected}")
    got_t = summary["newey_west_t_lag7"]
    if got_t is None or abs(got_t - t_stat) > 1e-3:
        raise SystemExit(f"unrestricted {label} Newey-West t is {got_t}, expected {t_stat}")


def year_bucket(day: Any) -> str:
    year = day.year
    if year <= 2023:
        return "2023"
    if year == 2024:
        return "2024"
    return "2025-2026"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def render(rows: list[dict[str, Any]], years: list[dict[str, Any]]) -> str:
    lines = [
        "# Step 3 sensitivity: minimum High and Low bucket size",
        "",
        "官方 Step 3 现已改为 N=5。本文件的 official 行仍是不设最少合约数的旧口径（YESMV 884 天，High−Low +0.209，t 1.21），不再等于 `step3_spreads.csv`。更高的 N 在 High 或 Low 合约数不足时剔除该类别日。Winsorize、30/70、raw open interest 和类别权重不变，也没有权重上限。",
        "",
        "N = 5 is the main sensitivity. Paper Table IA.15 YESMV is Low +0.084, High −0.171, High−Low −0.255 (t = −5.81).",
        "",
        "## YESMV",
        "",
        "| Scheme | Dates | Category-days | Dates dropped | Category-days dropped | Low | High | High−Low | NW(7) t |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        if row["characteristic"] != "YESMV":
            continue
        mark = " **" if row["scheme"] == "min_high_low_5" else ""
        lines.append(
            f"| {row['scheme']}{mark} | {row['n_dates']} | {row['n_category_days']} | "
            f"{row['dates_dropped_vs_official']} | {row['category_days_dropped_vs_official']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {float(row['newey_west_t_lag7']):.2f} |"
        )
    lines.extend(
        [
            "",
            "The official row in this file is the old unrestricted sort: YESMV High +0.283, Low +0.074, High−Low +0.209, t 1.21, 884 dates. It is not the current `step3_spreads.csv`.",
            "",
            "## All characteristics",
            "",
            "| Scheme | Characteristic | Dates | Category-days | Dropped dates | Dropped category-days | Low | High | High−Low | NW(7) t |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['scheme']} | {row['characteristic']} | {row['n_dates']} | {row['n_category_days']} | "
            f"{row['dates_dropped_vs_official']} | {row['category_days_dropped_vs_official']} | "
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
        t_stat = row["newey_west_t_lag7"]
        t_text = "" if t_stat == "" else f"{float(t_stat):.2f}"
        lines.append(
            f"| {row['scheme']} | {row['years']} | {row['n_dates']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {t_text} |"
        )
    lines.extend(
        [
            "",
            "中文：这张表把 High 和 Low 桶的最少合约数从“非空”提高到 2、5、10、20、30。表内 official 行是旧的不设下限口径。当前正式结果是 N=5，写在 `STEP3_SUMMARY.md`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if not FACTOR.exists():
        raise SystemExit("missing the Step 2 factor panel")
    grouped = load_panel()
    results: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, minimum in SCHEMES:
        print(f"scheme {name}", flush=True)
        results[name] = run_scheme(grouped, minimum)
    official_summary = {label: summarize(results["official"][label]) for _key, label in CHARACTERISTICS}
    for _key, label in CHARACTERISTICS:
        check_unrestricted(official_summary[label], label)
    print("unrestricted row matches the frozen no-minimum table", flush=True)
    rows: list[dict[str, Any]] = []
    for name, minimum in SCHEMES:
        for _key, label in CHARACTERISTICS:
            stats = summarize(results[name][label])
            base = official_summary[label]
            t_stat = stats["newey_west_t_lag7"]
            rows.append(
                {
                    "scheme": name,
                    "min_high_low_n": "" if minimum is None else str(minimum),
                    "main_sensitivity": "true" if name == "min_high_low_5" else "false",
                    "characteristic": label,
                    "n_dates": stats["n_dates"],
                    "n_category_days": stats["n_category_days"],
                    "dates_dropped_vs_official": base["n_dates"] - stats["n_dates"],
                    "category_days_dropped_vs_official": base["n_category_days"] - stats["n_category_days"],
                    "mean_low_cents": f"{stats['mean_low_cents']:.6f}",
                    "mean_high_cents": f"{stats['mean_high_cents']:.6f}",
                    "mean_high_minus_low_cents": f"{stats['mean_high_minus_low_cents']:.6f}",
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                    "paper_yesmv_low": f"{PAPER_YESMV['low']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_high": f"{PAPER_YESMV['high']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_high_minus_low": f"{PAPER_YESMV['hl']:.3f}" if label == "YESMV" else "",
                    "paper_yesmv_t": f"{PAPER_YESMV['t']:.2f}" if label == "YESMV" else "",
                }
            )
    years: list[dict[str, Any]] = []
    for name, _minimum in SCHEMES:
        buckets: dict[str, list[dict[str, Any]]] = {"2023": [], "2024": [], "2025-2026": []}
        for point in results[name]["YESMV"]:
            buckets[year_bucket(point["date"])].append(point)
        for bucket_name in ("2023", "2024", "2025-2026"):
            series = buckets[bucket_name]
            if not series:
                continue
            stats = summarize(series)
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


if __name__ == "__main__":
    raise SystemExit(main())
