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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/grid_3x3_weekend"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/grid_3x3_weekend_report.md"

DEFAULT_BTC_INPUTS = (
    Path("D:/cursor/202604_stra")
    / "data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_2020_2026.parquet",
    PROJECT_ROOT
    / "data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_20260401_20260601.parquet",
    PROJECT_ROOT
    / "data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_20260601_20260618_daily.parquet",
)

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

BTC_LOOKBACKS = ("btc_ret_1h", "btc_ret_4h", "btc_ret_12h")
NQ_TARGETS = ("nq_fwd_1h", "nq_fwd_4h", "nq_fwd_to_1600_same_day")


@dataclass(frozen=True)
class ContractCoverage:
    first_utc: pd.Timestamp
    last_utc: pd.Timestamp
    close: pd.Series


@dataclass(frozen=True)
class ComboBuild:
    trades: pd.DataFrame
    missing: pd.DataFrame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-NQ old weekly 3x3 grid test.")
    parser.add_argument("--is-dataset", type=Path, default=DEFAULT_IS_DATASET)
    parser.add_argument("--oos-dataset", type=Path, default=DEFAULT_OOS_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"unsupported extension: {path}")


def detect_timestamp(frame: pd.DataFrame) -> pd.Series:
    for column in ("open_time_utc", "timestamp", "ts_event_utc", "ts_event", "open_time"):
        if column not in frame.columns:
            continue
        values = frame[column]
        if pd.api.types.is_numeric_dtype(values):
            numeric = pd.to_numeric(values, errors="coerce")
            unit = "ms" if float(numeric.dropna().max()) >= 1e11 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(values, utc=True, errors="coerce")
    raise ValueError(f"could not detect timestamp column from {list(frame.columns)}")


def load_btc_hourly() -> pd.Series:
    frames: list[pd.DataFrame] = []
    for path in DEFAULT_BTC_INPUTS:
        if not path.exists():
            raise FileNotFoundError(f"BTC input not found: {path}")
        frame = read_table(path)
        timestamps = detect_timestamp(frame)
        close = pd.to_numeric(frame["close"], errors="coerce")
        out = pd.DataFrame({"timestamp_utc": timestamps, "close": close}).dropna()
        frames.append(out)
    merged = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc", kind="mergesort")
    if merged["timestamp_utc"].duplicated().any():
        duplicate_count = int(merged["timestamp_utc"].duplicated().sum())
        raise ValueError(f"merged BTC has duplicate timestamps: {duplicate_count}")
    minute = merged.set_index("timestamp_utc")["close"].astype(float)
    return minute.resample("1h", label="left", closed="left").last().dropna().astype(float)


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


def lookup(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


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
    for column in ("btc_ret_1h", "btc_ret_4h", "nq_px_t0", "nq_fwd_1h", "nq_fwd_4h"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("event_time_utc_dt", kind="mergesort").reset_index(drop=True)


def add_btc_12h(events: pd.DataFrame, btc_hourly: pd.Series) -> pd.DataFrame:
    out = events.copy()
    values: list[float] = []
    starts: list[str] = []
    ends: list[str] = []
    for row in out.itertuples(index=False):
        t0 = pd.Timestamp(row.event_time_utc_dt).floor("1h")
        start = t0 - pd.Timedelta(hours=12)
        start_px = lookup(btc_hourly, start)
        end_px = lookup(btc_hourly, t0)
        starts.append(start.isoformat())
        ends.append(t0.isoformat())
        if start_px is None or end_px is None:
            values.append(float("nan"))
        else:
            values.append(float(math.log(end_px / start_px)))
    out["btc_ret_12h_start_utc"] = starts
    out["btc_ret_12h_end_utc"] = ends
    out["btc_ret_12h"] = values
    return out


def target_endpoint(row: pd.Series, target: str) -> tuple[str, pd.Timestamp | None]:
    if target == "nq_fwd_to_1600_same_day":
        event_time_ny = pd.Timestamp(row["event_time_ny_dt"])
        target_local = pd.Timestamp.combine(event_time_ny.date(), pd.Timestamp("16:00").time()).tz_localize(NEW_YORK)
        return "exact Monday 16:00 America/New_York 1m bar", target_local.tz_convert(UTC)
    end_col = f"{target}_end_utc"
    if end_col not in row or pd.isna(row[end_col]):
        return "existing event dataset endpoint", None
    return "existing event dataset endpoint", pd.to_datetime(row[end_col], utc=True, errors="coerce")


def target_log_return(
    row: pd.Series, *, target: str, contracts: dict[str, ContractCoverage]
) -> tuple[float, pd.Timestamp | None, float | None, str]:
    convention, end_utc = target_endpoint(row, target)
    if target != "nq_fwd_to_1600_same_day":
        value = row.get(target)
        if pd.notna(value):
            end_px_col = f"nq_px_end_{target.removeprefix('nq_fwd_')}"
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
    combo_name: str,
    btc_lookback: str,
    nq_target: str,
    target_end_utc: pd.Timestamp | None,
    signal_missing: bool,
    target_missing: bool,
    contracts: dict[str, ContractCoverage],
) -> dict[str, object]:
    active = str(row["active_contract"])
    reason = "unknown"
    endpoint_missing = bool(target_missing)
    coverage_issue = False
    holiday_or_cutoff = False
    if signal_missing:
        reason = f"missing_{btc_lookback}"
    elif active not in contracts:
        reason = "missing_active_contract_series"
        coverage_issue = True
    elif target_end_utc is None or pd.isna(target_end_utc):
        reason = "missing_target_endpoint_timestamp"
    elif target_missing:
        coverage = contracts[active]
        if target_end_utc < coverage.first_utc or target_end_utc > coverage.last_utc:
            reason = "target_endpoint_outside_active_contract_coverage_or_data_cutoff"
            coverage_issue = True
            holiday_or_cutoff = True
        else:
            reason = "target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap"
            holiday_or_cutoff = True
    return {
        "combo_name": combo_name,
        "btc_lookback": btc_lookback,
        "nq_target": nq_target,
        "sample_period": row["sample_period"],
        "event_id": row["event_id"],
        "event_date": pd.Timestamp(row["event_time_ny_dt"]).strftime("%Y-%m-%d"),
        "event_time_ny": row["event_time_ny"],
        "active_contract": active,
        "target_end_utc": target_end_utc.isoformat() if target_end_utc is not None and pd.notna(target_end_utc) else "",
        "missing_target": nq_target if target_missing else "",
        "skipped_reason": reason,
        "endpoint_missing": endpoint_missing,
        "nq_contract_coverage_issue": coverage_issue,
        "likely_holiday_session_or_data_cutoff": holiday_or_cutoff,
    }


def build_combo(
    events: pd.DataFrame,
    *,
    btc_lookback: str,
    nq_target: str,
    contracts: dict[str, ContractCoverage],
) -> ComboBuild:
    combo_name = f"{btc_lookback}__{nq_target}"
    rows: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        signal_value = event.get(btc_lookback)
        signal = float(signal_value) if pd.notna(signal_value) else float("nan")
        target_log, end_utc, end_px, convention = target_log_return(event, target=nq_target, contracts=contracts)
        signal_missing = not math.isfinite(signal) or signal == 0.0
        target_missing = not math.isfinite(target_log)
        if signal_missing or target_missing:
            missing_rows.append(
                classify_missing(
                    event,
                    combo_name=combo_name,
                    btc_lookback=btc_lookback,
                    nq_target=nq_target,
                    target_end_utc=end_utc,
                    signal_missing=signal_missing,
                    target_missing=target_missing,
                    contracts=contracts,
                )
            )
            continue
        target_simple = math.exp(target_log) - 1.0
        side = "long" if signal > 0 else "short"
        gross = target_simple if side == "long" else -target_simple
        rows.append(
            {
                "combo_name": combo_name,
                "btc_lookback": btc_lookback,
                "nq_target": nq_target,
                "sample_period": event["sample_period"],
                "event_sequence": int(event["event_sequence"]),
                "event_id": event["event_id"],
                "event_name": "monday_0930",
                "event_time_ny": event["event_time_ny"],
                "event_time_utc": event["event_time_utc"],
                "active_contract": event["active_contract"],
                "signal_col": btc_lookback,
                "target_col": nq_target,
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
    return ComboBuild(pd.DataFrame(rows), pd.DataFrame(missing_rows))


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


def summarize(frame: pd.DataFrame, *, combo_name: str, sample_mode: str, sample_name: str) -> dict[str, object]:
    gross = frame["strategy_return_gross"].to_numpy(dtype=float)
    net = frame["strategy_return_net"].to_numpy(dtype=float)
    count = int(len(frame))
    is_events = frame.loc[frame["sample_period"] == "is"].sort_values("event_time_utc", kind="mergesort")
    half = len(is_events) // 2
    btc = frame["btc_lookback"].iloc[0] if count else combo_name.split("__")[0]
    target = frame["nq_target"].iloc[0] if count else combo_name.split("__", 1)[1]
    return {
        "sample_mode": sample_mode,
        "combo_name": combo_name,
        "btc_lookback": btc,
        "nq_target": target,
        "sample_name": sample_name,
        "total_events": count,
        "event_count": count,
        "trade_count": count,
        "is_events": int((frame["sample_period"] == "is").sum()) if count else 0,
        "oos_events": int((frame["sample_period"] == "oos").sum()) if count else 0,
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


def all_combo_names() -> list[str]:
    return [f"{btc}__{target}" for btc in BTC_LOOKBACKS for target in NQ_TARGETS]


def common_event_ids(trades: pd.DataFrame) -> set[str]:
    sets = [set(sub["event_id"]) for _, sub in trades.groupby("combo_name", sort=False)]
    if not sets:
        return set()
    return set.intersection(*sets)


def build_summary(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combo_name in all_combo_names():
        sub = trades.loc[trades["combo_name"] == combo_name].copy()
        rows.append(summarize(sub, combo_name=combo_name, sample_mode=sample_mode, sample_name="full_is_oos"))
    return pd.DataFrame(rows)


def build_subsample(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combo_name in all_combo_names():
        sub = trades.loc[trades["combo_name"] == combo_name].copy()
        is_sub = sub.loc[sub["sample_period"] == "is"].sort_values("event_time_utc", kind="mergesort")
        oos_sub = sub.loc[sub["sample_period"] == "oos"].sort_values("event_time_utc", kind="mergesort")
        half = len(is_sub) // 2
        for sample_name, sample in (
            ("first_half", is_sub.iloc[:half].copy()),
            ("second_half", is_sub.iloc[half:].copy()),
            ("oos", oos_sub.copy()),
        ):
            rows.append(summarize(sample, combo_name=combo_name, sample_mode=sample_mode, sample_name=sample_name))
    return pd.DataFrame(rows)


def build_side(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combo_name in all_combo_names():
        sub = trades.loc[trades["combo_name"] == combo_name].copy()
        for strategy_name, side in (("long_only", "long"), ("short_only", "short"), ("symmetric", None)):
            side_sub = sub.copy() if side is None else sub.loc[sub["side"] == side].copy()
            row = summarize(side_sub, combo_name=combo_name, sample_mode=sample_mode, sample_name=strategy_name)
            row["strategy_name"] = strategy_name
            rows.append(row)
    return pd.DataFrame(rows)


def missing_summary(all_events: pd.DataFrame, missing: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    total_by_sample = all_events.groupby("sample_period").size().to_dict()
    available = trades.groupby(["combo_name", "sample_period"]).size().to_dict()
    rows: list[dict[str, object]] = []
    for combo_name in all_combo_names():
        btc, target = combo_name.split("__", 1)
        sub = missing.loc[missing["combo_name"] == combo_name].copy() if not missing.empty else pd.DataFrame()
        reasons = sub["skipped_reason"].value_counts().to_dict() if not sub.empty else {}
        rows.append(
            {
                "combo_name": combo_name,
                "btc_lookback": btc,
                "nq_target": target,
                "is_total_events": int(total_by_sample.get("is", 0)),
                "oos_total_events": int(total_by_sample.get("oos", 0)),
                "is_available_events": int(available.get((combo_name, "is"), 0)),
                "oos_available_events": int(available.get((combo_name, "oos"), 0)),
                "skipped_events": int(len(sub)),
                "is_skipped_events": int((sub["sample_period"] == "is").sum()) if not sub.empty else 0,
                "oos_skipped_events": int((sub["sample_period"] == "oos").sum()) if not sub.empty else 0,
                "skipped_event_dates": ";".join(sub["event_date"].astype(str).tolist()) if not sub.empty else "",
                "oos_skipped_event_dates": ";".join(
                    sub.loc[sub["sample_period"] == "oos", "event_date"].astype(str).tolist()
                )
                if not sub.empty
                else "",
                "missing_target": target if not sub.empty and sub["endpoint_missing"].any() else "",
                "skipped_reasons": str(reasons),
                "endpoint_missing": bool((not sub.empty) and sub["endpoint_missing"].any()),
                "nq_contract_coverage_issue": bool((not sub.empty) and sub["nq_contract_coverage_issue"].any()),
                "likely_holiday_session_or_data_cutoff": bool(
                    (not sub.empty) and sub["likely_holiday_session_or_data_cutoff"].any()
                ),
            }
        )
    return pd.DataFrame(rows)


def plot_nav(trades: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 8))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    for combo_name, sub in trades.groupby("combo_name", sort=False):
        ordered = sub.sort_values("event_time_utc", kind="mergesort").copy()
        ordered["event_time_dt"] = pd.to_datetime(ordered["event_time_ny"], utc=True).dt.tz_convert(
            "America/New_York"
        )
        ordered["nav_net"] = (1.0 + ordered["strategy_return_net"]).cumprod()
        ax.plot(ordered["event_time_dt"], ordered["nav_net"], linewidth=1.6, label=combo_name)
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
    ax.set_title("BTC-NQ 3x3 weekend grid: monday_0930 old_raw_contract")
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


def stability_labels(subsample: pd.DataFrame, side: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combo_name in all_combo_names():
        sub = subsample.loc[(subsample["sample_mode"] == "available") & (subsample["combo_name"] == combo_name)]
        first = sub.loc[sub["sample_name"] == "first_half"].iloc[0]
        second = sub.loc[sub["sample_name"] == "second_half"].iloc[0]
        oos = sub.loc[sub["sample_name"] == "oos"].iloc[0]
        side_sub = side.loc[
            (side["sample_mode"] == "available")
            & (side["combo_name"] == combo_name)
            & (side["strategy_name"].isin(["long_only", "short_only"]))
        ]
        long_net = float(side_sub.loc[side_sub["strategy_name"] == "long_only", "cumulative_net_return"].iloc[0])
        short_net = float(side_sub.loc[side_sub["strategy_name"] == "short_only", "cumulative_net_return"].iloc[0])
        rows.append(
            {
                "combo_name": combo_name,
                "three_segments_profitable": bool(
                    first["cumulative_net_return"] > 0
                    and second["cumulative_net_return"] > 0
                    and oos["cumulative_net_return"] > 0
                ),
                "is_good_oos_bad": bool(
                    first["cumulative_net_return"] > 0
                    and second["cumulative_net_return"] > 0
                    and oos["cumulative_net_return"] < 0
                ),
                "oos_good_is_unstable": bool(
                    oos["cumulative_net_return"] > 0
                    and (first["cumulative_net_return"] <= 0 or second["cumulative_net_return"] <= 0)
                ),
                "oos_positive_low_sample": bool(
                    oos["cumulative_net_return"] > 0 and str(oos["low_sample_warning"]) == "true"
                ),
                "long_short_extreme_imbalance": bool((long_net > 0 and short_net < 0) or (short_net > 0 and long_net < 0)),
                "score_tuple": (
                    int(first["cumulative_net_return"] > 0),
                    int(second["cumulative_net_return"] > 0),
                    int(oos["cumulative_net_return"] > -0.01),
                    float(oos["net_win_rate"]),
                    float(sub["cumulative_net_return"].sum()),
                ),
            }
        )
    return pd.DataFrame(rows)


def report_lines(
    *,
    summary: pd.DataFrame,
    common: pd.DataFrame,
    subsample: pd.DataFrame,
    side: pd.DataFrame,
    endpoint: pd.DataFrame,
    labels: pd.DataFrame,
) -> list[str]:
    lines = [
        "# BTC-NQ Weekend 3x3 Grid Report",
        "",
        "Scope: old weekly/weekend BTC-NQ strategy grid only. Event is `monday_0930`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC threshold optimization, daily strategy, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.",
        "",
        "## Grid",
        "",
        f"- BTC lookbacks: {', '.join(BTC_LOOKBACKS)}",
        f"- NQ targets: {', '.join(NQ_TARGETS)}",
        "- `btc_ret_12h` is computed in this report script from local BTC parquet with the same hourly bar-close convention as existing BTC returns.",
        "- `nq_fwd_to_1600_same_day` uses exact Monday 16:00 America/New_York 1m bar on the same active raw NQ contract.",
        "",
        "## Available-Sample Summary",
        "",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"- {row.combo_name}: first/second/OOS events={row.first_half_events}/{row.second_half_events}/{row.oos_events}, "
            f"cumulative net={pct(row.cumulative_net_return)}, average net={pct(row.average_net_return)}, "
            f"net win rate={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Common-Sample Summary", ""])
    for row in common.itertuples(index=False):
        lines.append(
            f"- {row.combo_name}: events={row.total_events}, cumulative net={pct(row.cumulative_net_return)}, "
            f"average net={pct(row.average_net_return)}, net win rate={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Stability Labels", ""])
    three = labels.loc[labels["three_segments_profitable"], "combo_name"].tolist()
    is_bad = labels.loc[labels["is_good_oos_bad"], "combo_name"].tolist()
    oos_unstable = labels.loc[labels["oos_good_is_unstable"], "combo_name"].tolist()
    extreme = labels.loc[labels["long_short_extreme_imbalance"], "combo_name"].tolist()
    lines.append(f"- Three segments profitable: {three or 'none'}")
    lines.append(f"- IS good but OOS bad: {is_bad or 'none'}")
    lines.append(f"- OOS good but IS unstable: {oos_unstable or 'none'}")
    lines.append(f"- Long/short extreme imbalance: {extreme or 'none'}")
    lines.extend(["", "## Endpoint Missing Attribution", ""])
    for row in endpoint.itertuples(index=False):
        if int(row.skipped_events) == 0:
            continue
        lines.append(
            f"- {row.combo_name}: skipped={row.skipped_events}, OOS skipped={row.oos_skipped_event_dates or 'none'}, "
            f"reason={row.skipped_reasons}."
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "- Stability is judged by first_half, second_half, OOS, OOS win rate, low sample status, and side concentration, not by full-period return alone.",
            "- This grid is exploratory within the old weekly strategy frame and should not be treated as threshold optimization or a new daily strategy.",
            "",
        ]
    )
    return lines


def main() -> int:
    args = parse_args()
    btc_hourly = load_btc_hourly()
    contracts = load_contracts()
    is_events = add_btc_12h(load_events(args.is_dataset, "is"), btc_hourly)
    oos_events = add_btc_12h(load_events(args.oos_dataset, "oos"), btc_hourly)
    all_events = pd.concat([is_events, oos_events], ignore_index=True)

    trade_parts: list[pd.DataFrame] = []
    missing_parts: list[pd.DataFrame] = []
    for btc in BTC_LOOKBACKS:
        for target in NQ_TARGETS:
            built = build_combo(all_events, btc_lookback=btc, nq_target=target, contracts=contracts)
            trade_parts.append(built.trades)
            missing_parts.append(built.missing)
    trades = pd.concat(trade_parts, ignore_index=True)
    missing = pd.concat(missing_parts, ignore_index=True)
    common_ids = common_event_ids(trades)
    common_trades = trades.loc[trades["event_id"].isin(common_ids)].copy()

    summary = build_summary(trades, sample_mode="available")
    common_summary = build_summary(common_trades, sample_mode="common")
    subsample = pd.concat(
        [build_subsample(trades, sample_mode="available"), build_subsample(common_trades, sample_mode="common")],
        ignore_index=True,
    )
    side = pd.concat(
        [build_side(trades, sample_mode="available"), build_side(common_trades, sample_mode="common")],
        ignore_index=True,
    )
    endpoint = missing_summary(all_events, missing, trades)
    labels = stability_labels(subsample, side)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_dir / "grid_3x3_summary.csv", index=False)
    common_summary.to_csv(args.output_dir / "grid_3x3_common_sample_summary.csv", index=False)
    subsample.to_csv(args.output_dir / "grid_3x3_subsample_stats.csv", index=False)
    side.to_csv(args.output_dir / "grid_3x3_side_attribution.csv", index=False)
    endpoint.to_csv(args.output_dir / "grid_3x3_endpoint_missing_attribution.csv", index=False)
    trades.to_csv(args.output_dir / "grid_3x3_event_trades.csv", index=False)
    labels.to_csv(args.output_dir / "grid_3x3_stability_labels.csv", index=False)
    plot_nav(trades, args.output_dir / "grid_3x3_nav.png")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "\n".join(
            report_lines(
                summary=summary,
                common=common_summary,
                subsample=subsample,
                side=side,
                endpoint=endpoint,
                labels=labels,
            )
        ),
        encoding="utf-8",
    )

    print(f"Wrote summary: {args.output_dir / 'grid_3x3_summary.csv'}")
    print(f"Wrote common summary: {args.output_dir / 'grid_3x3_common_sample_summary.csv'}")
    print(f"Wrote subsample stats: {args.output_dir / 'grid_3x3_subsample_stats.csv'}")
    print(f"Wrote side attribution: {args.output_dir / 'grid_3x3_side_attribution.csv'}")
    print(f"Wrote endpoint attribution: {args.output_dir / 'grid_3x3_endpoint_missing_attribution.csv'}")
    print(f"Wrote event trades: {args.output_dir / 'grid_3x3_event_trades.csv'}")
    print(f"Wrote NAV chart: {args.output_dir / 'grid_3x3_nav.png'}")
    print(f"Wrote report: {args.report}")
    print("No BTC threshold optimization, daily strategy, continuous NQ, downloads, or API calls were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
