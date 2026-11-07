from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_watchlist_monitor import (  # noqa: E402
    calculate_opportunity,
    get_watchlist_market,
    read_books,
)
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


CONFIRMATION_TEXT = "EXECUTE WC PORTUGAL TEST 10"
DEFAULT_PM_MIN_SHARES = 5.0
DEFAULT_HL_MIN_NOTIONAL = 10.0
DEFAULT_PM_MIN_NOTIONAL = 1.0
DEFAULT_SHARE_PRECISION = 0.000001
STRATEGY_VARIANTS = ("S1_HOLD_TO_MATURITY", "S2_EARLY_EXIT")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def allowed_markets() -> set[str]:
    return {item.strip() for item in os.environ.get("ALLOWED_MARKETS", "").split(",") if item.strip()}


def stop_file_exists() -> bool:
    return (PROJECT_ROOT / "STOP").exists()


def max_order_notional() -> float:
    return float(os.environ.get("MAX_ORDER_NOTIONAL", "100") or 100)


def hl_min_notional() -> float:
    return float(os.environ.get("HL_MIN_NOTIONAL", str(DEFAULT_HL_MIN_NOTIONAL)) or DEFAULT_HL_MIN_NOTIONAL)


def pm_min_notional() -> float:
    return float(os.environ.get("PM_MIN_NOTIONAL", str(DEFAULT_PM_MIN_NOTIONAL)) or DEFAULT_PM_MIN_NOTIONAL)


def share_precision() -> float:
    return float(os.environ.get("SHARE_PRECISION", str(DEFAULT_SHARE_PRECISION)) or DEFAULT_SHARE_PRECISION)


def floor_by_precision(value: float, precision: float | None = None) -> float:
    step = precision or share_precision()
    if step <= 0:
        return value
    return math.floor(value / step) * step


def selected_tokens(market: dict[str, Any], selected_dir: str) -> tuple[str, str]:
    if selected_dir == "dir1":
        return str(market["pm_yes"]), str(market["hl_no_coin"])
    return str(market["pm_no"]), str(market["hl_yes_coin"])


def exit_policy_for(strategy_variant: str) -> str:
    if strategy_variant == "S2_EARLY_EXIT":
        return "exit_if_profit_available"
    return "hold_to_resolution"


def calculate_plan(
    market: dict[str, Any],
    max_total_notional: float,
    strategy_variant: str,
    box_shares: float | None = None,
) -> dict[str, Any]:
    books = read_books(market)
    opportunity = calculate_opportunity(market, books)
    selected = opportunity["selected"]
    pm_token, hl_coin = selected_tokens(market, selected["direction"])
    pm_ask = float(selected["pm_direct_ask"] or 0)
    hl_ask = float(selected["hl_direct_ask"] or 0)
    unit_cost = pm_ask + hl_ask
    sizing_mode = "shares" if box_shares is not None else "notional"
    shares = (
        floor_by_precision(float(box_shares))
        if box_shares is not None
        else floor_by_precision(max_total_notional / unit_cost) if unit_cost > 0 else 0.0
    )
    executable_size = float(selected["executable_size"] or 0)
    pm_leg_notional = shares * pm_ask
    hl_leg_notional = shares * hl_ask
    total_notional = pm_leg_notional + hl_leg_notional
    pm_fee_total = shares * 0.03 * pm_ask * (1 - pm_ask)
    hl_fee_total = shares * hl_ask * float(os.environ.get("HL_TAKER_FEE", "0") or 0)
    estimated_total_fees = pm_fee_total + hl_fee_total
    gross_profit = shares * (1 - pm_ask - hl_ask)
    expected_profit = gross_profit - estimated_total_fees
    net_edge = expected_profit / total_notional if total_notional > 0 else 0.0
    entry_cost = pm_ask + hl_ask
    settlement_locked_profit = expected_profit
    required_min_total_notional_for_hl = (
        floor_by_precision(hl_min_notional() / hl_ask + share_precision()) * entry_cost
        if hl_ask > 0
        else None
    )
    return {
        "strategy_variant": strategy_variant,
        "entry_policy": "buy_pm_and_buy_hl_complement_direct_asks",
        "exit_policy": exit_policy_for(strategy_variant),
        "early_exit_enabled": strategy_variant == "S2_EARLY_EXIT" and bool(market.get("allow_early_exit", False)),
        "settlement_date": market.get("settlement_date"),
        "market": market,
        "books": books,
        "opportunity": opportunity,
        "selected": selected,
        "pm_token": pm_token,
        "hl_coin": hl_coin,
        "sizing_mode": sizing_mode,
        "box_shares_per_strategy": shares if box_shares is not None else None,
        "shares": shares,
        "pm_leg_notional": pm_leg_notional,
        "hl_leg_notional": hl_leg_notional,
        "pm_notional": pm_leg_notional,
        "hl_notional": hl_leg_notional,
        "total_notional": total_notional,
        "target_total_notional": max_total_notional,
        "required_min_total_notional_for_hl": required_min_total_notional_for_hl,
        "executable_size": executable_size,
        "estimated_total_fees": estimated_total_fees,
        "pm_fee": pm_fee_total,
        "hl_fee": hl_fee_total,
        "gross_profit": gross_profit,
        "computed_net_edge": net_edge,
        "entry_cost": entry_cost,
        "settlement_locked_profit": settlement_locked_profit,
        "expected_profit": expected_profit,
        "order_sequence": ["PM", "HL"] if pm_leg_notional <= hl_leg_notional else ["HL", "PM"],
    }


def read_balances(dry_run: bool) -> dict[str, Any]:
    balances: dict[str, Any] = {
        "pm_cash": None,
        "hl_usdc": None,
        "pm_positions": None,
        "hl_spot": None,
        "errors": [],
    }
    try:
        if not dry_run:
            client = pm.build_client()
            cash, _ = pm.get_cash(client)
            balances["pm_cash"] = float(cash or 0)
        else:
            balances["pm_cash"] = None
    except Exception as exc:
        balances["errors"].append(f"PM cash unavailable: {str(exc)[:120]}")
    try:
        positions = pm.get_positions(pm.get_funder())
        balances["pm_positions"] = positions if isinstance(positions, list) else []
    except Exception as exc:
        balances["errors"].append(f"PM positions unavailable: {str(exc)[:120]}")
    try:
        spot = hl.spot_balances(hl.get_account())
        balances["hl_spot"] = spot
        balances["hl_usdc"] = float(dict(spot).get("USDC", 0.0))
    except Exception as exc:
        balances["errors"].append(f"HL spot unavailable: {str(exc)[:120]}")
    return balances


def validate_live_gates(market_key: str, max_total_notional: float) -> list[str]:
    failures = []
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED must be true")
    if not bool_env("REQUIRE_MANUAL_CONFIRMATION", True):
        failures.append("REQUIRE_MANUAL_CONFIRMATION must be true")
    if market_key not in allowed_markets():
        failures.append(f"ALLOWED_MARKETS must include {market_key}")
    if max_order_notional() < max_total_notional:
        failures.append(f"MAX_ORDER_NOTIONAL must be >= {max_total_notional}")
    if stop_file_exists():
        failures.append("STOP file exists")
    if pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")):
        failures.append("Missing PM_FUNDER or PM_PRIVATE_KEY")
    if hl.missing_env(("HL_ACCOUNT", "HL_AGENT_KEY")):
        failures.append("Missing HL_ACCOUNT or HL_AGENT_KEY")
    return failures


def validate_trade_conditions(
    plan: dict[str, Any],
    balances: dict[str, Any],
    max_total_notional: float,
) -> list[str]:
    market = plan["market"]
    selected = plan["selected"]
    failures = []
    if market.get("mapping_status") != "verified":
        failures.append("mapping_status is not verified")
    if float(plan.get("computed_net_edge", selected["net_edge"]) or 0) <= 0:
        failures.append("net_edge must be > 0")
    if plan["expected_profit"] <= 0:
        failures.append("expected_profit must be > 0")
    if plan["total_notional"] > max_total_notional + 1e-9:
        failures.append(f"total_notional must be <= {max_total_notional}")
    if plan["shares"] < DEFAULT_PM_MIN_SHARES:
        failures.append(f"PM leg min order size not OK: shares {plan['shares']:.4f} < {DEFAULT_PM_MIN_SHARES}")
    if plan["pm_leg_notional"] < pm_min_notional():
        failures.append(
            f"PM leg notional not OK: ${plan['pm_leg_notional']:.4f} < ${pm_min_notional():.2f}"
        )
    if plan["hl_notional"] < hl_min_notional():
        required = plan.get("required_min_total_notional_for_hl")
        suffix = f"; required_min_total_notional_for_hl=${required:.4f}" if required is not None else ""
        failures.append(f"HL leg min notional not OK: ${plan['hl_notional']:.4f} < ${hl_min_notional():.2f}{suffix}")
    pm_cash = balances.get("pm_cash")
    if pm_cash is not None and pm_cash < plan["pm_notional"]:
        failures.append(f"PM cash insufficient: ${pm_cash:.2f} < ${plan['pm_notional']:.2f}")
    hl_usdc = balances.get("hl_usdc")
    if hl_usdc is not None and hl_usdc < plan["hl_notional"]:
        failures.append(f"HL USDC insufficient: ${hl_usdc:.2f} < ${plan['hl_notional']:.2f}")
    return failures


def print_plan(plan: dict[str, Any], balances: dict[str, Any]) -> None:
    selected = plan["selected"]
    market = plan["market"]
    print("ONE-SHOT PM-HL TEST TRADE PLAN")
    print(f"market: {market['market']}")
    print(f"strategy_variant: {plan['strategy_variant']}")
    print(f"entry_policy: {plan['entry_policy']}")
    print(f"exit_policy: {plan['exit_policy']}")
    print(f"early_exit_enabled: {plan['early_exit_enabled']}")
    print(f"mapping_status: {market['mapping_status']}")
    print(f"payoff_description: {market['payoff_description']}")
    print(f"selected direction: {selected['direction']}")
    print(f"PM leg: {selected['pm_leg']} token={plan['pm_token']}")
    print(f"HL leg: {selected['hl_leg']} coin={plan['hl_coin']}")
    print(f"PM direct ask: {selected['pm_direct_ask']}")
    print(f"HL direct ask: {selected['hl_direct_ask']}")
    print(f"shares: {plan['shares']:.6f}")
    print(f"pm_leg_notional: {plan['pm_leg_notional']:.6f}")
    print(f"hl_leg_notional: {plan['hl_leg_notional']:.6f}")
    print(f"total notional: {plan['total_notional']:.6f}")
    print(f"target total notional: {plan['target_total_notional']:.6f}")
    print(f"required_min_total_notional_for_hl: {plan['required_min_total_notional_for_hl']}")
    print(f"estimated fees: {plan['estimated_total_fees']:.6f}")
    print(f"entry_cost: {plan['entry_cost']:.6f}")
    print(f"settlement_locked_profit: {plan['settlement_locked_profit']:.6f}")
    print(f"gross_edge: {selected['gross_edge']:.6f}")
    print(f"net_edge: {selected['net_edge']:.6f}")
    print(f"expected_profit: {plan['expected_profit']:.6f}")
    print(f"balances before: {json.dumps(balances, default=str, sort_keys=True)}")
    print(f"exact order sequence: {' -> '.join(plan['order_sequence'])} using immediate-or-cancel style buys")


def pm_ioc_buy(client: Any, token: str, price: float, shares: float) -> Any:
    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    _, _, tick_size, neg_risk = pm.top(token)
    limit_price = min(round(price, 4), 0.999)
    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=limit_price, size=shares, side=Side.BUY),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.FAK,
    )


def hl_ioc_buy(exchange: Any, coin: str, price: float, shares: float) -> Any:
    limit_price = min(round(price * 1.02, 6), 0.999)
    return exchange.order(coin, True, shares, limit_price, {"limit": {"tif": "Ioc"}})


def response_indicates_failure(venue: str, response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    if response.get("error") or response.get("blocked"):
        return True
    if venue == "PM":
        if response.get("success") is False:
            return True
        if response.get("status") in {"failed", "rejected", "cancelled"}:
            return True
    if venue == "HL":
        try:
            status = response["response"]["data"]["statuses"][0]
        except Exception:
            return True
        if "error" in status or "filled" not in status:
            return True
        try:
            return float(status["filled"].get("totalSz", 0) or 0) <= 0
        except Exception:
            return True
    return False


def filled_shares(venue: str, response: Any) -> float:
    if venue == "PM" and isinstance(response, dict):
        return float(response.get("takingAmount") or 0)
    if venue == "HL" and isinstance(response, dict):
        try:
            status = response["response"]["data"]["statuses"][0]
            return float(status["filled"].get("totalSz", 0) or 0)
        except Exception:
            return 0.0
    return 0.0


def assert_target_fill(venue: str, response: Any, target_shares: float, tolerance: float = 1e-6) -> None:
    filled = filled_shares(venue, response)
    if abs(filled - target_shares) > tolerance:
        raise RuntimeError(
            f"{venue} filled shares mismatch: filled={filled:.6f}, target={target_shares:.6f}"
        )


def execute_live(plan: dict[str, Any]) -> dict[str, Any]:
    pm_client = pm.build_client()
    hl_exchange, agent_address, account = hl.build_exchange()
    results: dict[str, Any] = {"agent_address": agent_address, "hl_account": account, "orders": []}
    selected = plan["selected"]
    for order_index, venue in enumerate(plan["order_sequence"]):
        try:
            if venue == "PM":
                response = pm_ioc_buy(
                    pm_client,
                    plan["pm_token"],
                    float(selected["pm_direct_ask"]),
                    float(plan["shares"]),
                )
            else:
                response = hl_ioc_buy(
                    hl_exchange,
                    plan["hl_coin"],
                    float(selected["hl_direct_ask"]),
                    float(plan["shares"]),
                )
            results["orders"].append({"venue": venue, "response": response})
            if response_indicates_failure(venue, response):
                if order_index == 1:
                    print("ORPHAN WARNING: first leg may have executed but second leg failed. Manual review required.")
                raise RuntimeError(f"{venue} IOC/FAK response indicates failure")
            assert_target_fill(venue, response, float(plan["shares"]))
        except Exception as exc:
            results["orders"].append({"venue": venue, "error": str(exc)})
            if order_index == 0:
                print("ORDER WARNING: first leg did not fill exactly as targeted. Manual review required before any next action.")
            if order_index == 1:
                print("ORPHAN WARNING: first leg may have executed but second leg failed. Manual review required.")
            raise
    return results


def write_log(payload: dict[str, Any]) -> Path:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"pm_hl_test_trade_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot controlled PM-HL test trade.")
    parser.add_argument("--market", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--strategy-variant",
        choices=STRATEGY_VARIANTS,
        default="S1_HOLD_TO_MATURITY",
    )
    parser.add_argument("--max-total-notional", type=float, default=10.0)
    parser.add_argument("--once", action="store_true", required=True)
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    market = get_watchlist_market(args.market)
    if args.strategy_variant not in market.get("enabled_strategies", []):
        raise SystemExit(f"Strategy variant not enabled for market: {args.strategy_variant}")
    plan = calculate_plan(market, args.max_total_notional, args.strategy_variant)
    dry_run = not args.live
    balances_before = read_balances(dry_run=dry_run)
    print_plan(plan, balances_before)

    live_gate_failures = validate_live_gates(args.market, args.max_total_notional) if args.live else []
    condition_failures = validate_trade_conditions(plan, balances_before, args.max_total_notional)
    if live_gate_failures:
        print("LIVE GATE CHECK FAILED:")
        for failure in live_gate_failures:
            print(f"  - {failure}")
    if condition_failures:
        print("TRADE CONDITION CHECK FAILED:")
        for failure in condition_failures:
            print(f"  - {failure}")

    payload: dict[str, Any] = {
        "ts": now_iso(),
        "dry_run": dry_run,
        "market": args.market,
        "plan": plan,
        "balances_before": balances_before,
        "live_gate_failures": live_gate_failures,
        "condition_failures": condition_failures,
        "status": "dry_run_no_order" if dry_run else "pending",
    }

    if dry_run:
        print("DRY-RUN: no orders placed.")
        path = write_log(payload)
        print(f"log_file: {path}")
        return

    if live_gate_failures or condition_failures:
        payload["status"] = "aborted_precheck_failed"
        path = write_log(payload)
        print("ABORT: prechecks failed; no orders placed.")
        print(f"log_file: {path}")
        return

    confirmation = input(f'Type "{CONFIRMATION_TEXT}" to execute: ')
    if confirmation != CONFIRMATION_TEXT:
        payload["status"] = "aborted_confirmation_mismatch"
        path = write_log(payload)
        print("ABORT: confirmation text mismatch; no orders placed.")
        print(f"log_file: {path}")
        return

    try:
        payload["execution"] = execute_live(plan)
        payload["status"] = "submitted"
    except Exception as exc:
        payload["status"] = "execution_error_or_orphan_warning"
        payload["execution_error"] = str(exc)
        print(f"Execution error: {exc}")
        print("ORPHAN WARNING: verify PM and HL balances/positions manually before any further action.")
    payload["balances_after"] = read_balances(dry_run=False)
    path = write_log(payload)
    print(f"log_file: {path}")


if __name__ == "__main__":
    main()
