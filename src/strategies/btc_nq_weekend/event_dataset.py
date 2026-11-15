from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")

DEFAULT_BTC_LOOKBACKS = ("1h", "4h", "1d", "2d")
DEFAULT_NQ_FORWARDS = ("5m", "10m", "30m", "1h", "4h", "1d", "2d")
PRIMARY_EVENT = "monday_0930"
PRIMARY_SIGNAL = "btc_ret_4h"
PRIMARY_TARGET = "nq_fwd_1d"
PRIMARY_COST_RATE = 0.001

BTC_TIMESTAMP_CANDIDATES = ("open_time_utc", "timestamp", "ts_event_utc", "ts_event")
NQ_TIMESTAMP_CANDIDATES = ("ts_event_utc", "ts_event", "timestamp", "open_time_utc")


@dataclass(frozen=True)
class EventSpec:
    event_name: str
    local_tz: ZoneInfo
    weekday: int
    local_time: time


def get_event_spec(event_name: str) -> EventSpec:
    if event_name == "monday_0930":
        return EventSpec(event_name=event_name, local_tz=NEW_YORK, weekday=0, local_time=time(9, 30))
    if event_name == "sunday_1700":
        return EventSpec(event_name=event_name, local_tz=CHICAGO, weekday=6, local_time=time(17, 0))
    raise ValueError(f"unsupported event_name: {event_name!r}")


def parse_window(spec: str) -> pd.Timedelta:
    match = re.match(r"^\s*(\d+)\s*([mhd])\s*$", spec, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"invalid window spec {spec!r}; expected like 5m, 4h, 1d")
    value = int(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        raise ValueError(f"window must be positive: {spec!r}")
    if unit == "m":
        return pd.Timedelta(minutes=value)
    if unit == "h":
        return pd.Timedelta(hours=value)
    if unit == "d":
        return pd.Timedelta(days=value)
    raise AssertionError("unreachable")


def parse_bar_freq(spec: str) -> str:
    match = re.match(r"^\s*(\d+)\s*([mhd])\s*$", spec, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"invalid bar freq {spec!r}; expected like 1m, 1h")
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return f"{value}min"
    if unit == "h":
        return f"{value}h"
    if unit == "d":
        return f"{value}d"
    raise AssertionError("unreachable")


def parse_timestamp(value: object) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (int, float, np.integer, np.floating)):
        numeric = float(value)
        unit = "ms" if numeric >= 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True)
    text = str(value).strip()
    if not text:
        return pd.NaT
    if text.isdigit():
        numeric = float(text)
        unit = "ms" if numeric >= 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True)
    return pd.to_datetime(text, utc=True, errors="coerce")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"input not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"unsupported input extension {path.suffix!r}: {path}")


def _detect_timestamp(frame: pd.DataFrame, candidates: tuple[str, ...]) -> tuple[str, pd.Series]:
    for column in candidates:
        if column in frame.columns:
            values = frame[column]
            if pd.api.types.is_numeric_dtype(values):
                numeric = pd.to_numeric(values, errors="coerce")
                unit = "ms" if float(numeric.dropna().max()) >= 1e11 else "s"
                return column, pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
            return column, pd.to_datetime(values, utc=True, errors="coerce")
    if "open_time" in frame.columns:
        values = frame["open_time"]
        if pd.api.types.is_numeric_dtype(values):
            return "open_time", pd.to_datetime(values, unit="ms", utc=True, errors="coerce")
        return "open_time", values.map(parse_timestamp)
    if isinstance(frame.index, pd.DatetimeIndex):
        return "index", pd.Series(pd.to_datetime(frame.index, utc=True, errors="coerce"), index=frame.index)
    raise ValueError(f"could not detect timestamp column; candidates={candidates}")


def load_price_series(path: Path, *, asset: str) -> pd.Series:
    frame = read_table(path)
    if "close" not in frame.columns:
        raise ValueError(f"{asset} input missing close column: {path}")
    candidates = BTC_TIMESTAMP_CANDIDATES if asset == "btc" else NQ_TIMESTAMP_CANDIDATES
    _, timestamps = _detect_timestamp(frame, candidates)
    close = pd.to_numeric(frame["close"], errors="coerce")
    out = pd.DataFrame({"timestamp_utc": timestamps, "close": close})
    out = out.dropna(subset=["timestamp_utc", "close"]).copy()
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
    out = out.sort_values("timestamp_utc", kind="mergesort")
    duplicate_count = int(out["timestamp_utc"].duplicated().sum())
    if duplicate_count:
        raise ValueError(f"{asset} input has duplicate timestamps: {duplicate_count}")
    if (out["close"] <= 0).any():
        raise ValueError(f"{asset} input has non-positive close values: {path}")
    return out.set_index("timestamp_utc")["close"].astype(float)


def resample_bar_close(series: pd.Series, rule: str) -> pd.Series:
    """
    Convert finer bars to coarser bar-open labels with bar-close values.

    This is needed for old BTC parity: the old 1h CSV timestamp is the bar open,
    while its close is the final close inside that hour.
    """

    if rule == "1min":
        return series
    return series.resample(rule, label="left", closed="left").last().dropna().astype(float)


def iter_event_times(
    *,
    event_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[pd.Timestamp]:
    spec = get_event_spec(event_name)
    start_local = start.tz_convert(spec.local_tz)
    end_local = end.tz_convert(spec.local_tz)
    day = start_local.normalize().date()
    last_day = end_local.normalize().date()
    out: list[pd.Timestamp] = []
    while day <= last_day:
        if day.weekday() == spec.weekday:
            t0_local = pd.Timestamp.combine(day, spec.local_time).tz_localize(spec.local_tz)
            t0_utc = t0_local.tz_convert(UTC)
            if start <= t0_utc <= end:
                out.append(t0_utc)
        day = day + timedelta(days=1)
    return out


def _lookup_price(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


def _log_return(start_price: float | None, end_price: float | None) -> float:
    if start_price is None or end_price is None:
        return float("nan")
    if start_price <= 0 or end_price <= 0:
        return float("nan")
    return float(math.log(end_price / start_price))


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def _event_bounds(
    btc: pd.Series,
    nq: pd.Series,
    *,
    start: str | None,
    end: str | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if start is not None:
        start_ts = pd.to_datetime(start, utc=True)
    else:
        start_ts = max(btc.index.min(), nq.index.min())
    if end is not None:
        end_ts = pd.to_datetime(end, utc=True)
    else:
        end_ts = min(btc.index.max(), nq.index.max())
    if start_ts > end_ts:
        raise ValueError(f"start is after end: {start_ts} > {end_ts}")
    return start_ts, end_ts


def build_event_dataset(
    *,
    btc_input: Path,
    nq_input: Path,
    start: str | None = None,
    end: str | None = None,
    event_names: tuple[str, ...] = ("monday_0930", "sunday_1700"),
    btc_lookbacks: tuple[str, ...] = DEFAULT_BTC_LOOKBACKS,
    nq_forwards: tuple[str, ...] = DEFAULT_NQ_FORWARDS,
    btc_bar_freq: str = "1m",
    cost_rate: float = PRIMARY_COST_RATE,
) -> pd.DataFrame:
    btc = load_price_series(btc_input, asset="btc")
    nq = load_price_series(nq_input, asset="nq")
    start_ts, end_ts = _event_bounds(btc, nq, start=start, end=end)
    btc_rule = parse_bar_freq(btc_bar_freq)
    btc = resample_bar_close(btc, btc_rule)
    lookback_windows = {name: parse_window(name) for name in btc_lookbacks}
    forward_windows = {name: parse_window(name) for name in nq_forwards}

    rows: list[dict[str, object]] = []
    event_seq = 0
    for event_name in event_names:
        for event_time_utc in iter_event_times(event_name=event_name, start=start_ts, end=end_ts):
            event_seq += 1
            event_time_ny = event_time_utc.tz_convert(NEW_YORK)
            event_time_chicago = event_time_utc.tz_convert(CHICAGO)
            event_id = f"{event_name}_{event_time_utc.strftime('%Y%m%dT%H%M%SZ')}"

            btc_t0 = event_time_utc.floor(btc_rule)
            btc_px_t0 = _lookup_price(btc, btc_t0)
            nq_t0 = event_time_utc.floor("1min")
            nq_px_t0 = _lookup_price(nq, nq_t0)
            missing_reasons: list[str] = []

            row: dict[str, object] = {
                "event_id": event_id,
                "event_name": event_name,
                "event_sequence": event_seq,
                "event_time_ny": _iso(event_time_ny),
                "event_time_chicago": _iso(event_time_chicago),
                "event_time_utc": _iso(event_time_utc),
                "btc_source_path": str(btc_input),
                "nq_source_path": str(nq_input),
                "btc_px_t0": btc_px_t0 if btc_px_t0 is not None else np.nan,
                "btc_t0_utc": _iso(btc_t0),
                "nq_px_t0": nq_px_t0 if nq_px_t0 is not None else np.nan,
                "nq_t0_utc": _iso(nq_t0),
                "is_primary_pair_event": event_name == PRIMARY_EVENT,
            }

            btc_feature_ok = True
            if btc_px_t0 is None:
                btc_feature_ok = False
                missing_reasons.append("missing_btc_t0")

            for name, window in lookback_windows.items():
                start_key = (event_time_utc - window).floor(btc_rule)
                end_key = btc_t0
                start_px = _lookup_price(btc, start_key)
                end_px = btc_px_t0
                if start_px is None:
                    btc_feature_ok = False
                    missing_reasons.append(f"missing_btc_start_{name}")
                row[f"btc_ret_{name}_start_utc"] = _iso(start_key)
                row[f"btc_ret_{name}_end_utc"] = _iso(end_key)
                row[f"btc_px_start_{name}"] = start_px if start_px is not None else np.nan
                row[f"btc_px_end_{name}"] = end_px if end_px is not None else np.nan
                row[f"btc_ret_{name}"] = _log_return(start_px, end_px)

            nq_primary_target_ok = True
            nq_session_gap_warning = False
            if nq_px_t0 is None:
                nq_primary_target_ok = False
                nq_session_gap_warning = True
                missing_reasons.append("missing_nq_t0")

            for name, window in forward_windows.items():
                start_key = nq_t0
                end_key = (event_time_utc + window).floor("1min")
                start_px = nq_px_t0
                end_px = _lookup_price(nq, end_key)
                if end_px is None:
                    nq_session_gap_warning = True
                    missing_reasons.append(f"missing_nq_end_{name}")
                    if f"nq_fwd_{name}" == PRIMARY_TARGET:
                        nq_primary_target_ok = False
                row[f"nq_fwd_{name}_start_utc"] = _iso(start_key)
                row[f"nq_fwd_{name}_end_utc"] = _iso(end_key)
                row[f"nq_px_start_{name}"] = start_px if start_px is not None else np.nan
                row[f"nq_px_end_{name}"] = end_px if end_px is not None else np.nan
                row[f"nq_fwd_{name}"] = _log_return(start_px, end_px)

            signal = row.get(PRIMARY_SIGNAL, np.nan)
            target = row.get(PRIMARY_TARGET, np.nan)
            row["signal_btc_ret_4h"] = signal
            gross = np.nan
            net = np.nan
            if event_name == PRIMARY_EVENT and pd.notna(signal) and pd.notna(target):
                long_simple = math.exp(float(target)) - 1.0
                side = float(np.sign(float(signal)))
                gross = side * long_simple
                net = gross - cost_rate if side != 0.0 else -cost_rate
            row["gross_strategy_ret_monday_0930_4h_1d"] = gross
            row["net_strategy_ret_monday_0930_4h_1d_cost_001"] = net
            row["btc_feature_ok"] = bool(btc_feature_ok)
            row["nq_target_ok"] = bool(nq_primary_target_ok)
            row["nq_session_gap_warning"] = bool(nq_session_gap_warning)
            row["missing_data_reason"] = ";".join(sorted(set(missing_reasons)))
            rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["event_time_utc", "event_name"], kind="mergesort").reset_index(drop=True)
    return out


def write_event_dataset(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(output, index=False)
        return
    if suffix == ".parquet":
        frame.to_parquet(output, index=False)
        return
    raise ValueError(f"unsupported output extension {output.suffix!r}; use .csv or .parquet")


def read_event_dataset(path: Path) -> pd.DataFrame:
    return read_table(path)

