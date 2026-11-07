from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_watchlist_monitor import get_watchlist_market  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import pm_fee  # noqa: E402


STRATEGY_VARIANT = "S2_EARLY_EXIT"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hl_taker_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def pm_position_size(token: str) -> float:
    positions = pm.get_positions(pm.get_funder())
    for position in positions if isinstance(positions, list) else []:
        if str(position.get("asset")) == token:
            return float(position.get("size", 0) or 0)
    return 0.0


def hl_position_size(coin: str) -> float:
    spot = dict(hl.spot_balances(hl.get_account()))
    aliases = [coin, "+" + coin.lstrip("#")]
    for alias in aliases:
        if alias in spot:
            return float(spot[alias] or 0)
    return 0.0


def bid_for_pm(token: str) -> float | None:
    bids, _, _ = pm.book(token)
    return bids[0][0] if bids else None


def bid_for_hl(coin: str) -> float | None:
    bids, _ = hl.coin_book(coin)
    return bids[0][0] if bids else None


def leg_config(market: dict[str, Any], direction: str) -> dict[str, str]:
    if direction == "dir1":
        return {
            "held_pm_leg": "PM Portugal YES",
            "held_hl_leg": "HL Portugal NO",
            "pm_token": str(market["pm_yes"]),
            "hl_coin": str(market["hl_no_coin"]),
        }
    return {
        "held_pm_leg": "PM Portugal NO",
        "held_hl_leg": "HL Portugal YES",
        "pm_token": str(market["pm_no"]),
        "hl_coin": str(market["hl_yes_coin"]),
    }


def analyze_direction(market: dict[str, Any], direction: str) -> dict[str, Any]:
    cfg = leg_config(market, direction)
    shares_pm = pm_position_size(cfg["pm_token"])
    shares_hl = hl_position_size(cfg["hl_coin"])
    matched_box_shares = min(shares_pm, shares_hl)
    pm_bid = bid_for_pm(cfg["pm_token"]) if shares_pm > 0 else None
    hl_bid = bid_for_hl(cfg["hl_coin"]) if shares_hl > 0 else None
    original_entry_cost_per_share = None

    status = "no_position"
    estimated_exit_fees = None
    exit_value_per_share = None
    realized_profit_if_exit = None

    if shares_pm != shares_hl and (shares_pm > 0 or shares_hl > 0):
        status = "orphan_position"
    if matched_box_shares > 0:
        if pm_bid is None or hl_bid is None:
            status = "data_incomplete"
        else:
            estimated_exit_fees = pm_fee(pm_bid) + hl_taker_fee()
            exit_value_per_share = pm_bid + hl_bid - estimated_exit_fees
            if original_entry_cost_per_share is None:
                status = "entry_cost_unknown"
            else:
                realized_profit_if_exit = (
                    exit_value_per_share * matched_box_shares
                    - original_entry_cost_per_share * matched_box_shares
                )
                min_profit = float(market.get("min_early_exit_profit_usd", 0) or 0)
                min_bps = float(market.get("min_early_exit_profit_bps", 0) or 0)
                profit_bps = (
                    realized_profit_if_exit
                    / (original_entry_cost_per_share * matched_box_shares)
                    * 10000
                )
                status = (
                    "early_exit_candidate"
                    if realized_profit_if_exit >= min_profit and profit_bps >= min_bps
                    else "no_early_exit"
                )

    return {
        "strategy_variant": STRATEGY_VARIANT,
        "market": market["market"],
        "direction": direction,
        "held_pm_leg": cfg["held_pm_leg"],
        "held_hl_leg": cfg["held_hl_leg"],
        "shares_pm": shares_pm,
        "shares_hl": shares_hl,
        "matched_box_shares": matched_box_shares,
        "pm_bid": pm_bid,
        "hl_bid": hl_bid,
        "exit_value_per_share": exit_value_per_share,
        "estimated_exit_fees": estimated_exit_fees,
        "original_entry_cost_per_share": original_entry_cost_per_share,
        "realized_profit_if_exit": realized_profit_if_exit,
        "status": status,
        "rules": {
            "dry_run": True,
            "read_only": True,
            "uses_direct_bids_only": True,
            "uses_mid": False,
            "uses_one_minus_opposite_book": False,
            "no_short": True,
            "no_sell_above_real_position": True,
            "exit_requires_existing_position": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only PM-HL early exit monitor.")
    parser.add_argument("--market", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--once", action="store_true", required=True)
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    market = get_watchlist_market(args.market)
    if not market.get("allow_early_exit", False):
        print(f"{args.market}: early exit disabled in watchlist")

    print("Mode: dry-run exit monitor; read-only; no orders are placed.")
    print(f"Market: {market['market']} | strategy_variant={STRATEGY_VARIANT}")
    outputs = {
        "ts": now_iso(),
        "market": args.market,
        "dry_run": True,
        "analyses": [
            analyze_direction(market, "dir1"),
            analyze_direction(market, "dir2"),
        ],
    }
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
