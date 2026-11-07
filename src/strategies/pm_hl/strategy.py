from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.opportunity_model import HL_MIN_NOTIONAL


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STOP_FILE = PROJECT_ROOT / "STOP"
MATCH_TOL = 2.0
HL_SLIP = 0.02
MIN_HL_FILL = 5.0


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class SafetyConfig:
    dry_run: bool = True
    trading_enabled: bool = False
    require_manual_confirmation: bool = True
    max_order_notional: float = 100.0
    allowed_markets: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "SafetyConfig":
        allowed = tuple(
            item.strip()
            for item in os.environ.get("ALLOWED_MARKETS", "").split(",")
            if item.strip()
        )
        return cls(
            dry_run=env_bool("DRY_RUN", True),
            trading_enabled=env_bool("TRADING_ENABLED", False),
            require_manual_confirmation=env_bool("REQUIRE_MANUAL_CONFIRMATION", True),
            max_order_notional=float(os.environ.get("MAX_ORDER_NOTIONAL", "100") or 100),
            allowed_markets=allowed,
        )


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str


def check_gate(
    market: str,
    notional: float,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> GateResult:
    cfg = config or SafetyConfig.from_env()
    if STOP_FILE.exists():
        return GateResult(False, f"STOP file present: {STOP_FILE}")
    if cfg.dry_run:
        return GateResult(False, "DRY_RUN=true")
    if not cfg.trading_enabled:
        return GateResult(False, "TRADING_ENABLED=false")
    if cfg.allowed_markets and market not in cfg.allowed_markets:
        return GateResult(False, f"market not allowed: {market}")
    if notional > cfg.max_order_notional:
        return GateResult(False, f"notional {notional:.2f} > MAX_ORDER_NOTIONAL {cfg.max_order_notional:.2f}")
    if cfg.require_manual_confirmation and not manual_confirmed:
        return GateResult(False, "REQUIRE_MANUAL_CONFIRMATION=true and manual_confirmed=false")
    return GateResult(True, "allowed")


def hedge_leg(market: dict[str, Any], direction: str) -> tuple[str, str]:
    same = bool(market["same"])
    base = int(market["hl"]) * 10
    if direction == "dir1":
        return str(market["pm_yes"]), f"#{base + 1 if same else base}"
    return str(market["pm_no"]), f"#{base if same else base + 1}"


def parse_hl_fill(response: Any, ref_px: float) -> tuple[float, float]:
    filled = 0.0
    avg = ref_px
    try:
        status = response["response"]["data"]["statuses"][0]
        fill = status.get("filled")
        if fill:
            filled = float(fill.get("totalSz", 0) or 0)
            avg = float(fill.get("avgPx", ref_px) or ref_px)
    except Exception:
        pass
    return filled, avg


def hl_take(
    exchange: Any,
    coin: str,
    is_buy: bool,
    size: float,
    ref_px: float,
    market: str,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> tuple[float, float, Any]:
    notional = size * ref_px
    gate = check_gate(market, notional, config, manual_confirmed)
    if not gate.allowed:
        print(f"{now_iso()} [NO ORDER] HL {'BUY' if is_buy else 'SELL'} {coin}: {gate.reason}")
        return 0.0, ref_px, {"blocked": True, "reason": gate.reason}

    px = round(min(ref_px * (1 + HL_SLIP), 0.999), 6) if is_buy else round(max(ref_px * (1 - HL_SLIP), 0.001), 6)
    response = exchange.order(coin, is_buy, size, px, {"limit": {"tif": "Ioc"}})
    filled, avg = parse_hl_fill(response, ref_px)
    return filled, avg, response


def pm_marketable_buy(
    client: Any,
    token: str,
    shares: float,
    ref_ask: float,
    tick_size: str,
    neg_risk: bool,
    market: str,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> Any:
    gate = check_gate(market, shares * ref_ask, config, manual_confirmed)
    if not gate.allowed:
        print(f"{now_iso()} [NO ORDER] PM BUY {token[-8:]}: {gate.reason}")
        return {"blocked": True, "reason": gate.reason}

    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    px = min(round(ref_ask + 0.005, 3), 0.999)
    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=px, size=int(round(shares)), side=Side.BUY),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.FAK,
    )


def pm_limit_buy(
    client: Any,
    token: str,
    price: float,
    shares: float,
    tick_size: str,
    neg_risk: bool,
    market: str,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> Any:
    gate = check_gate(market, shares * price, config, manual_confirmed)
    if not gate.allowed:
        print(f"{now_iso()} [NO ORDER] PM LIMIT BUY {token[-8:]}: {gate.reason}")
        return {"blocked": True, "reason": gate.reason}

    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=round(price, 4), size=shares, side=Side.BUY),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.GTC,
    )


def pm_cancel(client: Any, order_id: str, market: str, config: SafetyConfig | None = None) -> Any:
    cfg = config or SafetyConfig.from_env()
    if STOP_FILE.exists():
        print(f"{now_iso()} [NO ORDER] PM CANCEL {order_id}: STOP file present")
        return {"blocked": True, "reason": "STOP file present"}
    if cfg.dry_run or not cfg.trading_enabled:
        print(f"{now_iso()} [NO ORDER] PM CANCEL {order_id}: dry-run or trading disabled")
        return {"blocked": True, "reason": "dry-run or trading disabled"}
    if cfg.allowed_markets and market not in cfg.allowed_markets:
        print(f"{now_iso()} [NO ORDER] PM CANCEL {order_id}: market not allowed")
        return {"blocked": True, "reason": "market not allowed"}

    from py_clob_client_v2 import OrderPayload

    return client.cancel_order(OrderPayload(orderID=order_id))


def pm_marketable_sell(
    client: Any,
    token: str,
    shares: float,
    ref_bid: float,
    tick_size: str,
    neg_risk: bool,
    market: str,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> Any:
    gate = check_gate(market, shares * ref_bid, config, manual_confirmed)
    if not gate.allowed:
        print(f"{now_iso()} [NO ORDER] PM SELL {token[-8:]}: {gate.reason}")
        return {"blocked": True, "reason": gate.reason}

    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    px = max(round(ref_bid - 0.005, 3), 0.001)
    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=px, size=int(round(shares)), side=Side.SELL),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.FAK,
    )


def maker_edge_now(market: dict[str, Any], direction: str) -> dict[str, Any]:
    pm_token, hl_coin = hedge_leg(market, direction)
    (pm_bid, pm_bid_size), (pm_ask, _), tick_size, neg_risk = pm.top(pm_token)
    _, hl_asks = hl.coin_book(hl_coin)
    hl_ask = hl_asks[0][0] if hl_asks else 1.0
    return {
        "edge": 1.0 - (pm_bid + hl_ask),
        "pm_token": pm_token,
        "hl_coin": hl_coin,
        "pm_bid": pm_bid,
        "pm_bid_size": pm_bid_size,
        "pm_ask": pm_ask,
        "hl_ask": hl_ask,
        "tick_size": tick_size,
        "neg_risk": neg_risk,
    }


def post_maker(
    market: dict[str, Any],
    direction: str,
    client: Any,
    shares: float,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> dict[str, Any]:
    quote = maker_edge_now(market, direction)
    response = pm_limit_buy(
        client,
        quote["pm_token"],
        quote["pm_bid"],
        shares,
        quote["tick_size"],
        quote["neg_risk"],
        str(market["name"]),
        config,
        manual_confirmed,
    )
    return {"market": market["name"], "direction": direction, "quote": quote, "response": response}


def box_value(pm_token: str, hl_coin: str) -> float:
    (pm_bid, _), _, _, _ = pm.top(pm_token)
    hl_bids, _ = hl.coin_book(hl_coin)
    return pm_bid + (hl_bids[0][0] if hl_bids else 0.0)


def close_position(
    market: str,
    pm_token: str,
    hl_coin: str,
    shares: float,
    client: Any,
    exchange: Any,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> dict[str, Any]:
    (pm_bid, _), _, tick_size, neg_risk = pm.top(pm_token)
    hl_bids, _ = hl.coin_book(hl_coin)
    hl_bid = hl_bids[0][0] if hl_bids else 0.0
    hl_result = hl_take(exchange, hl_coin, False, shares, hl_bid, market, config, manual_confirmed)
    pm_result = pm_marketable_sell(
        client,
        pm_token,
        shares,
        pm_bid,
        tick_size,
        neg_risk,
        market,
        config,
        manual_confirmed,
    )
    return {
        "market": market,
        "pm_token": pm_token,
        "hl_coin": hl_coin,
        "shares": shares,
        "exit_value": pm_bid + hl_bid,
        "hl_result": hl_result,
        "pm_result": pm_result,
    }


def open_box_atomic(
    market: dict[str, Any],
    direction: str,
    client: Any,
    exchange: Any,
    funder: str,
    target_shares: float,
    config: SafetyConfig | None = None,
    manual_confirmed: bool = False,
) -> dict[str, Any]:
    """Open both legs only when safety gates allow it and fills reconcile.

    Conservative orphan handling:
    - HL fills first.
    - PM is sized to the actual HL fill.
    - If PM fill does not match, the function refuses to record an open box.
    - If HL is longer than PM, it attempts to sell back the excess HL leg.
    - Any unresolved mismatch is returned with `requires_manual_intervention=True`.
    """
    name = str(market["name"])
    pm_token, hl_coin = hedge_leg(market, direction)
    hl_bids, hl_asks = hl.coin_book(hl_coin)
    if not hl_asks:
        return {"status": "rejected", "reason": f"no HL ask for {hl_coin}"}

    hl_ask = hl_asks[0][0]
    want = min(target_shares, (config or SafetyConfig.from_env()).max_order_notional / max(hl_ask, 0.01))
    if want * hl_ask < HL_MIN_NOTIONAL:
        return {"status": "rejected", "reason": f"HL notional below minimum: {want * hl_ask:.2f}"}

    (_, _), (pm_ask, _), tick_size, neg_risk = pm.top(pm_token)
    gate = check_gate(name, want * (pm_ask + hl_ask), config, manual_confirmed)
    if not gate.allowed:
        return {"status": "blocked", "reason": gate.reason, "would_buy": {"pm_token": pm_token, "hl_coin": hl_coin, "shares": want}}

    hl_filled, hl_avg, hl_raw = hl_take(
        exchange, hl_coin, True, want, hl_ask, name, config, manual_confirmed
    )
    if hl_filled < MIN_HL_FILL:
        return {"status": "rejected", "reason": f"HL fill too small: {hl_filled}", "hl_raw": hl_raw}

    before_pm = pm.positions_size(funder, pm_token)
    try:
        pm_marketable_buy(
            client,
            pm_token,
            hl_filled,
            pm_ask,
            tick_size,
            neg_risk,
            name,
            config,
            manual_confirmed,
        )
        after_pm = pm.positions_size(funder, pm_token)
        pm_filled = max(after_pm - before_pm, 0.0)
    except Exception as exc:
        pm_filled = 0.0
        print(f"{now_iso()} PM leg failed after HL fill: {exc}. Attempting HL unwind.")

    if abs(hl_filled - pm_filled) > MATCH_TOL:
        excess_hl = max(hl_filled - pm_filled, 0.0)
        if excess_hl > 0 and hl_bids:
            try:
                hl_take(exchange, hl_coin, False, excess_hl, hl_bids[0][0], name, config, manual_confirmed)
            except Exception as exc:
                print(f"{now_iso()} HL unwind failed: {exc}. Manual intervention required.")
        return {
            "status": "mismatch_rejected",
            "reason": "HL and PM fills did not reconcile; no open box recorded",
            "hl_filled": hl_filled,
            "pm_filled": pm_filled,
            "requires_manual_intervention": True,
        }

    shares = min(hl_filled, pm_filled)
    return {
        "status": "opened",
        "market": name,
        "direction": direction,
        "pm_token": pm_token,
        "hl_coin": hl_coin,
        "shares": shares,
        "entry_cost": hl_avg + pm_ask,
        "opened_at": now_iso(),
    }
