from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "databento" / "nq"
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol"]
CHICAGO = ZoneInfo("America/Chicago")
ONE_MIN = pd.Timedelta(minutes=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean one Databento NQ raw_symbol 1m CSV for old_raw_contract mode.")
    parser.add_argument("--input", type=Path, required=True, help="Raw CSV from download_nq_raw_contract_1m.py.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Clean CSV output path. Default: data/processed/databento/nq/{stem}_clean.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Optional summary text path. Default: alongside clean CSV with _summary.txt suffix.",
    )
    return parser.parse_args()


def build_summary(frame: pd.DataFrame) -> str:
    ts = frame["timestamp"]
    row_count = len(frame)
    symbol = str(frame["symbol"].iloc[0]).strip() if row_count else "unknown"
    duplicates = int(ts.duplicated().sum())
    strictly_increasing = bool(ts.is_monotonic_increasing and duplicates == 0)

    diffs = ts.diff().dropna()
    gaps_gt_1m = diffs[diffs > ONE_MIN]
    gap_count = int(gaps_gt_1m.shape[0])
    top_gaps = gaps_gt_1m.nlargest(min(5, gap_count)) if gap_count else pd.Series(dtype="timedelta64[ns]")

    na_lines = "\n".join(f"  {col}: {int(frame[col].isna().sum())}" for col in frame.columns)
    bad_hl = int((frame["high"] < frame["low"]).sum())
    non_positive = int(((frame[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())

    lines = [
        f"{symbol} 1m clean + check summary",
        "=" * 40,
        f"rows: {row_count}",
        f"first timestamp (America/Chicago): {ts.iloc[0] if row_count else None}",
        f"last timestamp (America/Chicago): {ts.iloc[-1] if row_count else None}",
        f"duplicate timestamps: {duplicates}",
        f"strictly increasing timestamps: {strictly_increasing}",
        "",
        "missing values (parsed before string export):",
        na_lines,
        "",
        f"adjacent bar gaps > 1 minute: {gap_count}",
        "largest gaps (up to 5):",
    ]
    if gap_count:
        for index, (idx, gap) in enumerate(top_gaps.items(), start=1):
            lines.append(f"  {index}. {gap}  (after {ts.iloc[idx - 1]} -> {ts.iloc[idx]})")
    else:
        lines.append("  (none)")

    lines.extend(
        [
            "",
            f"rows with high < low: {bad_hl}",
            f"rows with any OHLC <= 0: {non_positive}",
            "",
            "Note: reduced-quality / holiday gaps are not auto-fixed; review gaps above.",
        ]
    )
    return "\n".join(lines) + "\n"


def clean_raw_contract(input_path: Path, output_path: Path, summary_path: Path) -> tuple[Path, Path]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input not found: {input_path}")

    frame = pd.read_csv(input_path)
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"CSV missing columns {missing}; got {list(frame.columns)}")

    out = frame[COLUMNS].copy()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.strip()

    ts_utc = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    checked = out.copy()
    checked["timestamp"] = ts_utc.dt.tz_convert(CHICAGO)
    checked = checked.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    summary = build_summary(checked)
    export = checked.copy()
    export["timestamp"] = export["timestamp"].map(lambda value: value.isoformat(timespec="seconds"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    summary_path.write_text(summary, encoding="utf-8")
    return output_path, summary_path


def main() -> int:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else (PROJECT_ROOT / args.input).resolve()
    output_path = args.output or (DEFAULT_PROCESSED_DIR / f"{input_path.stem}_clean.csv")
    summary_path = args.summary or output_path.with_name(output_path.stem + "_summary.txt")

    clean_path, summary_file = clean_raw_contract(input_path, output_path, summary_path)
    print(summary_file.read_text(encoding="utf-8"))
    print(f"Wrote: {clean_path}")
    print(f"Wrote: {summary_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
