from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.mvp2_scanner.market_mapper import (
    discover_champion_markets,
    discover_champion_universes,
    discover_match_markets,
)
from src.strategies.pm_hl.mvp2_scanner.opportunity_builder import (
    add_champion_diagnostics,
    build_champion_full_diagnostic,
    build_champion_row,
    build_match_rows,
)
from src.strategies.pm_hl.mvp2_scanner.op1_strategy_dry_run import (
    Op1DryRunConfig,
    monitor_op1_strategy_dry_run,
)
from src.strategies.pm_hl.mvp2_scanner.match_opportunity_evaluator import (
    DEFAULT_HL_QUESTION_NAME,
    evaluate_match,
    monitor_match,
    print_evaluation,
    write_evaluation_json,
)
from src.strategies.pm_hl.mvp2_scanner.pm_match_universe import export_pm_match_universe
from src.strategies.pm_hl.mvp2_scanner.pm_sports_match_discovery import (
    discover_moneyline,
    print_discovery,
    write_discovery_json,
)
from src.strategies.pm_hl.mvp2_scanner.scanner_config import (
    DEFAULT_GAMMA_PAGES,
    DEFAULT_OUTPUT_DIR,
)
from src.strategies.pm_hl.mvp2_scanner.schemas import OpportunityRow, ScanSummary
from src.strategies.pm_hl.mvp2_scanner.sinks import (
    print_summary,
    print_table,
    write_csv,
    write_json,
)


T = TypeVar("T")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _limit_rows(rows: list[T], limit: int) -> list[T]:
    return rows[:limit] if limit > 0 else rows


def run_scan(args: argparse.Namespace) -> tuple[list[OpportunityRow], ScanSummary, dict[str, str]]:
    pm.load_env()
    hl.load_env()
    rows: list[OpportunityRow] = []
    failure_reasons: dict[str, int] = {}
    champion_stats: dict[str, int] = {}
    match_stats: dict[str, int] = {}
    full_champion_diagnostic: dict[str, object] = {}
    champion_failed = 0

    if args.scan in ("champion", "all"):
        champion_markets, champion_stats = discover_champion_markets(args.gamma_pages)
        pm_champion_universe, hl_champion_universe = discover_champion_universes(args.gamma_pages)
        full_champion_diagnostic = build_champion_full_diagnostic(
            pm_champion_universe,
            hl_champion_universe,
        )
        champion_markets = _limit_rows(champion_markets, args.max_champion_markets)
        for market in champion_markets:
            row, warnings = build_champion_row(market)
            rows.append(row)
            if warnings:
                champion_failed += 1
        rows = add_champion_diagnostics(rows, full_champion_diagnostic)

    if args.scan in ("matches", "all"):
        match_markets, match_stats = discover_match_markets(args.gamma_pages)
        match_markets = _limit_rows(match_markets, args.max_match_markets)
        for key, value in match_stats.items():
            if key not in {"candidates", "parsed", "matched", "failed"}:
                failure_reasons[key] = value
        for market in match_markets:
            match_rows, warnings = build_match_rows(market)
            rows.extend(match_rows)

    summary = ScanSummary(
        champion_candidates=int(champion_stats.get("intersection", 0)),
        champion_scanned=sum(1 for row in rows if row.strategy_type == "champion_cross_venue"),
        champion_failed=champion_failed,
        champion_matched_outcomes=int(champion_stats.get("intersection", 0)),
        champion_unmatched_outcomes=max(
            int(champion_stats.get("pm_unmatched", 0)),
            int(champion_stats.get("hl_unmatched", 0)),
        ),
        match_candidates=int(match_stats.get("candidates", 0)),
        match_parsed=int(match_stats.get("parsed", 0)),
        match_matched=int(match_stats.get("matched", 0)),
        match_failed=int(match_stats.get("failed", 0)),
        failure_reasons=failure_reasons,
    )
    discovery = {
        "pm_champion_active": str(champion_stats.get("pm_active", 0)),
        "hl_champion_active": str(champion_stats.get("hl_active", 0)),
        "champion_intersection": str(champion_stats.get("intersection", 0)),
        "pm_champion_unmatched": str(champion_stats.get("pm_unmatched", 0)),
        "hl_champion_unmatched": str(champion_stats.get("hl_unmatched", 0)),
        "match_matched": str(match_stats.get("matched", 0)),
    }
    if full_champion_diagnostic:
        pm_full = full_champion_diagnostic.get("pm", {})
        hl_full = full_champion_diagnostic.get("hl", {})
        if isinstance(pm_full, dict):
            discovery["pm_full_sum_yes"] = str(pm_full.get("sum_yes"))
            discovery["pm_full_sum_no"] = str(pm_full.get("sum_no"))
            discovery["pm_full_completeness_flag"] = str(pm_full.get("completeness_flag"))
        if isinstance(hl_full, dict):
            discovery["hl_full_sum_yes"] = str(hl_full.get("sum_yes"))
            discovery["hl_full_sum_no"] = str(hl_full.get("sum_no"))
            discovery["hl_full_completeness_flag"] = str(hl_full.get("completeness_flag"))
    return rows, summary, discovery


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MVP2 PM/HL scanner v0. Read-only: prints opportunity table and exports CSV/JSON.",
    )
    parser.add_argument(
        "--scan",
        choices=(
            "champion",
            "matches",
            "all",
            "pm-match-universe",
            "pm-sports-sample",
            "pm-hl-1v1-sample",
            "pm-hl-1v1-monitor",
            "pm-hl-op1-dry-run",
        ),
        default="all",
    )
    parser.add_argument("--event-slug", default="fifwc-arg-aut-2026-06-22")
    parser.add_argument("--hl-question-name", default=DEFAULT_HL_QUESTION_NAME)
    parser.add_argument("--output-label", default=None)
    parser.add_argument("--duration-minutes", type=float, default=10.0)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--s1-shares", type=float, default=20.0)
    parser.add_argument("--s2-shares", type=float, default=20.0)
    parser.add_argument(
        "--execution-enabled",
        action="store_true",
        help="Dry-run gate flag only for MVP2 op1; no live order submission is implemented.",
    )
    parser.add_argument("--gamma-pages", type=int, default=DEFAULT_GAMMA_PAGES)
    parser.add_argument("--max-champion-markets", type=int, default=0, help="0 means all discovered markets.")
    parser.add_argument("--max-match-markets", type=int, default=0, help="0 means all discovered match candidates.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--table-limit", type=int, default=80)
    parser.add_argument("--no-export", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.scan == "pm-match-universe":
        export_result = export_pm_match_universe(args.output_dir, args.gamma_pages)
        summary = export_result["summary"]
        print("PM World Cup 1v1 candidate universe export (READ ONLY)")
        print(
            "Summary: "
            f"pm_candidates={summary['pm_candidate_count']} "
            f"clearly_parsed={summary['clearly_parsed_count']} "
            f"has_draw={summary['has_draw_count']} "
            f"three_way_like={summary['is_three_way_like_count']}"
        )
        print(f"Top title patterns: {summary['top_title_patterns']}")
        print(f"CSV: {export_result['csv_path']}")
        print(f"JSON: {export_result['json_path']}")
        print(f"Crosswalk template: {export_result['crosswalk_template_path']}")
        return
    if args.scan == "pm-sports-sample":
        discovery = discover_moneyline(args.event_slug)
        print_discovery(discovery)
        if not args.no_export:
            json_path = write_discovery_json(args.output_dir, discovery)
            print(f"JSON: {json_path}")
        return
    if args.scan == "pm-hl-1v1-sample":
        evaluation = evaluate_match(args.event_slug, args.hl_question_name)
        print_evaluation(evaluation)
        if not args.no_export:
            json_path = write_evaluation_json(args.output_dir, evaluation)
            print(f"JSON: {json_path}")
        return
    if args.scan == "pm-hl-1v1-monitor":
        monitor_match(
            output_dir=args.output_dir,
            pm_event_slug=args.event_slug,
            hl_question_name=args.hl_question_name,
            duration_minutes=args.duration_minutes,
            interval_seconds=args.interval_seconds,
            output_label=args.output_label,
        )
        return
    if args.scan == "pm-hl-op1-dry-run":
        monitor_op1_strategy_dry_run(
            output_dir=args.output_dir,
            config=Op1DryRunConfig(
                pm_event_slug=args.event_slug,
                hl_question_name=args.hl_question_name,
                duration_minutes=args.duration_minutes,
                interval_seconds=args.interval_seconds,
                s1_shares=args.s1_shares,
                s2_shares=args.s2_shares,
                execution_enabled=args.execution_enabled,
            ),
        )
        return

    rows, summary, discovery = run_scan(args)
    print_summary(summary, discovery)
    print_table(rows, limit=args.table_limit)

    if not args.no_export:
        stamp = _stamp()
        csv_path = write_csv(args.output_dir / f"pm_hl_mvp2_scanner_{stamp}.csv", rows)
        json_path = write_json(args.output_dir / f"pm_hl_mvp2_scanner_{stamp}.json", rows, summary)
        print(f"CSV: {csv_path}")
        print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

