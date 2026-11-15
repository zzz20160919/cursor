from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUMMARY_JSON = (
    PROJECT_ROOT
    / "reports/btc_nq_weekend/old_output_reproduction/old_focused_validation_reproduction_summary.json"
)

EXPECTED_EVENT_COUNT = 66
EXPECTED_FOCUSED_SPLIT = [33, 33]
EXPECTED_NQ_MODE = "old_raw_contract"
EXPECTED_COST_RATE = 0.001
MAX_ABS_DIFF_TOLERANCE = 1e-12

REQUIRED_TABLES = (
    "event_level_symmetric",
    "event_trade_summary",
    "subsample_stats",
    "performance_fullsample",
    "performance_first_half",
    "performance_second_half",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lightweight smoke/regression check for BTC-NQ old output reproduction baseline. "
            "Reads the reproduction summary JSON only; does not rerun backtests."
        )
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_SUMMARY_JSON,
        help="Path to old_focused_validation_reproduction_summary.json",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=MAX_ABS_DIFF_TOLERANCE,
        help="Maximum allowed abs diff for table comparisons",
    )
    return parser.parse_args()


def _fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def _check_scalar(
    *,
    name: str,
    actual: object,
    expected: object,
    failures: list[str],
) -> None:
    if actual != expected:
        _fail(f"{name}: expected {expected!r}, got {actual!r}", failures)


def _check_table_summary(
    table_summary: list[dict[str, object]],
    tolerance: float,
    failures: list[str],
) -> None:
    by_name = {str(row["table_name"]): row for row in table_summary}

    for table_name in REQUIRED_TABLES:
        row = by_name.get(table_name)
        if row is None:
            _fail(f"missing table_summary entry: {table_name}", failures)
            continue

        all_exact_match = row.get("all_exact_match")
        if all_exact_match is not True:
            _fail(f"{table_name}: all_exact_match is not true ({all_exact_match!r})", failures)

        max_abs_diff = row.get("max_abs_diff")
        if max_abs_diff is None:
            _fail(f"{table_name}: missing max_abs_diff", failures)
            continue

        try:
            max_abs_diff_value = float(max_abs_diff)
        except (TypeError, ValueError):
            _fail(f"{table_name}: max_abs_diff is not numeric ({max_abs_diff!r})", failures)
            continue

        if max_abs_diff_value > tolerance:
            _fail(
                f"{table_name}: max_abs_diff {max_abs_diff_value} exceeds tolerance {tolerance}",
                failures,
            )


def run_smoke_test(summary_path: Path, tolerance: float) -> list[str]:
    failures: list[str] = []

    if not summary_path.is_file():
        return [f"summary JSON not found: {summary_path}"]

    with summary_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)

    _check_scalar(
        name="event_count",
        actual=summary.get("event_count"),
        expected=EXPECTED_EVENT_COUNT,
        failures=failures,
    )
    _check_scalar(
        name="focused_split",
        actual=summary.get("focused_split"),
        expected=EXPECTED_FOCUSED_SPLIT,
        failures=failures,
    )
    _check_scalar(
        name="nq_mode",
        actual=summary.get("nq_mode"),
        expected=EXPECTED_NQ_MODE,
        failures=failures,
    )
    _check_scalar(
        name="cost_rate",
        actual=summary.get("cost_rate"),
        expected=EXPECTED_COST_RATE,
        failures=failures,
    )

    if summary.get("all_exact_match") is not True:
        _fail(f"all_exact_match is not true ({summary.get('all_exact_match')!r})", failures)

    table_summary = summary.get("table_summary")
    if not isinstance(table_summary, list):
        _fail("table_summary is missing or not a list", failures)
    else:
        _check_table_summary(table_summary, tolerance, failures)

    return failures


def main() -> int:
    args = parse_args()
    failures = run_smoke_test(args.summary_json.resolve(), args.tolerance)

    print("Smoke test: BTC-NQ old output reproduction baseline")
    print(f"Summary JSON: {args.summary_json.resolve()}")
    print(f"Tolerance: {args.tolerance}")

    if failures:
        print("RESULT: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("RESULT: PASS")
    print(f"  event_count == {EXPECTED_EVENT_COUNT}")
    print(f"  focused_split == {EXPECTED_FOCUSED_SPLIT}")
    print(f"  nq_mode == {EXPECTED_NQ_MODE!r}")
    print(f"  cost_rate == {EXPECTED_COST_RATE}")
    for table_name in REQUIRED_TABLES:
        print(f"  {table_name}: all_exact_match and max_abs_diff <= {args.tolerance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
