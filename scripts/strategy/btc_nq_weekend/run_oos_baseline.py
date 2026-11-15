from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")

PRIMARY_EVENT = "monday_0930"
PRIMARY_SIGNAL = "btc_ret_4h"
PRIMARY_TARGET = "nq_fwd_1d"
DEFAULT_COST_RATE = 0.001
DEFAULT_BTC_LOOKBACKS = ("1h", "4h", "1d", "2d")
DEFAULT_NQ_FORWARDS = ("5m", "10m", "30m", "1h", "4h", "1d", "2d")
DEFAULT_NQ_ROLL_CHAIN = ("NQH5", "NQM5", "NQU5", "NQZ5", "NQH6", "NQM6", "NQU6")

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

DEFAULT_OUTPUT_DATASET = (
    PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_oos_20260317_20260618_raw_contract.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/oos_baseline"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/oos_baseline_report.md"
DEFAULT_IS_TRADES = (
    PROJECT_ROOT / "reports/btc_nq_weekend/old_output_reproduction/monday_0930_trade_v2_reproduction.csv"
)
DEFAULT_SMOKE_SUMMARY = (
    PROJECT_ROOT / "reports/btc_nq_weekend/old_output_reproduction/old_focused_validation_reproduction_summary.json"
)

TIMESTAMP_CANDIDATES = ("open_time_utc", "timestamp", "ts_event_utc", "ts_event", "open_time")


@dataclass(frozen=True)
class EventSpec:
    event_name: str
    local_tz: ZoneInfo
    weekday: int
    local_time: time


@dataclass(frozen=True)
class NqContract:
    symbol: str
    path: Path
    close: pd.Series
    first_utc: pd.Timestamp
    last_utc: pd.Timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build BTC-NQ Weekend old_raw_contract OOS event dataset and baseline report."
    )
    parser.add_argument("--start", default="2026-03-17T00:00:00Z")
    parser.add_argument("--end", default="2026-06-18T23:59:00Z")
    parser.add_argument("--output-dataset", type=Path, default=DEFAULT_OUTPUT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cost-rate", type=float, default=DEFAULT_COST_RATE)
    return parser.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"input not found: {path}")
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"unsupported input extension: {path}")


def detect_timestamp(frame: pd.DataFrame) -> pd.Series:
    for column in TIMESTAMP_CANDIDATES:
        if column not in frame.columns:
            continue
        values = frame[column]
        if pd.api.types.is_numeric_dtype(values):
            numeric = pd.to_numeric(values, errors="coerce")
            max_value = float(numeric.dropna().max())
            unit = "ms" if max_value >= 1e11 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(values, utc=True, errors="coerce")
    if isinstance(frame.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(frame.index, utc=True, errors="coerce"), index=frame.index)
    raise ValueError(f"could not detect timestamp column from {list(frame.columns)}")


def load_price_series(path: Path) -> pd.Series:
    frame = read_table(path)
    if "close" not in frame.columns:
        raise ValueError(f"input missing close column: {path}")
    timestamps = detect_timestamp(frame)
    close = pd.to_numeric(frame["close"], errors="coerce")
    out = pd.DataFrame({"timestamp_utc": timestamps, "close": close})
    out = out.dropna(subset=["timestamp_utc", "close"]).copy()
    out = out.sort_values("timestamp_utc", kind="mergesort")
    if (out["close"] <= 0).any():
        raise ValueError(f"input has non-positive close values: {path}")
    duplicate_count = int(out["timestamp_utc"].duplicated().sum())
    if duplicate_count:
        raise ValueError(f"input has duplicate timestamps: {path} duplicate_count={duplicate_count}")
    return out.set_index("timestamp_utc")["close"].astype(float)


def load_merged_btc(paths: tuple[Path, ...]) -> pd.Series:
    frames = []
    for path in paths:
        series = load_price_series(path)
        frames.append(series.rename("close").reset_index())
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("timestamp_utc", kind="mergesort")
    duplicate_count = int(merged["timestamp_utc"].duplicated().sum())
    if duplicate_count:
        raise ValueError(f"merged BTC source has duplicate timestamps: {duplicate_count}")
    return merged.set_index("timestamp_utc")["close"].astype(float)


def load_nq_contracts(paths: dict[str, Path]) -> dict[str, NqContract]:
    contracts: dict[str, NqContract] = {}
    for symbol in DEFAULT_NQ_ROLL_CHAIN:
        path = paths[symbol]
        close = load_price_series(path)
        contracts[symbol] = NqContract(
            symbol=symbol,
            path=path,
            close=close,
            first_utc=close.index.min(),
            last_utc=close.index.max(),
        )
    return contracts


def parse_window(spec: str) -> pd.Timedelta:
    value = int(spec[:-1])
    unit = spec[-1].lower()
    if unit == "m":
        return pd.Timedelta(minutes=value)
    if unit == "h":
        return pd.Timedelta(hours=value)
    if unit == "d":
        return pd.Timedelta(days=value)
    raise ValueError(f"unsupported window: {spec}")


def get_event_spec(event_name: str) -> EventSpec:
    if event_name == "monday_0930":
        return EventSpec(event_name=event_name, local_tz=NEW_YORK, weekday=0, local_time=time(9, 30))
    raise ValueError(f"unsupported event_name: {event_name}")


def iter_event_times(start: pd.Timestamp, end: pd.Timestamp, event_name: str) -> list[pd.Timestamp]:
    spec = get_event_spec(event_name)
    start_local = start.tz_convert(spec.local_tz)
    end_local = end.tz_convert(spec.local_tz)
    day = start_local.normalize().date()
    last_day = end_local.normalize().date()
    events: list[pd.Timestamp] = []
    while day <= last_day:
        if day.weekday() == spec.weekday:
            local = pd.Timestamp.combine(day, spec.local_time).tz_localize(spec.local_tz)
            utc = local.tz_convert(UTC)
            if start <= utc <= end:
                events.append(utc)
        day += timedelta(days=1)
    return events


def lookup(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


def log_return(start_price: float | None, end_price: float | None) -> float:
    if start_price is None or end_price is None or start_price <= 0 or end_price <= 0:
        return float("nan")
    return float(math.log(end_price / start_price))


def iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def pick_active_contract(
    ts_utc: pd.Timestamp, contracts: dict[str, NqContract]
) -> tuple[str | None, list[str]]:
    candidates = [
        symbol
        for symbol in DEFAULT_NQ_ROLL_CHAIN
        if contracts[symbol].first_utc <= ts_utc <= contracts[symbol].last_utc
    ]
    if not candidates:
        return None, []
    active = max(candidates, key=lambda symbol: DEFAULT_NQ_ROLL_CHAIN.index(symbol))
    return active, candidates


def build_oos_dataset(
    *,
    btc: pd.Series,
    contracts: dict[str, NqContract],
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost_rate: float,
) -> pd.DataFrame:
    scan_end = min(end, btc.index.max(), max(contract.last_utc for contract in contracts.values()))
    btc_hourly = btc.resample("1h", label="left", closed="left").last().dropna().astype(float)
    btc_windows = {name: parse_window(name) for name in DEFAULT_BTC_LOOKBACKS}
    nq_windows = {name: parse_window(name) for name in DEFAULT_NQ_FORWARDS}
    nq_source_path = ";".join(f"{symbol}={contracts[symbol].path}" for symbol in DEFAULT_NQ_ROLL_CHAIN)

    rows: list[dict[str, object]] = []
    for sequence, event_time_utc in enumerate(iter_event_times(start, scan_end, PRIMARY_EVENT), start=1):
        event_time_ny = event_time_utc.tz_convert(NEW_YORK)
        event_time_chicago = event_time_utc.tz_convert(CHICAGO)
        active, candidates = pick_active_contract(event_time_utc, contracts)
        missing_reasons: list[str] = []

        row: dict[str, object] = {
            "event_id": f"{PRIMARY_EVENT}_{event_time_utc.strftime('%Y%m%dT%H%M%SZ')}",
            "event_name": PRIMARY_EVENT,
            "event_sequence": sequence,
            "event_time_ny": iso(event_time_ny),
            "event_time_chicago": iso(event_time_chicago),
            "event_time_utc": iso(event_time_utc),
            "btc_source_path": ";".join(str(path) for path in DEFAULT_BTC_INPUTS),
            "nq_source_path": nq_source_path,
            "nq_mode": "old_raw_contract",
            "active_contract": active if active is not None else "",
            "nq_active_candidates": ";".join(candidates),
            "nq_overlap_candidate_count": len(candidates),
            "nq_contract_selection_overlap_hit": len(candidates) > 1,
            "is_primary_pair_event": True,
        }

        btc_t0 = event_time_utc.floor("1h")
        btc_px_t0 = lookup(btc_hourly, btc_t0)
        row["btc_px_t0"] = btc_px_t0 if btc_px_t0 is not None else np.nan
        row["btc_t0_utc"] = iso(btc_t0)
        btc_feature_ok = btc_px_t0 is not None
        if btc_px_t0 is None:
            missing_reasons.append("missing_btc_t0")

        for name, window in btc_windows.items():
            start_key = (event_time_utc - window).floor("1h")
            start_px = lookup(btc_hourly, start_key)
            if start_px is None:
                btc_feature_ok = False
                missing_reasons.append(f"missing_btc_start_{name}")
            row[f"btc_ret_{name}_start_utc"] = iso(start_key)
            row[f"btc_ret_{name}_end_utc"] = iso(btc_t0)
            row[f"btc_px_start_{name}"] = start_px if start_px is not None else np.nan
            row[f"btc_px_end_{name}"] = btc_px_t0 if btc_px_t0 is not None else np.nan
            row[f"btc_ret_{name}"] = log_return(start_px, btc_px_t0)

        nq_primary_target_ok = active is not None
        nq_session_gap_warning = False
        if active is None:
            nq_primary_target_ok = False
            nq_session_gap_warning = True
            missing_reasons.append("no_active_contract_for_t0")
            nq_series = pd.Series(dtype=float)
        else:
            nq_series = contracts[active].close

        nq_t0 = event_time_utc.floor("1min")
        nq_px_t0 = lookup(nq_series, nq_t0)
        row["nq_px_t0"] = nq_px_t0 if nq_px_t0 is not None else np.nan
        row["nq_t0_utc"] = iso(nq_t0)
        if nq_px_t0 is None:
            nq_primary_target_ok = False
            nq_session_gap_warning = True
            missing_reasons.append("missing_nq_t0")

        for name, window in nq_windows.items():
            end_key = (event_time_utc + window).floor("1min")
            end_active, end_candidates = pick_active_contract(end_key, contracts)
            end_px = lookup(nq_series, end_key)
            if end_px is None:
                nq_session_gap_warning = True
                missing_reasons.append(f"missing_nq_end_{name}")
                if f"nq_fwd_{name}" == PRIMARY_TARGET:
                    nq_primary_target_ok = False

            row[f"nq_fwd_{name}_start_utc"] = iso(nq_t0)
            row[f"nq_fwd_{name}_end_utc"] = iso(end_key)
            row[f"nq_fwd_{name}_active_contract"] = active if active is not None else ""
            row[f"nq_fwd_{name}_active_contract_at_end"] = end_active if end_active is not None else ""
            row[f"nq_fwd_{name}_end_candidates"] = ";".join(end_candidates)
            row[f"nq_fwd_{name}_end_candidate_count"] = len(end_candidates)
            row[f"nq_fwd_{name}_crosses_contract_boundary"] = bool(active and end_active and active != end_active)
            row[f"nq_px_start_{name}"] = nq_px_t0 if nq_px_t0 is not None else np.nan
            row[f"nq_px_end_{name}"] = end_px if end_px is not None else np.nan
            row[f"nq_fwd_{name}"] = log_return(nq_px_t0, end_px)

        signal = row.get(PRIMARY_SIGNAL, np.nan)
        target = row.get(PRIMARY_TARGET, np.nan)
        row["signal_btc_ret_4h"] = signal
        row["btc_feature_ok"] = bool(btc_feature_ok)
        row["nq_target_ok"] = bool(nq_primary_target_ok)
        row["nq_session_gap_warning"] = bool(nq_session_gap_warning)
        row["missing_data_reason"] = ";".join(sorted(set(missing_reasons)))

        gross = np.nan
        net = np.nan
        if btc_feature_ok and nq_primary_target_ok and pd.notna(signal) and pd.notna(target):
            side = float(np.sign(float(signal)))
            target_simple = math.exp(float(target)) - 1.0
            if side != 0.0:
                gross = side * target_simple
                net = gross - cost_rate
        row["gross_strategy_ret_monday_0930_4h_1d"] = gross
        row["net_strategy_ret_monday_0930_4h_1d_cost_001"] = net
        rows.append(row)

    return pd.DataFrame(rows)


def build_trades(events: pd.DataFrame, *, cost_rate: float) -> pd.DataFrame:
    usable = events.loc[
        (events["event_name"] == PRIMARY_EVENT) & events["btc_feature_ok"] & events["nq_target_ok"]
    ].copy()
    usable[PRIMARY_SIGNAL] = pd.to_numeric(usable[PRIMARY_SIGNAL], errors="coerce")
    usable[PRIMARY_TARGET] = pd.to_numeric(usable[PRIMARY_TARGET], errors="coerce")
    usable = usable.loc[np.isfinite(usable[PRIMARY_SIGNAL]) & np.isfinite(usable[PRIMARY_TARGET])]
    usable = usable.sort_values("event_time_utc", kind="mergesort").reset_index(drop=True)

    rows: list[dict[str, object]] = []
    for index, row in usable.iterrows():
        signal = float(row[PRIMARY_SIGNAL])
        target_log = float(row[PRIMARY_TARGET])
        if signal == 0.0:
            continue
        target_simple = math.exp(target_log) - 1.0
        side = "long" if signal > 0.0 else "short"
        gross = target_simple if side == "long" else -target_simple
        rows.append(
            {
                "event_index": int(index) + 1,
                "event_name": PRIMARY_EVENT,
                "t0_event_local": row["event_time_ny"],
                "t0_chicago": row["event_time_chicago"],
                "active_contract": row["active_contract"],
                "signal_col": PRIMARY_SIGNAL,
                "target_col": PRIMARY_TARGET,
                "signal_value": signal,
                "target_log_return": target_log,
                "target_simple_return": target_simple,
                "cost_rate": cost_rate,
                "side": side,
                "strategy_return_gross": gross,
                "strategy_return_net": gross - cost_rate,
                "benchmark_return_gross": target_simple,
                "benchmark_return_net": target_simple - cost_rate,
            }
        )
    return pd.DataFrame(rows)


def summarize_returns(trades: pd.DataFrame) -> dict[str, object]:
    gross = trades["strategy_return_gross"].to_numpy(dtype=float)
    net = trades["strategy_return_net"].to_numpy(dtype=float)
    benchmark_gross = trades["benchmark_return_gross"].to_numpy(dtype=float)
    benchmark_net = trades["benchmark_return_net"].to_numpy(dtype=float)
    return {
        "event_name": PRIMARY_EVENT,
        "signal_col": PRIMARY_SIGNAL,
        "target_col": PRIMARY_TARGET,
        "nq_mode": "old_raw_contract",
        "cost_rate": DEFAULT_COST_RATE,
        "trade_count": int(len(trades)),
        "long_count": int((trades["side"] == "long").sum()),
        "short_count": int((trades["side"] == "short").sum()),
        "gross_return_sum": float(np.sum(gross)) if gross.size else float("nan"),
        "net_return_sum": float(np.sum(net)) if net.size else float("nan"),
        "cumulative_gross_return": float(np.prod(1.0 + gross) - 1.0) if gross.size else float("nan"),
        "cumulative_net_return": float(np.prod(1.0 + net) - 1.0) if net.size else float("nan"),
        "win_rate_gross": float(np.mean(gross > 0.0)) if gross.size else float("nan"),
        "win_rate_net": float(np.mean(net > 0.0)) if net.size else float("nan"),
        "average_gross_return": float(np.mean(gross)) if gross.size else float("nan"),
        "average_net_return": float(np.mean(net)) if net.size else float("nan"),
        "benchmark_gross_return_sum": float(np.sum(benchmark_gross)) if benchmark_gross.size else float("nan"),
        "benchmark_net_return_sum": float(np.sum(benchmark_net)) if benchmark_net.size else float("nan"),
        "benchmark_cumulative_gross_return": float(np.prod(1.0 + benchmark_gross) - 1.0)
        if benchmark_gross.size
        else float("nan"),
        "benchmark_cumulative_net_return": float(np.prod(1.0 + benchmark_net) - 1.0)
        if benchmark_net.size
        else float("nan"),
    }


def summarize_is_baseline(path: Path) -> dict[str, object]:
    frame = pd.read_csv(path)
    net = pd.to_numeric(frame["strategy_return_net"], errors="coerce").to_numpy(dtype=float)
    gross = pd.to_numeric(frame["strategy_return_gross"], errors="coerce").to_numpy(dtype=float)
    return {
        "is_trade_count": int(len(frame)),
        "is_average_gross_return": float(np.mean(gross)),
        "is_average_net_return": float(np.mean(net)),
        "is_cumulative_gross_return": float(np.prod(1.0 + gross) - 1.0),
        "is_cumulative_net_return": float(np.prod(1.0 + net) - 1.0),
        "is_win_rate_gross": float(np.mean(gross > 0.0)),
        "is_win_rate_net": float(np.mean(net > 0.0)),
    }


def format_pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not math.isfinite(number):
        return "nan"
    return f"{number:.6%}"


def skipped_summary(events: pd.DataFrame) -> dict[str, int]:
    skipped = events.loc[~(events["btc_feature_ok"] & events["nq_target_ok"])].copy()
    counts: dict[str, int] = {}
    for reason_text in skipped["missing_data_reason"].fillna("").astype(str):
        reasons = [item for item in reason_text.split(";") if item]
        if not reasons:
            reasons = ["unknown"]
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def write_report(
    *,
    path: Path,
    smoke_pass: bool,
    events: pd.DataFrame,
    trades: pd.DataFrame,
    summary: dict[str, object],
    is_summary: dict[str, object],
    skipped: dict[str, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = events.loc[events["btc_feature_ok"] & events["nq_target_ok"]].copy()
    event_range = "N/A"
    latest_event = "N/A"
    if not valid.empty:
        event_range = f"{valid['event_time_ny'].iloc[0]} to {valid['event_time_ny'].iloc[-1]}"
        latest_event = str(valid["event_time_ny"].iloc[-1])

    conclusion = (
        "OOS remains profitable on this local data window."
        if float(summary["cumulative_net_return"]) > 0.0
        else "OOS is not profitable on this local data window."
    )
    stability = (
        "The OOS sample is small, so stability should be treated as provisional."
        if int(summary["trade_count"]) < 20
        else "The OOS sample has enough weekly observations for an initial stability read."
    )

    lines = [
        "# BTC-NQ Weekend OOS Baseline Report",
        "",
        "Scope: BTC-NQ Weekend only. Baseline NQ mode is `old_raw_contract`. No PM-HL, Futu, live trading, paper trading, parameter optimization, QQQ proxy, 4pm target variant, data download, or external API calls were used.",
        "",
        "## Smoke Test",
        "",
        f"- smoke_test_old_output_reproduction: {'PASS' if smoke_pass else 'FAIL'}",
        "",
        "## Inputs",
        "",
        "- BTC inputs:",
        *[f"  - `{path}`" for path in DEFAULT_BTC_INPUTS],
        "- NQ raw contract inputs:",
        *[f"  - `{symbol}`: `{DEFAULT_NQ_CONTRACT_PATHS[symbol]}`" for symbol in DEFAULT_NQ_ROLL_CHAIN],
        f"- Roll chain: {' -> '.join(DEFAULT_NQ_ROLL_CHAIN)}",
        "",
        "## OOS Event Dataset",
        "",
        f"- OOS valid event range: {event_range}",
        f"- Latest valid event: {latest_event}",
        f"- OOS valid event count: {summary['trade_count']}",
        f"- Candidate Monday events scanned: {len(events)}",
        f"- Skipped events: {int(len(events) - int(summary['trade_count']))}",
        f"- Skipped reasons: {json.dumps(skipped, sort_keys=True)}",
        "",
        "## Baseline Strategy",
        "",
        "- Event: `monday_0930`",
        "- Feature: `btc_ret_4h`",
        "- Target: `nq_fwd_1d`",
        "- Signal: long NQ if BTC 4h return > 0; short NQ if BTC 4h return < 0",
        f"- Cost: {DEFAULT_COST_RATE}",
        "",
        "## OOS Results",
        "",
        f"- Long / short count: {summary['long_count']} / {summary['short_count']}",
        f"- Gross return sum: {format_pct(summary['gross_return_sum'])}",
        f"- Net return sum after cost: {format_pct(summary['net_return_sum'])}",
        f"- Cumulative gross return: {format_pct(summary['cumulative_gross_return'])}",
        f"- Cumulative net return: {format_pct(summary['cumulative_net_return'])}",
        f"- Gross win rate: {format_pct(summary['win_rate_gross'])}",
        f"- Net win rate: {format_pct(summary['win_rate_net'])}",
        f"- Average gross return: {format_pct(summary['average_gross_return'])}",
        f"- Average net return: {format_pct(summary['average_net_return'])}",
        f"- Benchmark NQ gross return sum: {format_pct(summary['benchmark_gross_return_sum'])}",
        f"- Benchmark NQ net return sum: {format_pct(summary['benchmark_net_return_sum'])}",
        f"- Benchmark NQ cumulative gross return: {format_pct(summary['benchmark_cumulative_gross_return'])}",
        f"- Benchmark NQ cumulative net return: {format_pct(summary['benchmark_cumulative_net_return'])}",
        "",
        "## IS Baseline Comparison",
        "",
        f"- IS events: {is_summary['is_trade_count']}",
        f"- OOS events: {summary['trade_count']}",
        f"- IS average net return: {format_pct(is_summary['is_average_net_return'])}",
        f"- OOS average net return: {format_pct(summary['average_net_return'])}",
        f"- IS cumulative net return: {format_pct(is_summary['is_cumulative_net_return'])}",
        f"- OOS cumulative net return: {format_pct(summary['cumulative_net_return'])}",
        f"- IS net win rate: {format_pct(is_summary['is_win_rate_net'])}",
        f"- OOS net win rate: {format_pct(summary['win_rate_net'])}",
        "",
        "## Conclusion",
        "",
        f"- {conclusion}",
        f"- {stability}",
        "- This is worth reviewing before any QQQ proxy or 4pm target variant work; those were not run in this task.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    for path in DEFAULT_BTC_INPUTS:
        if not path.exists():
            raise FileNotFoundError(f"BTC input not found: {path}")
    for symbol, path in DEFAULT_NQ_CONTRACT_PATHS.items():
        if not path.exists():
            raise FileNotFoundError(f"NQ input not found for {symbol}: {path}")

    smoke_pass = False
    if DEFAULT_SMOKE_SUMMARY.exists():
        with DEFAULT_SMOKE_SUMMARY.open("r", encoding="utf-8") as handle:
            smoke = json.load(handle)
        smoke_pass = (
            smoke.get("event_count") == 66
            and smoke.get("focused_split") == [33, 33]
            and smoke.get("nq_mode") == "old_raw_contract"
            and smoke.get("cost_rate") == DEFAULT_COST_RATE
            and smoke.get("all_exact_match") is True
        )

    btc = load_merged_btc(DEFAULT_BTC_INPUTS)
    contracts = load_nq_contracts(DEFAULT_NQ_CONTRACT_PATHS)
    events = build_oos_dataset(
        btc=btc,
        contracts=contracts,
        start=pd.to_datetime(args.start, utc=True),
        end=pd.to_datetime(args.end, utc=True),
        cost_rate=args.cost_rate,
    )

    args.output_dataset.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.output_dataset, index=False)

    trades = build_trades(events, cost_rate=args.cost_rate)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trades_path = args.output_dir / "monday_0930_trade_v2_oos.csv"
    summary_path = args.output_dir / "oos_baseline_summary.csv"
    metadata_path = args.output_dir / "oos_baseline_metadata.json"
    trades.to_csv(trades_path, index=False)

    summary = summarize_returns(trades)
    is_summary = summarize_is_baseline(DEFAULT_IS_TRADES)
    skipped = skipped_summary(events)
    pd.DataFrame([{**summary, **is_summary}]).to_csv(summary_path, index=False)

    metadata = {
        "smoke_test_pass": smoke_pass,
        "btc_input_paths": [str(path) for path in DEFAULT_BTC_INPUTS],
        "nq_contract_paths": {symbol: str(DEFAULT_NQ_CONTRACT_PATHS[symbol]) for symbol in DEFAULT_NQ_ROLL_CHAIN},
        "roll_chain": list(DEFAULT_NQ_ROLL_CHAIN),
        "event_dataset": str(args.output_dataset),
        "trades_csv": str(trades_path),
        "summary_csv": str(summary_path),
        "report": str(args.report),
        "skipped_reasons": skipped,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    write_report(
        path=args.report,
        smoke_pass=smoke_pass,
        events=events,
        trades=trades,
        summary=summary,
        is_summary=is_summary,
        skipped=skipped,
    )

    print(f"Smoke summary check: {'PASS' if smoke_pass else 'FAIL'}")
    print(f"Wrote OOS event dataset: {args.output_dataset}")
    print(f"Wrote OOS trades: {trades_path}")
    print(f"Wrote OOS summary: {summary_path}")
    print(f"Wrote OOS report: {args.report}")
    print(f"Candidate Monday events: {len(events)}")
    print(f"Usable OOS trades: {summary['trade_count']}")
    if not trades.empty:
        print(f"OOS event range: {trades['t0_event_local'].iloc[0]} to {trades['t0_event_local'].iloc[-1]}")
    print(f"Skipped reasons: {json.dumps(skipped, sort_keys=True)}")
    print(f"Cumulative net return: {summary['cumulative_net_return']:.12f}")
    print("No external API calls or data downloads were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
