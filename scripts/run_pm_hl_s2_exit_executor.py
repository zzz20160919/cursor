from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_one_shot_test_trade import (  # noqa: E402
    allowed_markets,
    bool_env,
    response_indicates_failure,
    stop_file_exists,
)
from scripts.run_pm_hl_watchlist_monitor import get_watchlist_market  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import pm_fee  # noqa: E402


CONFIRMATION_TEXT = "EXECUTE WC PORTUGAL S2 EXIT"
STRATEGY_VARIANT = "S2_EARLY_EXIT"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hl_taker_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def logs_dir() -> Path:
    path = PROJECT_ROOT / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_exit_log(payload: dict[str, Any]) -> Path:
    path = logs_dir() / f"pm_hl_s2_exit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def latest_submitted_s2_entry(market_key: str) -> dict[str, Any] | None:
    candidates = sorted(logs_dir().glob("pm_hl_s2_entry_*.json"), reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        plan = payload.get("plan", {})
        market = plan.get("market", {})
        if (
            payload.get("status") == "submitted"
            and plan.get("strategy_variant") == STRATEGY_VARIANT
            and market.get("market") == market_key
        ):
            payload["_log_path"] = str(path)
            return payload
    return None


def pm_position_size(token: str) -> float:
    positions = pm.get_positions(pm.get_funder())
    for position in positions if isinstance(positions, list) else []:
        if str(position.get("asset")) == token:
            return float(position.get("size", 0) or 0)
    return 0.0


def hl_position_size(coin: str) -> float:
    balances = dict(hl.spot_balances(hl.get_account()))
    aliases = [coin, "+" + coin.lstrip("#")]
    for alias in aliases:
        if alias in balances:
            return float(balances[alias] or 0)
    return 0.0


def bid_for_pm(token: str) -> float | None:
    bids, _, _ = pm.book(token)
    return bids[0][0] if bids else None


def bid_for_hl(coin: str) -> float | None:
    bids, _ = hl.coin_book(coin)
    return bids[0][0] if bids else None


def fallback_leg_configs(market: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "direction": "dir1",
            "held_pm_leg": "PM Portugal YES",
            "held_hl_leg": "HL Portugal NO",
            "pm_token": str(market["pm_yes"]),
            "hl_coin": str(market["hl_no_coin"]),
        },
        {
            "direction": "dir2",
            "held_pm_leg": "PM Portugal NO",
            "held_hl_leg": "HL Portugal YES",
            "pm_token": str(market["pm_no"]),
            "hl_coin": str(market["hl_yes_coin"]),
        },
    ]


def leg_config_from_entry(entry: dict[str, Any], market: dict[str, Any]) -> dict[str, str]:
    plan = entry["plan"]
    return {
        "direction": plan["selected"]["direction"],
        "held_pm_leg": plan["selected"]["pm_leg"],
        "held_hl_leg": plan["selected"]["hl_leg"],
        "pm_token": plan["pm_token"],
        "hl_coin": plan["hl_coin"],
    }


def find_any_position(market: dict[str, Any]) -> dict[str, Any] | None:
    for cfg in fallback_leg_configs(market):
        shares_pm = pm_position_size(cfg["pm_token"])
        shares_hl = hl_position_size(cfg["hl_coin"])
        if shares_pm > 0 or shares_hl > 0:
            return {**cfg, "shares_pm": shares_pm, "shares_hl": shares_hl}
    return None


def profit_bps(realized_profit: float, original_entry_cost: float) -> float:
    if original_entry_cost <= 0:
        return 0.0
    return realized_profit / original_entry_cost * 10000


def analyze_exit(market: dict[str, Any]) -> dict[str, Any]:
    min_usd = float(market.get("min_early_exit_profit_usd", 0.03) or 0.03)
    min_bps = float(market.get("min_early_exit_profit_bps", 20.0) or 20.0)
    entry = latest_submitted_s2_entry(market["market"])
    if entry is None:
        any_position = find_any_position(market)
        if any_position is None:
            return {
                "strategy_variant": STRATEGY_VARIANT,
                "market": market["market"],
                "min_early_exit_profit_usd": min_usd,
                "min_early_exit_profit_bps": min_bps,
                "realized_profit_if_exit": None,
                "realized_profit_bps": None,
                "exit_allowed": False,
                "status": "no_position",
                "reason": "no submitted S2 entry log and no matching WC Portugal box position found",
            }
        return {
            "strategy_variant": STRATEGY_VARIANT,
            "market": market["market"],
            "min_early_exit_profit_usd": min_usd,
            "min_early_exit_profit_bps": min_bps,
            "realized_profit_if_exit": None,
            "realized_profit_bps": None,
            "exit_allowed": False,
            "status": "cannot_distinguish_s1_s2_position",
            "reason": "position exists but no submitted S2 entry log was found",
            **any_position,
        }

    cfg = leg_config_from_entry(entry, market)
    shares_pm = pm_position_size(cfg["pm_token"])
    shares_hl = hl_position_size(cfg["hl_coin"])
    matched_box_shares = min(shares_pm, shares_hl)
    if shares_pm != shares_hl:
        status = "orphan_position"
    elif matched_box_shares <= 0:
        status = "no_position"
    else:
        status = "observed"

    pm_bid = bid_for_pm(cfg["pm_token"]) if shares_pm > 0 else None
    hl_bid = bid_for_hl(cfg["hl_coin"]) if shares_hl > 0 else None
    original_entry_cost_per_share = entry.get("plan", {}).get("entry_cost")
    original_entry_shares = float(entry.get("plan", {}).get("shares") or 0)
    original_entry_cost = (
        float(original_entry_cost_per_share) * min(matched_box_shares, original_entry_shares)
        if original_entry_cost_per_share is not None
        else None
    )

    exit_value = None
    estimated_exit_fees = None
    realized_profit_if_exit = None
    profit_bps_value = None
    if matched_box_shares > 0:
        if pm_bid is None or hl_bid is None:
            status = "data_incomplete"
        elif original_entry_cost is None:
            status = "entry_cost_unknown"
        elif status == "observed":
            estimated_exit_fees = (pm_fee(pm_bid) + hl_taker_fee()) * matched_box_shares
            exit_value = pm_bid + hl_bid
            realized_profit_if_exit = exit_value * matched_box_shares - original_entry_cost - estimated_exit_fees
            profit_bps_value = profit_bps(realized_profit_if_exit, original_entry_cost)
            status = (
                "early_exit_candidate"
                if realized_profit_if_exit > min_usd and profit_bps_value > min_bps
                else "no_early_exit"
            )
    exit_allowed = status == "early_exit_candidate"

    return {
        "strategy_variant": STRATEGY_VARIANT,
        "market": market["market"],
        "min_early_exit_profit_usd": min_usd,
        "min_early_exit_profit_bps": min_bps,
        "entry_log": entry.get("_log_path"),
        "direction": cfg["direction"],
        "held_pm_leg": cfg["held_pm_leg"],
        "held_hl_leg": cfg["held_hl_leg"],
        "pm_token": cfg["pm_token"],
        "hl_coin": cfg["hl_coin"],
        "shares_pm": shares_pm,
        "shares_hl": shares_hl,
        "matched_box_shares": matched_box_shares,
        "pm_bid": pm_bid,
        "hl_bid": hl_bid,
        "exit_value": exit_value,
        "estimated_exit_fees": estimated_exit_fees,
        "original_entry_cost": original_entry_cost,
        "original_entry_cost_per_share": original_entry_cost_per_share,
        "realized_profit_if_exit": realized_profit_if_exit,
        "realized_profit_bps": profit_bps_value,
        "profit_bps": profit_bps_value,
        "exit_allowed": exit_allowed,
        "status": status,
        "rules": {
            "read_only_until_live_confirmed": True,
            "uses_direct_bids_only": True,
            "uses_mid": False,
            "uses_synthetic_prices": False,
            "uses_one_minus_opposite_book": False,
            "no_short": True,
            "no_sell_above_real_position": True,
            "no_auto_chase": True,
            "no_auto_repair": True,
        },
    }


def live_gate_failures(market_key: str, analysis: dict[str, Any]) -> list[str]:
    failures = []
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED must be true")
    if not bool_env("REQUIRE_MANUAL_CONFIRMATION", True):
        failures.append("REQUIRE_MANUAL_CONFIRMATION must be true")
    if market_key not in allowed_markets():
        failures.append(f"ALLOWED_MARKETS must include {market_key}")
    if stop_file_exists():
        failures.append("STOP file exists")
    if not analysis.get("exit_allowed"):
        failures.append(f"exit_allowed must be true, got {analysis.get('exit_allowed')}")
    if float(analysis.get("matched_box_shares") or 0) <= 0:
        failures.append("matched_box_shares must be > 0")
    if analysis.get("original_entry_cost") is None:
        failures.append("original_entry_cost is required")
    if analysis.get("pm_bid") is None or analysis.get("hl_bid") is None:
        failures.append("PM bid and HL bid must both be available")
    if pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")):
        failures.append("Missing PM_FUNDER or PM_PRIVATE_KEY")
    if hl.missing_env(("HL_ACCOUNT", "HL_AGENT_KEY")):
        failures.append("Missing HL_ACCOUNT or HL_AGENT_KEY")
    return failures


def print_exit_plan(analysis: dict[str, Any]) -> None:
    print("PM-HL S2 EXIT PLAN")
    print(f"market: {analysis.get('market')}")
    print(f"strategy_variant={STRATEGY_VARIANT}")
    print(f"status: {analysis.get('status')}")
    print(f"reason: {analysis.get('reason')}")
    print(f"min_early_exit_profit_bps: {analysis.get('min_early_exit_profit_bps')}")
    print(f"min_early_exit_profit_usd: {analysis.get('min_early_exit_profit_usd')}")
    print(f"held PM leg: {analysis.get('held_pm_leg')}")
    print(f"held HL leg: {analysis.get('held_hl_leg')}")
    print(f"matched_box_shares: {analysis.get('matched_box_shares')}")
    print(f"original_entry_cost: {analysis.get('original_entry_cost')}")
    print(f"PM bid: {analysis.get('pm_bid')}")
    print(f"HL bid: {analysis.get('hl_bid')}")
    print(f"exit_value: {analysis.get('exit_value')}")
    print(f"estimated_exit_fees: {analysis.get('estimated_exit_fees')}")
    print(f"realized_profit_if_exit: {analysis.get('realized_profit_if_exit')}")
    print(f"realized_profit_bps: {analysis.get('realized_profit_bps')}")
    print(f"exit_allowed: {str(bool(analysis.get('exit_allowed'))).lower()}")
    print(f"expected profit USD: {analysis.get('realized_profit_if_exit')}")
    print("exact exit order sequence: PM SELL FAK -> HL SELL IOC")


def pm_ioc_sell(client: Any, token: str, bid: float, shares: float) -> Any:
    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    _, _, tick_size, neg_risk = pm.top(token)
    limit_price = max(round(bid - 0.005, 3), 0.001)
    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=limit_price, size=int(round(shares)), side=Side.SELL),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.FAK,
    )


def hl_ioc_sell(exchange: Any, coin: str, bid: float, shares: float) -> Any:
    limit_price = max(round(bid * 0.98, 6), 0.001)
    return exchange.order(coin, False, shares, limit_price, {"limit": {"tif": "Ioc"}})


def execute_exit(analysis: dict[str, Any]) -> dict[str, Any]:
    shares = float(analysis["matched_box_shares"])
    pm_client = pm.build_client()
    hl_exchange, agent_address, account = hl.build_exchange()
    results: dict[str, Any] = {"agent_address": agent_address, "hl_account": account, "orders": []}
    sequence = ("PM", "HL")
    for order_index, venue in enumerate(sequence):
        try:
            if venue == "PM":
                response = pm_ioc_sell(pm_client, analysis["pm_token"], float(analysis["pm_bid"]), shares)
            else:
                response = hl_ioc_sell(hl_exchange, analysis["hl_coin"], float(analysis["hl_bid"]), shares)
            results["orders"].append({"venue": venue, "response": response})
            if response_indicates_failure(venue, response):
                if order_index == 1:
                    print("ORPHAN WARNING: PM exit may have executed but HL exit failed. Manual review required.")
                raise RuntimeError(f"{venue} exit response indicates failure")
        except Exception as exc:
            results["orders"].append({"venue": venue, "error": str(exc)})
            if order_index == 1:
                print("ORPHAN WARNING: first exit leg may have executed but second failed. Manual review required.")
            raise
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled S2 early-exit executor.")
    parser.add_argument("--market", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--max-loops", type=int, default=None)
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    market = get_watchlist_market(args.market)
    dry_run = not args.live
    loops = 0
    while True:
        loops += 1
        analysis = analyze_exit(market)
        print_exit_plan(analysis)
        failures = live_gate_failures(args.market, analysis) if args.live else []
        payload = {
            "ts": now_iso(),
            "dry_run": dry_run,
            "market": args.market,
            "analysis": analysis,
            "live_gate_failures": failures,
            "status": "dry_run_no_order" if dry_run else "pending",
        }
        if failures:
            print("LIVE EXIT GATE CHECK FAILED:")
            for failure in failures:
                print(f"  - {failure}")
        if dry_run:
            print("DRY-RUN: no exit orders placed.")
            path = write_exit_log(payload)
            print(f"log_file: {path}")
        elif failures:
            payload["status"] = "aborted_precheck_failed"
            path = write_exit_log(payload)
            print("ABORT: prechecks failed; no exit orders placed.")
            print(f"log_file: {path}")
        else:
            confirmation = input(f'Type "{CONFIRMATION_TEXT}" to execute S2 exit: ')
            if confirmation != CONFIRMATION_TEXT:
                payload["status"] = "aborted_confirmation_mismatch"
                path = write_exit_log(payload)
                print("ABORT: confirmation text mismatch; no exit orders placed.")
                print(f"log_file: {path}")
            else:
                try:
                    payload["execution"] = execute_exit(analysis)
                    payload["status"] = "submitted"
                except Exception as exc:
                    payload["status"] = "execution_error_or_orphan_warning"
                    payload["execution_error"] = str(exc)
                    print(f"Execution error: {exc}")
                    print("ORPHAN WARNING: verify PM/HL balances manually before further action.")
                path = write_exit_log(payload)
                print(f"log_file: {path}")

        if args.once or (args.max_loops is not None and loops >= args.max_loops):
            break
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
