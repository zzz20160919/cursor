from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_one_shot_test_trade import (  # noqa: E402
    calculate_plan,
    execute_live,
    read_balances,
    validate_live_gates,
    validate_trade_conditions,
)
from scripts.run_pm_hl_s2_exit_executor import (  # noqa: E402
    find_any_position,
    latest_submitted_s2_entry,
)
from scripts.run_pm_hl_watchlist_monitor import get_watchlist_market, hl_taker_fee  # noqa: E402
from src.db import connect, init_db, insert_row  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import OPPORTUNITY_TYPE, pm_fee  # noqa: E402


START_CONFIRMATION_TEXT = "EXECUTE WC PORTUGAL S1 S2 TEST 20 EACH"
VARIANTS = ("S1_HOLD_TO_MATURITY", "S2_EARLY_EXIT")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id(market: str, variant: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"pm_hl_{market}_{variant}_{stamp}"


def entry_log_path(variant: str) -> Path:
    logs = PROJECT_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    prefix = "pm_hl_s1_entry" if variant == "S1_HOLD_TO_MATURITY" else "pm_hl_s2_entry"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return logs / f"{prefix}_{stamp}.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def selected_ask_books(plan: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    books = plan["books"]
    direction = plan["selected"]["direction"]
    if direction == "dir1":
        return books["pm_yes_asks"], books["hl_no_asks"]
    return books["pm_no_asks"], books["hl_yes_asks"]


def walk_combined_executable_size(
    pm_asks: list[tuple[float, float]],
    hl_asks: list[tuple[float, float]],
) -> float:
    pm_levels = [list(level) for level in pm_asks]
    hl_levels = [list(level) for level in hl_asks]
    qty = 0.0
    i = 0
    j = 0
    while i < len(pm_levels) and j < len(hl_levels):
        pm_px, pm_sz = pm_levels[i]
        hl_px, hl_sz = hl_levels[j]
        unit_gross_edge = 1.0 - (pm_px + hl_px)
        unit_estimated_cost = pm_fee(pm_px) + hl_taker_fee()
        unit_net_edge = unit_gross_edge - unit_estimated_cost
        if unit_net_edge < 0:
            break
        take = min(pm_sz, hl_sz)
        if take <= 0:
            break
        qty += take
        pm_levels[i][1] -= take
        hl_levels[j][1] -= take
        if pm_levels[i][1] <= 1e-9:
            i += 1
        if hl_levels[j][1] <= 1e-9:
            j += 1
    return qty


def combined_depth_check(plans: list[dict[str, Any]]) -> dict[str, Any]:
    s1, s2 = plans
    pm_asks, hl_asks = selected_ask_books(s1)
    combined_required_shares = float(s1["shares"]) + float(s2["shares"])
    combined_executable_size = walk_combined_executable_size(pm_asks, hl_asks)
    combined_depth_ok = combined_executable_size + 1e-9 >= combined_required_shares
    suggested_per_strategy_notional = None
    if not combined_depth_ok and s1["entry_cost"]:
        suggested_per_strategy_notional = combined_executable_size * float(s1["entry_cost"]) / 2.0
    return {
        "s1_shares": float(s1["shares"]),
        "s2_shares": float(s2["shares"]),
        "combined_required_shares": combined_required_shares,
        "combined_executable_size": combined_executable_size,
        "combined_depth_ok": combined_depth_ok,
        "suggested_per_strategy_notional": suggested_per_strategy_notional,
        "selected_dir": s1["selected"]["direction"],
        "rule": "walk selected PM/HL direct asks until marginal net_edge would become negative",
    }


def opportunity_status(plan: dict[str, Any]) -> str:
    selected = plan["selected"]
    if selected.get("status") == "data_incomplete":
        return "data_incomplete"
    if float(plan.get("computed_net_edge", selected.get("net_edge")) or 0) <= 0 or plan["expected_profit"] <= 0:
        return "observed_not_actionable"
    return "dry_run_entry_candidate"


def opportunity_raw(
    plan: dict[str, Any],
    status: str,
    combined_depth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = plan["selected"]
    market = plan["market"]
    return {
        "strategy_variant": plan["strategy_variant"],
        "entry_policy": plan["entry_policy"],
        "exit_policy": plan["exit_policy"],
        "early_exit_enabled": plan["early_exit_enabled"],
        "market": market["market"],
        "mapping_status": market["mapping_status"],
        "settlement_date": market.get("settlement_date"),
        "selected_dir": selected["direction"],
        "entry_pm_leg": selected["pm_leg"],
        "entry_hl_leg": selected["hl_leg"],
        "entry_pm_ask": selected["pm_direct_ask"],
        "entry_hl_ask": selected["hl_direct_ask"],
        "entry_cost": plan["entry_cost"],
        "entry_gross_edge": selected["gross_edge"],
        "entry_estimated_cost": selected["estimated_cost"],
        "entry_net_edge": selected["net_edge"],
        "settlement_locked_profit": plan["settlement_locked_profit"],
        "expected_profit": plan["expected_profit"],
        "box_shares_per_strategy": plan.get("box_shares_per_strategy"),
        "gross_profit": plan.get("gross_profit"),
        "estimated_fees": plan.get("estimated_total_fees"),
        "net_edge": plan.get("computed_net_edge"),
        "shares": plan["shares"],
        "pm_leg_notional": plan["pm_leg_notional"],
        "hl_leg_notional": plan["hl_leg_notional"],
        "pm_notional": plan["pm_notional"],
        "hl_notional": plan["hl_notional"],
        "total_notional": plan["total_notional"],
        "target_total_notional": plan["target_total_notional"],
        "required_min_total_notional_for_hl": plan["required_min_total_notional_for_hl"],
        "status": status,
        "combined_depth": combined_depth,
        "rules": {
            "buy_only": True,
            "uses_direct_asks_only": True,
            "uses_mid": False,
            "uses_one_minus_opposite_book": False,
            "no_auto_chase": True,
            "no_auto_repair": True,
        },
    }


def write_opportunity(plan: dict[str, Any], combined_depth: dict[str, Any] | None = None) -> int:
    selected = plan["selected"]
    status = opportunity_status(plan)
    raw = opportunity_raw(plan, status, combined_depth)
    rid = run_id(plan["market"]["market"], plan["strategy_variant"])
    ts = now_iso()
    db_path = init_db()
    with connect(db_path) as conn:
        insert_row(
            conn,
            "runs",
            {
                "run_id": rid,
                "run_type": "pm_hl_s1_s2_start",
                "strategy_id": "pm_hl",
                "started_at": ts,
                "finished_at": ts,
                "status": "dry_run_completed",
                "notes": f"{plan['strategy_variant']} start dry-run",
                "created_at": ts,
            },
        )
        opp_id = insert_row(
            conn,
            "opportunities",
            {
                "run_id": rid,
                "strategy_id": "pm_hl",
                "ts": ts,
                "venue_1": "polymarket",
                "venue_2": "hyperliquid",
                "instrument_1": selected["pm_leg"],
                "instrument_2": selected["hl_leg"],
                "opportunity_type": OPPORTUNITY_TYPE,
                "gross_edge": float(selected["gross_edge"] or 0),
                "estimated_cost": float(selected["estimated_cost"] or 0),
                "net_edge": float(selected["net_edge"] or 0),
                "executable_size": float(selected["executable_size"] or 0),
                "status": status,
                "notes": f"{plan['strategy_variant']} WC Portugal starter dry-run",
                "raw_json": json.dumps(raw, sort_keys=True),
                "created_at": ts,
            },
        )
        conn.commit()
    return opp_id


def print_combined_plan(
    plans: list[dict[str, Any]],
    balances: dict[str, Any],
    depth: dict[str, Any],
) -> None:
    print("COMBINED PM-HL S1/S2 START PLAN")
    print(f"market: {plans[0]['market']['market']}")
    print(f"selected direction: {plans[0]['selected']['direction']}")
    for plan in plans:
        selected = plan["selected"]
        print("-" * 72)
        print(f"strategy_variant: {plan['strategy_variant']}")
        print(f"exit_policy: {plan['exit_policy']}")
        print(f"PM leg: {selected['pm_leg']} token={plan['pm_token']}")
        print(f"HL leg: {selected['hl_leg']} coin={plan['hl_coin']}")
        print(f"PM direct ask: {selected['pm_direct_ask']}")
        print(f"HL direct ask: {selected['hl_direct_ask']}")
        print(f"box_shares_per_strategy: {plan.get('box_shares_per_strategy')}")
        print(f"shares: {plan['shares']:.6f}")
        print(f"pm_leg_notional: {plan['pm_leg_notional']:.6f}")
        print(f"hl_leg_notional: {plan['hl_leg_notional']:.6f}")
        print(f"total_notional: {plan['total_notional']:.6f}")
        print(f"target_total_notional: {plan['target_total_notional']:.6f}")
        print(f"required_min_total_notional_for_hl: {plan['required_min_total_notional_for_hl']}")
        print(f"gross_profit: {plan['gross_profit']:.6f}")
        print(f"estimated_fees: {plan['estimated_total_fees']:.6f}")
        print(f"expected_profit: {plan['expected_profit']:.6f}")
        print(f"net_edge: {plan['computed_net_edge']:.6f}")
        print(f"entry_cost: {plan['entry_cost']:.6f}")
        print(f"order sequence: {' -> '.join(plan['order_sequence'])}")
    print("-" * 72)
    print(f"total expected notional: {sum(p['total_notional'] for p in plans):.6f}")
    print(f"net_edge: {plans[0]['computed_net_edge']:.6f}")
    print(f"s1_shares: {depth['s1_shares']:.6f}")
    print(f"s2_shares: {depth['s2_shares']:.6f}")
    print(f"combined_required_shares: {depth['combined_required_shares']:.6f}")
    print(f"combined_executable_size: {depth['combined_executable_size']:.6f}")
    print(f"combined_depth_ok: {str(depth['combined_depth_ok']).lower()}")
    print(f"suggested_per_strategy_notional: {depth['suggested_per_strategy_notional']}")
    print(f"balances before: {json.dumps(balances, default=str, sort_keys=True)}")
    print("combined execution order: S1_HOLD_TO_MATURITY -> S2_EARLY_EXIT")


def combined_prechecks(
    plans: list[dict[str, Any]],
    balances: dict[str, Any],
    market_key: str,
    max_total_notional_per_strategy: float,
    live: bool,
    depth: dict[str, Any],
    market: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    active_s2 = s2_active_guard(market)
    if active_s2["active"]:
        failures.append(f"S2 active guard: {active_s2['reason']}")
    if live:
        failures.extend(validate_live_gates(market_key, max_total_notional_per_strategy))
    if not depth["combined_depth_ok"]:
        failures.append(
            "combined depth insufficient: "
            f"required {depth['combined_required_shares']:.6f} shares, "
            f"executable {depth['combined_executable_size']:.6f} shares"
        )
    for plan in plans:
        failures.extend(
            f"{plan['strategy_variant']}: {failure}"
            for failure in validate_trade_conditions(plan, balances, max_total_notional_per_strategy)
        )
    pm_cash = balances.get("pm_cash")
    if pm_cash is not None:
        total_pm = sum(float(plan["pm_notional"]) for plan in plans)
        if pm_cash < total_pm:
            failures.append(f"PM cash insufficient for S1+S2: ${pm_cash:.2f} < ${total_pm:.2f}")
    hl_usdc = balances.get("hl_usdc")
    if hl_usdc is not None:
        total_hl = sum(float(plan["hl_notional"]) for plan in plans)
        if hl_usdc < total_hl:
            failures.append(f"HL USDC insufficient for S1+S2: ${hl_usdc:.2f} < ${total_hl:.2f}")
    return failures


def s2_active_guard(market: dict[str, Any]) -> dict[str, Any]:
    entry = latest_submitted_s2_entry(market["market"])
    if entry is not None:
        return {
            "active": True,
            "reason": f"submitted S2 entry log exists: {entry.get('_log_path')}",
            "entry_log": entry.get("_log_path"),
        }
    position = find_any_position(market)
    if position is not None:
        return {
            "active": True,
            "reason": "matching WC Portugal box position exists but cannot be proven exited",
            "position": position,
        }
    return {"active": False, "reason": "no active S2 entry log or matching position detected"}


def log_plan(
    plan: dict[str, Any],
    balances: dict[str, Any],
    status: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "ts": now_iso(),
        "status": status,
        "strategy_variant": plan["strategy_variant"],
        "entry_policy": plan["entry_policy"],
        "exit_policy": plan["exit_policy"],
        "early_exit_enabled": plan["early_exit_enabled"],
        "settlement_date": plan.get("settlement_date"),
        "plan": plan,
        "balances_before": balances,
    }
    if extra:
        payload.update(extra)
    path = entry_log_path(plan["strategy_variant"])
    write_json(path, payload)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start PM-HL WC Portugal S1 and S2 entries.")
    parser.add_argument("--market", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--box-shares-per-strategy", type=float, default=None)
    parser.add_argument("--max-total-notional-per-strategy", type=float, default=20.0)
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--start-exit-monitor-dry-run", action="store_true")
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    market = get_watchlist_market(args.market)
    dry_run = not args.live
    plans = [
        calculate_plan(
            market,
            args.max_total_notional_per_strategy,
            variant,
            box_shares=args.box_shares_per_strategy,
        )
        for variant in VARIANTS
    ]
    depth = combined_depth_check(plans)
    balances = read_balances(dry_run=dry_run)
    print_combined_plan(plans, balances, depth)
    s2_guard = s2_active_guard(market)
    print(f"s2_active_guard_active: {str(s2_guard['active']).lower()}")
    print(f"s2_active_guard_reason: {s2_guard['reason']}")

    failures = combined_prechecks(
        plans,
        balances,
        args.market,
        args.max_total_notional_per_strategy,
        live=args.live,
        depth=depth,
        market=market,
    )
    for plan in plans:
        opp_id = write_opportunity(plan, depth)
        log_path = log_plan(
            plan,
            balances,
            "dry_run_no_order" if dry_run else "pending",
            {
                "opportunity_id": opp_id,
                "precheck_failures": failures,
                "combined_depth": depth,
                "s2_active_guard": s2_guard,
            },
        )
        print(f"{plan['strategy_variant']} log_file: {log_path}")

    if failures:
        print("PRECHECK FAILED:")
        for failure in failures:
            print(f"  - {failure}")

    if dry_run:
        print("DRY-RUN: no orders placed.")
        if args.start_exit_monitor_dry_run:
            print("Exit monitor dry-run requested; run scripts/run_pm_hl_s2_exit_executor.py separately for controlled exit checks.")
        return

    if failures:
        print("ABORT: prechecks failed; no orders placed.")
        return

    confirmation = input(f'Type "{START_CONFIRMATION_TEXT}" to execute S1 then S2: ')
    if confirmation != START_CONFIRMATION_TEXT:
        print("ABORT: confirmation text mismatch; no orders placed.")
        return

    s1_result = None
    try:
        s1_result = execute_live(plans[0])
        log_plan(plans[0], balances, "submitted", {"execution": s1_result})
    except Exception as exc:
        print(f"S1 failed: {exc}")
        print("ORPHAN WARNING: verify PM/HL balances manually before further action.")
        log_plan(plans[0], balances, "execution_error_or_orphan_warning", {"execution_error": str(exc)})
        print("ABORT: S1 failed; S2 will not execute.")
        return

    try:
        s2_result = execute_live(plans[1])
        log_plan(plans[1], balances, "submitted", {"execution": s2_result, "s1_result": s1_result})
    except Exception as exc:
        print(f"S2 failed: {exc}")
        print("ORPHAN WARNING: verify PM/HL balances manually before further action.")
        log_plan(plans[1], balances, "execution_error_or_orphan_warning", {"execution_error": str(exc), "s1_result": s1_result})
        return

    balances_after = read_balances(dry_run=False)
    print(f"balances after: {json.dumps(balances_after, default=str, sort_keys=True)}")


if __name__ == "__main__":
    main()
