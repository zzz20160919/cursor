from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.btc_nq_weekend.event_dataset import (  # noqa: E402
    DEFAULT_BTC_LOOKBACKS,
    DEFAULT_NQ_FORWARDS,
    read_event_dataset,
)


DEFAULT_NEW_DATASET = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset.csv"
DEFAULT_OLD_MONDAY = (
    Path("D:/cursor/202604_stra")
    / "research/outputs/weekend_btc_leads_nq_monday_0930_v1/monday_0930_event_dataset.csv"
)
DEFAULT_OLD_SUNDAY = (
    Path("D:/cursor/202604_stra")
    / "research/outputs/weekend_btc_leads_nq_sunday_fullstats_v1/weekend_event_dataset.csv"
)
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/event_dataset_parity_report.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate BTC-NQ weekend event dataset parity against old event-study outputs."
    )
    parser.add_argument("--new-dataset", type=Path, default=DEFAULT_NEW_DATASET)
    parser.add_argument("--old-monday", type=Path, default=DEFAULT_OLD_MONDAY)
    parser.add_argument("--old-sunday", type=Path, default=DEFAULT_OLD_SUNDAY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--tolerance", type=float, default=1e-10)
    return parser.parse_args()


def load_old_reference(path: Path, *, event_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"old reference not found: {path}")
    frame = pd.read_csv(path)
    if "event_name" not in frame.columns:
        frame["event_name"] = event_name
    if "t0_event_local" in frame.columns:
        frame["event_time_utc"] = pd.to_datetime(frame["t0_event_local"], utc=True, errors="coerce")
    elif "t0_chicago" in frame.columns:
        frame["event_time_utc"] = pd.to_datetime(frame["t0_chicago"], utc=True, errors="coerce")
    else:
        raise ValueError(f"old reference lacks t0_event_local/t0_chicago: {path}")
    return frame


def normalize_new(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["event_time_utc"] = pd.to_datetime(out["event_time_utc"], utc=True, errors="coerce")
    return out


def compare_columns(
    merged: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    sample_size: int,
    tolerance: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    summary: dict[str, object] = {}
    sample = merged.head(sample_size).copy()
    for column in columns:
        old_col = f"{column}_old"
        new_col = f"{column}_new"
        if old_col not in merged.columns or new_col not in merged.columns:
            summary[column] = {"status": "missing_column"}
            continue
        old_values = pd.to_numeric(merged[old_col], errors="coerce")
        new_values = pd.to_numeric(merged[new_col], errors="coerce")
        diff = (new_values - old_values).abs()
        finite = np.isfinite(diff)
        max_abs_diff = float(diff[finite].max()) if finite.any() else float("nan")
        matched = bool(finite.any() and max_abs_diff <= tolerance)
        summary[column] = {
            "status": "match" if matched else "diff",
            "max_abs_diff": max_abs_diff,
            "finite_count": int(finite.sum()),
        }
        for row in sample.itertuples(index=False):
            rows.append(
                {
                    "event_time_utc": getattr(row, "event_time_utc").isoformat(),
                    "column": column,
                    "old": getattr(row, old_col, np.nan),
                    "new": getattr(row, new_col, np.nan),
                    "abs_diff": abs(float(getattr(row, new_col)) - float(getattr(row, old_col)))
                    if pd.notna(getattr(row, new_col, np.nan)) and pd.notna(getattr(row, old_col, np.nan))
                    else np.nan,
                }
            )
    return rows, summary


def markdown_table(records: list[dict[str, object]], *, max_rows: int = 20) -> str:
    if not records:
        return "_No rows._"
    keys = list(records[0].keys())
    lines = ["|" + "|".join(keys) + "|", "|" + "|".join(["---"] * len(keys)) + "|"]
    for record in records[:max_rows]:
        values = [str(record.get(key, "")).replace("\n", " ") for key in keys]
        lines.append("|" + "|".join(values) + "|")
    if len(records) > max_rows:
        lines.append(f"|...|{len(records) - max_rows} more rows omitted" + "|" * (len(keys) - 2) + "|")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    new = normalize_new(read_event_dataset(args.new_dataset))
    old_monday = load_old_reference(args.old_monday, event_name="monday_0930")
    old_sunday = load_old_reference(args.old_sunday, event_name="sunday_1700")

    new_monday = new.loc[new["event_name"] == "monday_0930"].copy()
    new_sunday = new.loc[new["event_name"] == "sunday_1700"].copy()
    old_monday_count = len(old_monday)
    old_sunday_count = len(old_sunday)

    monday_join = old_monday.merge(
        new_monday,
        on=["event_name", "event_time_utc"],
        how="inner",
        suffixes=("_old", "_new"),
    ).sort_values("event_time_utc", kind="mergesort")
    sunday_join = old_sunday.merge(
        new_sunday,
        on=["event_name", "event_time_utc"],
        how="inner",
        suffixes=("_old", "_new"),
    )

    btc_cols = tuple(f"btc_ret_{name}" for name in DEFAULT_BTC_LOOKBACKS)
    nq_cols = tuple(f"nq_fwd_{name}" for name in DEFAULT_NQ_FORWARDS)
    _, btc_summary = compare_columns(
        monday_join,
        columns=btc_cols,
        sample_size=args.sample_size,
        tolerance=args.tolerance,
    )
    sample_nq_rows, nq_summary = compare_columns(
        monday_join,
        columns=nq_cols,
        sample_size=args.sample_size,
        tolerance=args.tolerance,
    )
    sample_btc_rows, _ = compare_columns(
        monday_join,
        columns=btc_cols,
        sample_size=args.sample_size,
        tolerance=args.tolerance,
    )

    btc_grid_present = [col for col in btc_cols if col in new.columns]
    nq_grid_present = [col for col in nq_cols if col in new.columns]
    focused_rows = new_monday.loc[new_monday["btc_feature_ok"] & new_monday["nq_target_ok"]].copy()
    half = len(focused_rows) // 2

    result = {
        "new_dataset": str(args.new_dataset),
        "old_monday": str(args.old_monday),
        "old_sunday": str(args.old_sunday),
        "new_monday_rows": int(len(new_monday)),
        "old_monday_rows": int(old_monday_count),
        "monday_join_rows": int(len(monday_join)),
        "new_sunday_rows": int(len(new_sunday)),
        "old_sunday_rows": int(old_sunday_count),
        "sunday_join_rows": int(len(sunday_join)),
        "monday_66_event_parity": bool(len(new_monday) == 66 and old_monday_count == 66 and len(monday_join) == 66),
        "focused_usable_rows": int(len(focused_rows)),
        "focused_split": [int(half), int(len(focused_rows) - half)],
        "focused_33_33_parity": bool(len(focused_rows) == 66 and half == 33),
        "btc_grid_present": btc_grid_present,
        "nq_grid_present": nq_grid_present,
        "btc_grid_complete": bool(len(btc_grid_present) == 4),
        "nq_grid_complete": bool(len(nq_grid_present) == 7),
        "btc_sample_summary": btc_summary,
        "nq_sample_summary": nq_summary,
        "continuous_nq_exact_match": bool(
            all(v.get("status") == "match" for v in nq_summary.values() if isinstance(v, dict))
        ),
    }

    lines = [
        "# BTC-NQ Weekend Event Dataset Parity Report",
        "",
        "This report is generated by `scripts/strategy/btc_nq_weekend/validate_event_dataset_parity.py`.",
        "It validates event-study dataset parity only; it is not a production backtest.",
        "",
        "## Summary JSON",
        "",
        "```json",
        json.dumps(result, indent=2, sort_keys=True),
        "```",
        "",
        "## BTC Sample Comparisons",
        "",
        markdown_table(sample_btc_rows, max_rows=30),
        "",
        "## NQ Sample Comparisons",
        "",
        markdown_table(sample_nq_rows, max_rows=30),
        "",
        "## Difference Interpretation",
        "",
        "- BTC parity is expected only when the new 1m parquet is queried on the same UTC endpoint convention as the old 1h CSV, typically via `--btc-bar-freq 1h`.",
        "- NQ parity is not guaranteed because the old output used raw-symbol active-contract assignment while the new input is continuous `NQ.v.0` parquet.",
        "- Row-count parity can still hold even when NQ return values differ.",
        "- Missing NQ endpoints are surfaced through `nq_target_ok`, `nq_session_gap_warning`, and `missing_data_reason`.",
        "",
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"Wrote parity report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

