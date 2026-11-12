from __future__ import annotations

import argparse
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRID_TRADES = PROJECT_ROOT / "reports/btc_nq_weekend/grid_3x3_weekend/grid_3x3_event_trades.csv"
DEFAULT_ENDPOINT_ATTR = (
    PROJECT_ROOT / "reports/btc_nq_weekend/grid_3x3_weekend/grid_3x3_endpoint_missing_attribution.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/grid_3x3_threshold_0p5"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/grid_3x3_threshold_0p5_report.md"

BTC_LOOKBACKS = ("btc_ret_1h", "btc_ret_4h", "btc_ret_12h")
NQ_TARGETS = ("nq_fwd_1h", "nq_fwd_4h", "nq_fwd_to_1600_same_day")
SIGNAL_MODES = ("no_threshold", "threshold_0p5")
THRESHOLD = 0.005
TRADES_PER_YEAR = 52.0
LOW_SAMPLE_WARN_THRESHOLD = 20
OOS_START_LOCAL_DATE = "2026-03-23"
NEW_YORK = ZoneInfo("America/New_York")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-NQ 3x3 threshold 0.5% comparison.")
    parser.add_argument("--grid-trades", type=Path, default=DEFAULT_GRID_TRADES)
    parser.add_argument("--endpoint-attribution", type=Path, default=DEFAULT_ENDPOINT_ATTR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def combo_names() -> list[str]:
    return [f"{btc}__{target}" for btc in BTC_LOOKBACKS for target in NQ_TARGETS]


def load_grid_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"grid trades not found: {path}")
    frame = pd.read_csv(path)
    frame["event_time_ny_dt"] = pd.to_datetime(frame["event_time_ny"], utc=True, errors="coerce").dt.tz_convert(
        "America/New_York"
    )
    frame["event_time_utc_dt"] = pd.to_datetime(frame["event_time_utc"], utc=True, errors="coerce")
    for column in ("signal_value", "strategy_return_gross", "strategy_return_net"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["combo_name", "event_time_utc_dt"], kind="mergesort").reset_index(drop=True)


def load_endpoint_attr(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"endpoint attribution not found: {path}")
    frame = pd.read_csv(path)
    for column in ("is_total_events", "oos_total_events", "is_available_events", "oos_available_events", "is_skipped_events", "oos_skipped_events"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    return frame


def apply_signal_mode(frame: pd.DataFrame, signal_mode: str) -> pd.DataFrame:
    out = frame.copy()
    out["signal_mode"] = signal_mode
    out["threshold_abs"] = 0.0 if signal_mode == "no_threshold" else THRESHOLD
    if signal_mode == "threshold_0p5":
        out = out.loc[out["signal_value"].abs() > THRESHOLD].copy()
    return out


def build_mode_trades(grid_trades: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([apply_signal_mode(grid_trades, mode) for mode in SIGNAL_MODES], ignore_index=True)


def max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return float("nan")
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(equity)
    return float(np.min(equity / peaks - 1.0))


def annualized_sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return float("nan")
    sd = float(np.std(returns, ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(np.mean(returns) / sd * math.sqrt(TRADES_PER_YEAR))


def endpoint_counts(endpoint: pd.DataFrame, combo_name: str) -> tuple[int, int, int, int]:
    row = endpoint.loc[endpoint["combo_name"] == combo_name]
    if row.empty:
        return 0, 0, 0, 0
    record = row.iloc[0]
    return (
        int(record["is_total_events"]),
        int(record["oos_total_events"]),
        int(record["is_skipped_events"]),
        int(record["oos_skipped_events"]),
    )


def available_event_count(endpoint: pd.DataFrame, combo_name: str, sample_period: str) -> int:
    row = endpoint.loc[endpoint["combo_name"] == combo_name]
    if row.empty:
        return 0
    column = "is_available_events" if sample_period == "is" else "oos_available_events"
    return int(row.iloc[0][column])


def summarize(
    frame: pd.DataFrame,
    *,
    combo_name: str,
    signal_mode: str,
    sample_mode: str,
    sample_name: str,
    available_events: int,
    endpoint_missing_count: int,
) -> dict[str, object]:
    gross = frame["strategy_return_gross"].to_numpy(dtype=float)
    net = frame["strategy_return_net"].to_numpy(dtype=float)
    count = int(len(frame))
    no_trade_count = max(int(available_events) - count, 0)
    return {
        "sample_mode": sample_mode,
        "signal_mode": signal_mode,
        "threshold_abs": 0.0 if signal_mode == "no_threshold" else THRESHOLD,
        "combo_name": combo_name,
        "btc_lookback": combo_name.split("__", 1)[0],
        "nq_target": combo_name.split("__", 1)[1],
        "sample_name": sample_name,
        "total_events": int(available_events) + int(endpoint_missing_count),
        "trade_count": count,
        "no_trade_count": no_trade_count,
        "endpoint_missing_count": int(endpoint_missing_count),
        "long_count": int((frame["side"] == "long").sum()) if count else 0,
        "short_count": int((frame["side"] == "short").sum()) if count else 0,
        "average_gross_return": float(np.mean(gross)) if count else float("nan"),
        "average_net_return": float(np.mean(net)) if count else float("nan"),
        "cumulative_gross_return": float(np.prod(1.0 + gross) - 1.0) if count else float("nan"),
        "cumulative_net_return": float(np.prod(1.0 + net) - 1.0) if count else float("nan"),
        "net_win_rate": float(np.mean(net > 0.0)) if count else float("nan"),
        "max_drawdown_net": max_drawdown(net),
        "sharpe_net": annualized_sharpe(net),
        "low_sample_warning": str(count < LOW_SAMPLE_WARN_THRESHOLD).lower(),
    }


def split_samples(no_threshold_combo: pd.DataFrame) -> dict[str, set[str]]:
    is_events = no_threshold_combo.loc[no_threshold_combo["sample_period"] == "is"].sort_values(
        "event_time_utc_dt", kind="mergesort"
    )
    oos_events = no_threshold_combo.loc[no_threshold_combo["sample_period"] == "oos"].sort_values(
        "event_time_utc_dt", kind="mergesort"
    )
    half = len(is_events) // 2
    return {
        "first_half": set(is_events.iloc[:half]["event_id"]),
        "second_half": set(is_events.iloc[half:]["event_id"]),
        "oos": set(oos_events["event_id"]),
    }


def build_summary(trades: pd.DataFrame, endpoint: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_mode in SIGNAL_MODES:
        for combo_name in combo_names():
            sub = trades.loc[(trades["signal_mode"] == signal_mode) & (trades["combo_name"] == combo_name)]
            is_total, oos_total, is_endpoint, oos_endpoint = endpoint_counts(endpoint, combo_name)
            if sample_mode == "common":
                endpoint_missing = 0
                available_events = int(sub["event_id"].nunique())
            else:
                endpoint_missing = is_endpoint + oos_endpoint
                available_events = max(is_total + oos_total - endpoint_missing, int(sub["event_id"].nunique()))
            rows.append(
                summarize(
                    sub,
                    combo_name=combo_name,
                    signal_mode=signal_mode,
                    sample_mode=sample_mode,
                    sample_name="full_is_oos",
                    available_events=available_events,
                    endpoint_missing_count=endpoint_missing,
                )
            )
            rows[-1]["first_half_trades"] = int(
                len(sub.loc[(sub["sample_period"] == "is")].iloc[: len(sub.loc[sub["sample_period"] == "is"]) // 2])
            )
            rows[-1]["second_half_trades"] = int(
                len(sub.loc[(sub["sample_period"] == "is")].iloc[len(sub.loc[sub["sample_period"] == "is"]) // 2 :])
            )
            rows[-1]["oos_trades"] = int((sub["sample_period"] == "oos").sum())
    return pd.DataFrame(rows)


def build_subsample(trades: pd.DataFrame, no_threshold_trades: pd.DataFrame, endpoint: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_mode in SIGNAL_MODES:
        for combo_name in combo_names():
            base = no_threshold_trades.loc[no_threshold_trades["combo_name"] == combo_name].copy()
            sample_ids = split_samples(base)
            for sample_name, ids in sample_ids.items():
                sub = trades.loc[
                    (trades["signal_mode"] == signal_mode)
                    & (trades["combo_name"] == combo_name)
                    & (trades["event_id"].isin(ids))
                ].copy()
                if sample_name == "oos":
                    endpoint_missing = endpoint_counts(endpoint, combo_name)[3] if sample_mode == "available" else 0
                else:
                    endpoint_missing = 0
                rows.append(
                    summarize(
                        sub,
                        combo_name=combo_name,
                        signal_mode=signal_mode,
                        sample_mode=sample_mode,
                        sample_name=sample_name,
                        available_events=len(ids),
                        endpoint_missing_count=endpoint_missing,
                    )
                )
                rows[-1]["event_count"] = len(ids)
    return pd.DataFrame(rows)


def build_side(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_mode in SIGNAL_MODES:
        for combo_name in combo_names():
            combo = trades.loc[(trades["signal_mode"] == signal_mode) & (trades["combo_name"] == combo_name)].copy()
            for strategy_name, side in (("long_only", "long"), ("short_only", "short"), ("symmetric", None)):
                sub = combo.copy() if side is None else combo.loc[combo["side"] == side].copy()
                row = summarize(
                    sub,
                    combo_name=combo_name,
                    signal_mode=signal_mode,
                    sample_mode=sample_mode,
                    sample_name=strategy_name,
                    available_events=len(sub),
                    endpoint_missing_count=0,
                )
                row["strategy_name"] = strategy_name
                rows.append(row)
    return pd.DataFrame(rows)


def common_ids_by_mode(no_threshold_trades: pd.DataFrame) -> set[str]:
    sets = [set(sub["event_id"]) for _, sub in no_threshold_trades.groupby("combo_name", sort=False)]
    return set.intersection(*sets) if sets else set()


def build_skip_attribution(mode_trades: pd.DataFrame, endpoint: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combo_name in combo_names():
        is_total, oos_total, is_endpoint, oos_endpoint = endpoint_counts(endpoint, combo_name)
        base = mode_trades.loc[
            (mode_trades["signal_mode"] == "no_threshold") & (mode_trades["combo_name"] == combo_name)
        ]
        threshold = mode_trades.loc[
            (mode_trades["signal_mode"] == "threshold_0p5") & (mode_trades["combo_name"] == combo_name)
        ]
        no_trade_ids = sorted(set(base["event_id"]) - set(threshold["event_id"]))
        no_trade = base.loc[base["event_id"].isin(no_trade_ids)].copy()
        oos_no_trade = no_trade.loc[no_trade["sample_period"] == "oos"]
        rows.append(
            {
                "combo_name": combo_name,
                "btc_lookback": combo_name.split("__", 1)[0],
                "nq_target": combo_name.split("__", 1)[1],
                "is_total_events": is_total,
                "oos_total_events": oos_total,
                "is_endpoint_missing": is_endpoint,
                "oos_endpoint_missing": oos_endpoint,
                "threshold_no_trade_count": int(len(no_trade)),
                "threshold_no_trade_is_count": int((no_trade["sample_period"] == "is").sum()),
                "threshold_no_trade_oos_count": int(len(oos_no_trade)),
                "threshold_no_trade_dates": ";".join(no_trade["event_time_ny"].astype(str).str[:10].tolist()),
                "threshold_no_trade_oos_dates": ";".join(oos_no_trade["event_time_ny"].astype(str).str[:10].tolist()),
                "no_trade_reason": "abs(btc_return) <= 0.005",
                "endpoint_missing_reason": "see grid_3x3_weekend endpoint attribution",
            }
        )
    return pd.DataFrame(rows)


def plot_nav(trades: pd.DataFrame, output_path: Path, *, signal_mode: str, combos: list[str] | None = None) -> None:
    fig, ax = plt.subplots(figsize=(14, 8))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    sub_trades = trades.loc[trades["signal_mode"] == signal_mode].copy()
    if combos is not None:
        sub_trades = sub_trades.loc[sub_trades["combo_name"].isin(combos)].copy()
    for combo_name, sub in sub_trades.groupby("combo_name", sort=False):
        ordered = sub.sort_values("event_time_utc_dt", kind="mergesort").copy()
        ordered["nav_net"] = (1.0 + ordered["strategy_return_net"]).cumprod()
        ax.plot(ordered["event_time_ny_dt"], ordered["nav_net"], linewidth=1.8, label=combo_name)
    ax.axvline(oos_start, linestyle="--", color="black", linewidth=1.2)
    ax.annotate(
        f"OOS start: {OOS_START_LOCAL_DATE}",
        xy=(oos_start, ax.get_ylim()[1]),
        xytext=(8, -24),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "black", "lw": 0.8},
    )
    ax.set_title(f"BTC-NQ 3x3 weekend threshold 0.5%: {signal_mode}")
    ax.set_xlabel("Event time")
    ax.set_ylabel("Cumulative net NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_candidate_comparison(trades: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 8))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    combos = [
        "btc_ret_1h__nq_fwd_1h",
        "btc_ret_1h__nq_fwd_4h",
        "btc_ret_1h__nq_fwd_to_1600_same_day",
    ]
    for signal_mode in SIGNAL_MODES:
        for combo_name in combos:
            sub = trades.loc[(trades["signal_mode"] == signal_mode) & (trades["combo_name"] == combo_name)].copy()
            ordered = sub.sort_values("event_time_utc_dt", kind="mergesort")
            ordered["nav_net"] = (1.0 + ordered["strategy_return_net"]).cumprod()
            style = "-" if signal_mode == "no_threshold" else "--"
            ax.plot(ordered["event_time_ny_dt"], ordered["nav_net"], linestyle=style, linewidth=1.8, label=f"{combo_name} {signal_mode}")
    ax.axvline(oos_start, linestyle="--", color="black", linewidth=1.2)
    ax.annotate(
        f"OOS start: {OOS_START_LOCAL_DATE}",
        xy=(oos_start, ax.get_ylim()[1]),
        xytext=(8, -24),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "black", "lw": 0.8},
    )
    ax.set_title("BTC-NQ threshold 0.5% candidate comparison")
    ax.set_xlabel("Event time")
    ax.set_ylabel("Cumulative net NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not math.isfinite(number):
        return "nan"
    return f"{number:.6%}"


def report_lines(summary: pd.DataFrame, subsample: pd.DataFrame, skip: pd.DataFrame) -> list[str]:
    lines = [
        "# BTC-NQ Weekend 3x3 Threshold 0.5% Report",
        "",
        "Scope: threshold 0.5% comparison only. Event is `monday_0930`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, daily strategy, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.",
        "",
        "## Signal Modes",
        "",
        "- `no_threshold`: old rule, sign(btc_ret).",
        "- `threshold_0p5`: long if btc_ret > 0.005, short if btc_ret < -0.005, otherwise no trade.",
        "",
        "## Threshold Summary",
        "",
    ]
    for combo_name in combo_names():
        row = summary.loc[(summary["signal_mode"] == "threshold_0p5") & (summary["combo_name"] == combo_name)].iloc[0]
        lines.append(
            f"- {combo_name}: trades={row.trade_count}, no_trade={row.no_trade_count}, endpoint_missing={row.endpoint_missing_count}, "
            f"cum net={pct(row.cumulative_net_return)}, net win={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Threshold Subsample OOS", ""])
    for combo_name in combo_names():
        row = subsample.loc[
            (subsample["signal_mode"] == "threshold_0p5")
            & (subsample["combo_name"] == combo_name)
            & (subsample["sample_name"] == "oos")
        ].iloc[0]
        lines.append(
            f"- {combo_name}: OOS trades={row.trade_count}, no_trade={row.no_trade_count}, cum net={pct(row.cumulative_net_return)}, net win={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Skip Attribution", ""])
    for row in skip.itertuples(index=False):
        lines.append(
            f"- {row.combo_name}: threshold no-trade={row.threshold_no_trade_count}, OOS no-trade={row.threshold_no_trade_oos_count}, "
            f"OOS endpoint missing={row.oos_endpoint_missing}."
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "- Stability is judged by first_half, second_half, OOS, OOS trade count, OOS win rate, no-trade count, endpoint missing, and side attribution.",
            "- This is a single threshold test, not a threshold grid search.",
            "",
        ]
    )
    return lines


def main() -> int:
    args = parse_args()
    grid_trades = load_grid_trades(args.grid_trades)
    endpoint = load_endpoint_attr(args.endpoint_attribution)
    mode_trades = build_mode_trades(grid_trades)
    common_ids = common_ids_by_mode(grid_trades)
    common_trades = mode_trades.loc[mode_trades["event_id"].isin(common_ids)].copy()

    summary = build_summary(mode_trades, endpoint, sample_mode="available")
    common_summary = build_summary(common_trades, endpoint, sample_mode="common")
    subsample = pd.concat(
        [
            build_subsample(mode_trades, grid_trades, endpoint, sample_mode="available"),
            build_subsample(common_trades, grid_trades.loc[grid_trades["event_id"].isin(common_ids)].copy(), endpoint, sample_mode="common"),
        ],
        ignore_index=True,
    )
    side = pd.concat(
        [build_side(mode_trades, sample_mode="available"), build_side(common_trades, sample_mode="common")],
        ignore_index=True,
    )
    skip = build_skip_attribution(mode_trades, endpoint)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_dir / "grid_3x3_threshold_summary.csv", index=False)
    common_summary.to_csv(args.output_dir / "grid_3x3_threshold_common_sample_summary.csv", index=False)
    subsample.to_csv(args.output_dir / "grid_3x3_threshold_subsample_stats.csv", index=False)
    side.to_csv(args.output_dir / "grid_3x3_threshold_side_attribution.csv", index=False)
    skip.to_csv(args.output_dir / "grid_3x3_threshold_skip_attribution.csv", index=False)
    mode_trades.to_csv(args.output_dir / "grid_3x3_threshold_event_trades.csv", index=False)
    plot_nav(mode_trades, args.output_dir / "grid_3x3_threshold_nav.png", signal_mode="threshold_0p5")
    plot_candidate_comparison(mode_trades, args.output_dir / "grid_3x3_threshold_candidate_comparison_nav.png")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines(summary, subsample, skip)), encoding="utf-8")

    print(f"Wrote summary: {args.output_dir / 'grid_3x3_threshold_summary.csv'}")
    print(f"Wrote common summary: {args.output_dir / 'grid_3x3_threshold_common_sample_summary.csv'}")
    print(f"Wrote subsample: {args.output_dir / 'grid_3x3_threshold_subsample_stats.csv'}")
    print(f"Wrote side attribution: {args.output_dir / 'grid_3x3_threshold_side_attribution.csv'}")
    print(f"Wrote skip attribution: {args.output_dir / 'grid_3x3_threshold_skip_attribution.csv'}")
    print(f"Wrote event trades: {args.output_dir / 'grid_3x3_threshold_event_trades.csv'}")
    print(f"Wrote NAV charts under: {args.output_dir}")
    print(f"Wrote report: {args.report}")
    print("No daily strategy, continuous NQ, downloads, API calls, or additional thresholds were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
