#!/usr/bin/env python3
"""Dollar performance of the official YESMV book. Does not rewrite Step 3.

Long the Low leg and short the High leg, $10,000 of market value on each
leg. Official files are read only as a check.
"""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_step3 import newey_west_t  # noqa: E402
from hlz_paper import assign_legs  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
OFFICIAL = OUT / "step3_spreads.csv"
OFFICIAL_DAILY = OUT / "step3_spreads_daily.csv"
REPORT = OUT / "STEP3_5_PERFORMANCE.md"
DAILY_PATH = OUT / "step3_5_daily.csv"
YEAR_PATH = OUT / "step3_5_by_year.csv"
CHART = OUT / "step3_5_wealth.png"

EQUITY = 10_000.0
PERIODS_PER_YEAR = 365.25
MIN_N = 5
YEARS = (2022, 2023, 2024, 2025, 2026)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_rows() -> dict[date, list[dict[str, Any]]]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT formation_date, market_id, category, yesmv, oi_shares, p_form, p_end, r_pp
        FROM read_parquet('{FACTOR}')
        WHERE in_portfolio_sample
          AND category <> ''
          AND oi_shares > 0
          AND r_pp IS NOT NULL
        """
    ).fetchall()
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for formation_date, market_id, category, yesmv, oi, price, end_price, payoff in rows:
        grouped[formation_date].append(
            {
                "market_id": market_id,
                "category": category,
                "yesmv": yesmv,
                "oi": float(oi),
                "p_form": None if price is None else float(price),
                "p_end": None if end_price is None else float(end_price),
                "r": float(payoff),
            }
        )
    return grouped


def book_for_day(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Official N=5 YESMV membership and two-stage raw-OI weights."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["yesmv"] is None:
            continue
        grouped[row["category"]].append(row)
    matched: list[tuple[float, dict[str, list[dict[str, Any]]]]] = []
    for members in grouped.values():
        if len(members) < 3:
            continue
        legs = assign_legs([float(member["yesmv"]) for member in members])
        buckets: dict[str, list[dict[str, Any]]] = {"low": [], "middle": [], "high": []}
        for member, leg in zip(members, legs):
            buckets[leg].append(member)
        if not all(buckets[name] for name in ("low", "middle", "high")):
            continue
        if len(buckets["high"]) < MIN_N or len(buckets["low"]) < MIN_N:
            continue
        presort = sum(member["oi"] for member in members)
        if presort <= 0:
            continue
        matched.append((presort, buckets))
    if not matched:
        return None
    total_presort = sum(presort for presort, _buckets in matched)
    holdings = {"low": [], "high": []}
    leg_return = {}
    for leg in ("low", "high"):
        weighted = 0.0
        for presort, buckets in matched:
            category_weight = presort / total_presort
            bucket = buckets[leg]
            leg_oi = sum(member["oi"] for member in bucket)
            for member in bucket:
                weight = category_weight * (member["oi"] / leg_oi)
                weighted += weight * member["r"]
                holdings[leg].append({**member, "weight": weight})
        leg_return[leg] = weighted
    return {
        "low": leg_return["low"],
        "high": leg_return["high"],
        "high_minus_low": leg_return["high"] - leg_return["low"],
        "holdings": holdings,
    }


def usable_price(price: float | None) -> bool:
    return price is not None and price > 0.0


def day_pnl(book: dict[str, Any]) -> dict[str, Any]:
    dropped = []
    pnl = {"low": 0.0, "high": 0.0}
    invested = {"low": 0.0, "high": 0.0}
    names = {"low": 0, "high": 0}
    for leg, sign in (("low", 1.0), ("high", -1.0)):
        for member in book["holdings"][leg]:
            price = member["p_form"]
            if not usable_price(price):
                dropped.append(
                    {
                        "market_id": member["market_id"],
                        "leg": leg,
                        "p_form": price,
                        "weight": member["weight"],
                    }
                )
                continue
            dollars = EQUITY * member["weight"]
            shares = dollars / price
            change = member["p_end"] - price
            pnl[leg] += sign * shares * change
            invested[leg] += dollars
            names[leg] += 1
    total = pnl["low"] + pnl["high"]
    return {
        "pnl": total,
        "long_pnl": pnl["low"],
        "short_pnl": pnl["high"],
        "return": total / EQUITY,
        "dollars_low": invested["low"],
        "dollars_high": invested["high"],
        "names_low": names["low"],
        "names_high": names["high"],
        "dropped": dropped,
    }


def check_official(books: dict[date, dict[str, Any]]) -> None:
    official = {row["characteristic"]: row for row in read_csv(OFFICIAL)}
    yes = official["YESMV"]
    dates = sorted(books)
    if len(dates) != int(yes["n_dates"]):
        raise SystemExit(f"YESMV dates {len(dates)} != official {yes['n_dates']}")
    daily = {
        date.fromisoformat(row["date"])
        for row in read_csv(OFFICIAL_DAILY)
        if row["characteristic"] == "YESMV"
    }
    if set(dates) != daily:
        raise SystemExit("rebuilt YESMV dates do not match step3_spreads_daily.csv")
    count = len(dates)
    low = sum(books[day]["low"] for day in dates) / count * 100.0
    high = sum(books[day]["high"] for day in dates) / count * 100.0
    spread = sum(books[day]["high_minus_low"] for day in dates) / count * 100.0
    t_stat = newey_west_t([books[day]["high_minus_low"] * 100.0 for day in dates], 7)
    checks = (
        ("low", low, float(yes["mean_low_cents"])),
        ("high", high, float(yes["mean_high_cents"])),
        ("high-low", spread, float(yes["mean_high_minus_low_cents"])),
    )
    for name, got, expected in checks:
        if abs(got - expected) > 5e-4:
            raise SystemExit(f"rebuilt YESMV {name} {got:.6f} != official {expected:.6f}")
    expected_t = float(yes["newey_west_t_lag7"])
    if t_stat is None or abs(t_stat - expected_t) > 5e-3:
        raise SystemExit(f"rebuilt YESMV t {t_stat} != official {expected_t}")
    for day in dates:
        for leg in ("low", "high"):
            weight = sum(member["weight"] for member in books[day]["holdings"][leg])
            if abs(weight - 1.0) > 1e-8:
                raise SystemExit(f"{day} {leg} weights sum to {weight}")


def calendar_span(first: date, last: date) -> list[date]:
    days = []
    cursor = first
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def downside_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(min(value, 0.0) ** 2 for value in values) / len(values))


def compound(returns: list[float]) -> float:
    wealth = 1.0
    for value in returns:
        wealth *= 1.0 + value
    return wealth


def max_drawdown(points: list[tuple[date, float]], entry_wealth: float, entry_label: str) -> dict[str, Any]:
    peak = entry_wealth
    peak_date = entry_label
    worst = 0.0
    worst_peak = peak
    worst_peak_date = peak_date
    trough = peak
    trough_date = entry_label
    for day, wealth in points:
        if wealth >= peak:
            peak = wealth
            peak_date = day.isoformat()
        drawdown = wealth / peak - 1.0 if peak else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak
            worst_peak_date = peak_date
            trough = wealth
            trough_date = day.isoformat()
    recovery = ""
    if worst < 0.0:
        after = False
        for day, wealth in points:
            if day.isoformat() == trough_date:
                after = True
                continue
            if after and wealth >= worst_peak:
                recovery = day.isoformat()
                break
        if not recovery:
            recovery = "未恢复"
    return {
        "max_drawdown": worst,
        "peak_wealth": worst_peak,
        "trough_wealth": trough,
        "peak_date": worst_peak_date,
        "trough_date": trough_date if worst < 0.0 else "",
        "recovery_date": recovery,
        "dollar_loss": trough - worst_peak,
    }


def summarize(label: str, returns: list[float], periods: int) -> dict[str, Any]:
    wealth_ratio = compound(returns)
    mean = sum(returns) / len(returns) if returns else 0.0
    deviation = sample_std(returns)
    down = downside_deviation(returns)
    ann_arith = mean * PERIODS_PER_YEAR
    ann_vol = None if deviation is None else deviation * math.sqrt(PERIODS_PER_YEAR)
    ann_down = down * math.sqrt(PERIODS_PER_YEAR)
    # A negative product has no real calendar-power. Do not emit a complex number.
    compound_ann = None
    if periods and wealth_ratio > 0.0:
        compound_ann = wealth_ratio ** (PERIODS_PER_YEAR / periods) - 1.0
    sharpe = None if not ann_vol else ann_arith / ann_vol
    sortino = None if ann_down == 0.0 else ann_arith / ann_down
    negative = sum(value < 0.0 for value in returns)
    return {
        "view": label,
        "periods": periods,
        "ending_wealth": EQUITY * wealth_ratio,
        "total_return": wealth_ratio - 1.0,
        "wealth_ratio_positive": wealth_ratio > 0.0,
        "annualized_compound": compound_ann,
        "annualized_arithmetic": ann_arith,
        "annualized_vol": ann_vol,
        "downside_deviation": ann_down,
        "sortino": sortino,
        "sharpe": sharpe,
        "negative_day_share": negative / len(returns) if returns else 0.0,
        "negative_days": negative,
        "mean_daily": mean,
        "total_pnl": EQUITY * sum(returns),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value * 100:.{digits}f}%"


def money(value: float) -> str:
    return f"${value:,.2f}"


def first_nonpositive(points: list[tuple[date, float]]) -> tuple[date, float] | None:
    for day, wealth in points:
        if wealth <= 0.0:
            return day, wealth
    return None


def save_chart(dates: list[date], wealth: list[float], drawdown: list[float]) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(dates, wealth, color="#1f4e79", linewidth=1.2)
    axes[0].set_ylabel("Wealth ($)")
    axes[0].set_title("Compounded wealth through the day equity crosses zero")
    axes[1].fill_between(dates, drawdown, 0.0, color="#9a3412", alpha=0.8)
    axes[1].set_ylabel("Drawdown")
    axes[1].yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _pos: f"{value:.0%}"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(CHART, dpi=120)
    plt.close(fig)
    return True


def num_text(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "无实数"
    return f"{value:.2f}"


def render(
    first: date,
    last: date,
    invested_dates: list[date],
    calendar: list[dict[str, Any]],
    view_a: dict[str, Any],
    view_b: dict[str, Any],
    drawdown: dict[str, Any],
    years: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    chart_ok: bool,
    ruin: dict[str, Any],
) -> str:
    by_year = defaultdict(int)
    for day in invested_dates:
        by_year[day.year] += 1
    year_counts = ", ".join(f"{year} 年 {by_year[year]} 天" for year in YEARS)
    lines = [
        "# Step 3.5：官方 YESMV 的美元绩效",
        "",
        "这不是新的官方分组，也不改 Step 3 的参数。评估的就是现行官方 YESMV：7 类、N=5、无权重上限。",
        "方向是做多 Low、做空 High。每个形成日，Low 和 High 各投入 10,000 美元市值，权益按 10,000 美元计。没有融资成本、买卖价差或手续费。",
        "名字 i 的官方权重是 w_i，形成价是 P_i。dollars_i = 10000 × w_i，shares_i = dollars_i / P_i。多头盈亏是 shares × (P_next − P)，空头盈亏是 shares × (P − P_next)。日收益率 r_t = 当日盈亏 / 10000。",
        "下一期价格变动记在形成日当天。两个形成日之间没有官方组合的自然日，收益记为 0。这不是把已有的约 −0.10 美分 High−Low 乘一个常数。",
        "",
        "## 样本",
        "",
        f"- 有持仓的形成日：{len(invested_dates)} 天，从 {first.isoformat()} 到 {last.isoformat()}。",
        f"- 分年持仓日：{year_counts}。",
        f"- 第一天到最后一天共 {len(calendar)} 个自然日，其中没有官方组合、记为现金的 {(len(calendar) - len(invested_dates))} 天。",
        f"- 形成价缺失或 ≤ 0 而被跳过的名字：{len(dropped)}。跳过的美元不重新分配给其他名字。",
        "",
        "## 公式",
        "",
        "一年按 365.25 个期间。样本标准差用 n−1。",
        "- 复利年化：(W_end / 10000) ^ (365.25 / 期间数) − 1。",
        "- 算术年化：日收益均值 × 365.25。",
        "- 年化波动：日收益样本标准差 × sqrt(365.25)。",
        "- 下行波动：sqrt(均值(min(r_t, 0)^2)) × sqrt(365.25)。均值按该视图里的全部期间平均，包含 0。",
        "- Sortino：算术年化 / 年化下行波动，基准为 0。下行波动为 0 时不计算。",
        "- Sharpe：算术年化 / 年化波动，基准为 0。",
        "- 复利路径：W_t = 10000 × ∏(1+r_s)。现金日的 r 为 0，乘上去仍是 1。若某一天 r≤−1，财富变成负数，之后的连乘不再是可加仓的账户余额，(W_end/10000) 的 365.25 次方也没有实数。",
        "- (A) 只使用 671 个持仓日，期间数是 671。这是“每个自然日都有持仓”的年化。",
        "- (B) 使用第一天到最后一天的每个自然日，没有组合的日子收益为 0。期间数是这段日历的天数。",
        "- 恒定名义累计盈亏 = Σ 当日盈亏。它对应“每天把权益放回 10,000 美元”，不把已经亏穿的账户继续复利。",
        "",
        "## 全样本",
        "",
        "| 视图 | 期间数 | 日均收益 | 算术年化 | 年化波动 | 下行波动 | Sortino | Sharpe | 下跌日占比 | 恒定名义累计盈亏 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for view in (view_a, view_b):
        lines.append(
            f"| {view['view']} | {view['periods']} | {pct(view['mean_daily'])} | "
            f"{pct(view['annualized_arithmetic'])} | {pct(view['annualized_vol'])} | "
            f"{pct(view['downside_deviation'])} | {num_text(view['sortino'])} | "
            f"{num_text(view['sharpe'])} | {pct(view['negative_day_share'])} | {money(view['total_pnl'])} |"
        )
    lines.extend(
        [
            "",
            (
                f"复利路径在 {ruin['peak_date']} 达到 {money(ruin['peak_wealth'])}，"
                f"下一笔形成在 {ruin['date']}，当日盈亏 {money(ruin['pnl'])}，收益率 {pct(ruin['return'])}，"
                f"财富变成 {money(ruin['wealth'])}。"
            ),
            "这一天 Low 里有形成价 0.001 和 0.002 的合约结算到 0，多头按美元/价格换成的张数几乎亏光；空头同时小亏，所以亏损超过 10,000 美元权益。",
            "此后 ∏(1+r) 为负。全样本复利年化和“期末仍是正财富”的总复利都没有实数解，这里不把负数财富再开方。",
            (
                f"正财富上的最大回撤就是这一次穿仓：峰值 {money(drawdown['peak_wealth'])}（{drawdown['peak_date']}），"
                f"谷值 {money(drawdown['trough_wealth'])}（{drawdown['trough_date']}），"
                f"回撤 {pct(drawdown['max_drawdown'])}，金额 {money(drawdown['dollar_loss'])}。恢复日：{drawdown['recovery_date']}。"
            ),
            "穿仓之后财富不再回到这个正的峰值。",
            "",
            "## 分年",
            "",
            "波动和下行波动用该年窗口内的自然日，按 365.25 年化。最大回撤把该年单独从 10,000 美元复利到第一次财富小于等于 0，不承接上一年已经变成负数的余额。",
            "连乘结果是该年 ∏(1+r)−1。一旦年中有 r≤−1，这个连乘为负，不能读成普通百分比；同列旁边给出每天重置权益的盈亏。",
            "2022 和 2023 都在 2024-01-22 之前，不在第一天到最后一天的窗口里，所以不是窗口内的现金日。窗口内的现金日全部出现在 2024 年。",
            "",
            "| 年 | 连乘结果 | 恒定名义盈亏 | 年化波动 | 下行波动 | 最大回撤 | 持仓日 | 现金日 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in years:
        lines.append(
            f"| {row['year']} | {row['compounded_return']} | {row['constant_notional_pnl']} | {row['annualized_vol']} | "
            f"{row['downside_deviation']} | {row['max_drawdown']} | {row['invested_days']} | {row['cash_days']} |"
        )
    lines.extend(
        [
            "",
            "## 中文结论",
            "",
            (
                f"官方 YESMV 按做多 Low、做空 High 评估，没有改分组。样本 {first.isoformat()} 至 {last.isoformat()}，"
                f"持仓 {len(invested_dates)} 天，窗口内现金 {(len(calendar) - len(invested_dates))} 天，都在 2024 年。"
                f"2022 和 2023 不在这个窗口里。形成价没有缺失，也没有小于等于 0 的名字被剔除。"
                f"每天把权益放回 10,000 美元，Low 和 High 各做 10,000 美元市值，累计盈亏 {money(view_b['total_pnl'])}。"
                f"持仓日日均收益 {pct(view_a['mean_daily'])}，把现金日算进日历后日均 {pct(view_b['mean_daily'])}。"
                f"只算持仓日：算术年化 {pct(view_a['annualized_arithmetic'])}，年化波动 {pct(view_a['annualized_vol'])}，"
                f"下行波动 {pct(view_a['downside_deviation'])}，Sharpe {view_a['sharpe']:.2f}，Sortino {view_a['sortino']:.2f}，"
                f"下跌日占持仓日的 {pct(view_a['negative_day_share'])}。"
                f"日历含现金日：算术年化 {pct(view_b['annualized_arithmetic'])}，年化波动 {pct(view_b['annualized_vol'])}，"
                f"下行波动 {pct(view_b['downside_deviation'])}，Sharpe {view_b['sharpe']:.2f}，Sortino {view_b['sortino']:.2f}，"
                f"下跌日占日历的 {pct(view_b['negative_day_share'])}。"
                f"复利在 {ruin['peak_date']} 到 {money(ruin['peak_wealth'])}，{ruin['date']} 当天收益 {pct(ruin['return'])}，"
                f"财富变成 {money(ruin['wealth'])}。最大回撤 {pct(drawdown['max_drawdown'])}，没有恢复。"
                "复利年化没有实数解。比率这么大，是因为张数等于投入美元除以形成价，不是因为每张合约涨了零点几美分。"
                "官方 High−Low 大约 −0.10 美分/张，本身不是这笔 10,000 美元的收益率。这是没有成本的回测。"
            ),
            "",
            f"日报：`outputs/strategy/hlz_cross_section/step3_5_daily.csv`。分年：`step3_5_by_year.csv`。",
            f"图：`outputs/strategy/hlz_cross_section/step3_5_wealth.png`。" if chart_ok else "图没有生成。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if not FACTOR.exists() or not OFFICIAL.exists() or not OFFICIAL_DAILY.exists():
        raise SystemExit("missing the factor panel or official Step 3 files")
    grouped = load_rows()
    books = {}
    for day in sorted(grouped):
        book = book_for_day(grouped[day])
        if book is not None:
            books[day] = book
    check_official(books)
    print(f"official YESMV book matches, {len(books)} dates", flush=True)
    invested_dates = sorted(books)
    first, last = invested_dates[0], invested_dates[-1]
    dropped: list[dict[str, Any]] = []
    invested_rows = {}
    for day in invested_dates:
        result = day_pnl(books[day])
        dropped.extend({**item, "date": day.isoformat()} for item in result["dropped"])
        invested_rows[day] = result
    calendar_days = calendar_span(first, last)
    daily_out = []
    wealth = EQUITY
    peak = EQUITY
    series: list[tuple[date, float]] = []
    for day in calendar_days:
        invested = day in invested_rows
        if invested:
            result = invested_rows[day]
            pnl = result["pnl"]
            ret = result["return"]
        else:
            pnl = 0.0
            ret = 0.0
        wealth *= 1.0 + ret
        if wealth > peak and wealth > 0.0:
            peak = wealth
        drawdown = wealth / peak - 1.0 if peak else 0.0
        series.append((day, wealth))
        daily_out.append(
            {
                "date": day.isoformat(),
                "invested": "1" if invested else "0",
                "r_t": f"{ret:.10f}",
                "pnl": f"{pnl:.6f}",
                "wealth": f"{wealth:.6f}",
                "drawdown": f"{drawdown:.10f}",
            }
        )
    returns_b = [float(row["r_t"]) for row in daily_out]
    returns_a = [invested_rows[day]["return"] for day in invested_dates]
    view_a = summarize("A 只算持仓日", returns_a, len(returns_a))
    view_b = summarize("B 日历含现金日", returns_b, len(returns_b))
    solvent: list[tuple[date, float]] = []
    ruin_point: tuple[date, float] | None = None
    for day, marked in series:
        solvent.append((day, marked))
        if marked <= 0.0:
            ruin_point = (day, marked)
            break
    if ruin_point is None:
        raise SystemExit("expected the compounded path to cross zero")
    drawdown = max_drawdown(solvent, EQUITY, f"{first.isoformat()} 开盘前")
    ruin_row = next(row for row in daily_out if row["date"] == ruin_point[0].isoformat())
    ruin = {
        "date": ruin_point[0].isoformat(),
        "wealth": ruin_point[1],
        "pnl": float(ruin_row["pnl"]),
        "return": float(ruin_row["r_t"]),
        "peak_date": drawdown["peak_date"],
        "peak_wealth": drawdown["peak_wealth"],
    }
    year_rows = []
    for year in YEARS:
        invested_n = sum(day.year == year for day in invested_dates)
        rets = [float(row["r_t"]) for row in daily_out if row["date"].startswith(f"{year}-")]
        if not rets:
            year_rows.append(
                {
                    "year": year,
                    "in_window": "0",
                    "compounded_return": "",
                    "constant_notional_pnl": "",
                    "annualized_vol": "",
                    "downside_deviation": "",
                    "max_drawdown": "",
                    "invested_days": invested_n,
                    "cash_days": 0,
                    "peak_date": "",
                    "trough_date": "",
                    "recovery_date": "",
                    "peak_wealth": "",
                    "trough_wealth": "",
                }
            )
            continue
        fresh: list[tuple[date, float]] = []
        marked = EQUITY
        for row in daily_out:
            if not row["date"].startswith(f"{year}-"):
                continue
            marked *= 1.0 + float(row["r_t"])
            fresh.append((date.fromisoformat(row["date"]), marked))
            if marked <= 0.0:
                break
        path = max_drawdown(fresh, EQUITY, f"{year}-01-01 前")
        deviation = sample_std(rets)
        down = downside_deviation(rets)
        year_rows.append(
            {
                "year": str(year),
                "in_window": "1",
                "compounded_return": f"{compound(rets) - 1.0:.6e}",
                "constant_notional_pnl": f"{sum(rets) * EQUITY:.2f}",
                "annualized_vol": "" if deviation is None else f"{deviation * math.sqrt(PERIODS_PER_YEAR):.6f}",
                "downside_deviation": f"{down * math.sqrt(PERIODS_PER_YEAR):.6f}",
                "max_drawdown": f"{path['max_drawdown']:.6f}",
                "invested_days": invested_n,
                "cash_days": len(rets) - invested_n,
                "peak_date": path["peak_date"],
                "trough_date": path["trough_date"],
                "recovery_date": path["recovery_date"],
                "peak_wealth": f"{path['peak_wealth']:.2f}",
                "trough_wealth": f"{path['trough_wealth']:.2f}",
            }
        )
    write_csv(DAILY_PATH, daily_out)
    write_csv(YEAR_PATH, year_rows)
    chart_days = [day for day, _wealth in solvent]
    chart_wealth = [value for _day, value in solvent]
    chart_dd = []
    running_peak = EQUITY
    for value in chart_wealth:
        if value > running_peak and value > 0.0:
            running_peak = value
        chart_dd.append(value / running_peak - 1.0)
    chart_ok = save_chart(chart_days, chart_wealth, chart_dd)
    display_years = []
    for row in year_rows:
        if row["in_window"] != "1":
            display_years.append(
                {
                    "year": row["year"],
                    "compounded_return": "窗口外",
                    "constant_notional_pnl": "",
                    "annualized_vol": "",
                    "downside_deviation": "",
                    "max_drawdown": "",
                    "invested_days": row["invested_days"],
                    "cash_days": row["cash_days"],
                }
            )
            continue
        compounded = float(row["compounded_return"])
        if compounded <= -1.0:
            compounded_text = "连乘为负"
        elif abs(compounded) >= 10.0:
            compounded_text = f"{compounded:.3e}"
        else:
            compounded_text = pct(compounded)
        display_years.append(
            {
                "year": row["year"],
                "compounded_return": compounded_text,
                "constant_notional_pnl": money(float(row["constant_notional_pnl"])),
                "annualized_vol": pct(float(row["annualized_vol"])) if row["annualized_vol"] else "",
                "downside_deviation": pct(float(row["downside_deviation"])),
                "max_drawdown": pct(float(row["max_drawdown"])),
                "invested_days": row["invested_days"],
                "cash_days": row["cash_days"],
            }
        )
    REPORT.write_text(
        render(
            first,
            last,
            invested_dates,
            daily_out,
            view_a,
            view_b,
            drawdown,
            display_years,
            dropped,
            chart_ok,
            ruin,
        ),
        encoding="utf-8",
    )
    print(f"wrote {REPORT}", flush=True)
    print(
        f"pnl {view_b['total_pnl']:.2f} ruin {ruin['date']} {ruin['wealth']:.2f} "
        f"mdd {drawdown['max_drawdown']:.4f} dropped {len(dropped)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
