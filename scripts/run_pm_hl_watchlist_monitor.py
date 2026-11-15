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

from src.db import connect, init_db, insert_row  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import OPPORTUNITY_TYPE, pm_fee  # noqa: E402


WATCHLIST_PATH = PROJECT_ROOT / "src" / "strategies" / "pm_hl" / "watchlist.json"
STRATEGY_ID = "pm_hl_watchlist"
DEFAULT_INTERVAL_SECONDS = 120


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id(market: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"pm_hl_watchlist_{market}_{stamp}"


def load_watchlist() -> list[dict[str, Any]]:
    return json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))


def get_watchlist_market(market_key: str) -> dict[str, Any]:
    for item in load_watchlist():
        if item.get("market") == market_key:
            return item
    raise ValueError(f"Market not found in watchlist: {market_key}")


def top(levels: list[tuple[float, float]], side: str) -> dict[str, float | None]:
    if not levels:
        return {side: None, "size": None}
    return {side: levels[0][0], "size": levels[0][1]}


def read_books(market: dict[str, Any]) -> dict[str, Any]:
    pm_yes_bids, pm_yes_asks, _ = pm.book(str(market["pm_yes"]))
    pm_no_bids, pm_no_asks, _ = pm.book(str(market["pm_no"]))
    hl_yes_bids, hl_yes_asks = hl.coin_book(str(market["hl_yes_coin"]))
    hl_no_bids, hl_no_asks = hl.coin_book(str(market["hl_no_coin"]))
    return {
        "pm_yes_bids": pm_yes_bids,
        "pm_yes_asks": pm_yes_asks,
        "pm_no_bids": pm_no_bids,
        "pm_no_asks": pm_no_asks,
        "hl_yes_bids": hl_yes_bids,
        "hl_yes_asks": hl_yes_asks,
        "hl_no_bids": hl_no_bids,
        "hl_no_asks": hl_no_asks,
        "pm_yes_top": {"bid": top(pm_yes_bids, "bid")["bid"], "ask": top(pm_yes_asks, "ask")["ask"]},
        "pm_no_top": {"bid": top(pm_no_bids, "bid")["bid"], "ask": top(pm_no_asks, "ask")["ask"]},
        "hl_yes_top": {"bid": top(hl_yes_bids, "bid")["bid"], "ask": top(hl_yes_asks, "ask")["ask"]},
        "hl_no_top": {"bid": top(hl_no_bids, "bid")["bid"], "ask": top(hl_no_asks, "ask")["ask"]},
    }


def hl_taker_fee() -> float:
    return float(os.environ.get("HL_TAKER_FEE", "0") or 0)


def build_direction(
    name: str,
    pm_leg: str,
    hl_leg: str,
    pm_asks: list[tuple[float, float]],
    hl_asks: list[tuple[float, float]],
) -> dict[str, Any]:
    if not pm_asks or not hl_asks:
        return {
            "direction": name,
            "status": "data_incomplete",
            "reason": "missing direct ask book",
            "pm_leg": pm_leg,
            "hl_leg": hl_leg,
            "pm_direct_ask": None,
            "hl_direct_ask": None,
            "entry_cost": None,
            "gross_edge": 0.0,
            "estimated_cost": 0.0,
            "net_edge": 0.0,
            "executable_size": 0.0,
            "expected_profit": 0.0,
        }

    pm_ask, pm_size = pm_asks[0]
    hl_ask, hl_size = hl_asks[0]
    executable_size = min(pm_size, hl_size)
    entry_cost = pm_ask + hl_ask
    gross_edge = 1.0 - (pm_ask + hl_ask)
    estimated_cost = pm_fee(pm_ask) + hl_taker_fee()
    net_edge = gross_edge - estimated_cost
    expected_profit = net_edge * executable_size
    return {
        "direction": name,
        "status": "dry_run_observed" if net_edge > 0 else "observed_not_actionable",
        "reason": None,
        "pm_leg": pm_leg,
        "hl_leg": hl_leg,
        "pm_direct_ask": pm_ask,
        "hl_direct_ask": hl_ask,
        "entry_cost": entry_cost,
        "gross_edge": gross_edge,
        "estimated_cost": estimated_cost,
        "net_edge": net_edge,
        "executable_size": executable_size,
        "expected_profit": expected_profit,
    }


def calculate_opportunity(market: dict[str, Any], books: dict[str, Any]) -> dict[str, Any]:
    outcome = str(market.get("pm_outcome") or market.get("hl_outcome") or "Outcome")
    dir1 = build_direction(
        "dir1",
        f"PM {outcome} YES",
        f"HL {outcome} NO",
        books["pm_yes_asks"],
        books["hl_no_asks"],
    )
    dir2 = build_direction(
        "dir2",
        f"PM {outcome} NO",
        f"HL {outcome} YES",
        books["pm_no_asks"],
        books["hl_yes_asks"],
    )
    candidates = [direction for direction in (dir1, dir2) if direction["status"] != "data_incomplete"]
    selected = max(candidates, key=lambda row: row["net_edge"], default=dir1)
    status = selected["status"]
    if dir1["status"] == "data_incomplete" and dir2["status"] == "data_incomplete":
        status = "data_incomplete"
    strategy_variant = str(market.get("default_entry_strategy", "S1_HOLD_TO_MATURITY"))
    exit_policy = (
        "exit_if_profit_available"
        if strategy_variant == "S2_EARLY_EXIT"
        else "hold_to_resolution"
    )
    settlement_locked_profit = selected["net_edge"] * selected["executable_size"]

    raw = {
        "strategy_variant": strategy_variant,
        "entry_policy": "buy_pm_and_buy_hl_complement_direct_asks",
        "exit_policy": exit_policy,
        "market": market["market"],
        "mapping_status": market["mapping_status"],
        "enabled_strategies": market.get("enabled_strategies", []),
        "early_exit_enabled": bool(market.get("allow_early_exit", False)),
        "settlement_date": market.get("settlement_date"),
        "payoff_description": market["payoff_description"],
        "pm_market_name": market["pm_market_name"],
        "pm_outcome": market["pm_outcome"],
        "hl_market_name": market["hl_market_name"],
        "hl_outcome": market["hl_outcome"],
        "pm_yes_top": books["pm_yes_top"],
        "pm_no_top": books["pm_no_top"],
        "hl_yes_top": books["hl_yes_top"],
        "hl_no_top": books["hl_no_top"],
        "selected_dir": selected["direction"],
        "selected_pm_leg": selected["pm_leg"],
        "selected_hl_leg": selected["hl_leg"],
        "selected_pm_direct_ask": selected["pm_direct_ask"],
        "selected_hl_direct_ask": selected["hl_direct_ask"],
        "entry_pm_leg": selected["pm_leg"],
        "entry_hl_leg": selected["hl_leg"],
        "entry_pm_ask": selected["pm_direct_ask"],
        "entry_hl_ask": selected["hl_direct_ask"],
        "entry_cost": selected["entry_cost"],
        "entry_gross_edge": selected["gross_edge"],
        "entry_estimated_cost": selected["estimated_cost"],
        "entry_net_edge": selected["net_edge"],
        "gross_edge": selected["gross_edge"],
        "estimated_cost": selected["estimated_cost"],
        "net_edge": selected["net_edge"],
        "executable_size": selected["executable_size"],
        "expected_profit": selected["expected_profit"],
        "settlement_locked_profit": settlement_locked_profit,
        "status": status,
        "directions": {"dir1": dir1, "dir2": dir2},
        "rules": {
            "buy_only": True,
            "uses_direct_asks_only": True,
            "uses_one_minus_opposite_bid": False,
        },
    }
    return {
        "selected": selected,
        "status": status,
        "raw": raw,
    }


def write_opportunity(run_id: str, market: dict[str, Any], opportunity: dict[str, Any]) -> int:
    selected = opportunity["selected"]
    ts = now_iso()
    row = {
        "run_id": run_id,
        "strategy_id": STRATEGY_ID,
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
        "status": opportunity["status"],
        "notes": f"watchlist monitor {market['market']} direct-ask dry-run",
        "raw_json": json.dumps(opportunity["raw"], sort_keys=True),
        "created_at": ts,
    }
    db_path = init_db()
    with connect(db_path) as conn:
        opp_id = insert_row(conn, "opportunities", row)
        conn.commit()
    return opp_id


def ensure_run(run_id: str, market: str) -> None:
    ts = now_iso()
    db_path = init_db()
    with connect(db_path) as conn:
        insert_row(
            conn,
            "runs",
            {
                "run_id": run_id,
                "run_type": "pm_hl_watchlist_monitor",
                "strategy_id": STRATEGY_ID,
                "started_at": ts,
                "finished_at": ts,
                "status": "dry_run_started",
                "notes": f"watchlist monitor dry_run {market}",
                "created_at": ts,
            },
        )
        conn.commit()


def run_once(run_id: str, market: dict[str, Any]) -> None:
    books = read_books(market)
    opportunity = calculate_opportunity(market, books)
    opp_id = write_opportunity(run_id, market, opportunity)
    selected = opportunity["selected"]
    print(
        f"{now_iso()} {market['market']} {selected['direction']} "
        f"cost={(selected['pm_direct_ask'] or 0) + (selected['hl_direct_ask'] or 0):.6f} "
        f"gross_edge={selected['gross_edge']:.6f} "
        f"estimated_cost={selected['estimated_cost']:.6f} "
        f"net_edge={selected['net_edge']:.6f} "
        f"size={selected['executable_size']:.4f} "
        f"expected_profit={selected['expected_profit']:.6f} "
        f"status={opportunity['status']} "
        f"opportunity_id={opp_id}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="PM-HL watchlist direct-ask monitor.")
    parser.add_argument("--market", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-loops", type=int, default=None)
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    market = get_watchlist_market(args.market)
    if not market.get("enabled", False):
        raise SystemExit(f"Market disabled in watchlist: {args.market}")

    run = new_run_id(args.market)
    ensure_run(run, args.market)
    print("Mode: dry-run monitor only; no orders are placed.")
    print(f"Market: {market['market']} | mapping_status={market['mapping_status']}")
    print(f"Payoff: {market['payoff_description']}")

    loops = 0
    while True:
        loops += 1
        run_once(run, market)
        if args.once or (args.max_loops is not None and loops >= args.max_loops):
            break
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
