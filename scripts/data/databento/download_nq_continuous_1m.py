from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = "GLBX.MDP3"
DEFAULT_SCHEMA = "ohlcv-1m"
DEFAULT_SYMBOL = "NQ.v.0"
DEFAULT_STYPE_IN = "continuous"
DEFAULT_START = "2020-01-01"
DEFAULT_END = "2026-05-01"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "market_data"
    / "databento"
    / DEFAULT_DATASET
    / "NQ"
    / "1m"
    / "nq_continuous_volume_front_1m_2020_2026.parquet"
)
DEFAULT_RAW_DBN = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "market_data"
    / "databento"
    / DEFAULT_DATASET
    / "NQ"
    / "1m"
    / "nq_continuous_volume_front_1m_2020_2026.dbn"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Databento NQ continuous 1m OHLCV. Defaults to safe dry-run."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--stype-in", default=DEFAULT_STYPE_IN)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-dbn", type=Path, default=DEFAULT_RAW_DBN)
    parser.add_argument("--execute", action="store_true", help="Actually call Databento Historical API.")
    parser.add_argument(
        "--confirm-use-api-credits",
        action="store_true",
        help="Required with --execute to call Databento Historical API and consume credits.",
    )
    return parser.parse_args()


def require_api_key() -> str:
    api_key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY is not configured.")
    return api_key


def store_to_frame(store, fallback_symbol: str) -> pd.DataFrame:
    df = store.to_df(price_type="float", pretty_ts=True, map_symbols=True, tz="UTC")
    if df.empty:
        return pd.DataFrame()

    out = df.reset_index()
    first_col = out.columns[0]
    if first_col != "ts_event":
        out = out.rename(columns={first_col: "ts_event"})
    if "timestamp" in out.columns and "ts_event" not in out.columns:
        out = out.rename(columns={"timestamp": "ts_event"})
    if "symbol" not in out.columns:
        out["symbol"] = fallback_symbol
    return out


def clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    if "ts_event" not in out.columns:
        raise RuntimeError(f"Databento frame missing ts_event. Columns: {list(out.columns)}")
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True, errors="raise")
    out["ts_event_utc"] = out["ts_event"]
    for column in ("open", "high", "low", "close", "volume"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.sort_values("ts_event", kind="mergesort").drop_duplicates("ts_event", keep="first").reset_index(drop=True)


def dry_run_report(args: argparse.Namespace) -> str:
    return "\n".join(
        [
            "Databento NQ continuous 1m dry-run",
            "No Databento API call was made.",
            f"dataset: {args.dataset}",
            f"schema: {args.schema}",
            f"symbol: {args.symbol}",
            f"stype_in: {args.stype_in}",
            f"start: {args.start}",
            f"end: {args.end}",
            f"output: {args.output}",
            f"raw_dbn: {args.raw_dbn}",
            "To execute, rerun with both --execute and --confirm-use-api-credits.",
        ]
    )


def main() -> int:
    args = parse_args()
    if not args.execute or not args.confirm_use_api_credits:
        print(dry_run_report(args))
        return 0

    try:
        import databento as db
    except ImportError as exc:
        raise SystemExit("Missing dependency: databento. Install with: python -m pip install databento") from exc

    api_key = require_api_key()
    client = db.Historical(key=api_key)
    store = client.timeseries.get_range(
        dataset=args.dataset,
        schema=args.schema,
        symbols=args.symbol,
        stype_in=args.stype_in,
        start=args.start,
        end=args.end,
    )

    args.raw_dbn.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(store, "to_file"):
        store.to_file(args.raw_dbn)

    cleaned = clean_frame(store_to_frame(store, args.symbol))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(args.output, index=False)

    print(f"output: {args.output}")
    print(f"raw_dbn: {args.raw_dbn}")
    print(f"rows: {len(cleaned)}")
    if not cleaned.empty:
        print(f"first_ts_event_utc: {cleaned['ts_event_utc'].min()}")
        print(f"last_ts_event_utc: {cleaned['ts_event_utc'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
