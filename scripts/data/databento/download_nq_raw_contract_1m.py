from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = "GLBX.MDP3"
DEFAULT_SCHEMA = "ohlcv-1m"
DEFAULT_STYPE_IN = "raw_symbol"
OUT_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol"]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Databento NQ raw_symbol 1m OHLCV. Defaults to safe dry-run."
    )
    parser.add_argument("--symbol", required=True, help="Raw contract symbol, e.g. NQM6, NQU6.")
    parser.add_argument("--start", required=True, help="Inclusive UTC start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Exclusive UTC end date, YYYY-MM-DD.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    parser.add_argument("--stype-in", default=DEFAULT_STYPE_IN)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. Default: data/raw/databento/GLBX.MDP3/NQ/raw_symbol/{SYMBOL}/...",
    )
    parser.add_argument("--execute", action="store_true", help="Actually call Databento Historical API.")
    parser.add_argument(
        "--confirm-use-api-credits",
        action="store_true",
        help="Required with --execute to call Databento Historical API and consume credits.",
    )
    return parser.parse_args()


def compact_date(value: str) -> str:
    return value.replace("-", "")


def default_output_path(symbol: str, start: str, end: str) -> Path:
    sym = symbol.strip().upper()
    return (
        PROJECT_ROOT
        / "data"
        / "raw"
        / "databento"
        / DEFAULT_DATASET
        / "NQ"
        / "raw_symbol"
        / sym
        / f"{sym}_1m_{compact_date(start)}_{compact_date(end)}.csv"
    )


def validate_dates(start: str, end: str) -> None:
    if not _DATE_RE.match(start) or not _DATE_RE.match(end):
        raise ValueError("start and end must be YYYY-MM-DD")
    if start >= end:
        raise ValueError("--end must be after --start")


def require_api_key() -> str:
    api_key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY is not configured.")
    return api_key


def ts_series_to_iso_utc_z(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, utc=True)
    return dt.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def dry_run_report(args: argparse.Namespace, output: Path) -> str:
    return "\n".join(
        [
            "Databento NQ raw_symbol 1m dry-run",
            "No Databento API call was made.",
            f"dataset: {args.dataset}",
            f"schema: {args.schema}",
            f"stype_in: {args.stype_in}",
            f"symbol: {args.symbol.strip().upper()}",
            f"start: {args.start}",
            f"end: {args.end}",
            f"output: {output}",
            "To execute, rerun with both --execute and --confirm-use-api-credits.",
        ]
    )


def download_raw_contract(args: argparse.Namespace, output: Path) -> pd.DataFrame:
    try:
        import databento as db
    except ImportError as exc:
        raise SystemExit("Missing dependency: databento. Install with: python -m pip install databento") from exc

    api_key = require_api_key()
    sym = args.symbol.strip().upper()
    client = db.Historical(key=api_key)
    store = client.timeseries.get_range(
        dataset=args.dataset,
        schema=args.schema,
        symbols=sym,
        stype_in=args.stype_in,
        start=args.start,
        end=args.end,
    )

    df = store.to_df(price_type="float", pretty_ts=True, map_symbols=True, tz="UTC")
    if df.empty:
        return pd.DataFrame(columns=OUT_COLUMNS)

    out = df.reset_index()
    idx_name = out.columns[0]
    if idx_name != "timestamp":
        out = out.rename(columns={idx_name: "timestamp"})
    if "symbol" not in out.columns:
        out["symbol"] = sym

    missing = [column for column in ("open", "high", "low", "close", "volume") if column not in out.columns]
    if missing:
        raise RuntimeError(f"Unexpected dataframe columns; missing {missing}: {list(out.columns)}")

    out["timestamp"] = ts_series_to_iso_utc_z(out["timestamp"])
    return out[OUT_COLUMNS].sort_values("timestamp").reset_index(drop=True)


def main() -> int:
    args = parse_args()
    validate_dates(args.start, args.end)
    output = args.output or default_output_path(args.symbol, args.start, args.end)

    if not args.execute or not args.confirm_use_api_credits:
        print(dry_run_report(args, output))
        return 0

    frame = download_raw_contract(args, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"output: {output}")
    print(f"rows: {len(frame)}")
    if not frame.empty:
        print(f"first_timestamp: {frame['timestamp'].iloc[0]}")
        print(f"last_timestamp: {frame['timestamp'].iloc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
