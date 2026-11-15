from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "data"
    / "market_data"
    / "binance"
    / "futures"
    / "um"
    / "klines"
    / "BTCUSDT"
    / "1m"
    / "btcusdt_um_1m_2020_2026.parquet"
)
REQUIRED_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
}
TIMESTAMP_CANDIDATES = ["open_time_utc", "timestamp", "ts_event_utc", "ts_event"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local Binance BTCUSDT USD-M perpetual 1m clean data.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=None, help="Optional text report output path.")
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {path}")
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported input extension: {path.suffix}")


def detect_timestamp(frame: pd.DataFrame) -> tuple[str, pd.Series] | tuple[str, None]:
    for column in TIMESTAMP_CANDIDATES:
        if column in frame.columns:
            return column, pd.to_datetime(frame[column], utc=True, errors="coerce")
    if isinstance(frame.index, pd.DatetimeIndex):
        return "index", pd.Series(pd.to_datetime(frame.index, utc=True, errors="coerce"), index=frame.index)
    if "open_time" in frame.columns:
        return "open_time_ms", pd.to_datetime(frame["open_time"], unit="ms", utc=True, errors="coerce")
    return "not_found", None


def validate(frame: pd.DataFrame, input_path: Path) -> tuple[str, bool]:
    timestamp_source, timestamp_values = detect_timestamp(frame)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    lines = [
        "Binance BTCUSDT USD-M Perpetual 1m Validation",
        f"Input: {input_path}",
        f"Rows: {len(frame)}",
        f"Columns: {', '.join(frame.columns)}",
        "",
        "Schema:",
        f"- timestamp_source: {timestamp_source}",
        f"- missing_required_columns: {sorted(missing)}",
    ]
    if missing or timestamp_values is None:
        return "\n".join(lines) + "\n", False

    out = frame.copy()
    out["timestamp_utc"] = timestamp_values.to_numpy()
    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    sorted_input = bool(out["timestamp_utc"].is_monotonic_increasing)
    out = out.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    duplicates = int(out["timestamp_utc"].duplicated().sum())
    gaps = out["timestamp_utc"].diff()
    gap_rows = out.loc[gaps > pd.Timedelta(minutes=1), ["timestamp_utc"]].copy()
    high_ok = out["high"] >= out[["open", "close", "low"]].max(axis=1)
    low_ok = out["low"] <= out[["open", "close", "high"]].min(axis=1)
    positive_ohlc = (out[["open", "high", "low", "close"]] > 0).all(axis=1)

    lines.extend(
        [
            "",
            "Timestamp Range:",
            f"- first_timestamp_utc: {out['timestamp_utc'].min()}",
            f"- last_timestamp_utc: {out['timestamp_utc'].max()}",
            "",
            "Quality Checks:",
            f"- sorted_ascending_input: {sorted_input}",
            f"- duplicate_timestamp_utc: {duplicates}",
            f"- gaps_gt_1m: {len(gap_rows)}",
            f"- high_lt_max_ohlc_violations: {int((~high_ok).sum())}",
            f"- low_gt_min_ohlc_violations: {int((~low_ok).sum())}",
            f"- non_positive_ohlc_rows: {int((~positive_ohlc).sum())}",
            f"- negative_volume_rows: {int((out['volume'] < 0).sum())}",
            f"- missing_values_total: {int(out[list(REQUIRED_COLUMNS)].isna().sum().sum())}",
        ]
    )
    ok = (
        duplicates == 0
        and len(gap_rows) == 0
        and high_ok.all()
        and low_ok.all()
        and positive_ohlc.all()
        and (out["volume"] >= 0).all()
    )
    lines.append("")
    lines.append(f"Validation status: {'PASS' if ok else 'FAIL'}")
    return "\n".join(lines) + "\n", ok


def main() -> int:
    args = parse_args()
    report, ok = validate(load_frame(args.input), args.input)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
