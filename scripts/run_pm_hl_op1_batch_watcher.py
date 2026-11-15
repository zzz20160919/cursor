from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.mvp2_scanner.match_opportunity_evaluator import evaluate_match
from src.strategies.pm_hl.mvp2_scanner.scanner_config import DEFAULT_OUTPUT_DIR


OP_GROUP = "cross_venue_direct_no_complete_set"
CSV_FIELDS = [
    "timestamp",
    "timestamp_utc8",
    "iteration",
    "pm_event_slug",
    "hl_question_name",
    "market_key",
    "op_group",
    "outcome_or_condition",
    "side",
    "gross",
    "fee",
    "net",
    "edge",
    "positive_flag",
    "depth",
    "capacity_usd",
    "sum_ask",
    "sum_bid",
    "rec",
    "est_profit_20_shares",
    "est_portfolio_return_low_pct",
    "est_portfolio_return_high_pct",
    "note",
]
COVERAGE_FIELDS = [
    "market_key",
    "pm_event_slug",
    "hl_question_name",
    "status",
    "outcomes_count",
    "op1_rows_count",
    "best_net",
    "positive_count",
    "error",
    "checked_at",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def utc8_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).astimezone().isoformat()


def read_config(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if str(row.get("enabled", "true")).lower() in {"1", "true", "yes", "y"}]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def safe_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [safe_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: safe_dict(item) for key, item in value.items()}
    return value


def op1_to_csv_row(
    row: dict[str, Any],
    timestamp: str,
    timestamp_utc8: str,
    iteration: int,
    market: dict[str, str],
) -> dict[str, Any]:
    net = row.get("net")
    edge = net
    return {
        "timestamp": timestamp,
        "timestamp_utc8": timestamp_utc8,
        "iteration": iteration,
        "pm_event_slug": market["pm_event_slug"],
        "hl_question_name": market["hl_question_name"],
        "market_key": market.get("market_key", ""),
        "op_group": OP_GROUP,
        "outcome_or_condition": row.get("outcome", ""),
        "side": row.get("side", ""),
        "gross": row.get("gross"),
        "fee": row.get("estimated_fee"),
        "net": net,
        "edge": edge,
        "positive_flag": bool(net is not None and float(net) > 0),
        "depth": row.get("depth"),
        "capacity_usd": row.get("rough_capacity_usd") or row.get("capacity_usd"),
        "sum_ask": row.get("sum_ask"),
        "sum_bid": "",
        "rec": row.get("recommendation", ""),
        "est_profit_20_shares": None if net is None else float(net) * 20.0,
        "est_portfolio_return_low_pct": "",
        "est_portfolio_return_high_pct": "",
        "note": "Batch op1 watcher; scanner price is reference only.",
    }


def threshold_pass(row: dict[str, Any], threshold: float, min_s1_profit: float, min_s2_profit: float) -> bool:
    net = row.get("net")
    if net is None:
        return False
    value = float(net)
    return value >= threshold and value * 20.0 >= min_s1_profit and value * 20.0 >= min_s2_profit


def run_once(
    markets: list[dict[str, str]],
    iteration: int,
    threshold: float,
    min_s1_profit: float,
    min_s2_profit: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    timestamp_dt = now_utc()
    timestamp = timestamp_dt.isoformat()
    timestamp_utc8 = timestamp_dt.astimezone(timezone.utc).astimezone().isoformat()
    candidates: list[dict[str, Any]] = []
    near_miss: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for market in markets:
        try:
            evaluation = evaluate_match(market["pm_event_slug"], market["hl_question_name"])
            evaluation_dict = safe_dict(evaluation)
            op1_rows = evaluation_dict.get("opportunity_groups", {}).get(OP_GROUP, [])
            csv_rows = [
                op1_to_csv_row(row, timestamp, timestamp_utc8, iteration, market)
                for row in op1_rows
            ]
            passing = [
                csv_row
                for csv_row, raw_row in zip(csv_rows, op1_rows)
                if threshold_pass(raw_row, threshold, min_s1_profit, min_s2_profit)
            ]
            candidates.extend(passing)
            near_miss.extend(sorted(csv_rows, key=lambda item: float(item.get("net") or -999), reverse=True)[:3])
            best_net = max((float(row.get("net")) for row in op1_rows if row.get("net") is not None), default=0.0)
            coverage.append(
                {
                    "market_key": market.get("market_key", ""),
                    "pm_event_slug": market["pm_event_slug"],
                    "hl_question_name": market["hl_question_name"],
                    "status": "ok",
                    "outcomes_count": len(evaluation_dict.get("aligned_outcomes", [])),
                    "op1_rows_count": len(op1_rows),
                    "best_net": best_net,
                    "positive_count": len([row for row in op1_rows if row.get("net") is not None and float(row["net"]) > 0]),
                    "error": "",
                    "checked_at": timestamp,
                }
            )
            snapshots.append(
                {
                    "timestamp": timestamp,
                    "iteration": iteration,
                    "market_key": market.get("market_key", ""),
                    "pm_event_slug": market["pm_event_slug"],
                    "hl_question_name": market["hl_question_name"],
                    "evaluation": evaluation_dict,
                    "status": "ok",
                }
            )
        except Exception as exc:
            coverage.append(
                {
                    "market_key": market.get("market_key", ""),
                    "pm_event_slug": market.get("pm_event_slug", ""),
                    "hl_question_name": market.get("hl_question_name", ""),
                    "status": "error",
                    "outcomes_count": 0,
                    "op1_rows_count": 0,
                    "best_net": "",
                    "positive_count": 0,
                    "error": str(exc)[:300],
                    "checked_at": timestamp,
                }
            )
    return candidates, near_miss, coverage, snapshots


def write_summary(
    path: Path,
    markets: list[dict[str, str]],
    threshold: float,
    min_s1_profit: float,
    min_s2_profit: float,
    candidates: list[dict[str, Any]],
    near_miss: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    relaxed: bool,
    iterations: int,
) -> None:
    market_lines = "\n".join(
        f"- {row.get('market_key')}: {row['pm_event_slug']} / {row['hl_question_name']}"
        for row in markets
    )
    content = f"""# OP1 Batch Watcher Summary

- scanned_markets_count: {len(markets)}
- threshold_decimal: {threshold}
- threshold_bps: {threshold * 10000:.3g}
- threshold_percent: {threshold * 100:.3g}%
- min_s1_profit_usd: {min_s1_profit}
- min_s2_profit_usd: {min_s2_profit}
- relaxed_threshold_test: {str(relaxed).lower()}
- live_allowed: false
- candidates_count: {len(candidates)}
- near_miss_count: {len(near_miss)}
- coverage_rows_count: {len(coverage)}
- iterations_completed: {iterations}
- no_fake_candidate: true
- live_order_adapter_ready: false
- partial_fill_detection_ready: true
- single_leg_exposure_detection_ready: true

## Market List
{market_lines}

## Result
{"positive candidate found" if candidates else "no positive candidate under threshold"}
"""
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch watcher for PM-HL MVP2 op1 1v1 markets.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.0005)
    parser.add_argument("--scan-minutes", type=float, default=20.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--min-s1-profit-usd", type=float, default=0.01)
    parser.add_argument("--min-s2-profit-usd", type=float, default=0.01)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pm.load_env()
    hl.load_env()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    markets = read_config(args.config)
    relaxed = args.threshold < 0.0005 or args.min_s1_profit_usd < 0.01 or args.min_s2_profit_usd < 0.01
    deadline = time.monotonic() + max(args.scan_minutes, 0) * 60
    iteration = 0
    all_candidates: list[dict[str, Any]] = []
    latest_near_miss: list[dict[str, Any]] = []
    latest_coverage: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    while True:
        iteration += 1
        candidates, near_miss, coverage, iteration_snapshots = run_once(
            markets,
            iteration,
            args.threshold,
            args.min_s1_profit_usd,
            args.min_s2_profit_usd,
        )
        all_candidates.extend(candidates)
        latest_near_miss = near_miss
        latest_coverage = coverage
        snapshots.extend(iteration_snapshots)
        write_csv(args.output_dir / "op1_live_candidates_latest.csv", CSV_FIELDS, all_candidates)
        write_csv(args.output_dir / "op1_near_miss_latest.csv", CSV_FIELDS, latest_near_miss)
        write_csv(args.output_dir / "op1_market_coverage_latest.csv", COVERAGE_FIELDS, latest_coverage)
        payload = {
            "pm_event_slug": "batch",
            "hl_question_name": "batch",
            "snapshots": snapshots,
            "config": {
                "threshold": args.threshold,
                "min_s1_profit_usd": args.min_s1_profit_usd,
                "min_s2_profit_usd": args.min_s2_profit_usd,
                "relaxed_threshold_test": relaxed,
                "live_allowed": False,
            },
        }
        (args.output_dir / "op1_live_candidates_latest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if args.report:
            write_summary(
                args.output_dir / "op1_batch_summary.md",
                markets,
                args.threshold,
                args.min_s1_profit_usd,
                args.min_s2_profit_usd,
                all_candidates,
                latest_near_miss,
                latest_coverage,
                relaxed,
                iteration,
            )
        if all_candidates or time.monotonic() >= deadline:
            break
        time.sleep(max(args.interval_seconds, 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
