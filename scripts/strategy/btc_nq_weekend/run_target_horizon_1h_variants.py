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
UTC = ZoneInfo("UTC")
DEFAULT_COST_RATE = 0.001
TRADES_PER_YEAR = 52.0
LOW_SAMPLE_WARN_THRESHOLD = 20
OOS_START_LOCAL_DATE = "2026-03-23"

DEFAULT_IS_DATASET = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_20241215_20260316_raw_contract.csv"
DEFAULT_OOS_DATASET = (
    PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_oos_20260317_20260618_raw_contract.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/target_horizon_variants"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/target_horizon_1h_variant_report.md"

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
    ("nq_fwd_1h", "nq_fwd_1h", "existing old grid: 1h after Monday 09:30 NY"),
    ("nq_fwd_4h", "nq_fwd_4h", "existing old grid: 4h after Monday 09:30 NY"),
    (
        "nq_fwd_to_1600_same_day",
        "nq_fwd_to_1600_same_day",
        "new target: Monday 09:30 NY to exact Monday 16:00 NY 1m bar close",
    ),
    ("nq_fwd_1d", "nq_fwd_1d", "old baseline target"),
    ("nq_fwd_2d", "nq_fwd_2d", "optional old-grid reference target"),
)


@dataclass(frozen=True)
class ContractCoverage:
    first_utc: pd.Timestamp
    last_utc: pd.Timestamp
    close: pd.Series


@dataclass(frozen=True)
class TargetBuild:
    trades: pd.DataFrame
    missing: pd.DataFrame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-NQ target horizon variants with nq_fwd_1h.")
    parser.add_argument("--is-dataset", type=Path, default=DEFAULT_IS_DATASET)
    parser.add_argument("--oos-dataset", type=Path, default=DEFAULT_OOS_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


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


def load_contracts() -> dict[str, ContractCoverage]:
    contracts: dict[str, ContractCoverage] = {}
    for symbol, path in DEFAULT_NQ_CONTRACT_PATHS.items():
        if not path.exists():
            raise FileNotFoundError(f"NQ contract file not found: {symbol} {path}")
        frame = pd.read_csv(path)
        timestamps = detect_timestamp(frame)
        close = pd.to_numeric(frame["close"], errors="coerce")
        out = pd.DataFrame({"timestamp_utc": timestamps, "close": close}).dropna()
        out = out.sort_values("timestamp_utc", kind="mergesort")
        series = out.set_index("timestamp_utc")["close"].astype(float)
        contracts[symbol] = ContractCoverage(first_utc=series.index.min(), last_utc=series.index.max(), close=series)
    return contracts


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
    for target, _, _ in TARGET_VARIANTS:
        if target in frame.columns:
            frame[target] = pd.to_numeric(frame[target], errors="coerce")
    return frame.sort_values("event_time_utc_dt", kind="mergesort").reset_index(drop=True)


def lookup(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


def target_endpoint(row: pd.Series, target_variant: str) -> tuple[str, pd.Timestamp | None]:
    if target_variant == "nq_fwd_to_1600_same_day":
        event_time_ny = pd.Timestamp(row["event_time_ny_dt"])
        target_local = pd.Timestamp.combine(event_time_ny.date(), pd.Timestamp("16:00").time()).tz_localize(NEW_YORK)
        return "exact Monday 16:00 America/New_York 1m bar", target_local.tz_convert(UTC)
    end_col = f"{target_variant}_end_utc"
    if end_col not in row or pd.isna(row[end_col]):
        return "existing event dataset endpoint", None
    return "existing event dataset endpoint", pd.to_datetime(row[end_col], utc=True, errors="coerce")


def target_log_return(
    row: pd.Series,
    *,
    target_variant: str,
    contracts: dict[str, ContractCoverage],
) -> tuple[float, pd.Timestamp | None, float | None, str]:
    convention, end_utc = target_endpoint(row, target_variant)
    if target_variant != "nq_fwd_to_1600_same_day":
        value = row.get(target_variant)
        if pd.notna(value):
            end_px_col = f"nq_px_end_{target_variant.removeprefix('nq_fwd_')}"
            end_px = row.get(end_px_col)
            return float(value), end_utc, float(end_px) if pd.notna(end_px) else None, convention

    active = str(row["active_contract"])
    start_px = float(row["nq_px_t0"]) if pd.notna(row["nq_px_t0"]) else float("nan")
    if active not in contracts or end_utc is None or not math.isfinite(start_px) or start_px <= 0:
        return float("nan"), end_utc, None, convention
    end_px = lookup(contracts[active].close, end_utc)
    if end_px is None:
        return float("nan"), end_utc, None, convention
    return float(math.log(end_px / start_px)), end_utc, end_px, convention


def classify_missing(
    row: pd.Series,
    *,
    target_variant: str,
    target_end_utc: pd.Timestamp | None,
    contracts: dict[str, ContractCoverage],
) -> dict[str, object]:
    active = str(row["active_contract"])
    event_time_ny = str(row["event_time_ny"])
    event_date = pd.Timestamp(row["event_time_ny_dt"]).strftime("%Y-%m-%d")
    reason = "unknown"
    endpoint_missing = True
    contract_coverage_issue = False
    holiday_session_or_cutoff = False

    if active not in contracts:
        reason = "missing_active_contract_series"
        contract_coverage_issue = True
    elif target_end_utc is None or pd.isna(target_end_utc):
        reason = "missing_target_endpoint_timestamp"
    else:
        coverage = contracts[active]
        if target_end_utc < coverage.first_utc or target_end_utc > coverage.last_utc:
            reason = "target_endpoint_outside_active_contract_coverage_or_data_cutoff"
            contract_coverage_issue = True
            holiday_session_or_cutoff = True
        else:
            reason = "target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap"
            holiday_session_or_cutoff = True

    return {
        "target_variant": target_variant,
        "sample_period": row["sample_period"],
        "event_id": row["event_id"],
        "event_date": event_date,
        "event_time_ny": event_time_ny,
        "active_contract": active,
        "target_end_utc": target_end_utc.isoformat() if target_end_utc is not None and pd.notna(target_end_utc) else "",
        "skipped_reason": reason,
        "endpoint_missing": endpoint_missing,
        "nq_contract_coverage_issue": contract_coverage_issue,
        "holiday_session_or_data_cutoff": holiday_session_or_cutoff,
    }


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


def build_target(
    events: pd.DataFrame,
    *,
    target_variant: str,
    target_description: str,
    contracts: dict[str, ContractCoverage],
) -> TargetBuild:
    rows: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        signal = float(event["btc_ret_4h"]) if pd.notna(event["btc_ret_4h"]) else float("nan")
        target_log, end_utc, end_px, convention = target_log_return(
            event, target_variant=target_variant, contracts=contracts
        )
        if not math.isfinite(signal) or signal == 0.0 or not math.isfinite(target_log):
            missing_rows.append(classify_missing(event, target_variant=target_variant, target_end_utc=end_utc, contracts=contracts))
            continue
        target_simple = math.exp(target_log) - 1.0
        side = "long" if signal > 0 else "short"
        gross = target_simple if side == "long" else -target_simple
        rows.append(
            {
                "target_variant": target_variant,
                "target_description": target_description,
                "sample_period": event["sample_period"],
                "event_sequence": int(event["event_sequence"]),
                "event_id": event["event_id"],
                "event_name": "monday_0930",
                "event_time_ny": event["event_time_ny"],
                "event_time_utc": event["event_time_utc"],
                "active_contract": event["active_contract"],
                "signal_col": "btc_ret_4h",
                "target_col": target_variant,
                "signal_value": signal,
                "target_log_return": target_log,
                "target_simple_return": target_simple,
                "target_end_utc": end_utc.isoformat() if end_utc is not None and pd.notna(end_utc) else "",
                "target_end_px": end_px,
                "timestamp_convention": convention,
                "cost_rate": DEFAULT_COST_RATE,
                "side": side,
                "strategy_return_gross": gross,
                "strategy_return_net": gross - DEFAULT_COST_RATE,
                "benchmark_return_gross": target_simple,
                "benchmark_return_net": target_simple - DEFAULT_COST_RATE,
            }
        )
    return TargetBuild(pd.DataFrame(rows), pd.DataFrame(missing_rows))


def summarize(frame: pd.DataFrame, *, target_variant: str, sample_mode: str, sample_name: str) -> dict[str, object]:
    gross = frame["strategy_return_gross"].to_numpy(dtype=float)
    net = frame["strategy_return_net"].to_numpy(dtype=float)
    count = int(len(frame))
    is_count = int((frame["sample_period"] == "is").sum()) if count else 0
    oos_count = int((frame["sample_period"] == "oos").sum()) if count else 0
    is_events = frame.loc[frame["sample_period"] == "is"].sort_values("event_time_utc", kind="mergesort")
    half = len(is_events) // 2
    return {
        "sample_mode": sample_mode,
        "target_variant": target_variant,
        "sample_name": sample_name,
        "total_events": count,
        "event_count": count,
        "trade_count": count,
        "is_events": is_count,
        "oos_events": oos_count,
        "first_half_events": half if sample_name == "full_is_oos" else "",
        "second_half_events": len(is_events) - half if sample_name == "full_is_oos" else "",
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


def common_event_ids(trades: pd.DataFrame) -> set[str]:
    sets = [set(sub["event_id"]) for _, sub in trades.groupby("target_variant", sort=False)]
    if not sets:
        return set()
    return set.intersection(*sets)


def build_summary(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        rows.append(summarize(sub, target_variant=target_variant, sample_mode=sample_mode, sample_name="full_is_oos"))
    return pd.DataFrame(rows)


def build_subsample(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        is_sub = sub.loc[sub["sample_period"] == "is"].sort_values("event_time_utc", kind="mergesort")
        oos_sub = sub.loc[sub["sample_period"] == "oos"].sort_values("event_time_utc", kind="mergesort")
        half = len(is_sub) // 2
        for sample_name, sample in (
            ("first_half", is_sub.iloc[:half].copy()),
            ("second_half", is_sub.iloc[half:].copy()),
            ("oos", oos_sub.copy()),
        ):
            rows.append(summarize(sample, target_variant=target_variant, sample_mode=sample_mode, sample_name=sample_name))
    return pd.DataFrame(rows)


def build_side(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        for strategy_name, side in (("long_only", "long"), ("short_only", "short"), ("symmetric", None)):
            side_sub = sub.copy() if side is None else sub.loc[sub["side"] == side].copy()
            row = summarize(side_sub, target_variant=target_variant, sample_mode=sample_mode, sample_name=strategy_name)
            row["strategy_name"] = strategy_name
            rows.append(row)
    return pd.DataFrame(rows)


def missing_summary(all_events: pd.DataFrame, missing: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    total_by_sample = all_events.groupby("sample_period").size().to_dict()
    available = trades.groupby(["target_variant", "sample_period"]).size().to_dict()
    rows: list[dict[str, object]] = []
    for target_variant, target_missing in missing.groupby("target_variant", sort=False):
        is_missing = target_missing.loc[target_missing["sample_period"] == "is"]
        oos_missing = target_missing.loc[target_missing["sample_period"] == "oos"]
        reasons = target_missing["skipped_reason"].value_counts().to_dict()
        rows.append(
            {
                "target_variant": target_variant,
                "is_total_events": int(total_by_sample.get("is", 0)),
                "oos_total_events": int(total_by_sample.get("oos", 0)),
                "is_available_events": int(available.get((target_variant, "is"), 0)),
                "oos_available_events": int(available.get((target_variant, "oos"), 0)),
                "skipped_events": int(len(target_missing)),
                "is_skipped_events": int(len(is_missing)),
                "oos_skipped_events": int(len(oos_missing)),
                "skipped_event_dates": ";".join(target_missing["event_date"].astype(str).tolist()),
                "oos_skipped_event_dates": ";".join(oos_missing["event_date"].astype(str).tolist()),
                "skipped_reasons": str(reasons),
                "endpoint_missing": bool(target_missing["endpoint_missing"].any()),
                "nq_contract_coverage_issue": bool(target_missing["nq_contract_coverage_issue"].any()),
                "holiday_session_or_data_cutoff": bool(target_missing["holiday_session_or_data_cutoff"].any()),
            }
        )
    for target_variant in [target[0] for target in TARGET_VARIANTS]:
        if target_variant not in set(missing["target_variant"]) if not missing.empty else True:
            rows.append(
                {
                    "target_variant": target_variant,
                    "is_total_events": int(total_by_sample.get("is", 0)),
                    "oos_total_events": int(total_by_sample.get("oos", 0)),
                    "is_available_events": int(available.get((target_variant, "is"), 0)),
                    "oos_available_events": int(available.get((target_variant, "oos"), 0)),
                    "skipped_events": 0,
                    "is_skipped_events": 0,
                    "oos_skipped_events": 0,
                    "skipped_event_dates": "",
                    "oos_skipped_event_dates": "",
                    "skipped_reasons": "{}",
                    "endpoint_missing": False,
                    "nq_contract_coverage_issue": False,
                    "holiday_session_or_data_cutoff": False,
                }
            )
    return pd.DataFrame(rows).sort_values("target_variant", kind="mergesort")


def plot_nav(trades: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 7))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    for target_variant, sub in trades.groupby("target_variant", sort=False):
        if target_variant == "nq_fwd_2d":
            continue
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
    ax.set_title("BTC-NQ target horizon variants with 1h: monday_0930 + btc_ret_4h")
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


def report_lines(
    *,
    available_summary: pd.DataFrame,
    common_summary: pd.DataFrame,
    available_subsample: pd.DataFrame,
    common_subsample: pd.DataFrame,
    available_side: pd.DataFrame,
    endpoint: pd.DataFrame,
) -> list[str]:
    lines = [
        "# BTC-NQ Target Horizon 1h Variant Report",
        "",
        "Scope: BTC-NQ Weekend NQ target horizon test only. Event, BTC feature, signal rule, cost, OOS definition, and NQ mode remain unchanged. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC lookback optimization, BTC threshold optimization, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.",
        "",
        "## Endpoint Convention",
        "",
        "- `nq_fwd_1h`, `nq_fwd_4h`, `nq_fwd_1d`, and `nq_fwd_2d` use existing old-grid event dataset endpoints.",
        "- `nq_fwd_to_1600_same_day` uses exact Monday 16:00 America/New_York 1m bar on the same active raw NQ contract.",
        "- No nearest / previous / next fill is used; missing endpoint means skipped trade for that target.",
        "",
        "## Available-Sample Summary",
        "",
    ]
    for row in available_summary.itertuples(index=False):
        lines.append(
            f"- {row.target_variant}: total={row.total_events}, IS={row.is_events}, OOS={row.oos_events}, "
            f"cumulative net={pct(row.cumulative_net_return)}, OOS available shown in subsample table."
        )
    lines.extend(["", "## Common-Sample Summary", ""])
    for row in common_summary.itertuples(index=False):
        lines.append(
            f"- {row.target_variant}: total={row.total_events}, IS={row.is_events}, OOS={row.oos_events}, "
            f"cumulative net={pct(row.cumulative_net_return)}, average net={pct(row.average_net_return)}, "
            f"net win rate={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Available-Sample Subsample Stability", ""])
    for target_variant in available_summary["target_variant"].tolist():
        lines.append(f"### {target_variant}")
        sub = available_subsample.loc[available_subsample["target_variant"] == target_variant]
        for row in sub.itertuples(index=False):
            lines.append(
                f"- {row.sample_name}: events={row.event_count}, cumulative net={pct(row.cumulative_net_return)}, "
                f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}, "
                f"long/short={row.long_count}/{row.short_count}, low_sample_warning={row.low_sample_warning}."
            )
        lines.append("")
    lines.extend(["## Common-Sample Subsample Stability", ""])
    for target_variant in common_summary["target_variant"].tolist():
        lines.append(f"### {target_variant}")
        sub = common_subsample.loc[common_subsample["target_variant"] == target_variant]
        for row in sub.itertuples(index=False):
            lines.append(
                f"- {row.sample_name}: events={row.event_count}, cumulative net={pct(row.cumulative_net_return)}, "
                f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}, "
                f"long/short={row.long_count}/{row.short_count}, low_sample_warning={row.low_sample_warning}."
            )
        lines.append("")
    lines.extend(["## Available-Sample Side Attribution", ""])
    for target_variant in available_summary["target_variant"].tolist():
        lines.append(f"### {target_variant}")
        side_sub = available_side.loc[available_side["target_variant"] == target_variant]
        for row in side_sub.itertuples(index=False):
            lines.append(
                f"- {row.strategy_name}: trades={row.trade_count}, cumulative net={pct(row.cumulative_net_return)}, "
                f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}."
            )
        lines.append("")
    lines.extend(["## Endpoint Missing Attribution", ""])
    for row in endpoint.itertuples(index=False):
        lines.append(
            f"- {row.target_variant}: IS available={row.is_available_events}, OOS available={row.oos_available_events}, "
            f"skipped={row.skipped_events}, OOS skipped dates={row.oos_skipped_event_dates or 'none'}, "
            f"reason={row.skipped_reasons}."
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "- A target is only interesting if first_half, second_half, and OOS are all acceptable.",
            "- `nq_fwd_1h` should be compared against `nq_fwd_1d` using both available-sample and common-sample outputs before any BTC lookback test.",
            "",
        ]
    )
    return lines


def main() -> int:
    args = parse_args()
    contracts = load_contracts()
    is_events = load_events(args.is_dataset, "is")
    oos_events = load_events(args.oos_dataset, "oos")
    all_events = pd.concat([is_events, oos_events], ignore_index=True)

    trades_parts: list[pd.DataFrame] = []
    missing_parts: list[pd.DataFrame] = []
    for target_variant, _, description in TARGET_VARIANTS:
        built = build_target(all_events, target_variant=target_variant, target_description=description, contracts=contracts)
        trades_parts.append(built.trades)
        missing_parts.append(built.missing)
    available_trades = pd.concat(trades_parts, ignore_index=True)
    missing = pd.concat(missing_parts, ignore_index=True) if missing_parts else pd.DataFrame()
    common_ids = common_event_ids(available_trades)
    common_trades = available_trades.loc[available_trades["event_id"].isin(common_ids)].copy()

    available_summary = build_summary(available_trades, sample_mode="available")
    common_summary = build_summary(common_trades, sample_mode="common")
    available_subsample = build_subsample(available_trades, sample_mode="available")
    common_subsample = build_subsample(common_trades, sample_mode="common")
    available_side = build_side(available_trades, sample_mode="available")
    common_side = build_side(common_trades, sample_mode="common")
    endpoint = missing_summary(all_events, missing, available_trades)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    available_summary.to_csv(args.output_dir / "target_horizon_summary_with_1h.csv", index=False)
    common_summary.to_csv(args.output_dir / "target_horizon_common_sample_summary.csv", index=False)
    pd.concat([available_subsample, common_subsample], ignore_index=True).to_csv(
        args.output_dir / "target_horizon_subsample_stats_with_1h.csv", index=False
    )
    pd.concat([available_side, common_side], ignore_index=True).to_csv(
        args.output_dir / "target_horizon_side_attribution_with_1h.csv", index=False
    )
    endpoint.to_csv(args.output_dir / "target_horizon_endpoint_missing_attribution.csv", index=False)
    available_trades.to_csv(args.output_dir / "target_horizon_event_trades_with_1h.csv", index=False)
    plot_nav(available_trades, args.output_dir / "target_horizon_nav_with_1h.png")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "\n".join(
            report_lines(
                available_summary=available_summary,
                common_summary=common_summary,
                available_subsample=available_subsample,
                common_subsample=common_subsample,
                available_side=available_side,
                endpoint=endpoint,
            )
        ),
        encoding="utf-8",
    )

    print(f"Wrote available summary: {args.output_dir / 'target_horizon_summary_with_1h.csv'}")
    print(f"Wrote common summary: {args.output_dir / 'target_horizon_common_sample_summary.csv'}")
    print(f"Wrote subsample stats: {args.output_dir / 'target_horizon_subsample_stats_with_1h.csv'}")
    print(f"Wrote side attribution: {args.output_dir / 'target_horizon_side_attribution_with_1h.csv'}")
    print(f"Wrote endpoint attribution: {args.output_dir / 'target_horizon_endpoint_missing_attribution.csv'}")
    print(f"Wrote event trades: {args.output_dir / 'target_horizon_event_trades_with_1h.csv'}")
    print(f"Wrote NAV chart: {args.output_dir / 'target_horizon_nav_with_1h.png'}")
    print(f"Wrote report: {args.report}")
    print("No BTC lookback optimization, BTC threshold optimization, continuous NQ, downloads, or API calls were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
