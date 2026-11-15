from __future__ import annotations

import collections
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl import zscore
from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm


BASE = Path(__file__).resolve().parent
TEAM_MAP_PATH = BASE / "team_map.json"

MIN_NET_EDGE = 0.002
MAX_USDC_PER_TRADE = 100.0
INTERVAL_SEC = 10
PM_TAKER_FEE = 0.03
HL_TAKER_FEE = 0.0
HL_MIN_NOTIONAL = 10.0
OPPORTUNITY_TYPE = "pm_hl_cross_market_arbitrage"

HIST: dict[str, collections.deque[float]] = collections.defaultdict(
    lambda: collections.deque(maxlen=9000)
)


@dataclass(frozen=True)
class Market:
    name: str
    hl: int
    same: bool
    settle: str
    pm_yes: str
    pm_no: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_markets(include_world_cup: bool = True) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = [
        {
            "name": "Fed-NoChange",
            "hl": 104,
            "same": False,
            "settle": "2026-06-17",
            "pm_yes": "30767812841387255642892182147223249245545002662653079696958384408588201824258",
            "pm_no": "40302938956091099752849867077837976978448552504757012372843872340644441002059",
        }
    ]
    if not include_world_cup or not TEAM_MAP_PATH.exists():
        return markets

    team_map = json.loads(TEAM_MAP_PATH.read_text(encoding="utf-8"))
    for team in ["Portugal", "Spain", "France", "England", "Brazil", "Netherlands", "Germany"]:
        if team in team_map:
            markets.append(
                {
                    "name": team,
                    "hl": team_map[team]["hl"],
                    "same": True,
                    "settle": "2026-07-19",
                    "pm_yes": team_map[team]["pm_yes"],
                    "pm_no": team_map[team]["pm_no"],
                }
            )
    return markets


def pm_fee(price: float) -> float:
    return PM_TAKER_FEE * price * (1.0 - price)


def days_to(settle: str) -> float:
    year, month, day = map(int, settle.split("-"))
    return max((date(year, month, day) - date.today()).days, 0.5)


def walk(
    pm_asks: list[tuple[float, float]],
    hl_asks: list[tuple[float, float]],
    budget: float = MAX_USDC_PER_TRADE,
) -> dict[str, float]:
    pm_levels = [list(level) for level in pm_asks]
    hl_levels = [list(level) for level in hl_asks]
    qty = 0.0
    gross_cost = 0.0
    estimated_cost = 0.0
    first_gross_edge = 0.0
    first_net_edge = 0.0
    i = 0
    j = 0

    while i < len(pm_levels) and j < len(hl_levels):
        pm_px, pm_sz = pm_levels[i]
        hl_px, hl_sz = hl_levels[j]
        unit_gross_cost = pm_px + hl_px
        unit_fee = pm_fee(pm_px) + HL_TAKER_FEE
        unit_net_cost = unit_gross_cost + unit_fee
        if qty == 0:
            first_gross_edge = 1.0 - unit_gross_cost
            first_net_edge = 1.0 - unit_net_cost
        if unit_net_cost >= 1.0:
            break

        take = min(pm_sz, hl_sz)
        if gross_cost + estimated_cost + take * unit_net_cost > budget:
            take = (budget - gross_cost - estimated_cost) / unit_net_cost
        if take <= 1e-9:
            break

        qty += take
        gross_cost += take * unit_gross_cost
        estimated_cost += take * unit_fee
        pm_levels[i][1] -= take
        hl_levels[j][1] -= take
        if pm_levels[i][1] <= 1e-9:
            i += 1
        if hl_levels[j][1] <= 1e-9:
            j += 1

    return {
        "qty": qty,
        "gross_cost": gross_cost,
        "estimated_cost": estimated_cost,
        "net_profit": qty - gross_cost - estimated_cost,
        "first_gross_edge": first_gross_edge,
        "first_net_edge": first_net_edge,
        "avg_gross_cost": gross_cost / qty if qty else 0.0,
        "avg_estimated_cost": estimated_cost / qty if qty else 0.0,
        "avg_net_edge": (qty - gross_cost - estimated_cost) / qty if qty else first_net_edge,
    }


def zscore_for_market(name: str) -> tuple[float | None, float | None, float | None]:
    return zscore.latest_z(list(HIST[name]), INTERVAL_SEC)


def _hl_no_from_yes_bid(yes_bids: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(round(1.0 - price, 6), size) for price, size in yes_bids]


def _hl_coin_for(market: dict[str, Any], direction: str) -> str:
    same = bool(market["same"])
    base = int(market["hl"]) * 10
    if direction == "dir1":
        return f"#{base + 1 if same else base}"
    return f"#{base if same else base + 1}"


def scan_market(market: dict[str, Any]) -> dict[str, Any] | None:
    pm_yes_bids, pm_yes_asks, pm_yes_raw = pm.book(market["pm_yes"])
    pm_no_bids, pm_no_asks, pm_no_raw = pm.book(market["pm_no"])
    hl_yes_bids, hl_yes_asks = hl.yes_book(int(market["hl"]))

    if not (pm_yes_bids and pm_yes_asks and pm_no_bids and pm_no_asks and hl_yes_bids and hl_yes_asks):
        return None

    same = bool(market["same"])
    pm_yes_bid = pm_yes_bids[0][0]
    pm_no_bid = pm_no_bids[0][0]
    pm_yes_ask = pm_yes_asks[0][0]
    pm_no_ask = pm_no_asks[0][0]
    hl_yes_bid = hl_yes_bids[0][0]
    hl_yes_ask = hl_yes_asks[0][0]

    hl_event_bid = hl_yes_bid if same else round(1.0 - hl_yes_ask, 6)
    spread = hl_event_bid - pm_yes_bid
    HIST[market["name"]].append(spread)

    hl_no_asks = _hl_no_from_yes_bid(hl_yes_bids)
    dir1_hl_asks = hl_no_asks if same else list(hl_yes_asks)
    dir2_hl_asks = list(hl_yes_asks) if same else hl_no_asks
    dir1 = walk(pm_yes_asks, dir1_hl_asks)
    dir2 = walk(pm_no_asks, dir2_hl_asks)
    best_direction = "dir1" if dir1["avg_net_edge"] >= dir2["avg_net_edge"] else "dir2"
    best_walk = dir1 if best_direction == "dir1" else dir2

    maker_dir1 = 1.0 - (pm_yes_bid + dir1_hl_asks[0][0])
    maker_dir2 = 1.0 - (pm_no_bid + dir2_hl_asks[0][0])
    maker_direction = "dir1" if maker_dir1 >= maker_dir2 else "dir2"
    z, zmean, zsd = zscore_for_market(market["name"])
    days = days_to(market["settle"])
    gross_edge = best_walk["first_gross_edge"]
    net_edge = best_walk["avg_net_edge"]
    estimated_cost = gross_edge - net_edge

    return {
        "market": market["name"],
        "settle": market["settle"],
        "same": same,
        "spread": spread,
        "z": z,
        "zmean": zmean,
        "zsd": zsd,
        "days_to_settle": days,
        "taker_dir": best_direction,
        "maker_dir": maker_direction,
        "maker_edge": max(maker_dir1, maker_dir2),
        "pm_token": market["pm_yes"] if best_direction == "dir1" else market["pm_no"],
        "hl_coin": _hl_coin_for(market, best_direction),
        "pm_ask": pm_yes_ask if best_direction == "dir1" else pm_no_ask,
        "hl_ask": (dir1_hl_asks if best_direction == "dir1" else dir2_hl_asks)[0][0],
        "gross_edge": gross_edge,
        "estimated_cost": estimated_cost,
        "net_edge": net_edge,
        "apr": net_edge / days * 365 if days else 0.0,
        "executable_size": best_walk["qty"],
        "net_profit": best_walk["net_profit"],
        "is_real": bool(
            net_edge >= MIN_NET_EDGE
            and best_walk["qty"] > 0
            and best_walk["qty"] * max((dir1_hl_asks if best_direction == "dir1" else dir2_hl_asks)[0][0], 0)
            >= HL_MIN_NOTIONAL
        ),
        "raw_books": {
            "pm_yes_top": {"bid": pm_yes_bid, "ask": pm_yes_ask},
            "pm_no_top": {"bid": pm_no_bid, "ask": pm_no_ask},
            "hl_yes_top": {"bid": hl_yes_bid, "ask": hl_yes_ask},
            "pm_tick_size": pm_yes_raw.get("tick_size") or pm_no_raw.get("tick_size"),
        },
    }


def mock_scan_result() -> dict[str, Any]:
    return {
        "market": "Fed-NoChange",
        "settle": "2026-06-17",
        "same": False,
        "spread": 0.004,
        "z": None,
        "zmean": None,
        "zsd": None,
        "days_to_settle": days_to("2026-06-17"),
        "taker_dir": "dir2",
        "maker_dir": "dir2",
        "maker_edge": 0.004,
        "pm_token": "mock_pm_no",
        "hl_coin": "#1041",
        "pm_ask": 0.005,
        "hl_ask": 0.99,
        "gross_edge": 0.005,
        "estimated_cost": pm_fee(0.005) + HL_TAKER_FEE,
        "net_edge": 0.005 - pm_fee(0.005) - HL_TAKER_FEE,
        "apr": (0.005 - pm_fee(0.005) - HL_TAKER_FEE) / days_to("2026-06-17") * 365,
        "executable_size": 25.0,
        "net_profit": 25.0 * (0.005 - pm_fee(0.005) - HL_TAKER_FEE),
        "is_real": False,
        "raw_books": {"mock": True, "source": "smoke_test"},
    }


def to_opportunity_row(run_id: str, strategy_id: str, result: dict[str, Any]) -> dict[str, Any]:
    ts = now_iso()
    gross_edge = float(result.get("gross_edge") or 0)
    net_edge = float(result.get("net_edge") or 0)
    estimated_cost = gross_edge - net_edge
    normalized_result = dict(result)
    strategy_variant = str(normalized_result.get("strategy_variant", "S1_HOLD_TO_MATURITY"))
    exit_policy = (
        "exit_if_profit_available"
        if strategy_variant == "S2_EARLY_EXIT"
        else "hold_to_resolution"
    )
    normalized_result["estimated_cost"] = estimated_cost
    normalized_result.setdefault("strategy_variant", strategy_variant)
    normalized_result.setdefault("entry_policy", "buy_pm_and_buy_hl_complement_direct_asks")
    normalized_result.setdefault("exit_policy", exit_policy)
    normalized_result.setdefault("selected_dir", normalized_result.get("taker_dir"))
    normalized_result.setdefault("entry_pm_leg", normalized_result.get("pm_token"))
    normalized_result.setdefault("entry_hl_leg", normalized_result.get("hl_coin"))
    normalized_result.setdefault("entry_pm_ask", normalized_result.get("pm_ask"))
    normalized_result.setdefault("entry_hl_ask", normalized_result.get("hl_ask"))
    normalized_result.setdefault("entry_gross_edge", gross_edge)
    normalized_result.setdefault("entry_estimated_cost", estimated_cost)
    normalized_result.setdefault("entry_net_edge", net_edge)
    normalized_result.setdefault(
        "entry_cost",
        float(normalized_result.get("pm_ask") or 0) + float(normalized_result.get("hl_ask") or 0),
    )
    normalized_result.setdefault(
        "settlement_locked_profit",
        net_edge * float(normalized_result.get("executable_size") or 0),
    )
    normalized_result.setdefault("early_exit_enabled", strategy_variant == "S2_EARLY_EXIT")
    normalized_result.setdefault(
        "settlement_date",
        normalized_result.get("settlement") or normalized_result.get("settle"),
    )
    raw = {
        "source": "pm_hl_monitor",
        "calculation": normalized_result,
        "rules": {
            "entry": "ask",
            "exit": "bid",
            "mid_used": False,
            "status": "dry_run_observed",
        },
    }
    return {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "ts": ts,
        "venue_1": "polymarket",
        "venue_2": "hyperliquid",
        "instrument_1": str(result.get("pm_token", "")),
        "instrument_2": str(result.get("hl_coin", "")),
        "opportunity_type": OPPORTUNITY_TYPE,
        "gross_edge": gross_edge,
        "estimated_cost": estimated_cost,
        "net_edge": net_edge,
        "executable_size": float(result.get("executable_size") or 0),
        "status": "dry_run_observed",
        "notes": f"pm_hl dry_run opportunity for {result.get('market', 'unknown')}",
        "raw_json": json.dumps(raw, sort_keys=True),
        "created_at": ts,
    }
