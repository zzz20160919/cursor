#!/usr/bin/env python3
"""Step 3 portfolios from the existing Step 2 factor panel.

Sorts within formation date and vgregoire category. Breakpoints use the
winsorized characteristic. Weights are formation-time raw open interest.
This does not rebuild prices or the universe and does not start Step 4.
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from hlz_paper import category_portfolios  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
DIAGNOSTIC = OUT / "diagnostic_spreads.csv"
DAILY_PATH = OUT / "step3_spreads_daily.csv"
SUMMARY_PATH = OUT / "step3_spreads.csv"
COMPARE_PATH = OUT / "step3_vs_benchmarks.csv"
REPORT_PATH = OUT / "STEP3_SUMMARY.md"

# Column on the factor panel, then the label used in the tables.
CHARACTERISTICS = (
    ("yesmv", "YESMV"),
    ("oi_shares", "Open interest"),
    ("p_form", "Formation price"),
    ("lor_1", "LOR(1)"),
    ("lor_2", "LOR(2)"),
    ("lor_3", "LOR(3)"),
    ("lor_4", "LOR(4)"),
    ("lor_5", "LOR(5)"),
    ("lor_6", "LOR(6)"),
)

# Table IA.15, cents. Characteristics the paper reports and we can form.
PAPER = {
    "YESMV": {"low": 0.084, "middle": -0.020, "high": -0.171, "hl": -0.255, "t": -5.81},
    "Open interest": {"low": -0.191, "middle": -0.245, "high": -0.122, "hl": 0.069, "t": 1.18},
    "Formation price": {"low": -0.024, "middle": -0.207, "high": -0.240, "hl": -0.216, "t": -2.54},
    "LOR(1)": {"low": 0.121, "middle": -0.086, "high": -0.604, "hl": -0.725, "t": -5.29},
    "LOR(2)": {"low": 0.151, "middle": -0.147, "high": -0.452, "hl": -0.603, "t": -4.39},
    "LOR(3)": {"low": 0.046, "middle": -0.106, "high": -0.492, "hl": -0.538, "t": -4.22},
    "LOR(4)": {"low": 0.133, "middle": -0.112, "high": -0.420, "hl": -0.553, "t": -4.40},
    "LOR(5)": {"low": 0.180, "middle": -0.171, "high": -0.387, "hl": -0.566, "t": -4.87},
    "LOR(6)": {"low": 0.125, "middle": -0.099, "high": -0.376, "hl": -0.501, "t": -3.96},
}

# diagnostic_spreads.csv uses these names for the raw-OI scheme.
DIAGNOSTIC_NAME = {
    "YESMV": "yesmv",
    "LOR(1)": "lor_1",
    "LOR(2)": "lor_2",
    "LOR(3)": "lor_3",
    "LOR(4)": "lor_4",
    "LOR(5)": "lor_5",
    "LOR(6)": "lor_6",
}


def newey_west_t(values: list[float], lags: int = 7) -> float | None:
    """t-statistic of the mean. Bartlett kernel, `lags` Newey-West lags."""
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    errors = [value - mean for value in values]
    lag_cap = min(lags, count - 1)

    def gamma(lag: int) -> float:
        return sum(errors[index] * errors[index - lag] for index in range(lag, count)) / count

    variance = gamma(0)
    for lag in range(1, lag_cap + 1):
        weight = 1.0 - lag / (lag_cap + 1.0)
        variance += 2.0 * weight * gamma(lag)
    if variance <= 0:
        return None
    return mean / ((variance / count) ** 0.5)


def stars(t_stat: float | None) -> str:
    if t_stat is None:
        return ""
    magnitude = abs(t_stat)
    if magnitude >= 2.576:
        return "***"
    if magnitude >= 1.96:
        return "**"
    if magnitude >= 1.645:
        return "*"
    return ""


def self_test() -> None:
    t_stat = newey_west_t([1.0, 2.0, 3.0], lags=1)
    assert t_stat is not None
    assert abs(t_stat - 3.0 * math.sqrt(2.0)) < 1e-9
    assert newey_west_t([1.0, 1.0, 1.0], lags=7) is None
    assert stars(2.58) == "***"
    assert stars(2.0) == "**"
    assert stars(1.7) == "*"
    assert stars(1.0) == ""
    print("self-test ok")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_panel() -> dict[date, list[dict[str, Any]]]:
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
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for formation_date, category, yesmv, oi, price, l1, l2, l3, l4, l5, l6, payoff in rows:
        grouped[formation_date].append(
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
    print(f"portfolio dates {len(grouped)} rows {len(rows)}", flush=True)
    return grouped


def form_portfolios(
    grouped: dict[date, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_rows: list[dict[str, Any]] = []
    by_label: dict[str, list[dict[str, Any]]] = {label: [] for _key, label in CHARACTERISTICS}
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
            result = category_portfolios(usable)
            if result is None:
                continue
            record = {
                "date": day.isoformat(),
                "characteristic": label,
                "n_categories": result["n_categories"],
                "n_contracts": result["n_contracts"],
                "low_cents": result["low"] * 100,
                "middle_cents": result["middle"] * 100,
                "high_cents": result["high"] * 100,
                "high_minus_low_cents": result["high_minus_low"] * 100,
            }
            by_label[label].append(record)
            daily_rows.append(
                {
                    **record,
                    "low_cents": f"{record['low_cents']:.6f}",
                    "middle_cents": f"{record['middle_cents']:.6f}",
                    "high_cents": f"{record['high_cents']:.6f}",
                    "high_minus_low_cents": f"{record['high_minus_low_cents']:.6f}",
                }
            )
    summary = []
    for _key, label in CHARACTERISTICS:
        series = by_label[label]
        count = len(series)
        if count == 0:
            continue
        hl = [row["high_minus_low_cents"] for row in series]
        t_stat = newey_west_t(hl, 7)
        summary.append(
            {
                "characteristic": label,
                "n_dates": count,
                "mean_low_cents": sum(row["low_cents"] for row in series) / count,
                "mean_middle_cents": sum(row["middle_cents"] for row in series) / count,
                "mean_high_cents": sum(row["high_cents"] for row in series) / count,
                "mean_high_minus_low_cents": sum(hl) / count,
                "newey_west_t_lag7": t_stat,
            }
        )
    return daily_rows, summary


def diagnostic_lookup() -> dict[str, dict[str, str]]:
    if not DIAGNOSTIC.exists():
        return {}
    found = {}
    with DIAGNOSTIC.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["scheme"] != "aligned_raw_oi":
                continue
            found[row["characteristic"]] = row
    return found


def check_against_diagnostic(summary: list[dict[str, Any]]) -> None:
    previous = diagnostic_lookup()
    for row in summary:
        key = DIAGNOSTIC_NAME.get(row["characteristic"])
        if key is None or key not in previous:
            continue
        prior = float(previous[key]["mean_high_minus_low_cents"])
        if abs(row["mean_high_minus_low_cents"] - prior) > 1e-4:
            raise SystemExit(
                f"{row['characteristic']} High-Low {row['mean_high_minus_low_cents']:.6f} "
                f"disagrees with the diagnostic raw-OI spread {prior:.6f}"
            )
        if int(previous[key]["n_dates"]) != row["n_dates"]:
            raise SystemExit(f"{row['characteristic']} date count disagrees with the diagnostic")


def comparison_rows(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = diagnostic_lookup()
    rows = []
    for row in summary:
        paper = PAPER.get(row["characteristic"], {})
        diag_key = DIAGNOSTIC_NAME.get(row["characteristic"])
        diag = previous.get(diag_key or "", {})
        rows.append(
            {
                "characteristic": row["characteristic"],
                "n_dates": row["n_dates"],
                "our_low_cents": f"{row['mean_low_cents']:.6f}",
                "our_middle_cents": f"{row['mean_middle_cents']:.6f}",
                "our_high_cents": f"{row['mean_high_cents']:.6f}",
                "our_high_minus_low_cents": f"{row['mean_high_minus_low_cents']:.6f}",
                "our_newey_west_t": "" if row["newey_west_t_lag7"] is None else f"{row['newey_west_t_lag7']:.4f}",
                "diagnostic_high_minus_low_cents": diag.get("mean_high_minus_low_cents", ""),
                "diagnostic_newey_west_t": diag.get("newey_west_t_lag7", ""),
                "ia15_high_minus_low_cents": "" if not paper else f"{paper['hl']:.3f}",
                "ia15_t": "" if not paper else f"{paper['t']:.2f}",
            }
        )
    return rows


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def render(summary: list[dict[str, Any]]) -> str:
    lines = [
        "# HLZ Step 3 portfolios",
        "",
        "这是我们自己的分组结果，不是表 IA.15 的复述。价格仍是两小时内的小时收盘，类别仍是 vgregoire 的 7 个粗类。",
        "",
        "The input is the Step 2 portfolio sample in `a3_factor_daily.parquet`. "
        "Prices, the volume screen, and open interest are not rebuilt. "
        "Within each formation date and `markets.category`, the characteristic is winsorized "
        "at the 1st and 99th percentiles of that cell. Low / Middle / High use the 30th and 70th "
        "percentiles of the winsorized values. Those breakpoints decide membership only. "
        "Contracts are weighted by formation-time raw open interest. A category enters the day "
        "only when Low, Middle, and High are all non-empty. Category portfolios are then weighted "
        "by that category's total open interest measured before the sort. "
        "The reported number is the mean next-period price change in cents per YES claim. "
        "t-statistics are Newey–West with 7 lags on the daily High−Low series.",
        "",
        "Sample end remains 2026-03-29. Categories are Politics, Sports, Crypto, Culture, Finance, Tech, and Weather.",
        "",
        "## Our table",
        "",
        "| Characteristic | Dates | Low | Middle | High | High−Low | NW(7) t |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        t_stat = row["newey_west_t_lag7"]
        t_text = "" if t_stat is None else f"{t_stat:.2f}{stars(t_stat)}"
        lines.append(
            f"| {row['characteristic']} | {row['n_dates']} | {fmt(row['mean_low_cents'])} | "
            f"{fmt(row['mean_middle_cents'])} | {fmt(row['mean_high_cents'])} | "
            f"**{fmt(row['mean_high_minus_low_cents'])}** | {t_text} |"
        )
    lines.extend(
        [
            "",
            "Stars use the normal two-sided cuts 1.645 / 1.96 / 2.576. None of the required YESMV or LOR spreads reach the 10% cut on this sample.",
            "",
            "## Side by side",
            "",
            "The diagnostic High−Low means are the earlier raw-open-interest sorts on this same panel. "
            "They match this table. The diagnostic t-statistics were computed on the daily series in storage order, not calendar order, so they are not repeated as the inference. "
            "The t-statistics in this table are Newey–West with 7 lags on the calendar-ordered High−Low. "
            "IA.15 is the paper's Polymarket sort. It can use a quote midpoint when no fresh close exists, and it uses an official category this file does not contain.",
            "",
            "| Characteristic | Our High−Low | Our t | Diagnostic High−Low | IA.15 High−Low | IA.15 t |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    previous = diagnostic_lookup()
    for row in summary:
        paper = PAPER.get(row["characteristic"])
        diag = previous.get(DIAGNOSTIC_NAME.get(row["characteristic"], ""), {})
        t_stat = row["newey_west_t_lag7"]
        lines.append(
            "| {name} | {ours:.3f} | {t} | {diag} | {paper_hl} | {paper_t} |".format(
                name=row["characteristic"],
                ours=row["mean_high_minus_low_cents"],
                t="" if t_stat is None else f"{t_stat:.2f}",
                diag=diag.get("mean_high_minus_low_cents", ""),
                paper_hl="" if paper is None else f"{paper['hl']:.3f}",
                paper_t="" if paper is None else f"{paper['t']:.2f}",
            )
        )
    by_name = {row["characteristic"]: row for row in summary}
    yes = by_name["YESMV"]
    lor = by_name["LOR(1)"]
    chinese = (
        f"中文：YESMV 的 High−Low 是 {yes['mean_high_minus_low_cents']:+.3f} 分，"
        f"按日历排序的 Newey–West t 是 {yes['newey_west_t_lag7']:.2f}，"
        "和论文的 −0.255 分（t = −5.81）方向相反。"
        f"LOR(1) 是 {lor['mean_high_minus_low_cents']:+.3f} 分（t = {lor['newey_west_t_lag7']:.2f}），"
        "LOR(2) 到 LOR(6) 也都接近零且不显著。"
        "这些均值和诊断表里的原始持仓量加权结果一致。"
    )
    lines.extend(
        [
            "",
            "## What this is not",
            "",
            "- Not a replication of Table IA.15. The paper's High−Low YESMV is −0.255 cents (t = −5.81). Ours is positive and insignificant.",
            "- The paper can price a contract with a two-hour quote midpoint when the last trade is older than two hours. This panel cannot.",
            "- The paper's official category is unnamed. These sorts use seven vgregoire categories.",
            "- Open interest and formation price are included because they are already on the factor panel. Seven-day maximum price, maturity, volume, and liquidity sorts are not on the panel and are not filled in.",
            "- Bid–ask and cost-of-arbitrage sorts are omitted in the paper's Polymarket table and are omitted here.",
            "- Step 4 is not started.",
            "",
            "Daily series: `outputs/strategy/hlz_cross_section/step3_spreads_daily.csv`.",
            "",
            chinese,
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
        return 0
    if not FACTOR.exists():
        raise SystemExit(f"missing {FACTOR}")
    grouped = load_panel()
    daily_rows, summary = form_portfolios(grouped)
    check_against_diagnostic(summary)
    summary_out = []
    for row in summary:
        t_stat = row["newey_west_t_lag7"]
        summary_out.append(
            {
                "characteristic": row["characteristic"],
                "n_dates": row["n_dates"],
                "mean_low_cents": f"{row['mean_low_cents']:.6f}",
                "mean_middle_cents": f"{row['mean_middle_cents']:.6f}",
                "mean_high_cents": f"{row['mean_high_cents']:.6f}",
                "mean_high_minus_low_cents": f"{row['mean_high_minus_low_cents']:.6f}",
                "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                "stars": stars(t_stat),
            }
        )
    write_csv(DAILY_PATH, daily_rows)
    write_csv(SUMMARY_PATH, summary_out)
    write_csv(COMPARE_PATH, comparison_rows(summary))
    REPORT_PATH.write_text(render(summary), encoding="utf-8")
    print(f"wrote {REPORT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
