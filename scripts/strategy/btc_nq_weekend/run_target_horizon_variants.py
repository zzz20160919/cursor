from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_COST_RATE = 0.001
TRADES_PER_YEAR = 52.0
LOW_SAMPLE_WARN_THRESHOLD = 20
OOS_START_LOCAL_DATE = "2026-03-23"

DEFAULT_IS_DATASET = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_20241215_20260316_raw_contract.csv"
DEFAULT_OOS_DATASET = (
    PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_oos_20260317_20260618_raw_contract.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/target_horizon_variants"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/target_horizon_variant_report.md"

DEFAULT_NQ_CONTRACT_PATHS = {
    "NQH5": Path("D:/cursor/202604_stra")
    / "data/processed/databento/nq/NQH5_1m_20241211_20250322_clean.csv",
    "NQM5": Path("D:/cursor/202604_stra")
    / "data/processed/databento/nq/NQM5_1m_20250312_20250621_clean.csv",
    "NQU5": Path("D:/cursor/202604_stra")
    / "data/processed/databento/nq/NQU5_1m_20250611_20250920_clean.csv",
    "NQZ5": Path("D:/cursor/202604_stra")
    / "data/processed/databento/nq/NQZ5_1m_20250910_20251220_clean.csv",
    "NQH6": Path("D:/cursor/202604_stra")
    / "data/processed/databento/nq/NQH6_1m_20251219_20260320_clean.csv",
    "NQM6": PROJECT_ROOT / "data/processed/databento/nq/NQM6_1m_20260320_20260620_clean.csv",
    "NQU6": PROJECT_ROOT / "data/processed/databento/nq/NQU6_1m_20260620_latest_clean.csv",
}

TARGET_VARIANTS = (
    ("nq_fwd_4h", "nq_fwd_4h", "existing old grid: 4h after Monday 09:30 NY"),
    (
        "nq_fwd_to_1600_same_day",
        "nq_fwd_to_1600_same_day",
        "new target: Monday 09:30 NY to exact Monday 16:00 NY 1m bar close",
    ),
    ("nq_fwd_1d", "nq_fwd_1d", "old baseline target"),
    ("nq_fwd_2d", "nq_fwd_2d", "optional reference target from old grid"),
)


@dataclass(frozen=True)
class TargetResult:
    trades: pd.DataFrame
    skipped: dict[str, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-NQ target horizon variant test.")
    parser.add_argument("--is-dataset", type=Path, default=DEFAULT_IS_DATASET)
    parser.add_argument("--oos-dataset", type=Path, default=DEFAULT_OOS_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def load_events(path: Path, sample_period: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"event dataset not found: {path}")
    frame = pd.read_csv(path)
    frame = frame.loc[frame["event_name"] == "monday_0930"].copy()
    frame["sample_period"] = sample_period
    frame["event_time_ny_dt"] = pd.to_datetime(frame["event_time_ny"], utc=True, errors="coerce").dt.tz_convert(
        "America/New_York"
    )
    frame["event_time_utc_dt"] = pd.to_datetime(frame["event_time_utc"], utc=True, errors="coerce")
    frame["btc_ret_4h"] = pd.to_numeric(frame["btc_ret_4h"], errors="coerce")
    frame["nq_px_t0"] = pd.to_numeric(frame["nq_px_t0"], errors="coerce")
    return frame.sort_values("event_time_utc_dt", kind="mergesort").reset_index(drop=True)


def detect_timestamp(frame: pd.DataFrame) -> pd.Series:
    for column in ("timestamp", "ts_event_utc", "ts_event", "open_time_utc", "open_time"):
        if column not in frame.columns:
            continue
        values = frame[column]
        if pd.api.types.is_numeric_dtype(values):
            numeric = pd.to_numeric(values, errors="coerce")
            unit = "ms" if float(numeric.dropna().max()) >= 1e11 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(values, utc=True, errors="coerce")
    raise ValueError(f"could not detect timestamp column from {list(frame.columns)}")


def load_nq_contract_closes() -> dict[str, pd.Series]:
    closes: dict[str, pd.Series] = {}
    for symbol, path in DEFAULT_NQ_CONTRACT_PATHS.items():
        if not path.exists():
            raise FileNotFoundError(f"NQ contract file not found: {symbol} {path}")
        frame = pd.read_csv(path)
        timestamps = detect_timestamp(frame)
        close = pd.to_numeric(frame["close"], errors="coerce")
        out = pd.DataFrame({"timestamp_utc": timestamps, "close": close}).dropna()
        out = out.sort_values("timestamp_utc", kind="mergesort")
        closes[symbol] = out.set_index("timestamp_utc")["close"].astype(float)
    return closes


def lookup(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


def same_day_1600_target(row: pd.Series, closes: dict[str, pd.Series]) -> tuple[float, str, float | None]:
    active_contract = str(row["active_contract"])
    event_time_ny = pd.Timestamp(row["event_time_ny_dt"])
    target_local = pd.Timestamp.combine(event_time_ny.date(), pd.Timestamp("16:00").time()).tz_localize(NEW_YORK)
    target_utc = target_local.tz_convert("UTC")
    start_px = float(row["nq_px_t0"]) if pd.notna(row["nq_px_t0"]) else float("nan")
    end_px = lookup(closes[active_contract], target_utc) if active_contract in closes else None
    if not math.isfinite(start_px) or start_px <= 0 or end_px is None:
        return float("nan"), target_utc.isoformat(), end_px
    return float(math.log(end_px / start_px)), target_utc.isoformat(), end_px


def max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return float("nan")
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0
    return float(np.min(drawdowns))


def annualized_sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return float("nan")
    sd = float(np.std(returns, ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(np.mean(returns) / sd * math.sqrt(TRADES_PER_YEAR))


def summarize_returns(frame: pd.DataFrame, *, target_variant: str, sample_name: str) -> dict[str, object]:
    gross = frame["strategy_return_gross"].to_numpy(dtype=float)
    net = frame["strategy_return_net"].to_numpy(dtype=float)
    count = int(len(frame))
    return {
        "target_variant": target_variant,
        "sample_name": sample_name,
        "event_count": count,
        "trade_count": count,
        "long_count": int((frame["side"] == "long").sum()),
        "short_count": int((frame["side"] == "short").sum()),
        "average_gross_return": float(np.mean(gross)) if count else float("nan"),
        "average_net_return": float(np.mean(net)) if count else float("nan"),
        "median_gross_return": float(np.median(gross)) if count else float("nan"),
        "median_net_return": float(np.median(net)) if count else float("nan"),
        "gross_return_sum": float(np.sum(gross)) if count else float("nan"),
        "net_return_sum": float(np.sum(net)) if count else float("nan"),
        "cumulative_gross_return": float(np.prod(1.0 + gross) - 1.0) if count else float("nan"),
        "cumulative_net_return": float(np.prod(1.0 + net) - 1.0) if count else float("nan"),
        "net_win_rate": float(np.mean(net > 0.0)) if count else float("nan"),
        "gross_win_rate": float(np.mean(gross > 0.0)) if count else float("nan"),
        "max_drawdown_net": max_drawdown(net),
        "sharpe_net": annualized_sharpe(net),
        "low_sample_warning": str(count < LOW_SAMPLE_WARN_THRESHOLD).lower(),
    }


def build_trades_for_target(
    events: pd.DataFrame,
    *,
    target_variant: str,
    column_name: str,
    target_description: str,
    closes: dict[str, pd.Series],
) -> TargetResult:
    rows: list[dict[str, object]] = []
    skipped: dict[str, int] = {}
    for row in events.itertuples(index=False):
        row_data = row._asdict()
        event_time_ny = row_data["event_time_ny"]
        signal = float(row_data["btc_ret_4h"]) if pd.notna(row_data["btc_ret_4h"]) else float("nan")
        if column_name == "nq_fwd_to_1600_same_day":
            target_log, target_end_utc, target_end_px = same_day_1600_target(pd.Series(row_data), closes)
        else:
            target_log = float(row_data.get(column_name)) if pd.notna(row_data.get(column_name)) else float("nan")
            target_end_utc = str(row_data.get(f"{column_name}_end_utc") or "")
            target_end_px = row_data.get(f"nq_px_end_{column_name.removeprefix('nq_fwd_')}")

        if not math.isfinite(signal):
            skipped["missing_signal"] = skipped.get("missing_signal", 0) + 1
            continue
        if signal == 0.0:
            skipped["zero_signal"] = skipped.get("zero_signal", 0) + 1
            continue
        if not math.isfinite(target_log):
            skipped[f"missing_{column_name}"] = skipped.get(f"missing_{column_name}", 0) + 1
            continue

        target_simple = math.exp(target_log) - 1.0
        side = "long" if signal > 0 else "short"
        gross = target_simple if side == "long" else -target_simple
        rows.append(
            {
                "target_variant": target_variant,
                "target_description": target_description,
                "sample_period": row_data["sample_period"],
                "event_sequence": int(row_data["event_sequence"]),
                "event_id": row_data["event_id"],
                "event_name": "monday_0930",
                "event_time_ny": event_time_ny,
                "event_time_utc": row_data["event_time_utc"],
                "active_contract": row_data["active_contract"],
                "signal_col": "btc_ret_4h",
                "target_col": target_variant,
                "signal_value": signal,
                "target_log_return": target_log,
                "target_simple_return": target_simple,
                "target_end_utc": target_end_utc,
                "target_end_px": target_end_px,
                "timestamp_convention": (
                    "exact 1m bar at Monday 16:00 America/New_York"
                    if target_variant == "nq_fwd_to_1600_same_day"
                    else "existing event dataset endpoint"
                ),
                "cost_rate": DEFAULT_COST_RATE,
                "side": side,
                "strategy_return_gross": gross,
                "strategy_return_net": gross - DEFAULT_COST_RATE,
                "benchmark_return_gross": target_simple,
                "benchmark_return_net": target_simple - DEFAULT_COST_RATE,
            }
        )
    return TargetResult(pd.DataFrame(rows), skipped)


def build_all_results(is_events: pd.DataFrame, oos_events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    closes = load_nq_contract_closes()
    combined_events = pd.concat([is_events, oos_events], ignore_index=True)
    all_trades: list[pd.DataFrame] = []
    skipped_by_target: dict[str, dict[str, int]] = {}
    for target_variant, column_name, target_description in TARGET_VARIANTS:
        result = build_trades_for_target(
            combined_events,
            target_variant=target_variant,
            column_name=column_name,
            target_description=target_description,
            closes=closes,
        )
        all_trades.append(result.trades)
        skipped_by_target[target_variant] = result.skipped
    return pd.concat(all_trades, ignore_index=True), skipped_by_target


def build_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        is_sub = sub.loc[sub["sample_period"] == "is"]
        oos_sub = sub.loc[sub["sample_period"] == "oos"]
        row = summarize_returns(sub, target_variant=target_variant, sample_name="full_is_oos")
        row["total_events"] = row["event_count"]
        row["is_events"] = int(len(is_sub))
        row["oos_events"] = int(len(oos_sub))
        rows.append(row)
    return pd.DataFrame(rows)


def build_subsample_stats(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        is_sub = sub.loc[sub["sample_period"] == "is"].sort_values("event_time_utc", kind="mergesort")
        half = len(is_sub) // 2
        for sample_name, sample in (
            ("first_half", is_sub.iloc[:half].copy()),
            ("second_half", is_sub.iloc[half:].copy()),
            ("oos", sub.loc[sub["sample_period"] == "oos"].copy()),
        ):
            rows.append(summarize_returns(sample, target_variant=target_variant, sample_name=sample_name))
    return pd.DataFrame(rows)


def build_side_attribution(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        for strategy_name, side in (("long_only", "long"), ("short_only", "short"), ("symmetric", None)):
            side_sub = sub.copy() if side is None else sub.loc[sub["side"] == side].copy()
            row = summarize_returns(side_sub, target_variant=target_variant, sample_name=strategy_name)
            row["strategy_name"] = strategy_name
            rows.append(row)
    return pd.DataFrame(rows)


def build_nav_chart(trades: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 7))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        ordered = sub.sort_values("event_time_utc", kind="mergesort").copy()
        ordered["event_time_dt"] = pd.to_datetime(ordered["event_time_ny"], utc=True).dt.tz_convert(
            "America/New_York"
        )
        ordered["nav_net"] = (1.0 + ordered["strategy_return_net"]).cumprod()
        ax.plot(ordered["event_time_dt"], ordered["nav_net"], linewidth=2.0, label=target_variant)
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
    ax.set_title("BTC-NQ target horizon variants: monday_0930 + btc_ret_4h")
    ax.set_xlabel("Event time")
    ax.set_ylabel("Cumulative net NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
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


def report_lines(summary: pd.DataFrame, subsample: pd.DataFrame, side: pd.DataFrame, skipped: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "# BTC-NQ Target Horizon Variant Report",
        "",
        "Scope: BTC-NQ Weekend target horizon test only. Event, BTC feature, signal rule, cost, OOS definition, and NQ mode remain unchanged. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC lookback optimization, BTC threshold optimization, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.",
        "",
        "## Tested Targets",
        "",
        "- `nq_fwd_4h`: existing old grid, 4h after Monday 09:30 NY.",
        "- `nq_fwd_to_1600_same_day`: exact 1m bar at Monday 16:00 America/New_York on the same active raw NQ contract.",
        "- `nq_fwd_1d`: old locked baseline target.",
        "- `nq_fwd_2d`: optional old-grid reference only.",
        "",
        "## Full IS + OOS Summary",
        "",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"- {row.target_variant}: total={row.total_events}, IS={row.is_events}, OOS={row.oos_events}, "
            f"cumulative net={pct(row.cumulative_net_return)}, average net={pct(row.average_net_return)}, "
            f"net win rate={pct(row.net_win_rate)}, max DD={pct(row.max_drawdown_net)}, sharpe={row.sharpe_net:.3f}."
        )
    lines.extend(["", "## Subsample Stability", ""])
    for target_variant in summary["target_variant"].tolist():
        lines.append(f"### {target_variant}")
        sub = subsample.loc[subsample["target_variant"] == target_variant]
        for row in sub.itertuples(index=False):
            lines.append(
                f"- {row.sample_name}: events={row.event_count}, cumulative net={pct(row.cumulative_net_return)}, "
                f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}, "
                f"long/short={row.long_count}/{row.short_count}, low_sample_warning={row.low_sample_warning}."
            )
        lines.append("")
    lines.extend(["## Side Attribution", ""])
    for target_variant in summary["target_variant"].tolist():
        lines.append(f"### {target_variant}")
        side_sub = side.loc[side["target_variant"] == target_variant]
        for row in side_sub.itertuples(index=False):
            lines.append(
                f"- {row.strategy_name}: trades={row.trade_count}, cumulative net={pct(row.cumulative_net_return)}, "
                f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}."
            )
        lines.append("")
    lines.extend(
        [
            "## Skips and Timestamp Convention",
            "",
            f"- Skipped events by target: `{skipped}`",
            "- `nq_fwd_to_1600_same_day` uses the exact 1m bar timestamp for Monday 16:00 America/New_York, converted to UTC, and does not cross-fill across contracts.",
            "",
            "## Conclusion",
            "",
            "- A target is considered more interesting only if first_half, second_half, and OOS are all acceptable; OOS-only strength is not enough.",
            "- Based on this run, review the stability table before promoting any horizon to the next BTC lookback test.",
            "",
        ]
    )
    return lines


def main() -> int:
    args = parse_args()
    is_events = load_events(args.is_dataset, "is")
    oos_events = load_events(args.oos_dataset, "oos")
    trades, skipped = build_all_results(is_events, oos_events)
    summary = build_summary(trades)
    subsample = build_subsample_stats(trades)
    side = build_side_attribution(trades)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    trades_path = args.output_dir / "target_horizon_event_trades.csv"
    summary_path = args.output_dir / "target_horizon_summary.csv"
    subsample_path = args.output_dir / "target_horizon_subsample_stats.csv"
    side_path = args.output_dir / "target_horizon_side_attribution.csv"
    nav_path = args.output_dir / "target_horizon_nav.png"

    trades.to_csv(trades_path, index=False)
    summary.to_csv(summary_path, index=False)
    subsample.to_csv(subsample_path, index=False)
    side.to_csv(side_path, index=False)
    build_nav_chart(trades, nav_path)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines(summary, subsample, side, skipped)), encoding="utf-8")

    print(f"Wrote event trades: {trades_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote subsample stats: {subsample_path}")
    print(f"Wrote side attribution: {side_path}")
    print(f"Wrote NAV chart: {nav_path}")
    print(f"Wrote report: {args.report}")
    print("No BTC lookback optimization, BTC threshold optimization, continuous NQ, downloads, or API calls were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
