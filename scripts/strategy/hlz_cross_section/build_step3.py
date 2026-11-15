#!/usr/bin/env python3
"""Step 3 portfolios from the existing Step 2 factor panel.

Official sort: seven vgregoire categories, Low and High each at least 5
markets in that formation date and category, no weight cap. Breakpoints
use the winsorized characteristic. Weights are formation-time raw open
interest. This does not rebuild prices or the universe and does not start
Step 4.
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

OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
DAILY_PATH = OUT / "step3_spreads_daily.csv"
SUMMARY_PATH = OUT / "step3_spreads.csv"
COMPARE_PATH = OUT / "step3_vs_benchmarks.csv"
REPORT_PATH = OUT / "STEP3_SUMMARY.md"
MIN_HIGH_LOW = 5

# The previous official table had no minimum bucket size.
PREVIOUS_OFFICIAL = {
    "YESMV": {"n_dates": 884, "hl": 0.208871, "t": 1.2140},
    "Open interest": {"n_dates": 884, "hl": -0.012579, "t": -0.0709},
    "Formation price": {"n_dates": 880, "hl": 0.298026, "t": 1.4591},
    "LOR(1)": {"n_dates": 755, "hl": -0.086138, "t": -0.3991},
    "LOR(2)": {"n_dates": 729, "hl": -0.228806, "t": -1.0363},
    "LOR(3)": {"n_dates": 730, "hl": -0.005322, "t": -0.0408},
    "LOR(4)": {"n_dates": 722, "hl": 0.090265, "t": 0.5100},
    "LOR(5)": {"n_dates": 717, "hl": 0.010740, "t": 0.0890},
    "LOR(6)": {"n_dates": 710, "hl": -0.011034, "t": -0.0806},
}

# 7-class N=5 rows already published in the category comparison.
KNOWN_N5 = {
    "YESMV": (671, 0.056947, -0.043212, -0.100159, -3.5895),
    "Open interest": (671, 0.117697, -0.026239, -0.143936, -2.3618),
    "Formation price": (671, -0.001037, -0.009197, -0.008160, -0.1166),
    "LOR(1)": (653, 0.031340, -0.056874, -0.088214, -0.7939),
    "LOR(2)": (648, 0.074424, -0.070192, -0.144616, -1.5580),
    "LOR(3)": (652, 0.031915, 0.050449, 0.018534, 0.1586),
    "LOR(4)": (649, 0.086644, 0.017744, -0.068900, -0.5882),
    "LOR(5)": (647, 0.057793, 0.052206, -0.005587, -0.0526),
    "LOR(6)": (646, 0.028208, -0.009078, -0.037287, -0.3411),
}

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
    from build_step3_min_n_sensitivity import portfolios_min_bucket

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
            result = portfolios_min_bucket(usable, MIN_HIGH_LOW)
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


def check_known_n5(summary: list[dict[str, Any]]) -> None:
    by_name = {row["characteristic"]: row for row in summary}
    for label, (n_dates, low, high, spread, t_stat) in KNOWN_N5.items():
        row = by_name.get(label)
        if row is None:
            raise SystemExit(f"missing {label}")
        if row["n_dates"] != n_dates:
            raise SystemExit(f"{label} has {row['n_dates']} dates, expected {n_dates}")
        for name, got, expected in (
            ("low", row["mean_low_cents"], low),
            ("high", row["mean_high_cents"], high),
            ("high-low", row["mean_high_minus_low_cents"], spread),
        ):
            if abs(got - expected) > 5e-4:
                raise SystemExit(f"{label} {name} is {got:.6f}, expected {expected:.6f}")
        got_t = row["newey_west_t_lag7"]
        if got_t is None or abs(got_t - t_stat) > 5e-4:
            raise SystemExit(f"{label} t is {got_t}, expected {t_stat}")


def comparison_rows(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in summary:
        paper = PAPER.get(row["characteristic"], {})
        previous = PREVIOUS_OFFICIAL[row["characteristic"]]
        rows.append(
            {
                "characteristic": row["characteristic"],
                "n_dates": row["n_dates"],
                "our_low_cents": f"{row['mean_low_cents']:.6f}",
                "our_middle_cents": f"{row['mean_middle_cents']:.6f}",
                "our_high_cents": f"{row['mean_high_cents']:.6f}",
                "our_high_minus_low_cents": f"{row['mean_high_minus_low_cents']:.6f}",
                "our_newey_west_t": "" if row["newey_west_t_lag7"] is None else f"{row['newey_west_t_lag7']:.4f}",
                "previous_no_min_n_dates": previous["n_dates"],
                "previous_no_min_n_high_minus_low_cents": f"{previous['hl']:.6f}",
                "previous_no_min_n_t": f"{previous['t']:.4f}",
                "ia15_low_cents": "" if not paper else f"{paper['low']:.3f}",
                "ia15_high_cents": "" if not paper else f"{paper['high']:.3f}",
                "ia15_high_minus_low_cents": "" if not paper else f"{paper['hl']:.3f}",
                "ia15_t": "" if not paper else f"{paper['t']:.2f}",
            }
        )
    return rows


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def render(summary: list[dict[str, Any]]) -> str:
    by_name = {row["characteristic"]: row for row in summary}
    yes = by_name["YESMV"]
    lines = [
        "# HLZ Step 3 portfolios",
        "",
        "官方口径是 7 个 vgregoire 类别、N=5、没有权重上限。同一形成日、同一类别里，Low 和 High 各至少 5 个不同市场；任一不足则该类别日剔除，两腿只用共同留下的类别。",
        "其余仍按论文：类别内 1% / 99% winsorize，30% / 70% 分位只决定成员身份，raw open interest 两阶段加权，结果是下一期 YES 价格变动（美分/张），Newey–West 滞后 7 期。",
        "价格仍是两小时内的小时收盘，没有重跑价格或持仓，也没有换成 12 类。12 类对照仍在 `STEP3_CATEGORY12_SENSITIVITY.md`。",
        "",
        "The input is the Step 2 portfolio sample in `a3_factor_daily.parquet`. "
        "Sample end remains 2026-03-29. Categories are Politics, Sports, Crypto, Culture, Finance, Tech, and Weather.",
        "",
        "## Official table",
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
            "Stars use the normal two-sided cuts 1.645 / 1.96 / 2.576.",
            "",
            "## 与旧官方、与论文",
            "",
            "旧官方不设最少合约数：YESMV 884 天，High−Low +0.208871，t 1.2140。论文 IA.15 没有披露天数。",
            "",
            "| Characteristic | Dates | High−Low | t | 旧官方天数 | 旧官方 High−Low | 旧官方 t | IA.15 Low | IA.15 High | IA.15 High−Low | IA.15 t |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary:
        paper = PAPER[row["characteristic"]]
        previous = PREVIOUS_OFFICIAL[row["characteristic"]]
        t_stat = row["newey_west_t_lag7"]
        lines.append(
            f"| {row['characteristic']} | {row['n_dates']} | {fmt(row['mean_high_minus_low_cents'])} | "
            f"{'' if t_stat is None else f'{t_stat:.2f}'} | {previous['n_dates']} | {previous['hl']:+.3f} | "
            f"{previous['t']:.2f} | {paper['low']:+.3f} | {paper['high']:+.3f} | {paper['hl']:+.3f} | {paper['t']:.2f} |"
        )
    lor_bits = []
    for name in ("LOR(1)", "LOR(2)", "LOR(3)", "LOR(4)", "LOR(5)", "LOR(6)"):
        row = by_name[name]
        lor_bits.append(
            f"{name} {row['n_dates']} 天，Low {row['mean_low_cents']:+.3f}，High {row['mean_high_cents']:+.3f}，"
            f"High−Low {row['mean_high_minus_low_cents']:+.3f}，t {row['newey_west_t_lag7']:.2f}"
        )
    lines.extend(
        [
            "",
            (
                f"YESMV：{yes['n_dates']} 天，Low {yes['mean_low_cents']:+.6f}，High {yes['mean_high_cents']:+.6f}，"
                f"High−Low {yes['mean_high_minus_low_cents']:+.6f}，t {yes['newey_west_t_lag7']:.4f}。"
                "相对旧官方，天数从 884 减到 671，High−Low 从 +0.208871 变成 −0.100159。"
                "论文 IA.15 是 Low +0.084，High −0.171，High−Low −0.255，t −5.81。"
                "新的价差方向与论文相同，幅度大约是论文的四成，High 仍远没有到 −0.171。"
            ),
            "LOR：" + "；".join(lor_bits) + "。论文对应的 High−Low 是 −0.725、−0.603、−0.538、−0.553、−0.566、−0.501。",
            "",
            "## What this is not",
            "",
            "- Not a replication of Table IA.15. The paper's YESMV High−Low is −0.255 cents (t = −5.81). This table is −0.100 cents (t = −3.59) over 671 dates.",
            "- The paper can price a contract with a two-hour quote midpoint when the last trade is older than two hours. This panel cannot.",
            "- These sorts use seven vgregoire categories, not the 12-class map.",
            "- There is no single-name weight cap.",
            "- Open interest and formation price are included because they are already on the factor panel. Seven-day maximum price, maturity, volume, and liquidity sorts are not on the panel.",
            "- Bid–ask and cost-of-arbitrage sorts are omitted in the paper's Polymarket table and are omitted here.",
            "- Step 4 is not started. The 12-class comparison is unchanged.",
            "",
            "Daily series: `outputs/strategy/hlz_cross_section/step3_spreads_daily.csv`.",
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
    check_known_n5(summary)
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
