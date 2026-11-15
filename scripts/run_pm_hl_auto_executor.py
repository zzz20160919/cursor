from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_one_shot_test_trade import (  # noqa: E402
    allowed_markets,
    bool_env,
    calculate_plan,
    filled_shares,
    hl_min_notional,
    pm_ioc_buy,
    pm_min_notional,
    read_balances,
    response_indicates_failure,
    stop_file_exists,
)
from scripts.run_pm_hl_s2_exit_executor import bid_for_hl, bid_for_pm  # noqa: E402
from scripts.run_pm_hl_start_s1_s2 import selected_ask_books  # noqa: E402
from scripts.run_pm_hl_watchlist_monitor import get_watchlist_market, hl_taker_fee  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import pm_fee  # noqa: E402


SUPPORTED_MARKETS = {
    "WC-France-Champion",
    "WC-Spain-Champion",
    "WC-Germany-Champion",
    "WC-Portugal-Champion",
}
DEFAULT_MARKETS = (
    "WC-France-Champion",
    "WC-Spain-Champion",
    "WC-Germany-Champion",
)
STATE_IDLE = "IDLE"
STATE_ENTERING_S1 = "ENTERING_S1"
STATE_ENTERING_S2 = "ENTERING_S2"
STATE_ACTIVE = "ACTIVE_S1_S2"
STATE_EXITING_S2 = "EXITING_S2"
STATE_S2_EXITED = "S2_EXITED"
STATE_S1_ACTIVE_S2_IDLE = "S1_ACTIVE_S2_IDLE"
STATE_HALTED = "HALTED"
ACTIVE_STATES = {STATE_ENTERING_S1, STATE_ENTERING_S2, STATE_ACTIVE, STATE_EXITING_S2}
VALID_STATES = ACTIVE_STATES | {STATE_IDLE, STATE_S1_ACTIVE_S2_IDLE, STATE_S2_EXITED, STATE_HALTED}
S1_VARIANT = "S1_HOLD_TO_MATURITY"
S2_VARIANT = "S2_EARLY_EXIT"
S1_SHARES = 20.0
S2_SHARES = 20.0
BOX_SHARES = 20.0
COMBINED_REQUIRED_SHARES = S1_SHARES + S2_SHARES
MAX_S1_PER_MARKET = 1
MAX_ACTIVE_S2_PER_MARKET = 1
MAX_ACTIVE_S1_MARKETS = 4
MAX_TOTAL_BOX_SHARES = 160.0
ALLOWED_ACTIONS = {"FULL_ENTRY", "S2_REENTRY", "S2_EXIT"}
MAX_TOTAL_NOTIONAL_PER_STRATEGY = 25.0
MIN_ENTRY_NET_EDGE_BPS = 10.0
MIN_ENTRY_PROFIT_USD = 0.03
MIN_EXIT_PROFIT_BPS = 10.0
MIN_EXIT_PROFIT_USD = 0.03
THRESHOLD_PROFILES = {
    "normal": {
        "entry_min_net_edge_bps": 10.0,
        "entry_min_profit_usd": 0.03,
        "exit_min_profit_bps": 10.0,
        "exit_min_profit_usd": 0.03,
        "positive_only_mode": False,
    },
    "validation": {
        "entry_min_net_edge_bps": 5.0,
        "entry_min_profit_usd": 0.01,
        "exit_min_profit_bps": 5.0,
        "exit_min_profit_usd": 0.01,
        "positive_only_mode": False,
    },
    "micro_exit_test": {
        "entry_min_net_edge_bps": 10.0,
        "entry_min_profit_usd": 0.03,
        "exit_min_profit_bps": 5.0,
        "exit_min_profit_usd": 0.01,
        "positive_only_mode": False,
    },
    "micro_exit_no_hold_test": {
        "entry_min_net_edge_bps": 10.0,
        "entry_min_profit_usd": 0.03,
        "exit_min_profit_bps": 5.0,
        "exit_min_profit_usd": 0.01,
        "disable_exit_vs_hold_check": True,
        "positive_only_mode": False,
    },
    "positive": {
        "entry_min_net_edge_bps": 0.0001,
        "entry_min_profit_usd": 0.0001,
        "exit_min_profit_bps": 0.0001,
        "exit_min_profit_usd": 0.0001,
        "positive_only_mode": True,
    },
}
CURRENT_THRESHOLD_PROFILE = "normal"
CURRENT_THRESHOLDS = THRESHOLD_PROFILES[CURRENT_THRESHOLD_PROFILE].copy()
FILL_TOLERANCE = 0.01
ENTRY_CONFIRM_ATTEMPTS = 8
ENTRY_CONFIRM_DELAY_SECONDS = 1.75
HL_BACKOFF_INITIAL_SECONDS = 30.0
HL_BACKOFF_MAX_SECONDS = 120.0
S2_EXIT_FILL_TOLERANCE_PCT = 0.005
LOG_DIR = PROJECT_ROOT / "logs" / "pm_hl"
ACTIVE_FILE = LOG_DIR / "auto_active_market.json"
PORTFOLIO_FILE = LOG_DIR / "auto_portfolio_state.json"
NAV_SNAPSHOT_FILE = LOG_DIR / "portfolio_nav_snapshots.jsonl"
ORDERBOOK_SNAPSHOT_PREFIX = "orderbook_snapshots"
PM_AUTH_DIAGNOSTICS: list[dict[str, Any]] = []
PM_AUTH_WARNING_PRINTED = False
PM_CLIENT_CACHE: Any | None = None
HL_BACKOFF_UNTIL = 0.0
HL_BACKOFF_SECONDS = 0.0


class HaltedError(RuntimeError):
    pass


class PartialFillRequiresReview(HaltedError):
    def __init__(self, message: str, confirmation: dict[str, Any] | None = None):
        super().__init__(message)
        self.confirmation = confirmation or {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def scan_time_utc8() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def scan_progress_text(loop_index: int, max_loops: int | None) -> str:
    total = str(max_loops) if max_loops is not None else "unknown"
    return f"{loop_index} / {total}"


def print_portfolio_loop_scan_info(loop_index: int, max_loops: int | None) -> None:
    print("PORTFOLIO LOOP")
    print(f"scan_time_utc8: {scan_time_utc8()}")
    print(f"scan_progress: {scan_progress_text(loop_index, max_loops)}")


def set_threshold_profile(profile: str) -> None:
    global CURRENT_THRESHOLD_PROFILE, CURRENT_THRESHOLDS
    CURRENT_THRESHOLD_PROFILE = profile
    CURRENT_THRESHOLDS = THRESHOLD_PROFILES[profile].copy()


def threshold_value(name: str) -> float:
    return float(CURRENT_THRESHOLDS[name])


def exit_vs_hold_check_disabled() -> bool:
    return bool(CURRENT_THRESHOLDS.get("disable_exit_vs_hold_check"))


def exit_vs_hold_check_label() -> str:
    return "disabled_by_profile" if exit_vs_hold_check_disabled() else "enabled"


def print_threshold_profile() -> None:
    print(f"threshold_profile: {CURRENT_THRESHOLD_PROFILE}")
    if CURRENT_THRESHOLDS.get("positive_only_mode"):
        print("positive_only_mode: true")
    print(f"disable_exit_vs_hold_check: {str(exit_vs_hold_check_disabled()).lower()}")
    print(f"entry_min_net_edge_bps: {threshold_value('entry_min_net_edge_bps'):g}")
    print(f"entry_min_profit_usd: {threshold_value('entry_min_profit_usd'):g}")
    print(f"exit_min_profit_bps: {threshold_value('exit_min_profit_bps'):g}")
    print(f"exit_min_profit_usd: {threshold_value('exit_min_profit_usd'):g}")


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def event_log_path() -> Path:
    return LOG_DIR / f"auto_events_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def orderbook_snapshot_path() -> Path:
    return LOG_DIR / f"{ORDERBOOK_SNAPSHOT_PREFIX}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def market_slug(market_key: str) -> str:
    country = market_key.removeprefix("WC-").removesuffix("-Champion").lower()
    return f"wc_{country}"


def portfolio_market_label(market_key: str) -> str:
    return market_key.removeprefix("WC-").removesuffix("-Champion")


def fmt_num(value: float | int | None, decimals: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{decimals}f}"


def fmt_position(value: float | None, decimals: int = 1, unavailable_label: str = "unavailable") -> str:
    if value is None:
        return unavailable_label
    return fmt_num(value, decimals)


PM_POSITION_READ_ERRORS = (
    urllib.error.HTTPError,
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    OSError,
)


def fmt_pct(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{decimals}f}%"


def print_kv_block(title: str, rows: list[tuple[str, str]], *, blank_line: bool = True) -> None:
    print(title)
    if blank_line:
        print()
    label_width = max(len(label) for label, _ in rows) if rows else 0
    label_width = max(label_width, 18)
    for label, value in rows:
        print(f"{label + ':':<{label_width + 1}}{value}")
    print()


def print_ascii_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
    print("".join(header.ljust(width) for header, width in zip(headers, widths)))
    for row in rows:
        print("".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


def hl_mark_coin(coin: str) -> str:
    if coin.startswith("+"):
        return "#" + coin[1:]
    return coin


def estimate_hl_outcome_value(coin: str, amount: float) -> float:
    book_coin = hl_mark_coin(coin)
    book, _warning = safe_hl_coin_book(book_coin, context="nav_mark_outcome")
    if book is None:
        return 0.0
    bids, _ = book
    bid = bids[0][0] if bids else 0.0
    return amount * bid


def read_pm_portfolio_nav() -> tuple[float | None, str | None]:
    pm.load_env()
    funder = pm.get_funder()
    try:
        total = 0.0
        if not pm.missing_env(("PM_PRIVATE_KEY", "PM_FUNDER")):
            try:
                client = pm.build_client()
                cash, _ = pm.get_cash(client)
                total += float(cash or 0)
            except Exception:
                pass
        total += float(pm.get_value(funder) or 0)
        return total, None
    except Exception as exc:
        return None, str(exc)[:120]


def read_hl_portfolio_nav() -> tuple[float | None, str | None]:
    hl.load_env()
    try:
        total = 0.0
        spot, warning = safe_hl_spot_balances(context="portfolio_nav")
        if spot is None:
            return None, str((warning or {}).get("error") or "HL spot unavailable")[:120]
        for coin, amount in spot:
            if amount == 0:
                continue
            if coin == "USDC":
                total += amount
            elif coin.startswith(("#", "@", "+")):
                try:
                    total += estimate_hl_outcome_value(coin, amount)
                except Exception:
                    pass
        try:
            account_value, _ = hl.perp_state(hl.get_account())
            total += float(account_value or 0.0)
        except Exception:
            pass
        return total, None
    except Exception as exc:
        return None, str(exc)[:120]


def read_nav_snapshot_lines() -> list[dict[str, Any]]:
    if not NAV_SNAPSHOT_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in NAV_SNAPSHOT_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
    except Exception:
        return []
    return records


def append_nav_snapshot(snapshot: dict[str, Any]) -> None:
    ensure_log_dir()
    with NAV_SNAPSHOT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True, default=str) + "\n")


def collect_portfolio_nav_metrics() -> dict[str, Any]:
    pm_nav, pm_error = read_pm_portfolio_nav()
    hl_nav, hl_error = read_hl_portfolio_nav()
    if pm_nav is None or hl_nav is None:
        return {
            "pm_nav": pm_nav,
            "hl_nav": hl_nav,
            "total_nav": None,
            "nav_change": 0.0,
            "cum_return_pct": 0.0,
            "nav_status": "unavailable",
            "nav_errors": [item for item in (pm_error, hl_error) if item],
        }

    total_nav = float(pm_nav) + float(hl_nav)
    history = read_nav_snapshot_lines()
    first_total_nav = float(history[0]["total_nav"]) if history else None
    last_total_nav = float(history[-1]["total_nav"]) if history else None
    if first_total_nav is None:
        cum_return_pct = 0.0
        nav_change = 0.0
    else:
        cum_return_pct = ((total_nav / first_total_nav) - 1.0) * 100.0 if first_total_nav > 0 else 0.0
        nav_change = total_nav - last_total_nav if last_total_nav is not None else 0.0

    snapshot = {
        "timestamp": now_iso(),
        "pm_nav": round(float(pm_nav), 4),
        "hl_nav": round(float(hl_nav), 4),
        "total_nav": round(total_nav, 4),
        "nav_change": round(nav_change, 4),
        "cum_return_pct": round(cum_return_pct, 4),
    }
    append_nav_snapshot(snapshot)
    return {
        **snapshot,
        "nav_status": "ok",
        "nav_errors": [],
    }


def state_file(market_key: str) -> Path:
    return LOG_DIR / f"auto_state_{market_slug(market_key)}.json"


def append_event(event: dict[str, Any]) -> None:
    ensure_log_dir()
    payload = {"ts": now_iso(), **event}
    with event_log_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def default_state(market_key: str) -> dict[str, Any]:
    return {
        "market": market_key,
        "state": STATE_IDLE,
        "updated_at": now_iso(),
        "run_id": None,
        "s1": {
            "strategy_variant": S1_VARIANT,
            "entry_log": None,
            "pm_token": None,
            "hl_coin": None,
            "intended_shares": BOX_SHARES,
            "matched_shares": 0.0,
            "status": "none",
        },
        "s2": {
            "strategy_variant": S2_VARIANT,
            "entry_log": None,
            "exit_log": None,
            "pm_token": None,
            "hl_coin": None,
            "intended_shares": BOX_SHARES,
            "matched_shares": 0.0,
            "original_entry_cost": None,
            "status": "none",
        },
        "last_error": None,
        "halt_reason": None,
    }


def write_state(state: dict[str, Any]) -> None:
    ensure_log_dir()
    state["updated_at"] = now_iso()
    state_file(str(state["market"])).write_text(
        json.dumps(state, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def load_state(market_key: str) -> dict[str, Any]:
    ensure_log_dir()
    path = state_file(market_key)
    if not path.exists():
        state = default_state(market_key)
        write_state(state)
        append_event({"event": "state_created", "market": market_key, "state": STATE_IDLE, "state_file": str(path)})
        return state
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        state = default_state(market_key)
        state["state"] = STATE_HALTED
        state["last_error"] = str(exc)
        state["halt_reason"] = "state file corrupt"
        write_state(state)
        append_event({"event": "halted", "market": market_key, "reason": "state file corrupt", "error": str(exc)})
        return state
    if state.get("market") != market_key or state.get("state") not in VALID_STATES:
        state = default_state(market_key)
        state["state"] = STATE_HALTED
        state["last_error"] = "invalid state file content"
        state["halt_reason"] = "state file invalid"
        write_state(state)
        append_event({"event": "halted", "market": market_key, "reason": "state file invalid"})
    return state


def write_active_market(market_key: str, state: dict[str, Any]) -> None:
    ensure_log_dir()
    ACTIVE_FILE.write_text(
        json.dumps(
            {
                "market": market_key,
                "state": state["state"],
                "state_file": str(state_file(market_key)),
                "updated_at": now_iso(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def read_active_market() -> dict[str, Any] | None:
    if not ACTIVE_FILE.exists():
        return None
    try:
        return json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"market": None, "state": STATE_HALTED, "reason": "active file corrupt"}


def active_market_lock_exists() -> bool:
    active = read_active_market()
    return bool(active and active.get("market") is not None)


def clear_active_market(market_key: str) -> None:
    active = read_active_market()
    if active and active.get("market") == market_key and ACTIVE_FILE.exists():
        ACTIVE_FILE.unlink()


def evaluate_active_lock(active: dict[str, Any] | None = None) -> dict[str, Any]:
    if active is None:
        active = read_active_market()
    result: dict[str, Any] = {
        "active_lock_exists": bool(active and active.get("market") is not None),
        "active_lock_market": None,
        "active_lock_state": None,
        "active_lock_stale": False,
    }
    if not result["active_lock_exists"]:
        return result
    lock_market = str(active.get("market"))
    lock_state = active.get("state")
    result["active_lock_market"] = lock_market
    result["active_lock_state"] = lock_state
    state_file_path = active.get("state_file")
    if not state_file_path:
        result["active_lock_error"] = f"active lock missing state_file: {active}"
        return result
    path = Path(state_file_path)
    if not path.exists():
        result["active_lock_error"] = f"active lock state_file not found: {state_file_path}"
        return result
    try:
        per_market = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["active_lock_error"] = f"active lock state_file unreadable: {exc}"
        return result
    file_market = per_market.get("market")
    if file_market and str(file_market) != lock_market:
        result["active_lock_error"] = (
            f"active lock market mismatch: lock={lock_market} state_file={file_market}"
        )
        return result
    if lock_state == STATE_HALTED:
        if per_market.get("state") == STATE_HALTED:
            return result
        if per_market.get("halt_reason") or per_market.get("last_error"):
            result["active_lock_error"] = (
                f"active lock HALTED but per-market has errors: halt_reason={per_market.get('halt_reason')} "
                f"last_error={per_market.get('last_error')}"
            )
            return result
        result["active_lock_stale"] = True
    return result


def print_active_lock_status(lock_eval: dict[str, Any] | None = None) -> None:
    lock_eval = lock_eval or evaluate_active_lock()
    print(f"active_lock_exists: {str(lock_eval['active_lock_exists']).lower()}")
    print(f"active_lock_market: {lock_eval.get('active_lock_market')}")
    print(f"active_lock_state: {lock_eval.get('active_lock_state')}")
    print(f"active_lock_stale: {str(lock_eval.get('active_lock_stale', False)).lower()}")
    if lock_eval.get("active_lock_error"):
        print(f"active_lock_error: {lock_eval['active_lock_error']}")


def clear_stale_active_lock(active: dict[str, Any], reason: str) -> str:
    ensure_log_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = LOG_DIR / f"auto_active_market_backup_stale_{timestamp}.json"
    backup_path.write_text(json.dumps(active, indent=2, sort_keys=True), encoding="utf-8")
    if ACTIVE_FILE.exists():
        ACTIVE_FILE.unlink()
    append_event(
        {
            "event": "stale_active_lock_cleared",
            "market": active.get("market"),
            "active_lock_state": active.get("state"),
            "reason": reason,
            "backup_file": str(backup_path),
        }
    )
    return str(backup_path)


def maybe_clear_stale_active_lock_for_reconciled_market(
    market_key: str,
    state: dict[str, Any],
    reason: str = "s1_reconcile",
) -> str | None:
    if state.get("state") != STATE_S1_ACTIVE_S2_IDLE:
        return None
    if state.get("s1", {}).get("status") != "active":
        return None
    if state.get("s2", {}).get("status") not in {"none", "idle", "exited"}:
        return None
    if state.get("halt_reason") or state.get("last_error"):
        return None
    active = read_active_market()
    if not active or str(active.get("market")) != market_key or active.get("state") != STATE_HALTED:
        return None
    return clear_stale_active_lock(active, reason)


def resolve_stale_active_lock_if_needed() -> dict[str, Any]:
    lock_eval = evaluate_active_lock()
    if lock_eval.get("active_lock_error"):
        return lock_eval
    if lock_eval.get("active_lock_stale"):
        active = read_active_market()
        if active:
            backup_path = clear_stale_active_lock(active, "per_market_recovered")
            print("STALE ACTIVE LOCK CLEARED")
            print(f"backup_file: {backup_path}")
            lock_eval = evaluate_active_lock()
    return lock_eval


def transition(state: dict[str, Any], to_state: str, reason: str, extra: dict[str, Any] | None = None) -> None:
    from_state = state.get("state")
    state["state"] = to_state
    if to_state != STATE_HALTED:
        state["last_error"] = None
        state["halt_reason"] = None
    write_state(state)
    if to_state in ACTIVE_STATES:
        write_active_market(str(state["market"]), state)
    append_event(
        {
            "event": "state_transition",
            "market": state["market"],
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            **(extra or {}),
        }
    )


def halt(state: dict[str, Any], reason: str, extra: dict[str, Any] | None = None) -> None:
    state["state"] = STATE_HALTED
    state["last_error"] = reason
    state["halt_reason"] = reason
    write_state(state)
    write_active_market(str(state["market"]), state)
    append_event({"event": "halted", "market": state["market"], "reason": reason, **(extra or {})})


def write_json_log(market_key: str, prefix: str, payload: dict[str, Any]) -> str:
    ensure_log_dir()
    path = LOG_DIR / f"{prefix}_{market_slug(market_key)}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def direct_hl_ioc_buy(exchange: Any, coin: str, price: float, shares: float) -> Any:
    return exchange.order(coin, True, shares, min(round(price, 6), 0.999), {"limit": {"tif": "Ioc"}})


def direct_pm_fak_sell(client: Any, token: str, price: float, shares: float) -> Any:
    from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

    _, _, tick_size, neg_risk = pm.top(token)
    return client.create_and_post_order(
        order_args=OrderArgs(token_id=token, price=max(round(price, 4), 0.001), size=shares, side=Side.SELL),
        options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
        order_type=OrderType.FAK,
    )


def direct_hl_ioc_sell(exchange: Any, coin: str, price: float, shares: float) -> Any:
    return exchange.order(coin, False, shares, max(round(price, 6), 0.001), {"limit": {"tif": "Ioc"}})


def filled_ok(pm_filled: float, hl_filled: float, intended: float = BOX_SHARES) -> tuple[bool, str]:
    if abs(pm_filled - intended) > FILL_TOLERANCE:
        return False, f"PM partial fill: filled={pm_filled:.6f}, intended={intended:.6f}"
    if abs(hl_filled - intended) > FILL_TOLERANCE:
        return False, f"HL partial fill: filled={hl_filled:.6f}, intended={intended:.6f}"
    if abs(pm_filled - hl_filled) > FILL_TOLERANCE:
        return False, f"PM/HL fill mismatch: pm={pm_filled:.6f}, hl={hl_filled:.6f}"
    return True, "filled_ok"


def fill_error_fields(filled_qty: float, target_qty: float) -> dict[str, float]:
    error_qty = abs(float(filled_qty) - float(target_qty))
    error_pct = error_qty / float(target_qty) if float(target_qty or 0) > 0 else float("inf")
    return {"filled_qty": float(filled_qty), "fill_error_qty": error_qty, "fill_error_pct": error_pct}


def s2_exit_effective_filled_qty(
    position_delta_filled: float,
    order_response_filled: float | None,
    order_confirmed: bool,
    intended_shares: float,
    venue: str,
) -> tuple[float, list[str]]:
    warnings: list[str] = []
    delta = float(position_delta_filled or 0)
    if order_confirmed and order_response_filled is not None:
        effective = float(order_response_filled)
        if intended_shares > 0:
            delta_error_pct = abs(delta - effective) / intended_shares
            if delta <= 1e-9 and effective > 0:
                warnings.append(f"{venue.lower()}_position_delta_stale_or_inconsistent")
            elif delta_error_pct > S2_EXIT_FILL_TOLERANCE_PCT:
                warnings.append(f"{venue.lower()}_position_delta_stale_or_inconsistent")
        return effective, warnings
    return delta, warnings


def s2_exit_confirmation_status(pm_filled: float, hl_filled: float, target_qty: float) -> dict[str, Any]:
    pm = fill_error_fields(pm_filled, target_qty)
    hl = fill_error_fields(hl_filled, target_qty)
    pm_within = pm["fill_error_pct"] <= S2_EXIT_FILL_TOLERANCE_PCT
    hl_within = hl["fill_error_pct"] <= S2_EXIT_FILL_TOLERANCE_PCT
    pm_exact = pm["fill_error_qty"] <= 1e-9
    hl_exact = hl["fill_error_qty"] <= 1e-9
    if pm_exact and hl_exact:
        status = "confirmed_exact"
        requires_manual_review = False
    elif pm_within and hl_within:
        status = "confirmed_with_tolerance"
        requires_manual_review = False
    else:
        status = "partial_fill_requires_review"
        requires_manual_review = True
    return {
        "target_qty": float(target_qty),
        "tolerance_pct": S2_EXIT_FILL_TOLERANCE_PCT,
        "pm_filled_qty": pm["filled_qty"],
        "hl_filled_qty": hl["filled_qty"],
        "pm_fill_error_qty": pm["fill_error_qty"],
        "hl_fill_error_qty": hl["fill_error_qty"],
        "pm_fill_error_pct": pm["fill_error_pct"],
        "hl_fill_error_pct": hl["fill_error_pct"],
        "confirmation_status": status,
        "requires_manual_review": requires_manual_review,
        "state_after": STATE_S2_EXITED if not requires_manual_review else STATE_HALTED,
    }


def s2_exit_fills_ok(pm_filled: float, hl_filled: float, intended: float) -> tuple[bool, str, dict[str, Any]]:
    status = s2_exit_confirmation_status(pm_filled, hl_filled, intended)
    if not status["requires_manual_review"]:
        return True, str(status["confirmation_status"]), status
    return False, "partial_fill_outside_tolerance", status


def extract_order_id(response: Any) -> str | None:
    if isinstance(response, dict):
        for key in ("orderID", "orderId", "order_id", "oid"):
            if response.get(key) is not None:
                return str(response[key])
        for value in response.values():
            nested = extract_order_id(value)
            if nested:
                return nested
    if isinstance(response, list):
        for item in response:
            nested = extract_order_id(item)
            if nested:
                return nested
    return None


def pm_sell_response_reported_shares(response: Any, intended_shares: float) -> float | None:
    if isinstance(response, dict):
        making = maybe_float(response.get("makingAmount"))
        if making is not None and abs(making - intended_shares) / intended_shares <= S2_EXIT_FILL_TOLERANCE_PCT:
            return making
        for value in response.values():
            nested = pm_sell_response_reported_shares(value, intended_shares)
            if nested is not None:
                return nested
    if isinstance(response, list):
        for item in response:
            nested = pm_sell_response_reported_shares(item, intended_shares)
            if nested is not None:
                return nested
    return None


def response_reported_filled_shares(venue: str, response: Any, *, action_type: str | None = None, intended_shares: float | None = None) -> float | None:
    if venue == "PM" and action_type == "S2_EXIT" and intended_shares:
        return pm_sell_response_reported_shares(response, float(intended_shares))
    try:
        reported = float(filled_shares(venue, response))
    except Exception:
        return None
    return reported if reported > 0 else None


def pm_response_fill_price(response: Any, shares: float) -> float | None:
    if isinstance(response, dict):
        making = maybe_float(response.get("makingAmount"))
        taking = maybe_float(response.get("takingAmount"))
        if making and taking:
            if approx_equal(making, shares):
                return taking / making
            if approx_equal(taking, shares):
                return making / taking
        for value in response.values():
            nested = pm_response_fill_price(value, shares)
            if nested is not None:
                return nested
    if isinstance(response, list):
        for item in response:
            nested = pm_response_fill_price(item, shares)
            if nested is not None:
                return nested
    return None


def hl_response_fill_price(response: Any) -> float | None:
    if isinstance(response, dict):
        filled = response.get("filled")
        if isinstance(filled, dict) and filled.get("avgPx") is not None:
            return float(filled["avgPx"])
        for value in response.values():
            nested = hl_response_fill_price(value)
            if nested is not None:
                return nested
    if isinstance(response, list):
        for item in response:
            nested = hl_response_fill_price(item)
            if nested is not None:
                return nested
    return None


def order_response_fill_price(venue: str, response: Any, shares: float) -> float | None:
    if venue == "PM":
        return pm_response_fill_price(response, shares)
    if venue == "HL":
        return hl_response_fill_price(response)
    return None


def build_trade_confirmation(
    *,
    market_key: str,
    action_type: str,
    strategy_slot: str,
    pm_token: str,
    hl_coin: str,
    intended_shares: float,
    pm_before: float,
    pm_after: float,
    hl_before: float,
    hl_after: float,
    orders: list[dict[str, Any]],
    pm_filled: float,
    hl_filled: float,
    confirmed: bool,
) -> dict[str, Any]:
    pm_order = next((order for order in orders if order.get("venue") == "PM"), {})
    hl_order = next((order for order in orders if order.get("venue") == "HL"), {})
    pm_response_filled = response_reported_filled_shares(
        "PM",
        pm_order.get("response"),
        action_type=action_type,
        intended_shares=intended_shares,
    )
    hl_response_filled = response_reported_filled_shares(
        "HL",
        hl_order.get("response"),
        action_type=action_type,
        intended_shares=intended_shares,
    )
    if action_type == "S2_EXIT":
        pm_order_confirmed = (
            pm_response_filled is not None
            and abs(pm_response_filled - intended_shares) / intended_shares <= S2_EXIT_FILL_TOLERANCE_PCT
        )
        hl_order_confirmed = (
            hl_response_filled is not None
            and abs(hl_response_filled - intended_shares) / intended_shares <= S2_EXIT_FILL_TOLERANCE_PCT
        )
        pm_effective, pm_fill_warnings = s2_exit_effective_filled_qty(
            pm_filled,
            pm_response_filled,
            pm_order_confirmed,
            intended_shares,
            "PM",
        )
        hl_effective, hl_fill_warnings = s2_exit_effective_filled_qty(
            hl_filled,
            hl_response_filled,
            hl_order_confirmed,
            intended_shares,
            "HL",
        )
        fill_status = s2_exit_confirmation_status(pm_effective, hl_effective, intended_shares)
        pm_position_confirmed = abs(pm_filled - intended_shares) / intended_shares <= S2_EXIT_FILL_TOLERANCE_PCT if intended_shares else False
        hl_position_confirmed = abs(hl_filled - intended_shares) / intended_shares <= S2_EXIT_FILL_TOLERANCE_PCT if intended_shares else False
        fill_warnings = pm_fill_warnings + hl_fill_warnings
    else:
        fill_warnings = []
        pm_effective = pm_filled
        hl_effective = hl_filled
        fill_status = {
            "target_qty": float(intended_shares),
            "tolerance_pct": 0.0,
            "pm_filled_qty": float(pm_filled),
            "hl_filled_qty": float(hl_filled),
            "pm_fill_error_qty": abs(pm_filled - intended_shares),
            "hl_fill_error_qty": abs(hl_filled - intended_shares),
            "pm_fill_error_pct": abs(pm_filled - intended_shares) / intended_shares if intended_shares else float("inf"),
            "hl_fill_error_pct": abs(hl_filled - intended_shares) / intended_shares if intended_shares else float("inf"),
            "confirmation_status": "confirmed_exact" if confirmed else "partial_fill_requires_review",
            "requires_manual_review": not confirmed,
            "state_after": None,
        }
        pm_position_confirmed = abs(pm_filled - intended_shares) <= FILL_TOLERANCE
        hl_position_confirmed = abs(hl_filled - intended_shares) <= FILL_TOLERANCE
        pm_order_confirmed = pm_response_filled is not None and abs(pm_response_filled - intended_shares) <= FILL_TOLERANCE
        hl_order_confirmed = hl_response_filled is not None and abs(hl_response_filled - intended_shares) <= FILL_TOLERANCE
    pm_confirmed = pm_position_confirmed or pm_order_confirmed
    hl_confirmed = hl_position_confirmed or hl_order_confirmed
    trade_confirmed = pm_confirmed and hl_confirmed
    if pm_position_confirmed and hl_position_confirmed:
        source = "position_delta"
    elif pm_order_confirmed or hl_order_confirmed:
        source = "position_delta_plus_fill"
    else:
        source = "position_delta"
    if action_type == "S2_EXIT":
        pm_confirmed_filled = pm_effective
        hl_confirmed_filled = hl_effective
    else:
        pm_confirmed_filled = pm_filled
        hl_confirmed_filled = hl_filled
    return {
        "market": market_key,
        "action_type": action_type,
        "strategy_slot": strategy_slot,
        "pm": {
            "token": pm_token,
            "intended_shares": intended_shares,
            "order_submitted": "response" in pm_order,
            "order_id": extract_order_id(pm_order.get("response")),
            "position_before": pm_before,
            "position_after": pm_after,
            "position_delta_filled_shares": pm_filled,
            "confirmed_filled_shares": pm_confirmed_filled,
            "order_response_reported_filled_shares": pm_response_filled,
            "confirmation_source": source,
            "position_confirmed": pm_position_confirmed,
            "order_fill_confirmed": pm_order_confirmed,
            "confirmed": pm_confirmed,
        },
        "hl": {
            "coin": hl_coin,
            "intended_shares": intended_shares,
            "order_submitted": "response" in hl_order,
            "order_id": extract_order_id(hl_order.get("response")),
            "position_before": hl_before,
            "position_after": hl_after,
            "position_delta_filled_shares": hl_filled,
            "confirmed_filled_shares": hl_confirmed_filled,
            "order_response_reported_filled_shares": hl_response_filled,
            "confirmation_source": source,
            "position_confirmed": hl_position_confirmed,
            "order_fill_confirmed": hl_order_confirmed,
            "confirmed": hl_confirmed,
        },
        "auth_diagnostics": list(PM_AUTH_DIAGNOSTICS),
        "position_delta_confirmed": confirmed,
        **fill_status,
        "fill_warnings": fill_warnings if action_type == "S2_EXIT" else [],
        "trade_confirmed": trade_confirmed and not fill_status.get("requires_manual_review"),
        "state_update_allowed": trade_confirmed and not fill_status.get("requires_manual_review"),
        "orders_placed": bool(orders),
    }


def print_trade_confirmation(confirmation: dict[str, Any], reason: str | None = None) -> None:
    label = "TRADE CONFIRMATION" if confirmation.get("trade_confirmed") else "TRADE CONFIRMATION FAILED"
    pm = confirmation.get("pm") or {}
    hl = confirmation.get("hl") or {}
    print(label)
    print()
    print(f"PM position:   {fmt_num(pm.get('position_before'))} -> {fmt_num(pm.get('position_after'))}")
    print(f"HL position:   {fmt_num(hl.get('position_before'))} -> {fmt_num(hl.get('position_after'))}")
    print(f"Confirmed:     {'yes' if confirmation.get('trade_confirmed') else 'no'}")
    print(f"Source:        {pm.get('confirmation_source') or hl.get('confirmation_source') or 'n/a'}")
    if confirmation.get("action_type") == "S2_EXIT":
        print(f"confirmation_status: {confirmation.get('confirmation_status')}")
        print(f"target_qty: {float(confirmation.get('target_qty') or 0):.6f}")
        print(f"tolerance_pct: {float(confirmation.get('tolerance_pct') or 0):.6f}")
        print(f"pm_filled_qty: {float(confirmation.get('pm_filled_qty') or 0):.6f}")
        print(f"hl_filled_qty: {float(confirmation.get('hl_filled_qty') or 0):.6f}")
        print(f"pm_fill_error_qty: {float(confirmation.get('pm_fill_error_qty') or 0):.6f}")
        print(f"hl_fill_error_qty: {float(confirmation.get('hl_fill_error_qty') or 0):.6f}")
        print(f"pm_fill_error_pct: {float(confirmation.get('pm_fill_error_pct') or 0):.6f}")
        print(f"hl_fill_error_pct: {float(confirmation.get('hl_fill_error_pct') or 0):.6f}")
        print(f"requires_manual_review: {str(bool(confirmation.get('requires_manual_review'))).lower()}")
        print(f"state_after: {confirmation.get('state_after')}")
    if reason:
        print(f"Reason:        {reason}")
    print()


def execution_is_confirmed(result: dict[str, Any]) -> bool:
    confirmation = result.get("confirmation", {})
    if confirmation:
        return bool(
            confirmation.get("trade_confirmed")
            and confirmation.get("state_update_allowed")
            and confirmation.get("pm", {}).get("confirmed")
            and confirmation.get("hl", {}).get("confirmed")
        )
    ok, _ = filled_ok(float(result.get("pm_filled_shares") or 0), float(result.get("hl_filled_shares") or 0))
    return ok


def pm_position_size(token: str) -> float:
    positions = pm.get_positions(pm.get_funder())
    for position in positions if isinstance(positions, list) else []:
        if str(position.get("asset")) == token:
            return float(position.get("size", 0) or 0)
    return 0.0


def pm_position_read_risk_event(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError) and exc.code in {408, 504, 524}:
        return "PM_POSITION_READ_TIMEOUT"
    if isinstance(exc, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return "PM_POSITION_READ_TIMEOUT"
    return "PM_POSITION_UNAVAILABLE"


def log_pm_position_read_warning(
    *,
    market_key: str | None,
    token: str,
    context: str,
    exc: Exception,
) -> dict[str, Any]:
    risk_event = pm_position_read_risk_event(exc)
    status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
    payload = {
        "event": "PM_POSITION_READ_WARNING",
        "risk_event": risk_event,
        "market": market_key,
        "context": context,
        "token": token,
        "error_type": type(exc).__name__,
        "status": status,
        "action": "mark_pm_position_unavailable",
        "blocks_execution": False,
        "error": str(exc)[:200],
    }
    append_event(payload)
    print(
        "PM_POSITION_READ_WARNING "
        f"market={market_key or 'n/a'} context={context} "
        f"error_type={payload['error_type']} status={status} "
        f"risk_event={risk_event} action=mark_pm_position_unavailable blocks_execution=false"
    )
    return payload


def safe_pm_position_size(
    token: str,
    *,
    market_key: str | None = None,
    context: str = "summary",
) -> tuple[float | None, dict[str, Any] | None]:
    try:
        return pm_position_size(token), None
    except PM_POSITION_READ_ERRORS as exc:
        warning = log_pm_position_read_warning(
            market_key=market_key,
            token=token,
            context=context,
            exc=exc,
        )
        return None, warning


HL_API_ERRORS = (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError)


def hl_error_reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return "429"
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "url_error"
    if isinstance(exc, ConnectionError):
        return "connection_error"
    return type(exc).__name__


def is_hl_api_error(exc: Exception) -> bool:
    return isinstance(exc, HL_API_ERRORS)


def hl_backoff_active() -> tuple[bool, float]:
    remaining = max(HL_BACKOFF_UNTIL - time.time(), 0.0)
    return remaining > 0, remaining


def register_hl_backoff(exc: Exception | None = None) -> float:
    global HL_BACKOFF_SECONDS, HL_BACKOFF_UNTIL
    active, _remaining = hl_backoff_active()
    if active and HL_BACKOFF_SECONDS > 0:
        next_seconds = min(HL_BACKOFF_SECONDS * 2, HL_BACKOFF_MAX_SECONDS)
    else:
        next_seconds = HL_BACKOFF_INITIAL_SECONDS
    HL_BACKOFF_SECONDS = next_seconds
    HL_BACKOFF_UNTIL = time.time() + next_seconds
    return next_seconds


def clear_hl_backoff() -> None:
    global HL_BACKOFF_SECONDS, HL_BACKOFF_UNTIL
    HL_BACKOFF_SECONDS = 0.0
    HL_BACKOFF_UNTIL = 0.0


def log_hl_api_warning(
    *,
    context: str,
    exc: Exception,
    market_key: str | None = None,
    coin: str | None = None,
    action: str = "mark_hl_unavailable",
    blocks_execution: bool = False,
) -> dict[str, Any]:
    reason = hl_error_reason(exc)
    status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
    backoff_seconds = register_hl_backoff(exc)
    event_name = "HL_RATE_LIMIT_WARNING" if status == 429 else "HL_API_WARNING"
    payload = {
        "event": event_name,
        "market": market_key,
        "context": context,
        "coin": coin,
        "error_type": type(exc).__name__,
        "status": status,
        "reason": reason,
        "action": action,
        "blocks_execution": blocks_execution,
        "backoff_seconds": backoff_seconds,
        "error": str(exc)[:200],
    }
    append_event(payload)
    if status == 429:
        print("HL_RATE_LIMIT_WARNING: HTTP 429 Too Many Requests")
    else:
        print(f"HL_API_WARNING: {type(exc).__name__}: {str(exc)[:120]}")
    print(
        f"context={context} market={market_key or 'n/a'} coin={coin or 'n/a'} "
        f"action={action} blocks_execution={str(blocks_execution).lower()} "
        f"backoff_seconds={backoff_seconds:g}"
    )
    return payload


def skipped_for_hl_backoff(
    *,
    context: str,
    market_key: str | None = None,
    coin: str | None = None,
    blocks_execution: bool = False,
) -> dict[str, Any] | None:
    active, remaining = hl_backoff_active()
    if not active:
        return None
    payload = {
        "event": "HL_BACKOFF_ACTIVE",
        "market": market_key,
        "context": context,
        "coin": coin,
        "remaining_seconds": round(remaining, 3),
        "action": "skip_hl_api_call",
        "blocks_execution": blocks_execution,
    }
    append_event(payload)
    return payload


def safe_hl_spot_balances(
    *,
    context: str,
    market_key: str | None = None,
    coin: str | None = None,
    blocks_execution: bool = False,
) -> tuple[list[tuple[str, float]] | None, dict[str, Any] | None]:
    backoff_payload = skipped_for_hl_backoff(
        context=context,
        market_key=market_key,
        coin=coin,
        blocks_execution=blocks_execution,
    )
    if backoff_payload:
        return None, backoff_payload
    try:
        balances = hl.spot_balances(hl.get_account())
        clear_hl_backoff()
        return balances, None
    except HL_API_ERRORS as exc:
        warning = log_hl_api_warning(
            context=context,
            exc=exc,
            market_key=market_key,
            coin=coin,
            blocks_execution=blocks_execution,
        )
        return None, warning


def safe_hl_coin_book(
    coin: str,
    *,
    context: str,
    market_key: str | None = None,
    blocks_execution: bool = False,
) -> tuple[tuple[list[Any], list[Any]] | None, dict[str, Any] | None]:
    backoff_payload = skipped_for_hl_backoff(
        context=context,
        market_key=market_key,
        coin=coin,
        blocks_execution=blocks_execution,
    )
    if backoff_payload:
        return None, backoff_payload
    try:
        book = hl.coin_book(coin)
        clear_hl_backoff()
        return book, None
    except HL_API_ERRORS as exc:
        warning = log_hl_api_warning(
            context=context,
            exc=exc,
            market_key=market_key,
            coin=coin,
            blocks_execution=blocks_execution,
        )
        return None, warning


def safe_hl_open_orders(
    *,
    context: str,
    market_key: str | None = None,
    blocks_execution: bool = False,
) -> tuple[list[Any] | None, dict[str, Any] | None]:
    backoff_payload = skipped_for_hl_backoff(
        context=context,
        market_key=market_key,
        blocks_execution=blocks_execution,
    )
    if backoff_payload:
        return None, backoff_payload
    try:
        orders = hl.open_orders(hl.get_account())
        clear_hl_backoff()
        return orders if isinstance(orders, list) else [], None
    except HL_API_ERRORS as exc:
        warning = log_hl_api_warning(
            context=context,
            exc=exc,
            market_key=market_key,
            blocks_execution=blocks_execution,
        )
        return None, warning


def hl_position_size(coin: str) -> float:
    balances = dict(hl.spot_balances(hl.get_account()))
    aliases = {coin, "#" + coin.lstrip("#+"), "+" + coin.lstrip("#+")}
    for alias in aliases:
        if alias in balances:
            return float(balances[alias] or 0)
    return 0.0


def safe_hl_position_size(
    coin: str,
    *,
    market_key: str | None = None,
    context: str = "summary",
    blocks_execution: bool = False,
) -> tuple[float | None, dict[str, Any] | None]:
    spot, warning = safe_hl_spot_balances(
        context=context,
        market_key=market_key,
        coin=coin,
        blocks_execution=blocks_execution,
    )
    if spot is None:
        return None, warning
    balances = dict(spot)
    aliases = {coin, "#" + coin.lstrip("#+"), "+" + coin.lstrip("#+")}
    for alias in aliases:
        if alias in balances:
            return float(balances[alias] or 0), None
    return 0.0, None


def wc_position_snapshot(market: dict[str, Any]) -> dict[str, float]:
    return {
        "pm_yes": pm_position_size(str(market["pm_yes"])),
        "pm_no": pm_position_size(str(market["pm_no"])),
        "hl_yes": hl_position_size(str(market["hl_yes_coin"])),
        "hl_no": hl_position_size(str(market["hl_no_coin"])),
    }


def has_wc_position(snapshot: dict[str, float]) -> bool:
    return any(abs(value) > FILL_TOLERANCE for value in snapshot.values())


def approx_equal(left: float, right: float, tolerance: float = FILL_TOLERANCE) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def net_edge_bps(plan: dict[str, Any]) -> float:
    total_notional = float(plan.get("total_notional") or 0)
    return float(plan.get("expected_profit") or 0) / total_notional * 10000 if total_notional > 0 else 0.0


def walk_combined_executable_size_with_threshold(plan: dict[str, Any]) -> float:
    pm_asks, hl_asks = selected_ask_books(plan)
    pm_levels = [list(level) for level in pm_asks]
    hl_levels = [list(level) for level in hl_asks]
    qty = 0.0
    i = 0
    j = 0
    while i < len(pm_levels) and j < len(hl_levels):
        pm_px, pm_sz = pm_levels[i]
        hl_px, hl_sz = hl_levels[j]
        unit_notional = pm_px + hl_px
        unit_profit = 1.0 - unit_notional - pm_fee(pm_px) - hl_taker_fee()
        unit_bps = unit_profit / unit_notional * 10000 if unit_notional > 0 else 0.0
        if unit_profit < 0 or unit_bps < threshold_value("entry_min_net_edge_bps"):
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


def direct_combined_executable_size(plan: dict[str, Any]) -> float:
    pm_asks, hl_asks = selected_ask_books(plan)
    if not pm_asks or not hl_asks:
        return 0.0
    return min(float(pm_asks[0][1]), float(hl_asks[0][1]))


def build_entry_plans(market: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        calculate_plan(market, MAX_TOTAL_NOTIONAL_PER_STRATEGY, S1_VARIANT, box_shares=BOX_SHARES),
        calculate_plan(market, MAX_TOTAL_NOTIONAL_PER_STRATEGY, S2_VARIANT, box_shares=BOX_SHARES),
    ]


def parse_markets(args: argparse.Namespace) -> list[str]:
    raw = args.markets or args.market or ",".join(DEFAULT_MARKETS)
    markets = [item.strip() for item in raw.split(",") if item.strip()]
    unsupported = [market for market in markets if market not in SUPPORTED_MARKETS]
    if unsupported:
        raise SystemExit(f"Unsupported market(s): {', '.join(unsupported)}")
    return markets


def entry_failures(
    plans: list[dict[str, Any]],
    balances: dict[str, Any],
    combined_executable_size: float,
    position_detected: bool,
) -> list[str]:
    failures: list[str] = []
    if position_detected:
        failures.append("matching WC position already exists")
    if combined_executable_size + 1e-9 < COMBINED_REQUIRED_SHARES:
        failures.append(
            "combined depth insufficient at entry threshold: "
            f"required={COMBINED_REQUIRED_SHARES:.6f}, executable={combined_executable_size:.6f}"
        )
    for plan in plans:
        variant = plan["strategy_variant"]
        if float(plan["shares"]) != BOX_SHARES:
            failures.append(f"{variant}: shares must equal {BOX_SHARES}")
        if plan["market"].get("mapping_status") != "verified":
            failures.append(f"{variant}: mapping_status is not verified")
        if plan["expected_profit"] < threshold_value("entry_min_profit_usd"):
            failures.append(
                f"{variant}: expected_profit {plan['expected_profit']:.6f} < {threshold_value('entry_min_profit_usd'):.6f}"
            )
        if net_edge_bps(plan) < threshold_value("entry_min_net_edge_bps"):
            failures.append(
                f"{variant}: net_edge_bps {net_edge_bps(plan):.6f} < {threshold_value('entry_min_net_edge_bps'):.6f}"
            )
        if plan["total_notional"] > MAX_TOTAL_NOTIONAL_PER_STRATEGY + 1e-9:
            failures.append(f"{variant}: total_notional must be <= {MAX_TOTAL_NOTIONAL_PER_STRATEGY}")
        if plan["pm_leg_notional"] < pm_min_notional():
            failures.append(f"{variant}: PM leg notional below minimum")
        if plan["hl_notional"] < hl_min_notional():
            failures.append(f"{variant}: HL leg notional below minimum")
    pm_cash = balances.get("pm_cash")
    if pm_cash is not None and pm_cash < sum(float(plan["pm_notional"]) for plan in plans):
        failures.append("PM cash insufficient for S1+S2")
    hl_usdc = balances.get("hl_usdc")
    if hl_usdc is not None and hl_usdc < sum(float(plan["hl_notional"]) for plan in plans):
        failures.append("HL USDC insufficient for S1+S2")
    return failures


def live_gate_failures(args: argparse.Namespace, market_key: str) -> list[str]:
    failures: list[str] = []
    if not args.live:
        failures.append("--live is required")
    if bool_env("DRY_RUN", True):
        failures.append("DRY_RUN must be false")
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED must be true")
    if not bool_env("AUTO_LIVE_ENABLED", False):
        failures.append("AUTO_LIVE_ENABLED must be true")
    if not bool_env("AUTO_ENTRY_ENABLED", False):
        failures.append("AUTO_ENTRY_ENABLED must be true")
    if not bool_env("AUTO_EXIT_ENABLED", False):
        failures.append("AUTO_EXIT_ENABLED must be true")
    if market_key not in allowed_markets():
        failures.append(f"ALLOWED_MARKETS must include {market_key}")
    if stop_file_exists():
        failures.append("STOP file exists")
    if float(os.environ.get("MAX_ORDER_NOTIONAL", "0") or 0) < MAX_TOTAL_NOTIONAL_PER_STRATEGY:
        failures.append(f"MAX_ORDER_NOTIONAL must be >= {MAX_TOTAL_NOTIONAL_PER_STRATEGY}")
    if pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")):
        failures.append("Missing PM_FUNDER or PM_PRIVATE_KEY")
    if hl.missing_env(("HL_ACCOUNT", "HL_AGENT_KEY")):
        failures.append("Missing HL_ACCOUNT or HL_AGENT_KEY")
    return failures


def text_indicates_pm_auth_failure(text: str) -> bool:
    lowered = text.lower()
    return (
        "auth/api-key" in lowered
        or "could not create api key" in lowered
        or "request error status=400" in lowered
    )


def sanitize_pm_auth_error(text: str) -> str:
    redacted = text
    for key in ("PM_PRIVATE_KEY", "PM_RELAYER_API_KEY"):
        value = os.environ.get(key)
        if value:
            redacted = redacted.replace(value, "<redacted>")
    return redacted.strip().replace("\n", " ")[:500] or "unknown PM auth failure"


def pm_auth_diagnostic_from_output(text: str) -> dict[str, Any] | None:
    if not text_indicates_pm_auth_failure(text):
        return None
    lowered = text.lower()
    status = 400 if "status=400" in lowered or "could not create api key" in lowered else None
    message = "Could not create api key" if "could not create api key" in lowered else sanitize_pm_auth_error(text)
    return {
        "venue": "PM",
        "endpoint": "auth/api-key",
        "status": status,
        "message": message,
        "severity": "warning",
        "using_existing_auth": True,
        "blocks_execution": False,
    }


def record_pm_auth_diagnostic(diagnostic: dict[str, Any] | None) -> None:
    global PM_AUTH_WARNING_PRINTED
    if not diagnostic:
        return
    if diagnostic not in PM_AUTH_DIAGNOSTICS:
        PM_AUTH_DIAGNOSTICS.append(diagnostic)
    if PM_AUTH_WARNING_PRINTED:
        return
    PM_AUTH_WARNING_PRINTED = True
    print("PM_AUTH_DIAGNOSTIC_WARNING")
    print(f"endpoint: {diagnostic.get('endpoint')}")
    print(f"status: {diagnostic.get('status')}")
    print(f"message: {diagnostic.get('message')}")
    print(f"using_existing_auth: {str(bool(diagnostic.get('using_existing_auth'))).lower()}")
    print(f"blocks_execution: {str(bool(diagnostic.get('blocks_execution'))).lower()}")


def pm_auth_status() -> dict[str, Any]:
    blocking = [item for item in PM_AUTH_DIAGNOSTICS if item.get("blocks_execution")]
    return {
        "pm_auth_warning": bool(PM_AUTH_DIAGNOSTICS),
        "pm_auth_warning_count": len(PM_AUTH_DIAGNOSTICS),
        "pm_auth_blocks_execution": bool(blocking),
        "auth_diagnostics": list(PM_AUTH_DIAGNOSTICS),
    }


def build_pm_client_for_execution() -> Any:
    global PM_CLIENT_CACHE
    if PM_CLIENT_CACHE is not None:
        return PM_CLIENT_CACHE
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            PM_CLIENT_CACHE = pm.build_client()
    except Exception:
        diagnostic = pm_auth_diagnostic_from_output(f"{stdout.getvalue()}\n{stderr.getvalue()}")
        record_pm_auth_diagnostic(diagnostic)
        raise
    diagnostic = pm_auth_diagnostic_from_output(f"{stdout.getvalue()}\n{stderr.getvalue()}")
    record_pm_auth_diagnostic(diagnostic)
    return PM_CLIENT_CACHE


def check_pm_auth_cash() -> dict[str, Any]:
    attempted_create_api_key = PM_CLIENT_CACHE is None
    client = build_pm_client_for_execution()
    cash, _ = pm.get_cash(client)
    warning = PM_AUTH_DIAGNOSTICS[-1] if PM_AUTH_DIAGNOSTICS else None
    create_api_key_error = warning.get("message") if warning else None
    if cash is None:
        raise RuntimeError("cash unavailable")
    status = pm_auth_status()
    return {
        "cash": float(cash),
        "using_existing_creds": create_api_key_error is not None or not attempted_create_api_key,
        "attempted_create_api_key": attempted_create_api_key,
        "create_api_key_error": create_api_key_error,
        "final_auth_status": "PASS",
        **status,
    }


def read_live_balances_for_preflight() -> dict[str, Any]:
    balances: dict[str, Any] = {
        "pm_cash": None,
        "hl_usdc": None,
        "pm_positions": None,
        "hl_spot": None,
        "errors": [],
    }
    try:
        client = build_pm_client_for_execution()
        cash, _ = pm.get_cash(client)
        balances["pm_cash"] = float(cash or 0)
    except Exception as exc:
        balances["errors"].append(f"PM cash unavailable: {str(exc)[:120]}")
    try:
        positions = pm.get_positions(pm.get_funder())
        balances["pm_positions"] = positions if isinstance(positions, list) else []
    except Exception as exc:
        balances["errors"].append(f"PM positions unavailable: {str(exc)[:120]}")
    spot, warning = safe_hl_spot_balances(
        context="live_preflight_balance",
        blocks_execution=True,
    )
    if spot is None:
        reason = warning.get("reason") if warning else "unavailable"
        status = warning.get("status") if warning else None
        balances["errors"].append(f"HL spot unavailable: reason={reason} status={status}")
        balances["hl_unavailable"] = True
    else:
        balances["hl_spot"] = spot
        balances["hl_usdc"] = float(dict(spot).get("USDC", 0.0))
    return balances


def run_pm_auth_check_only() -> int:
    try:
        result = check_pm_auth_cash()
    except Exception as exc:
        print("PM_AUTH_CHECK_FAIL")
        print("using_existing_creds: false")
        print("attempted_create_api_key: true")
        print(f"create_api_key_error: {sanitize_pm_auth_error(str(exc))}")
        print("final_auth_status: FAIL")
        return 1
    print("PM_AUTH_CHECK_PASS")
    print(f"using_existing_creds: {str(bool(result['using_existing_creds'])).lower()}")
    print(f"attempted_create_api_key: {str(bool(result['attempted_create_api_key'])).lower()}")
    print(f"create_api_key_error: {result['create_api_key_error']}")
    print(f"final_auth_status: {result['final_auth_status']}")
    print(f"pm_auth_warning: {str(bool(result['pm_auth_warning'])).lower()}")
    print(f"pm_auth_blocks_execution: {str(bool(result['pm_auth_blocks_execution'])).lower()}")
    return 0


def run_pm_token_book_check(market_key: str) -> int:
    market = get_watchlist_market(market_key)
    token = str(market["pm_yes"])
    _, asks, _ = pm.book(token)
    best_ask = asks[0] if asks else (None, None)
    print(f"market: {market_key}")
    print(f"PM outcome: {market.get('pm_outcome')} YES")
    print(f"PM token: {token}")
    print(f"best ask price: {best_ask[0]}")
    print(f"best ask size: {best_ask[1]}")
    print(f"top 5 asks: {json.dumps(asks[:5])}")
    print(f"fetched_at: {now_iso()}")
    return 0


def pm_hl_position_summary(market_key: str) -> dict[str, Any]:
    market = get_watchlist_market(market_key)
    state = read_state_no_create(market_key)
    s1_status = str(state.get("s1", {}).get("status") or "none")
    s2_status = str(state.get("s2", {}).get("status") or "none")
    pm_yes_position = pm_position_size(str(market["pm_yes"]))
    hl_no_position = hl_position_size(str(market["hl_no_coin"]))
    expected_s1_shares = BOX_SHARES
    expected_s2_shares = BOX_SHARES
    balanced = approx_equal(pm_yes_position, hl_no_position)
    one_box_balanced = balanced and approx_equal(pm_yes_position, expected_s1_shares)
    two_box_balanced = balanced and approx_equal(pm_yes_position, expected_s1_shares + expected_s2_shares)
    inferred_s1_active = s1_status == "active" or (s1_status != "active" and s2_status != "active" and one_box_balanced)
    inferred_s2_active = s2_status == "active" and two_box_balanced
    inferred_s2_exited = s2_status == "exited" and one_box_balanced
    recommended_reconcile = (
        "mark_s1_active_if_balanced"
        if state.get("state") == STATE_HALTED
        and "PM partial fill" in str(state.get("halt_reason") or "")
        and s1_status != "active"
        and s2_status != "active"
        and one_box_balanced
        else None
    )
    return {
        "market": market_key,
        "pm_outcome": f"{market.get('pm_outcome')} YES",
        "hl_outcome": f"{market.get('hl_outcome')} NO",
        "pm_yes_position": pm_yes_position,
        "hl_no_position": hl_no_position,
        "expected_s1_shares": expected_s1_shares,
        "expected_s2_shares": expected_s2_shares,
        "inferred_s1_active": inferred_s1_active,
        "inferred_s2_active": inferred_s2_active,
        "inferred_s2_exited": inferred_s2_exited,
        "recommended_reconcile": recommended_reconcile,
        "balanced": balanced,
        "imbalance_amount": abs(pm_yes_position - hl_no_position),
    }


def run_pm_hl_position_check(market_key: str) -> int:
    summary = pm_hl_position_summary(market_key)
    print(f"market: {summary['market']}")
    print(f"PM {summary['pm_outcome']} current position: {summary['pm_yes_position']}")
    print(f"HL {summary['hl_outcome']} current position: {summary['hl_no_position']}")
    print(f"expected S1 shares: {summary['expected_s1_shares']}")
    print(f"expected S2 shares: {summary['expected_s2_shares']}")
    print(f"inferred S1 active: {str(bool(summary['inferred_s1_active'])).lower()}")
    print(f"inferred S2 active: {str(bool(summary['inferred_s2_active'])).lower()}")
    print(f"inferred S2 exited: {str(bool(summary['inferred_s2_exited'])).lower()}")
    print(f"recommended_reconcile: {summary['recommended_reconcile']}")
    print(f"balanced: {str(bool(summary['balanced'])).lower()}")
    print(f"imbalance amount: {summary['imbalance_amount']}")
    return 0


def open_exit_orders(market: dict[str, Any]) -> dict[str, Any]:
    pm_token = str(market["pm_yes"])
    hl_coin = str(market["hl_no_coin"])
    try:
        client = build_pm_client_for_execution()
        pm_orders_raw = client.get_open_orders()
    except Exception as exc:
        raise HaltedError(f"PM open orders check failed: {exc}") from exc
    try:
        hl_orders_raw, hl_warning = safe_hl_open_orders(
            context="open_exit_orders",
            market_key=str(market.get("market") or ""),
            blocks_execution=False,
        )
        if hl_orders_raw is None:
            reason = hl_warning.get("reason") if hl_warning else "unavailable"
            status = hl_warning.get("status") if hl_warning else None
            raise HaltedError(f"HL open orders check failed: reason={reason} status={status}")
    except HaltedError:
        raise

    pm_orders = [
        order
        for order in (pm_orders_raw if isinstance(pm_orders_raw, list) else [])
        if pm_token in json.dumps(order, default=str)
    ]
    hl_orders = [
        order
        for order in (hl_orders_raw if isinstance(hl_orders_raw, list) else [])
        if hl_coin in json.dumps(order, default=str)
    ]
    return {"pm_open_orders": pm_orders, "hl_open_orders": hl_orders}


def read_existing_state(market_key: str) -> dict[str, Any]:
    path = state_file(market_key)
    if not path.exists():
        raise HaltedError(f"state file does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def latest_existing_s2_exit_log(market_key: str) -> str | None:
    pattern = f"auto_exit_s2_{market_slug(market_key)}_*.json"
    matches = sorted(LOG_DIR.glob(pattern), reverse=True)
    return str(matches[0]) if matches else None


def s2_exit_reconcile_pnl_fields(
    analysis: dict[str, Any] | None,
    state_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not analysis:
        return {"pnl_source": "unavailable", "pnl_quality": "unknown"}
    exit_shares = float(analysis.get("exit_shares") or 0)
    pm_exit_price = analysis.get("pm_exit_price") or analysis.get("pm_bid")
    hl_exit_price = analysis.get("hl_exit_price") or analysis.get("hl_bid")
    original_entry_cost = analysis.get("entry_gross_cost") or analysis.get("original_entry_cost")
    entry_fees = s2_entry_fee_fields_from_state(state_before or {}, exit_shares)
    entry_pm_fee = analysis.get("entry_pm_fee")
    entry_hl_fee = analysis.get("entry_hl_fee")
    if entry_pm_fee is None:
        entry_pm_fee = entry_fees["entry_pm_fee"]
    if entry_hl_fee is None:
        entry_hl_fee = entry_fees["entry_hl_fee"]
    lifecycle_fields = s2_exit_lifecycle_pnl_fields(
        entry_gross_cost=original_entry_cost,
        exit_shares=exit_shares,
        pm_exit_price=pm_exit_price,
        hl_exit_price=hl_exit_price,
        entry_pm_fee=entry_pm_fee,
        entry_hl_fee=entry_hl_fee,
    )
    fields: dict[str, Any] = {
        "pnl_source": "fallback_from_exit_analysis",
        "pnl_quality": analysis.get("pnl_quality") or "estimated",
        "exit_analysis": analysis,
        "pm_exit_price": pm_exit_price,
        "hl_exit_price": hl_exit_price,
        "exit_shares": exit_shares,
        "original_entry_cost": original_entry_cost,
        **lifecycle_fields,
    }
    return fields


def build_s2_exit_reconcile_payload(
    market_key: str,
    summary: dict[str, Any],
    open_orders: dict[str, Any],
    state_before: dict[str, Any],
) -> dict[str, Any]:
    s1 = state_before.get("s1", {})
    s2 = state_before.get("s2", {})
    analysis = latest_positive_s2_exit_analysis(market_key)
    return {
        "event_type": "S2_EXIT_RECONCILED_FROM_POSITIONS",
        "market": market_key,
        "strategy_slot": "s2",
        "reason": "positions indicate S2 already exited after PM partial fill false negative",
        "pm_position_current": summary.get("pm_yes_position"),
        "hl_position_current": summary.get("hl_no_position"),
        "s1_matched_shares": float(s1.get("matched_shares") or 0),
        "s2_matched_shares_before": float(s2.get("matched_shares") or 0),
        "reconcile_method": "position_delta_after_halted_exit",
        "original_halt_reason": state_before.get("halt_reason"),
        "source": "portfolio_status_positions",
        "positions": summary,
        "open_orders": open_orders,
        "state_before": state_before,
        **s2_exit_reconcile_pnl_fields(analysis, state_before),
    }


def run_mark_s2_exited_if_balanced(market_key: str | None) -> int:
    if not market_key:
        print("S2_EXIT_RECONCILE_NOT_APPLIED")
        print("reason: --require-market is required")
        return 1
    if market_key not in SUPPORTED_MARKETS:
        print("S2_EXIT_RECONCILE_NOT_APPLIED")
        print(f"reason: market must be one of {sorted(SUPPORTED_MARKETS)}")
        return 1
    market = get_watchlist_market(market_key)
    state = read_existing_state(market_key)
    summary = pm_hl_position_summary(market_key)
    s1_matched = float(state.get("s1", {}).get("matched_shares") or 0)
    checks = [
        state.get("state") == STATE_HALTED or "PM partial fill" in str(state.get("last_error") or ""),
        "PM partial fill" in str(state.get("halt_reason") or state.get("last_error") or ""),
        state.get("s1", {}).get("status") == "active",
        state.get("s2", {}).get("status") == "active",
        approx_equal(float(summary["pm_yes_position"]), s1_matched),
        approx_equal(float(summary["hl_no_position"]), s1_matched),
        bool(summary["balanced"]),
        approx_equal(float(state.get("s2", {}).get("matched_shares") or 0), BOX_SHARES),
    ]
    try:
        open_orders = open_exit_orders(market)
        no_open_exit_orders = not open_orders["pm_open_orders"] and not open_orders["hl_open_orders"]
    except Exception as exc:
        print("S2_EXIT_RECONCILE_NOT_APPLIED")
        print(str(exc))
        return 1
    checks.append(no_open_exit_orders)
    if not all(checks):
        print("S2_EXIT_RECONCILE_NOT_APPLIED")
        print(f"state: {state.get('state')}")
        print(f"halt_reason: {state.get('halt_reason')}")
        print(f"last_error: {state.get('last_error')}")
        print(f"s1_status: {state.get('s1', {}).get('status')}")
        print(f"s2_status: {state.get('s2', {}).get('status')}")
        print(f"pm_position: {summary['pm_yes_position']}")
        print(f"hl_position: {summary['hl_no_position']}")
        print(f"s1_matched_shares: {s1_matched}")
        print(f"balanced: {summary['balanced']}")
        print(f"no_open_exit_orders: {no_open_exit_orders}")
        return 1

    state_before = json.loads(json.dumps(state, default=str))
    reconcile_payload = build_s2_exit_reconcile_payload(market_key, summary, open_orders, state_before)
    exit_log = write_json_log(market_key, "auto_exit_s2_reconcile", reconcile_payload)
    state["state"] = STATE_S1_ACTIVE_S2_IDLE
    state["halt_reason"] = None
    state["last_error"] = None
    state["s2"]["status"] = "exited"
    state["s2"]["exit_log"] = exit_log
    write_state(state)
    backup_path = maybe_clear_stale_active_lock_for_reconciled_market(market_key, state, "s2_exit_reconcile")
    portfolio = portfolio_summary(sorted(SUPPORTED_MARKETS), context="s2_exit_reconcile")
    write_portfolio_state(portfolio, None)
    append_event(
        {
            "event": "S2_EXIT_RECONCILED_FROM_POSITIONS",
            "market": market_key,
            "positions": summary,
            "exit_log": exit_log,
            "pnl_source": reconcile_payload.get("pnl_source"),
            "pnl_quality": reconcile_payload.get("pnl_quality"),
        }
    )
    print("S2_EXIT_RECONCILED")
    print(f"market: {market_key}")
    print("S1 remains active")
    print("S2 exited")
    print(f"state: {state['state']}")
    print(f"exit_log: {exit_log}")
    print(f"pnl_source: {reconcile_payload.get('pnl_source')}")
    print(f"pnl_quality: {reconcile_payload.get('pnl_quality')}")
    if backup_path:
        print("STALE ACTIVE LOCK CLEARED")
        print(f"backup_file: {backup_path}")
    print("orders_placed: no")
    return 0


def run_mark_s1_active_if_balanced(market_key: str) -> int:
    if market_key not in SUPPORTED_MARKETS:
        print("S1_ENTRY_RECONCILE_NOT_APPLIED")
        print(f"reason: market must be one of {sorted(SUPPORTED_MARKETS)}")
        return 1
    market = get_watchlist_market(market_key)
    state = read_existing_state(market_key)
    summary = pm_hl_position_summary(market_key)
    checks = [
        state.get("state") == STATE_HALTED,
        "PM partial fill" in str(state.get("halt_reason") or ""),
        approx_equal(float(summary["pm_yes_position"]), BOX_SHARES),
        approx_equal(float(summary["hl_no_position"]), BOX_SHARES),
        bool(summary["balanced"]),
        state.get("s1", {}).get("status") != "active",
        state.get("s2", {}).get("status") != "active",
    ]
    try:
        open_orders = open_exit_orders(market)
        no_open_orders = not open_orders["pm_open_orders"] and not open_orders["hl_open_orders"]
    except Exception as exc:
        print("S1_ENTRY_RECONCILE_NOT_APPLIED")
        print(str(exc))
        return 1
    checks.append(no_open_orders)
    if not all(checks):
        print("S1_ENTRY_RECONCILE_NOT_APPLIED")
        print(f"state: {state.get('state')}")
        print(f"halt_reason: {state.get('halt_reason')}")
        print(f"pm_position: {summary['pm_yes_position']}")
        print(f"hl_position: {summary['hl_no_position']}")
        print(f"balanced: {summary['balanced']}")
        print(f"no_open_orders: {no_open_orders}")
        return 1

    reconcile_payload = build_reconcile_s1_log_payload(
        market_key,
        summary,
        open_orders,
        state,
    )
    reconcile_log = write_json_log(market_key, "auto_entry_s1_reconcile", reconcile_payload)
    state["state"] = STATE_S1_ACTIVE_S2_IDLE
    state["halt_reason"] = None
    state["last_error"] = None
    state["s1"].update(
        {
            "status": "active",
            "matched_shares": BOX_SHARES,
            "intended_shares": BOX_SHARES,
            "pm_token": str(market["pm_yes"]),
            "hl_coin": str(market["hl_no_coin"]),
            "entry_log": reconcile_log,
        }
    )
    state["s2"].update(
        {
            "status": "none",
            "matched_shares": 0.0,
            "entry_log": None,
            "exit_log": None,
            "pm_token": None,
            "hl_coin": None,
            "original_entry_cost": None,
        }
    )
    write_state(state)
    backup_path = maybe_clear_stale_active_lock_for_reconciled_market(market_key, state)
    portfolio = portfolio_summary(sorted(SUPPORTED_MARKETS))
    write_portfolio_state(portfolio, None)
    append_event({"event": "s1_entry_reconciled", "market": market_key, "positions": summary, "entry_log": reconcile_log})
    print("S1_ENTRY_RECONCILED")
    print(f"market: {market_key}")
    print("S1 active")
    print("S2 idle")
    if backup_path:
        print("STALE ACTIVE LOCK CLEARED")
        print(f"backup_file: {backup_path}")
    print("orders_placed: no")
    return 0


def read_state_no_create(market_key: str) -> dict[str, Any]:
    path = state_file(market_key)
    if not path.exists():
        return default_state(market_key)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        state = default_state(market_key)
        state["state"] = STATE_HALTED
        state["halt_reason"] = f"state file read failed: {exc}"
        state["last_error"] = str(exc)
        return state


def portfolio_state_label(s1_status: str, s2_status: str, raw_state: str) -> str:
    if raw_state == STATE_HALTED:
        return STATE_HALTED
    if s1_status == "active" and s2_status in {"none", "idle", "exited"}:
        return "S1_ACTIVE_S2_IDLE"
    if s1_status == "active" and s2_status == "active":
        return STATE_ACTIVE
    if s1_status in {"none", "idle"} and s2_status in {"none", "idle", "exited"}:
        return STATE_IDLE
    return raw_state


def portfolio_market_summary(market_key: str, *, context: str = "summary") -> dict[str, Any]:
    state = read_state_no_create(market_key)
    market = get_watchlist_market(market_key)
    s1 = state.get("s1", {})
    s2 = state.get("s2", {})
    pm_position, pm_position_warning = safe_pm_position_size(
        str(market["pm_yes"]),
        market_key=market_key,
        context=context,
    )
    hl_position, hl_position_warning = safe_hl_position_size(
        str(market["hl_no_coin"]),
        market_key=market_key,
        context=context,
    )
    s1_status = str(s1.get("status") or "none")
    s2_status = str(s2.get("status") or "none")
    active_s1 = s1_status == "active"
    active_s2 = s2_status == "active"
    pm_position_unavailable = pm_position is None
    hl_position_unavailable = hl_position is None
    if pm_position_unavailable or hl_position_unavailable:
        balanced: bool | None = None
        imbalance_amount = None
    else:
        balanced = approx_equal(pm_position, float(hl_position))
        imbalance_amount = abs(float(pm_position) - float(hl_position))
    s2_reentry_eligible = active_s1 and s2_status in {"none", "idle", "exited"} and not active_s2
    return {
        "market": market_key,
        "state": state.get("state"),
        "portfolio_view": portfolio_state_label(s1_status, s2_status, str(state.get("state") or STATE_IDLE)),
        "s1_status": s1_status,
        "s2_status": s2_status,
        "s1_matched_shares": float(s1.get("matched_shares") or 0),
        "s2_matched_shares": float(s2.get("matched_shares") or 0),
        "pm_position": pm_position,
        "pm_position_unavailable": pm_position_unavailable,
        "pm_position_read_warning": pm_position_warning,
        "hl_position_unavailable": hl_position_unavailable,
        "hl_position_read_warning": hl_position_warning,
        "hl_position": hl_position,
        "balanced": balanced,
        "imbalance_amount": imbalance_amount,
        "active_s1": active_s1,
        "active_s2": active_s2,
        "s2_reentry_eligible": s2_reentry_eligible,
        "last_error": state.get("last_error"),
        "halt_reason": state.get("halt_reason"),
        "state_obj": state,
    }


def portfolio_summary(markets: list[str], *, context: str = "summary") -> dict[str, Any]:
    per_market = [portfolio_market_summary(market_key, context=context) for market_key in markets]
    active_s1_count = sum(1 for row in per_market if row["active_s1"])
    active_s2_count = sum(1 for row in per_market if row["active_s2"])
    active_box_shares = sum(
        (row["s1_matched_shares"] if row["active_s1"] else 0)
        + (row["s2_matched_shares"] if row["active_s2"] else 0)
        for row in per_market
    )
    has_halted = any(row["state"] == STATE_HALTED for row in per_market)
    position_read_warnings = sum(
        1
        for row in per_market
        if row.get("pm_position_unavailable") or row.get("hl_position_unavailable")
    )
    hl_unavailable = any(row.get("hl_position_unavailable") for row in per_market)
    return {
        "portfolio_state": STATE_HALTED if has_halted else "PORTFOLIO_ACTIVE" if active_s1_count else STATE_IDLE,
        "max_s1_slots": 4,
        "max_s2_active_slots": 4,
        "active_s1_count": active_s1_count,
        "active_s2_count": active_s2_count,
        "active_box_shares": active_box_shares,
        "per_market": per_market,
        "summary_status": "partial" if position_read_warnings else "ok",
        "position_read_warnings": position_read_warnings,
        "hl_unavailable": hl_unavailable,
        "updated_at": now_iso(),
    }


def print_portfolio_status(summary: dict[str, Any]) -> None:
    print("PM-HL PORTFOLIO STATUS")
    print()
    headers = ["Market", "S1", "S2", "View", "PM Pos", "HL Pos", "Balanced", "Reentry"]
    widths = [10, 8, 8, 19, 9, 9, 10, 8]
    rows: list[list[str]] = []
    for row in summary["per_market"]:
        rows.append(
            [
                portfolio_market_label(str(row["market"])),
                str(row["s1_status"]),
                str(row["s2_status"]),
                str(row["portfolio_view"]),
                fmt_position(row["pm_position"], 1),
                fmt_num(row["hl_position"], 1),
                "unknown" if row["balanced"] is None else ("yes" if row["balanced"] else "no"),
                "yes" if row["s2_reentry_eligible"] else "no",
            ]
        )
    print_ascii_table(headers, rows, widths)
    print()
    print("Summary:")
    print(f"active_s1_count: {summary['active_s1_count']}")
    print(f"active_s2_count: {summary['active_s2_count']}")
    print(f"portfolio_state: {summary['portfolio_state']}")
    if summary.get("summary_status") == "partial":
        print(f"summary_status: partial")
        print(f"position_read_warnings: {summary.get('position_read_warnings', 0)}")
    lock_eval = evaluate_active_lock()
    print(f"active_lock_exists: {str(lock_eval['active_lock_exists']).lower()}")
    if lock_eval.get("active_lock_market") is not None:
        print(f"active_lock_market: {lock_eval.get('active_lock_market')}")
    if lock_eval.get("active_lock_state") is not None:
        print(f"active_lock_state: {lock_eval.get('active_lock_state')}")
    if lock_eval.get("active_lock_stale"):
        print(f"active_lock_stale: true")
    if lock_eval.get("active_lock_error"):
        print(f"active_lock_error: {lock_eval['active_lock_error']}")
    for row in summary["per_market"]:
        if row.get("last_error") or row.get("halt_reason"):
            print(
                f"{portfolio_market_label(str(row['market']))} last_error={row.get('last_error')} "
                f"halt_reason={row.get('halt_reason')}"
            )
        if row.get("hl_position_unavailable"):
            warning = row.get("hl_position_read_warning") or {}
            print(
                f"{portfolio_market_label(str(row['market']))} hl_position_unavailable=true "
                f"reason={warning.get('reason')} status={warning.get('status')}"
            )


def run_portfolio_status() -> int:
    summary = portfolio_summary(sorted(SUPPORTED_MARKETS), context="portfolio_status")
    print_portfolio_status(summary)
    return 0


def entry_candidate_failures(plan: dict[str, Any], required_shares: float) -> list[str]:
    failures: list[str] = []
    threshold_depth = walk_combined_executable_size_with_threshold(plan)
    if threshold_depth + 1e-9 < required_shares:
        failures.append(
            f"combined depth insufficient: required={required_shares:.6f}, executable={threshold_depth:.6f}"
        )
    if plan["market"].get("mapping_status") != "verified":
        failures.append("mapping_status is not verified")
    if plan["expected_profit"] < threshold_value("entry_min_profit_usd"):
        failures.append(
            f"expected_profit {plan['expected_profit']:.6f} < {threshold_value('entry_min_profit_usd'):.6f}"
        )
    if net_edge_bps(plan) < threshold_value("entry_min_net_edge_bps"):
        failures.append(
            f"net_edge_bps {net_edge_bps(plan):.6f} < {threshold_value('entry_min_net_edge_bps'):.6f}"
        )
    if plan["total_notional"] > MAX_TOTAL_NOTIONAL_PER_STRATEGY + 1e-9:
        failures.append(f"total_notional must be <= {MAX_TOTAL_NOTIONAL_PER_STRATEGY}")
    if plan["pm_leg_notional"] < pm_min_notional():
        failures.append("PM leg notional below minimum")
    if plan["hl_notional"] < hl_min_notional():
        failures.append("HL leg notional below minimum")
    return failures


def evaluate_s2_exit_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["active_s2"]:
        return None
    market = get_watchlist_market(row["market"])
    try:
        analysis = analyze_s2_exit(row["state_obj"])
    except Exception as exc:
        if is_hl_api_error(exc):
            log_hl_api_warning(
                context="evaluate_s2_exit_candidate",
                exc=exc,
                market_key=str(row["market"]),
                coin=str(row.get("state_obj", {}).get("s2", {}).get("hl_coin") or ""),
                blocks_execution=False,
            )
        return {"action_type": "S2_EXIT", "market": row["market"], "eligible": False, "failures": [str(exc)]}
    combined_executable_size = min(float(analysis.get("pm_bid_size") or 0), float(analysis.get("hl_bid_size") or 0))
    base = {
        "action_type": "S2_EXIT",
        "market": row["market"],
        "direction": "exit_held_legs",
        "required_shares": analysis.get("exit_shares"),
        "expected_profit": analysis.get("realized_net_pnl_all_in"),
        "realized_profit_if_exit": analysis.get("realized_net_pnl_all_in"),
        "realized_net_pnl_all_in": analysis.get("realized_net_pnl_all_in"),
        "incremental_exit_net_pnl": analysis.get("incremental_exit_net_pnl"),
        "net_edge_bps": analysis.get("net_edge_bps_all_in"),
        "realized_profit_bps": analysis.get("net_edge_bps_all_in"),
        "net_edge_bps_all_in": analysis.get("net_edge_bps_all_in"),
        "exit_vs_hold_usd": analysis.get("exit_vs_hold_usd"),
        "exit_vs_hold_bps": analysis.get("exit_vs_hold_bps"),
        "pm_outcome": f"PM {market.get('pm_outcome')} YES",
        "pm_token": analysis.get("pm_token"),
        "pm_direct_bid_price": analysis.get("pm_bid"),
        "pm_direct_bid_size": analysis.get("pm_bid_size"),
        "hl_outcome": f"HL {market.get('hl_outcome')} NO",
        "hl_coin": analysis.get("hl_coin"),
        "hl_direct_bid_price": analysis.get("hl_bid"),
        "hl_direct_bid_size": analysis.get("hl_bid_size"),
        "combined_executable_size": combined_executable_size,
        "analysis": analysis,
    }
    if not analysis.get("exit_allowed"):
        return {
            **base,
            "eligible": False,
            "failures": analysis.get("exit_failures") or [f"exit status={analysis.get('status')}"],
        }
    return {
        **base,
        "eligible": True,
        "failures": [],
    }


def evaluate_s2_reentry_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["s2_reentry_eligible"]:
        return None
    market = get_watchlist_market(row["market"])
    try:
        plan = calculate_plan(market, MAX_TOTAL_NOTIONAL_PER_STRATEGY, S2_VARIANT, box_shares=BOX_SHARES)
    except HL_API_ERRORS as exc:
        log_hl_api_warning(
            context="evaluate_s2_reentry_candidate",
            exc=exc,
            market_key=str(row["market"]),
            blocks_execution=False,
        )
        return {
            "action_type": "S2_REENTRY",
            "market": row["market"],
            "eligible": False,
            "failures": [f"HL unavailable: reason={hl_error_reason(exc)}"],
        }
    failures = entry_candidate_failures(plan, BOX_SHARES)
    if row.get("pm_position_unavailable"):
        failures.append("PM position unavailable")
    if row["s2_matched_shares"] > 0 and row["s2_status"] == "active":
        failures.append("MAX_ACTIVE_S2_PER_MARKET exceeded")
    if row["s1_matched_shares"] + BOX_SHARES > S1_SHARES + S2_SHARES:
        failures.append("per-market max S1+active S2 shares exceeded")
    pm_asks, hl_asks = selected_ask_books(plan)
    return {
        "action_type": "S2_REENTRY",
        "market": row["market"],
        "eligible": not failures,
        "direction": plan["selected"]["direction"],
        "expected_profit": plan["expected_profit"],
        "net_edge_bps": net_edge_bps(plan),
        "required_shares": BOX_SHARES,
        "pm_outcome": plan["selected"]["pm_leg"],
        "pm_token": plan["pm_token"],
        "pm_direct_ask_price": plan["selected"]["pm_direct_ask"],
        "pm_direct_ask_size": pm_asks[0][1] if pm_asks else None,
        "hl_outcome": plan["selected"]["hl_leg"],
        "hl_coin": plan["hl_coin"],
        "hl_direct_ask_price": plan["selected"]["hl_direct_ask"],
        "hl_direct_ask_size": hl_asks[0][1] if hl_asks else None,
        "combined_executable_size": direct_combined_executable_size(plan),
        "cycle_action": "current_cycle_id + 1",
        "plan": {
            "direction": plan["selected"]["direction"],
            "pm_direct_ask": plan["selected"]["pm_direct_ask"],
            "hl_direct_ask": plan["selected"]["hl_direct_ask"],
            "entry_cost": plan["entry_cost"],
        },
        "failures": failures,
    }


def evaluate_full_entry_candidate(row: dict[str, Any], active_s1_count: int) -> dict[str, Any] | None:
    if row["s1_status"] != "none" or row["s2_status"] != "none" or active_s1_count >= 4:
        return None
    market = get_watchlist_market(row["market"])
    try:
        plans = build_entry_plans(market)
    except HL_API_ERRORS as exc:
        log_hl_api_warning(
            context="evaluate_full_entry_candidate",
            exc=exc,
            market_key=str(row["market"]),
            blocks_execution=False,
        )
        return {
            "action_type": "FULL_ENTRY",
            "market": row["market"],
            "eligible": False,
            "failures": [f"HL unavailable: reason={hl_error_reason(exc)}"],
        }
    failures = entry_candidate_failures(plans[0], COMBINED_REQUIRED_SHARES)
    if row.get("pm_position_unavailable"):
        failures.append("PM position unavailable")
    if active_s1_count >= MAX_ACTIVE_S1_MARKETS:
        failures.append("MAX_ACTIVE_S1_MARKETS exceeded")
    if row["s1_matched_shares"] > 0:
        failures.append("MAX_S1_PER_MARKET exceeded")
    if row["s2_status"] == "active":
        failures.append("MAX_ACTIVE_S2_PER_MARKET exceeded")
    combined_expected_profit = sum(float(plan["expected_profit"]) for plan in plans)
    pm_asks, hl_asks = selected_ask_books(plans[0])
    return {
        "action_type": "FULL_ENTRY",
        "market": row["market"],
        "eligible": not failures,
        "direction": plans[0]["selected"]["direction"],
        "expected_profit": combined_expected_profit,
        "net_edge_bps": net_edge_bps(plans[0]),
        "required_shares": COMBINED_REQUIRED_SHARES,
        "pm_outcome": plans[0]["selected"]["pm_leg"],
        "pm_token": plans[0]["pm_token"],
        "pm_direct_ask_price": plans[0]["selected"]["pm_direct_ask"],
        "pm_direct_ask_size": pm_asks[0][1] if pm_asks else None,
        "hl_outcome": plans[0]["selected"]["hl_leg"],
        "hl_coin": plans[0]["hl_coin"],
        "hl_direct_ask_price": plans[0]["selected"]["hl_direct_ask"],
        "hl_direct_ask_size": hl_asks[0][1] if hl_asks else None,
        "combined_executable_size": direct_combined_executable_size(plans[0]),
        "plan": {
            "direction": plans[0]["selected"]["direction"],
            "pm_direct_ask": plans[0]["selected"]["pm_direct_ask"],
            "hl_direct_ask": plans[0]["selected"]["hl_direct_ask"],
            "entry_cost": plans[0]["entry_cost"],
        },
        "failures": failures,
    }


def choose_portfolio_candidate(summary: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]]]:
    rows = summary["per_market"]
    exit_candidates = [candidate for row in rows if (candidate := evaluate_s2_exit_candidate(row))]
    eligible_exits = [candidate for candidate in exit_candidates if candidate.get("eligible")]
    if eligible_exits:
        selected = max(eligible_exits, key=lambda item: float(item.get("realized_net_pnl_all_in") or 0))
        selected["selected_reason"] = "highest all-in realized net among eligible S2 exit candidates"
        return selected, {"s2_exit_candidates": exit_candidates, "s2_reentry_candidates": [], "full_entry_candidates": []}
    reentry_candidates = [candidate for row in rows if (candidate := evaluate_s2_reentry_candidate(row))]
    full_entry_candidates = [
        candidate for row in rows if (candidate := evaluate_full_entry_candidate(row, summary["active_s1_count"]))
    ]
    for candidate in [*reentry_candidates, *full_entry_candidates]:
        projected_shares = float(summary.get("active_box_shares") or 0) + float(candidate.get("required_shares") or 0)
        if projected_shares > MAX_TOTAL_BOX_SHARES:
            candidate.setdefault("failures", []).append("MAX_TOTAL_BOX_SHARES exceeded")
            candidate["eligible"] = False
    eligible_entries = [
        candidate for candidate in [*reentry_candidates, *full_entry_candidates] if candidate.get("eligible")
    ]
    if eligible_entries:
        selected = max(eligible_entries, key=lambda item: float(item.get("expected_profit") or 0))
        selected["selected_reason"] = (
            "highest expected_profit among eligible entry candidates; no active S2 exit candidates"
        )
        return selected, {
            "s2_exit_candidates": exit_candidates,
            "s2_reentry_candidates": reentry_candidates,
            "full_entry_candidates": full_entry_candidates,
        }
    return None, {
        "s2_exit_candidates": exit_candidates,
        "s2_reentry_candidates": reentry_candidates,
        "full_entry_candidates": full_entry_candidates,
    }


def write_portfolio_state(summary: dict[str, Any], selected_candidate: dict[str, Any] | None) -> None:
    ensure_log_dir()
    payload = {
        "portfolio_state": summary["portfolio_state"],
        "max_s1_slots": summary["max_s1_slots"],
        "max_s2_active_slots": summary["max_s2_active_slots"],
        "active_s1_count": summary["active_s1_count"],
        "active_s2_count": summary["active_s2_count"],
        "active_box_shares": summary["active_box_shares"],
        "per_market": [
            {key: value for key, value in row.items() if key != "state_obj"}
            for row in summary["per_market"]
        ],
        "selected_candidate": selected_candidate,
        "updated_at": now_iso(),
    }
    PORTFOLIO_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def candidate_metric(candidate: dict[str, Any]) -> float:
    if candidate.get("action_type") == "S2_EXIT":
        return float(candidate.get("realized_net_pnl_all_in") or candidate.get("realized_profit_if_exit") or 0)
    return float(candidate.get("expected_profit") or 0)


def all_portfolio_candidates(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        *candidates.get("s2_exit_candidates", []),
        *candidates.get("s2_reentry_candidates", []),
        *candidates.get("full_entry_candidates", []),
    ]


def snapshot_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candidate_spread_snapshot(
    candidate: dict[str, Any],
    *,
    loop_index: int | None,
    run_context: str,
) -> dict[str, Any]:
    pm_yes_bid = snapshot_float(candidate.get("pm_direct_bid_price"))
    pm_yes_ask = snapshot_float(candidate.get("pm_direct_ask_price"))
    hl_no_bid = snapshot_float(candidate.get("hl_direct_bid_price"))
    hl_no_ask = snapshot_float(candidate.get("hl_direct_ask_price"))
    entry_spread_raw = (
        pm_yes_ask + hl_no_ask - 1.0
        if pm_yes_ask is not None and hl_no_ask is not None
        else None
    )
    exit_spread_raw = (
        pm_yes_bid + hl_no_bid - 1.0
        if pm_yes_bid is not None and hl_no_bid is not None
        else None
    )
    action_type = str(candidate.get("action_type") or "unknown")
    failures = candidate.get("failures") or []
    return {
        "timestamp": now_iso(),
        "market": candidate.get("market"),
        "loop_index": loop_index,
        "run_context": run_context,
        "strategy_check_type": action_type,
        "pm_yes_bid": pm_yes_bid,
        "pm_yes_ask": pm_yes_ask,
        "hl_no_bid": hl_no_bid,
        "hl_no_ask": hl_no_ask,
        "entry_spread_raw": entry_spread_raw,
        "exit_spread_raw": exit_spread_raw,
        "entry_net_edge_bps": snapshot_float(candidate.get("net_edge_bps")) if action_type in {"S2_REENTRY", "FULL_ENTRY"} else None,
        "exit_net_edge_bps": snapshot_float(candidate.get("net_edge_bps_all_in") or candidate.get("realized_profit_bps")) if action_type == "S2_EXIT" else None,
        "available_size": snapshot_float(candidate.get("combined_executable_size")),
        "pm_available_size": snapshot_float(candidate.get("pm_direct_bid_size") or candidate.get("pm_direct_ask_size")),
        "hl_available_size": snapshot_float(candidate.get("hl_direct_bid_size") or candidate.get("hl_direct_ask_size")),
        "candidate_eligible": bool(candidate.get("eligible")),
        "reason": candidate.get("selected_reason"),
        "skip_reason": "; ".join(str(item) for item in failures) if failures else None,
        "threshold_profile": CURRENT_THRESHOLD_PROFILE,
        "entry_min_net_edge_bps": threshold_value("entry_min_net_edge_bps"),
        "exit_min_profit_bps": threshold_value("exit_min_profit_bps"),
        "expected_profit": snapshot_float(candidate.get("expected_profit")),
        "realized_net_pnl_all_in": snapshot_float(candidate.get("realized_net_pnl_all_in")),
        "exit_vs_hold_usd": snapshot_float(candidate.get("exit_vs_hold_usd")),
    }


def append_pm_hl_spread_snapshot(snapshot: dict[str, Any]) -> None:
    try:
        ensure_log_dir()
        with orderbook_snapshot_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True, default=str) + "\n")
    except Exception as exc:
        print(f"ORDERBOOK_SNAPSHOT_WARNING: {str(exc)[:160]}")


def append_pm_hl_spread_snapshots(
    candidates: dict[str, list[dict[str, Any]]],
    *,
    loop_index: int | None = None,
    run_context: str = "portfolio_loop",
) -> None:
    try:
        for candidate in all_portfolio_candidates(candidates):
            append_pm_hl_spread_snapshot(
                candidate_spread_snapshot(candidate, loop_index=loop_index, run_context=run_context)
            )
    except Exception as exc:
        print(f"ORDERBOOK_SNAPSHOT_WARNING: {str(exc)[:160]}")


def annotate_candidates(candidates: dict[str, list[dict[str, Any]]], selected_candidate: dict[str, Any] | None) -> None:
    grouped: dict[str, int] = {}
    for action_type in ("S2_EXIT", "S2_REENTRY", "FULL_ENTRY"):
        eligible = [
            candidate for candidate in all_portfolio_candidates(candidates)
            if candidate.get("action_type") == action_type and candidate.get("eligible")
        ]
        eligible_sorted = sorted(eligible, key=candidate_metric, reverse=True)
        for rank, candidate in enumerate(eligible_sorted, start=1):
            grouped[f"{candidate['action_type']}:{candidate['market']}"] = rank
    selected_key = (
        f"{selected_candidate.get('action_type')}:{selected_candidate.get('market')}"
        if selected_candidate
        else None
    )
    for candidate in all_portfolio_candidates(candidates):
        key = f"{candidate.get('action_type')}:{candidate.get('market')}"
        candidate["selection_rank"] = grouped.get(key)
        if selected_key and key == selected_key:
            candidate["selected_reason"] = selected_candidate.get("selected_reason")
        elif not candidate.get("eligible"):
            candidate["selected_reason"] = "not selected: ineligible"
        elif selected_candidate and selected_candidate.get("action_type") == "S2_EXIT" and candidate.get("action_type") != "S2_EXIT":
            candidate["selected_reason"] = "not selected: eligible S2 exit candidates have priority"
        elif selected_candidate:
            candidate["selected_reason"] = (
                f"not selected: lower {'realized_net_pnl_all_in' if candidate.get('action_type') == 'S2_EXIT' else 'expected_profit'} "
                f"than selected {selected_candidate.get('action_type')} {selected_candidate.get('market')}"
            )
        else:
            candidate["selected_reason"] = "not selected: no eligible candidate"


def print_candidate_table(candidates: dict[str, list[dict[str, Any]]]) -> None:
    print("CANDIDATE_TABLE")
    for candidate in all_portfolio_candidates(candidates):
        print(
            "candidate "
            f"action_type={candidate.get('action_type')} "
            f"market={candidate.get('market')} "
            f"eligible={str(bool(candidate.get('eligible'))).lower()} "
            f"direction={candidate.get('direction')} "
            f"required_shares={candidate.get('required_shares')} "
            f"expected_profit={candidate.get('expected_profit')} "
            f"realized_profit_if_exit={candidate.get('realized_profit_if_exit')} "
            f"realized_net_pnl_all_in={candidate.get('realized_net_pnl_all_in')} "
            f"incremental_exit_net_pnl={candidate.get('incremental_exit_net_pnl')} "
            f"net_edge_bps={candidate.get('net_edge_bps')} "
            f"net_edge_bps_all_in={candidate.get('net_edge_bps_all_in')} "
            f"realized_profit_bps={candidate.get('realized_profit_bps')} "
            f"exit_vs_hold_usd={candidate.get('exit_vs_hold_usd')} "
            f"pm_outcome={candidate.get('pm_outcome')} "
            f"pm_token={candidate.get('pm_token')} "
            f"pm_ask={candidate.get('pm_direct_ask_price')} "
            f"pm_ask_size={candidate.get('pm_direct_ask_size')} "
            f"pm_bid={candidate.get('pm_direct_bid_price')} "
            f"pm_bid_size={candidate.get('pm_direct_bid_size')} "
            f"hl_outcome={candidate.get('hl_outcome')} "
            f"hl_coin={candidate.get('hl_coin')} "
            f"hl_ask={candidate.get('hl_direct_ask_price')} "
            f"hl_ask_size={candidate.get('hl_direct_ask_size')} "
            f"hl_bid={candidate.get('hl_direct_bid_price')} "
            f"hl_bid_size={candidate.get('hl_direct_bid_size')} "
            f"combined_executable_size={candidate.get('combined_executable_size')} "
            f"failures={candidate.get('failures')} "
            f"selection_rank={candidate.get('selection_rank')} "
            f"selected_reason={candidate.get('selected_reason')}"
        )


def parse_allowed_actions(raw: str | None) -> set[str]:
    if not raw:
        return set(ALLOWED_ACTIONS)
    actions = {item.strip() for item in raw.split(",") if item.strip()}
    invalid = actions - ALLOWED_ACTIONS
    if invalid:
        raise SystemExit(f"Invalid allowed action(s): {', '.join(sorted(invalid))}")
    return actions


def print_selected_candidate(selected_candidate: dict[str, Any] | None, candidates: dict[str, list[dict[str, Any]]]) -> None:
    print("SELECTED_CANDIDATE")
    if not selected_candidate:
        print("action_type: None")
        print("market: None")
        print("reason: no eligible candidate")
        return
    print(f"action_type: {selected_candidate.get('action_type')}")
    print(f"market: {selected_candidate.get('market')}")
    print(f"reason: {selected_candidate.get('selected_reason')}")
    print(f"expected_profit: {selected_candidate.get('expected_profit')}")
    print(f"realized_profit_if_exit: {selected_candidate.get('realized_profit_if_exit')}")
    print(f"realized_net_pnl_all_in: {selected_candidate.get('realized_net_pnl_all_in')}")
    print(f"incremental_exit_net_pnl: {selected_candidate.get('incremental_exit_net_pnl')}")
    print(f"net_edge_bps: {selected_candidate.get('net_edge_bps')}")
    print(f"net_edge_bps_all_in: {selected_candidate.get('net_edge_bps_all_in')}")
    print(f"realized_profit_bps: {selected_candidate.get('realized_profit_bps')}")
    print(f"exit_vs_hold_usd: {selected_candidate.get('exit_vs_hold_usd')}")
    print(f"required_shares: {selected_candidate.get('required_shares')}")
    print("why_other_candidates_were_not_selected:")
    for candidate in all_portfolio_candidates(candidates):
        if candidate is selected_candidate:
            continue
        print(f"- {candidate.get('action_type')} {candidate.get('market')}: {candidate.get('selected_reason')}")


def print_s2_exit_candidate_scan_log(candidate: dict[str, Any]) -> None:
    if candidate.get("action_type") != "S2_EXIT":
        return
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    reason = candidate.get("selected_reason")
    failures = candidate.get("failures") or []
    skip_reason = "; ".join(str(item) for item in failures) if failures else None
    print(
        "S2_EXIT_SCAN "
        f"market={candidate.get('market')} "
        f"threshold_profile={analysis.get('threshold_profile') or CURRENT_THRESHOLD_PROFILE} "
        f"disable_exit_vs_hold_check={str(bool(analysis.get('disable_exit_vs_hold_check'))).lower()} "
        f"exit_vs_hold_check={analysis.get('exit_vs_hold_check') or exit_vs_hold_check_label()} "
        f"scan_pm_bid={candidate.get('pm_direct_bid_price')} "
        f"scan_hl_bid={candidate.get('hl_direct_bid_price')} "
        f"scan_exit_net_edge_bps={candidate.get('net_edge_bps_all_in') or candidate.get('realized_profit_bps')} "
        f"scan_realized_net_pnl_all_in={candidate.get('realized_net_pnl_all_in')} "
        f"scan_exit_vs_hold_usd={candidate.get('exit_vs_hold_usd')} "
        f"scan_available_size={candidate.get('combined_executable_size')} "
        f"scan_candidate_eligible={str(bool(candidate.get('eligible'))).lower()} "
        f"scan_skip_reason={skip_reason} "
        f"reason={reason}"
    )


def print_s2_exit_scan_logs(candidates: dict[str, list[dict[str, Any]]]) -> None:
    for candidate in candidates.get("s2_exit_candidates", []):
        print_s2_exit_candidate_scan_log(candidate)


def candidate_expected_pnl(candidate: dict[str, Any]) -> float | None:
    if candidate.get("action_type") == "S2_EXIT":
        value = candidate.get("realized_net_pnl_all_in") or candidate.get("realized_profit_if_exit")
    else:
        value = candidate.get("expected_profit")
    return float(value) if value is not None else None


def print_selected_action_summary(selected_candidate: dict[str, Any] | None) -> None:
    print("SELECTED ACTION")
    print()
    if not selected_candidate:
        print("Action:        none")
        print("Market:        none")
        print("Reason:        no eligible candidate")
        print()
        return
    expected_pnl = candidate_expected_pnl(selected_candidate)
    print(f"Action:        {selected_candidate.get('action_type')}")
    print(f"Market:        {selected_candidate.get('market')}")
    print(f"Direction:     {selected_candidate.get('direction') or 'n/a'}")
    print(f"PM outcome:    {selected_candidate.get('pm_outcome') or 'n/a'}")
    print(f"HL outcome:    {selected_candidate.get('hl_outcome') or 'n/a'}")
    print(f"Shares:        {fmt_num(selected_candidate.get('required_shares'), 1)}")
    print(f"Expected PnL:  {fmt_num(expected_pnl)}")
    print(f"Net edge bps:  {fmt_num(selected_candidate.get('net_edge_bps') or selected_candidate.get('realized_profit_bps'))}")
    print()


def print_action_result_summary(
    selected_candidate: dict[str, Any],
    state_after: str | None,
    execution_status: dict[str, Any],
) -> None:
    print("ACTION RESULT")
    print()
    print(f"Orders placed: {'yes' if execution_status.get('pm_order_submitted') or execution_status.get('hl_order_submitted') else 'no'}")
    print(f"State after:   {state_after or 'n/a'}")
    print(f"Auth warnings: {int(execution_status.get('auth_warnings') or 0)}")
    print(f"Auth blocked:  {'yes' if execution_status.get('auth_blocks_execution') else 'no'}")
    print(f"Confirmed:     {'yes' if execution_status.get('trade_confirmed') else 'no'}")
    if execution_status.get("confirmation_status"):
        print(f"Confirmation status: {execution_status.get('confirmation_status')}")
        print(f"Requires manual review: {'yes' if execution_status.get('requires_manual_review') else 'no'}")
    print(f"Market:        {selected_candidate.get('market')}")
    print(f"Action:        {selected_candidate.get('action_type')}")
    print()


def portfolio_live_preflight(markets: list[str]) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    lock_eval = evaluate_active_lock()
    if stop_file_exists():
        failures.append("STOP file exists")
    for market_key in markets:
        failures.extend(live_gate_failures(argparse.Namespace(live=True), market_key))
    try:
        require_live_preflight(markets)
        lock_eval = evaluate_active_lock()
    except Exception as exc:
        failures.append(str(exc))
    if hl.missing_env(("HL_ACCOUNT", "HL_AGENT_KEY")):
        failures.append("Missing HL_ACCOUNT or HL_AGENT_KEY")
    try:
        balances = read_live_balances_for_preflight()
        if balances.get("errors"):
            failures.extend(str(error) for error in balances["errors"])
        if balances.get("hl_usdc") is None:
            failures.append("HL USDC balance unavailable")
    except Exception as exc:
        failures.append(f"balance preflight failed: {exc}")
    return not failures, failures, lock_eval


def failures_include_hl_unhealthy(failures: list[str]) -> bool:
    markers = ("hl spot unavailable", "hl orderbook unavailable", "hl summary unavailable", "429", "timeout", "rate_limit")
    return any(any(marker in failure.lower() for marker in markers) for failure in failures)


def print_and_log_hl_unhealthy_skip(
    *,
    context: str,
    failures: list[str],
    candidate: dict[str, Any] | None = None,
) -> None:
    active, remaining = hl_backoff_active()
    payload = {
        "event": "SKIP_ACTION_HL_UNHEALTHY",
        "context": context,
        "candidate": candidate,
        "failures": failures,
        "backoff_remaining_seconds": round(remaining, 3) if active else 0.0,
        "orders_placed": "no",
    }
    append_event(payload)
    print("SKIP_ACTION_HL_UNHEALTHY")
    print(f"context: {context}")
    print(f"reason: {'; '.join(failures) if failures else 'HL unavailable'}")
    if active:
        print(f"backoff_remaining_seconds: {remaining:.1f}")
    print("orders_placed: no")


def sleep_for_hl_backoff(default_seconds: float) -> None:
    active, remaining = hl_backoff_active()
    time.sleep(max(remaining if active else 0.0, default_seconds))


def run_live_preflight_only(markets: list[str]) -> int:
    summary = portfolio_summary(markets)
    ok, failures, lock_eval = portfolio_live_preflight(markets)
    print("PORTFOLIO LIVE PREFLIGHT ONLY")
    print(f"portfolio_state: {summary['portfolio_state']}")
    print(f"active_s1_count: {summary['active_s1_count']}")
    print(f"active_s2_count: {summary['active_s2_count']}")
    print_active_lock_status(lock_eval)
    auth_status = pm_auth_status()
    print(f"pm_auth_warning: {str(bool(auth_status['pm_auth_warning'])).lower()}")
    print(f"pm_auth_blocks_execution: {str(bool(auth_status['pm_auth_blocks_execution'])).lower()}")
    print(f"preflight_status: {'PASS' if ok else 'FAIL'}")
    print(f"failures: {failures}")
    print("orders_placed: no")
    return 0 if ok else 1


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def in_date_range(path: Path, from_date: str | None, to_date: str | None) -> bool:
    name = path.name
    digits = "".join(ch for ch in name if ch.isdigit())
    if len(digits) < 8:
        return True
    stamp = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if from_date and stamp < from_date:
        return False
    if to_date and stamp > to_date:
        return False
    return True


def zero_pnl_bucket() -> dict[str, float]:
    return {
        "realized_gross_pnl": 0.0,
        "realized_net_pnl": 0.0,
        "realized_net_pnl_all_in": 0.0,
        "open_locked_gross_pnl": 0.0,
        "open_locked_net_pnl": 0.0,
        "total_expected_gross_pnl": 0.0,
        "total_expected_net_pnl": 0.0,
        "pm_fee": 0.0,
        "hl_fee": 0.0,
        "entry_fee": 0.0,
        "exit_fee": 0.0,
        "total_fee": 0.0,
        "total_lifecycle_fee": 0.0,
        "exit_vs_hold_usd": 0.0,
        "capital_deployed": 0.0,
        "portfolio_action_count": 0,
        "strategy_cycle_count": 0,
        "venue_order_count": 0,
    }


def add_bucket(target: dict[str, float], source: dict[str, float]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0.0) + float(value or 0)


def latest_positive_s2_exit_analysis(market_key: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for path in sorted(LOG_DIR.glob("auto_events_*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            analysis = payload.get("analysis") if payload.get("event") == "s2_exit_check" else None
            if not isinstance(analysis, dict) or analysis.get("market") != market_key:
                continue
            if analysis.get("exit_allowed") or analysis.get("realized_profit_if_exit", 0) is not None:
                best = analysis
    return best


def s2_exit_analysis_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("analysis", "exit_analysis"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    if payload.get("event_type") == "S2_EXIT_RECONCILED_FROM_POSITIONS":
        return payload
    return None


def latest_s2_exit_analysis_for_state(
    market_key: str,
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    exit_log = state.get("s2", {}).get("exit_log")
    if exit_log:
        payload = read_json_file(Path(str(exit_log)))
        analysis = s2_exit_analysis_from_payload(payload)
        if analysis:
            return analysis, payload
    return latest_positive_s2_exit_analysis(market_key), None


def iter_event_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(LOG_DIR.glob("auto_events_*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.append(payload)
        except Exception:
            continue
    return records


def event_market_key(record: dict[str, Any]) -> str | None:
    for key in ("market", "selected_market"):
        value = record.get(key)
        if value:
            return str(value)
    candidate = record.get("candidate")
    if isinstance(candidate, dict) and candidate.get("market"):
        return str(candidate["market"])
    plan = record.get("plan")
    if isinstance(plan, dict):
        market = plan.get("market")
        if isinstance(market, dict) and market.get("market"):
            return str(market["market"])
    return None


def extract_event_entry_quotes(record: dict[str, Any], market_key: str) -> dict[str, Any] | None:
    if record.get("event") == "live_entry_pre_order_safety" and record.get("selected_market") == market_key:
        pm_ask = record.get("pm_direct_ask_price")
        hl_ask = record.get("hl_direct_ask_price")
        if pm_ask is None or hl_ask is None:
            return None
        return {
            "pm_ask": float(pm_ask),
            "hl_ask": float(hl_ask),
            "entry_cost": float(record.get("entry_cost") or float(pm_ask) + float(hl_ask)),
            "cost_basis_source": "live_entry_pre_order_safety",
            "cost_basis_quality": "estimated_from_pretrade_quote",
            "event_ts": record.get("ts"),
        }
    if record.get("event") == "portfolio_live_action_started" and record.get("market") == market_key:
        plan = record.get("plan") or {}
        selected = plan.get("selected") or {}
        pm_ask = selected.get("pm_direct_ask") or record.get("pm_direct_ask_price")
        hl_ask = selected.get("hl_direct_ask") or record.get("hl_direct_ask_price")
        if pm_ask is None or hl_ask is None:
            return None
        return {
            "pm_ask": float(pm_ask),
            "hl_ask": float(hl_ask),
            "entry_cost": float(plan.get("entry_cost") or float(pm_ask) + float(hl_ask)),
            "cost_basis_source": "portfolio_live_action_started",
            "cost_basis_quality": "estimated_from_pretrade_quote",
            "event_ts": record.get("ts"),
        }
    candidate = record.get("candidate")
    if isinstance(candidate, dict) and candidate.get("market") == market_key:
        plan = candidate.get("plan") or {}
        pm_ask = candidate.get("pm_direct_ask_price") or plan.get("pm_direct_ask")
        hl_ask = candidate.get("hl_direct_ask_price") or plan.get("hl_direct_ask")
        if pm_ask is None or hl_ask is None:
            return None
        return {
            "pm_ask": float(pm_ask),
            "hl_ask": float(hl_ask),
            "entry_cost": float(plan.get("entry_cost") or float(pm_ask) + float(hl_ask)),
            "cost_basis_source": "recovered_from_failed_full_entry_candidate",
            "cost_basis_quality": "estimated_from_pretrade_quote",
            "event_ts": record.get("ts"),
        }
    if record.get("event") == "entry_check" and record.get("market") == market_key:
        if float(record.get("expected_profit") or 0) <= 0:
            return None
        if record.get("status") not in {None, "entry_ready"} and record.get("dry_run") is not False:
            return None
        pm_ask = record.get("pm_direct_ask")
        hl_ask = record.get("hl_direct_ask")
        if pm_ask is None or hl_ask is None:
            return None
        return {
            "pm_ask": float(pm_ask),
            "hl_ask": float(hl_ask),
            "entry_cost": float(record.get("entry_cost") or float(pm_ask) + float(hl_ask)),
            "cost_basis_source": "entry_check",
            "cost_basis_quality": "estimated_from_pretrade_quote",
            "event_ts": record.get("ts"),
        }
    if record.get("event") in {"trade_confirmation", "trade_confirmation_failed"} and record.get("market") == market_key:
        confirmation = record.get("confirmation") or {}
        pm = confirmation.get("pm") or {}
        hl = confirmation.get("hl") or {}
        pm_ask = pm.get("selected_ask_price") or pm.get("order_fill_price")
        hl_ask = hl.get("selected_ask_price") or hl.get("order_fill_price")
        if pm_ask is None or hl_ask is None:
            orders = confirmation.get("orders") or []
            for order in orders:
                response = order.get("response") or {}
                if order.get("venue") == "HL":
                    try:
                        fill = response["response"]["data"]["statuses"][0]["filled"]
                        hl_ask = hl_ask or fill.get("avgPx")
                    except Exception:
                        pass
        if pm_ask is None or hl_ask is None:
            return None
        return {
            "pm_ask": float(pm_ask),
            "hl_ask": float(hl_ask),
            "entry_cost": float(pm_ask) + float(hl_ask),
            "cost_basis_source": "trade_confirmation",
            "cost_basis_quality": "estimated_from_pretrade_quote",
            "event_ts": record.get("ts"),
        }
    return None


def latest_halt_timestamp(market_key: str) -> str | None:
    for record in reversed(iter_event_records()):
        if record.get("event") == "halted" and record.get("market") == market_key:
            return str(record.get("ts") or "")
    state = read_state_no_create(market_key)
    state_before = state.get("state_before") if isinstance(state.get("state_before"), dict) else {}
    return str(state.get("updated_at") or state_before.get("updated_at") or "") or None


def recover_pm_buy_fill_price(pm_token: str, matched_shares: float) -> float | None:
    pm.load_env()
    funder = pm.get_funder()
    try:
        trades = pm.http_json(f"{pm.DATA_API}/trades?user={funder}&limit=100")
    except Exception:
        return None
    if not isinstance(trades, list):
        return None
    buys = [
        row
        for row in trades
        if str(row.get("asset")) == pm_token and str(row.get("side", "")).upper() == "BUY"
    ]
    if not buys:
        return None
    buys.sort(key=lambda row: int(row.get("timestamp") or 0))
    for row in buys:
        size = float(row.get("size") or 0)
        if approx_equal(size, matched_shares) or abs(size - matched_shares) <= max(FILL_TOLERANCE, matched_shares * 0.05):
            price = row.get("price")
            if price is not None:
                return float(price)
    return None


def recover_hl_buy_fill_price(hl_coin: str, matched_shares: float) -> float | None:
    hl.load_env()
    try:
        fills = hl.info({"type": "userFills", "user": hl.get_account()})
    except Exception:
        return None
    if not isinstance(fills, list):
        return None
    buys = [
        row
        for row in fills
        if str(row.get("coin")) == hl_coin and str(row.get("side", "")).upper() == "B"
    ]
    if not buys:
        return None
    buys.sort(key=lambda row: int(row.get("time") or 0))
    for row in buys:
        size = float(row.get("sz") or 0)
        if approx_equal(size, matched_shares) or abs(size - matched_shares) <= max(FILL_TOLERANCE, matched_shares * 0.05):
            price = row.get("px")
            if price is not None:
                return float(price)
    return None


def recover_venue_fill_cost_basis(market_key: str, matched_shares: float) -> dict[str, Any] | None:
    market = get_watchlist_market(market_key)
    pm_token = str(market["pm_yes"])
    hl_coin = str(market["hl_no_coin"])
    pm_ask = recover_pm_buy_fill_price(pm_token, matched_shares)
    hl_ask = recover_hl_buy_fill_price(hl_coin, matched_shares)
    if pm_ask is None or hl_ask is None:
        return None
    return {
        "pm_ask": pm_ask,
        "hl_ask": hl_ask,
        "entry_cost": pm_ask + hl_ask,
        "cost_basis_source": "venue_fill_recovery",
        "cost_basis_quality": "exact_fill",
        "event_ts": None,
    }


def recover_failed_entry_cost_basis(market_key: str) -> dict[str, Any] | None:
    halt_ts = latest_halt_timestamp(market_key)
    recovered: list[dict[str, Any]] = []
    for record in iter_event_records():
        if event_market_key(record) != market_key:
            continue
        quotes = extract_event_entry_quotes(record, market_key)
        if quotes:
            recovered.append(quotes)
    if not recovered:
        return None
    if halt_ts:
        before_halt = [item for item in recovered if str(item.get("event_ts") or "") <= halt_ts]
        if before_halt:
            return before_halt[-1]
    return recovered[-1]


def s1_plan_from_asks(
    market_key: str,
    pm_ask: float,
    hl_ask: float,
    shares: float = BOX_SHARES,
    *,
    cost_basis_source: str,
    cost_basis_quality: str,
) -> dict[str, Any]:
    market = get_watchlist_market(market_key)
    pm_ask = float(pm_ask)
    hl_ask = float(hl_ask)
    entry_cost = pm_ask + hl_ask
    pm_leg_notional = shares * pm_ask
    hl_leg_notional = shares * hl_ask
    total_notional = pm_leg_notional + hl_leg_notional
    pm_fee_total = shares * 0.03 * pm_ask * (1 - pm_ask)
    hl_fee_total = shares * hl_ask * float(os.environ.get("HL_TAKER_FEE", "0") or 0)
    gross_profit = shares * (1 - pm_ask - hl_ask)
    expected_profit = gross_profit - pm_fee_total - hl_fee_total
    return {
        "strategy_variant": S1_VARIANT,
        "strategy_slot": "s1",
        "market": market,
        "shares": shares,
        "matched_shares": shares,
        "pm_token": str(market["pm_yes"]),
        "hl_coin": str(market["hl_no_coin"]),
        "pm_outcome": f"PM {market.get('pm_outcome')} YES",
        "hl_outcome": f"HL {market.get('hl_outcome')} NO",
        "pm_entry_price": pm_ask,
        "hl_entry_price": hl_ask,
        "entry_cost": entry_cost,
        "pm_leg_notional": pm_leg_notional,
        "hl_leg_notional": hl_leg_notional,
        "total_notional": total_notional,
        "capital_deployed": total_notional,
        "pm_fee": pm_fee_total,
        "hl_fee": hl_fee_total,
        "estimated_total_fees": pm_fee_total + hl_fee_total,
        "gross_profit": gross_profit,
        "expected_profit": expected_profit,
        "selected": {
            "direction": "dir1",
            "pm_direct_ask": pm_ask,
            "hl_direct_ask": hl_ask,
            "pm_leg": f"PM {market.get('pm_outcome')} YES",
            "hl_leg": f"HL {market.get('hl_outcome')} NO",
        },
        "cost_basis_source": cost_basis_source,
        "cost_basis_quality": cost_basis_quality,
    }


def resolve_reconcile_s1_cost_basis(market_key: str, matched_shares: float) -> dict[str, Any]:
    recovered = recover_venue_fill_cost_basis(market_key, matched_shares)
    if not recovered:
        recovered = recover_failed_entry_cost_basis(market_key)
    if recovered:
        plan = s1_plan_from_asks(
            market_key,
            recovered["pm_ask"],
            recovered["hl_ask"],
            matched_shares,
            cost_basis_source=str(recovered["cost_basis_source"]),
            cost_basis_quality=str(recovered["cost_basis_quality"]),
        )
        return {"plan": plan, **recovered}
    live_plan = calculate_plan(
        get_watchlist_market(market_key),
        MAX_TOTAL_NOTIONAL_PER_STRATEGY,
        S1_VARIANT,
        box_shares=matched_shares,
    )
    selected = live_plan["selected"]
    plan = s1_plan_from_asks(
        market_key,
        float(selected["pm_direct_ask"]),
        float(selected["hl_direct_ask"]),
        matched_shares,
        cost_basis_source="estimated_from_current_pretrade_quote",
        cost_basis_quality="estimated_from_current_pretrade_quote",
    )
    return {
        "plan": plan,
        "pm_ask": float(selected["pm_direct_ask"]),
        "hl_ask": float(selected["hl_direct_ask"]),
        "entry_cost": float(plan["entry_cost"]),
        "cost_basis_source": "estimated_from_current_pretrade_quote",
        "cost_basis_quality": "estimated_from_current_pretrade_quote",
        "event_ts": None,
    }


def build_reconcile_s1_log_payload(
    market_key: str,
    summary: dict[str, Any],
    open_orders: dict[str, Any],
    state_before: dict[str, Any],
) -> dict[str, Any]:
    matched_shares = float(summary.get("expected_s1_shares") or BOX_SHARES)
    cost_basis = resolve_reconcile_s1_cost_basis(market_key, matched_shares)
    plan = cost_basis["plan"]
    return {
        "market": market_key,
        "strategy_slot": "s1",
        "status": "confirmed",
        "strategy_variant": S1_VARIANT,
        "matched_shares": matched_shares,
        "pm_token": plan["pm_token"],
        "hl_coin": plan["hl_coin"],
        "pm_outcome": plan["pm_outcome"],
        "hl_outcome": plan["hl_outcome"],
        "pm_entry_price": plan["pm_entry_price"],
        "hl_entry_price": plan["hl_entry_price"],
        "entry_cost": plan["entry_cost"],
        "capital_deployed": plan["capital_deployed"],
        "gross_profit": plan["gross_profit"],
        "expected_profit": plan["expected_profit"],
        "cost_basis_source": plan["cost_basis_source"],
        "cost_basis_quality": plan["cost_basis_quality"],
        "plan": plan,
        "positions": summary,
        "open_orders": open_orders,
        "state_before": state_before,
    }


def enrich_reconcile_log_if_needed(path: Path, market_key: str) -> bool:
    payload = read_json_file(path)
    if not payload:
        return False
    plan = payload.get("plan") or {}
    if (
        float(plan.get("gross_profit") or payload.get("gross_profit") or 0) > 0
        and float(plan.get("expected_profit") or payload.get("expected_profit") or 0) > 0
        and str(plan.get("cost_basis_quality") or payload.get("cost_basis_quality") or "") == "exact_fill"
    ):
        return False
    matched_shares = float(
        payload.get("matched_shares")
        or payload.get("positions", {}).get("expected_s1_shares")
        or BOX_SHARES
    )
    cost_basis = resolve_reconcile_s1_cost_basis(market_key, matched_shares)
    plan = cost_basis["plan"]
    payload.update(
        {
            "market": market_key,
            "strategy_slot": "s1",
            "status": "confirmed",
            "strategy_variant": S1_VARIANT,
            "matched_shares": matched_shares,
            "pm_token": plan["pm_token"],
            "hl_coin": plan["hl_coin"],
            "pm_outcome": plan["pm_outcome"],
            "hl_outcome": plan["hl_outcome"],
            "pm_entry_price": plan["pm_entry_price"],
            "hl_entry_price": plan["hl_entry_price"],
            "entry_cost": plan["entry_cost"],
            "capital_deployed": plan["capital_deployed"],
            "gross_profit": plan["gross_profit"],
            "expected_profit": plan["expected_profit"],
            "cost_basis_source": plan["cost_basis_source"],
            "cost_basis_quality": plan["cost_basis_quality"],
            "plan": plan,
        }
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    append_event(
        {
            "event": "reconcile_pnl_backfilled",
            "market": market_key,
            "entry_log": str(path),
            "cost_basis_source": plan["cost_basis_source"],
            "cost_basis_quality": plan["cost_basis_quality"],
            "capital_deployed": plan["capital_deployed"],
            "expected_profit": plan["expected_profit"],
        }
    )
    return True


def backfill_reconcile_logs_for_active_s1() -> None:
    for market_key in sorted(SUPPORTED_MARKETS):
        state = read_state_no_create(market_key)
        s1 = state.get("s1", {})
        entry_log = str(s1.get("entry_log") or "")
        if s1.get("status") != "active" or "reconcile" not in entry_log.lower():
            continue
        enrich_reconcile_log_if_needed(Path(entry_log), market_key)


def plan_fees_from_plan(plan: dict[str, Any], scale: float = 1.0) -> tuple[float, float, float]:
    pm_fee_val = plan.get("pm_fee")
    hl_fee_val = plan.get("hl_fee")
    if pm_fee_val is not None or hl_fee_val is not None:
        pm_total = float(pm_fee_val or 0) * scale
        hl_total = float(hl_fee_val or 0) * scale
    else:
        gross = float(plan.get("gross_profit") or 0) * scale
        net = float(plan.get("expected_profit") or 0) * scale
        if plan.get("estimated_total_fees") is not None:
            total = float(plan.get("estimated_total_fees") or 0) * scale
        else:
            total = max(gross - net, 0.0)
        pm_total = total
        hl_total = 0.0
    return pm_total, hl_total, pm_total + hl_total


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def s2_entry_fee_fields_from_state(state: dict[str, Any], exit_shares: float) -> dict[str, Any]:
    s2 = state.get("s2", {}) if isinstance(state, dict) else {}
    entry_log = s2.get("entry_log")
    plan: dict[str, Any] = {}
    if entry_log:
        payload = read_json_file(Path(str(entry_log)))
        if isinstance(payload, dict) and isinstance(payload.get("plan"), dict):
            plan = payload["plan"]
    plan_shares = float(plan.get("shares") or s2.get("matched_shares") or exit_shares or BOX_SHARES)
    scale = float(exit_shares or 0) / plan_shares if plan_shares > 0 else 1.0
    entry_pm_fee, entry_hl_fee, total_entry_fee = plan_fees_from_plan(plan, scale) if plan else (0.0, 0.0, 0.0)
    return {
        "entry_pm_fee": entry_pm_fee,
        "entry_hl_fee": entry_hl_fee,
        "total_entry_fee": total_entry_fee,
        "entry_fee_source": "s2_entry_log_plan" if plan else "unavailable",
    }


def s2_exit_lifecycle_pnl_fields(
    *,
    entry_gross_cost: Any,
    exit_shares: float,
    pm_exit_price: Any,
    hl_exit_price: Any,
    entry_pm_fee: Any,
    entry_hl_fee: Any,
) -> dict[str, Any]:
    shares = float(exit_shares or 0)
    entry_cost = maybe_float(entry_gross_cost)
    pm_price = maybe_float(pm_exit_price)
    hl_price = maybe_float(hl_exit_price)
    entry_pm = float(entry_pm_fee or 0)
    entry_hl = float(entry_hl_fee or 0)
    exit_pm = pm_fee(pm_price) * shares if pm_price is not None else 0.0
    exit_hl = hl_taker_fee() * shares if hl_price is not None else 0.0
    total_entry_fee = entry_pm + entry_hl
    total_exit_fee = exit_pm + exit_hl
    total_lifecycle_fee = total_entry_fee + total_exit_fee
    exit_gross_value = (pm_price + hl_price) * shares if pm_price is not None and hl_price is not None else None
    realized_gross = exit_gross_value - entry_cost if exit_gross_value is not None and entry_cost is not None else None
    incremental_exit_net = realized_gross - total_exit_fee if realized_gross is not None else None
    all_in_net = realized_gross - total_lifecycle_fee if realized_gross is not None else None
    net_edge_bps_all_in = all_in_net / entry_cost * 10000 if all_in_net is not None and entry_cost and entry_cost > 0 else None
    hold_value = shares * 1.0
    net_exit_value = exit_gross_value - total_exit_fee if exit_gross_value is not None else None
    exit_vs_hold = net_exit_value - hold_value if net_exit_value is not None else None
    exit_vs_hold_bps = exit_vs_hold / hold_value * 10000 if exit_vs_hold is not None and hold_value > 0 else None
    return {
        "entry_gross_cost": entry_cost,
        "original_entry_cost": entry_cost,
        "exit_gross_value": exit_gross_value,
        "exit_value": (pm_price + hl_price) if pm_price is not None and hl_price is not None else None,
        "pm_exit_price": pm_price,
        "hl_exit_price": hl_price,
        "pm_exit_notional": pm_price * shares if pm_price is not None else None,
        "hl_exit_notional": hl_price * shares if hl_price is not None else None,
        "realized_gross_pnl": realized_gross,
        "entry_pm_fee": entry_pm,
        "entry_hl_fee": entry_hl,
        "exit_pm_fee": exit_pm,
        "exit_hl_fee": exit_hl,
        "pm_exit_fee": exit_pm,
        "hl_exit_fee": exit_hl,
        "total_entry_fee": total_entry_fee,
        "total_exit_fee": total_exit_fee,
        "estimated_exit_fees": total_exit_fee,
        "total_lifecycle_fee": total_lifecycle_fee,
        "incremental_exit_net_pnl": incremental_exit_net,
        "realized_net_pnl_all_in": all_in_net,
        "realized_net_pnl": all_in_net,
        "realized_profit_if_exit": all_in_net,
        "net_edge_bps_all_in": net_edge_bps_all_in,
        "realized_profit_bps": net_edge_bps_all_in,
        "hold_to_maturity_value": hold_value,
        "net_exit_value_after_exit_fee": net_exit_value,
        "exit_vs_hold_usd": exit_vs_hold,
        "exit_vs_hold_bps": exit_vs_hold_bps,
    }


def s2_exit_actual_fill_pnl_fields(
    *,
    entry_gross_cost: Any,
    target_shares: Any,
    pm_filled_qty: Any,
    hl_filled_qty: Any,
    pm_exit_price: Any,
    hl_exit_price: Any,
    entry_pm_fee: Any,
    entry_hl_fee: Any,
) -> dict[str, Any]:
    target = float(target_shares or 0)
    pm_qty = maybe_float(pm_filled_qty)
    hl_qty = maybe_float(hl_filled_qty)
    pm_price = maybe_float(pm_exit_price)
    hl_price = maybe_float(hl_exit_price)
    entry_cost = maybe_float(entry_gross_cost)
    entry_pm = float(entry_pm_fee or 0)
    entry_hl = float(entry_hl_fee or 0)
    if target <= 0 or pm_qty is None or hl_qty is None or pm_price is None or hl_price is None:
        return {}
    exit_gross_value = pm_price * pm_qty + hl_price * hl_qty
    entry_scale = max(pm_qty, hl_qty) / target
    scaled_entry_cost = entry_cost * entry_scale if entry_cost is not None else None
    scaled_entry_pm = entry_pm * entry_scale
    scaled_entry_hl = entry_hl * entry_scale
    exit_pm = pm_fee(pm_price) * pm_qty
    exit_hl = hl_taker_fee() * hl_qty
    total_entry_fee = scaled_entry_pm + scaled_entry_hl
    total_exit_fee = exit_pm + exit_hl
    total_lifecycle_fee = total_entry_fee + total_exit_fee
    realized_gross = exit_gross_value - scaled_entry_cost if scaled_entry_cost is not None else None
    all_in_net = realized_gross - total_lifecycle_fee if realized_gross is not None else None
    net_edge_bps_all_in = (
        all_in_net / scaled_entry_cost * 10000
        if all_in_net is not None and scaled_entry_cost and scaled_entry_cost > 0
        else None
    )
    hold_value = max(pm_qty, hl_qty) * 1.0
    net_exit_value = exit_gross_value - total_exit_fee
    exit_vs_hold = net_exit_value - hold_value
    exit_vs_hold_bps = exit_vs_hold / hold_value * 10000 if hold_value > 0 else None
    return {
        "entry_gross_cost": scaled_entry_cost,
        "original_entry_cost": scaled_entry_cost,
        "exit_gross_value": exit_gross_value,
        "pm_exit_price": pm_price,
        "hl_exit_price": hl_price,
        "pm_exit_notional": pm_price * pm_qty,
        "hl_exit_notional": hl_price * hl_qty,
        "realized_gross_pnl": realized_gross,
        "entry_pm_fee": scaled_entry_pm,
        "entry_hl_fee": scaled_entry_hl,
        "exit_pm_fee": exit_pm,
        "exit_hl_fee": exit_hl,
        "pm_exit_fee": exit_pm,
        "hl_exit_fee": exit_hl,
        "total_entry_fee": total_entry_fee,
        "total_exit_fee": total_exit_fee,
        "estimated_exit_fees": total_exit_fee,
        "total_lifecycle_fee": total_lifecycle_fee,
        "incremental_exit_net_pnl": realized_gross - total_exit_fee if realized_gross is not None else None,
        "realized_net_pnl_all_in": all_in_net,
        "realized_net_pnl": all_in_net,
        "realized_profit_if_exit": all_in_net,
        "net_edge_bps_all_in": net_edge_bps_all_in,
        "realized_profit_bps": net_edge_bps_all_in,
        "hold_to_maturity_value": hold_value,
        "net_exit_value_after_exit_fee": net_exit_value,
        "exit_vs_hold_usd": exit_vs_hold,
        "exit_vs_hold_bps": exit_vs_hold_bps,
    }


def bucket_gross_pnl(bucket: dict[str, float]) -> float:
    return float(bucket.get("realized_gross_pnl") or 0) + float(bucket.get("open_locked_gross_pnl") or 0)


def bucket_net_pnl(bucket: dict[str, float]) -> float:
    return float(bucket.get("realized_net_pnl") or 0) + float(bucket.get("open_locked_net_pnl") or 0)


def bucket_total_fee(bucket: dict[str, float]) -> float:
    if float(bucket.get("total_fee") or 0):
        return float(bucket.get("total_fee") or 0)
    return float(bucket.get("pm_fee") or 0) + float(bucket.get("hl_fee") or 0)


def plan_pnl_bucket(plan: dict[str, Any], shares: float | None = None) -> dict[str, float]:
    plan_shares = float(plan.get("shares") or plan.get("matched_shares") or BOX_SHARES)
    target_shares = float(shares or plan_shares)
    scale = target_shares / plan_shares if plan_shares > 0 else 1.0
    pm_fee_total, hl_fee_total, total_fee = plan_fees_from_plan(plan, scale)
    return {
        "open_locked_gross_pnl": float(plan.get("gross_profit") or 0) * scale,
        "open_locked_net_pnl": float(plan.get("expected_profit") or 0) * scale,
        "total_expected_gross_pnl": float(plan.get("gross_profit") or 0) * scale,
        "total_expected_net_pnl": float(plan.get("expected_profit") or 0) * scale,
        "pm_fee": pm_fee_total,
        "hl_fee": hl_fee_total,
        "entry_fee": total_fee,
        "exit_fee": 0.0,
        "total_fee": total_fee,
        "total_lifecycle_fee": total_fee,
        "capital_deployed": float(plan.get("total_notional") or plan.get("capital_deployed") or 0) * scale,
        "strategy_cycle_count": 1,
        "venue_order_count": 2,
    }


def entry_pnl_from_log(path: Path) -> tuple[str, str, dict[str, float]] | None:
    payload = read_json_file(path)
    if not payload:
        return None
    plan = payload.get("plan", {})
    is_reconcile = "reconcile" in path.name
    market = payload.get("market") or plan.get("market", {}).get("market")
    strategy = payload.get("strategy_variant") or plan.get("strategy_variant")
    if not market or not strategy:
        return None
    if is_reconcile or (payload.get("status") in {"reconciled", "confirmed"} and plan):
        if float(plan.get("gross_profit") or payload.get("gross_profit") or 0) <= 0:
            return None
        matched_shares = float(payload.get("matched_shares") or plan.get("matched_shares") or plan.get("shares") or BOX_SHARES)
        bucket = plan_pnl_bucket(plan, matched_shares)
        bucket["portfolio_action_count"] = 1
        return str(market), str(strategy), bucket
    execution = payload.get("execution", {})
    if payload.get("status") != "confirmed" and not execution_is_confirmed(execution):
        return None
    bucket = plan_pnl_bucket(plan)
    bucket["venue_order_count"] = len(payload.get("execution", {}).get("orders", []) or [])
    return str(market), str(strategy), bucket


def run_pnl_review(from_date: str | None, to_date: str | None) -> int:
    backfill_reconcile_logs_for_active_s1()
    total = zero_pnl_bucket()
    by_country: dict[str, dict[str, float]] = {}
    by_strategy: dict[str, dict[str, float]] = {
        S1_VARIANT: zero_pnl_bucket(),
        S2_VARIANT: zero_pnl_bucket(),
    }
    s2_entry_by_market: dict[str, dict[str, float]] = {}
    s2_exit_details: list[dict[str, Any]] = []

    for path in sorted(LOG_DIR.glob("auto_entry_s*.json")):
        if not in_date_range(path, from_date, to_date):
            continue
        parsed = entry_pnl_from_log(path)
        if not parsed:
            continue
        market, strategy, bucket = parsed
        by_country.setdefault(market, zero_pnl_bucket())
        if strategy == S2_VARIANT:
            s2_entry_by_market[market] = bucket
        else:
            add_bucket(by_country[market], bucket)
            add_bucket(by_strategy[strategy], bucket)
            add_bucket(total, bucket)

    for market, entry_bucket in s2_entry_by_market.items():
        state = read_state_no_create(market)
        by_country.setdefault(market, zero_pnl_bucket())
        if state.get("s2", {}).get("status") == "exited":
            analysis, exit_payload = latest_s2_exit_analysis_for_state(market, state)
            if analysis:
                exit_shares = float(analysis.get("exit_shares") or 0)
                # Determine PM exit price (explicitly prefer gross price fields).
                # Do NOT treat UI/response net proceeds divided by shares as gross price.
                pm_exit_price = None
                # 1) explicit gross field persisted by reconcile
                if analysis.get("pm_gross_fill_price") is not None:
                    pm_exit_price = maybe_float(analysis.get("pm_gross_fill_price"))
                # 2) actual fill price from order_response if source indicates it's a gross clob trade
                elif analysis.get("actual_pm_fill_price") is not None and (
                    analysis.get("price_source") == "clob_trade_gross_price"
                    or analysis.get("actual_fill_source") == "order_response"
                ):
                    pm_exit_price = maybe_float(analysis.get("actual_pm_fill_price"))
                else:
                    # If exit payload contains reported proceeds (likely net), do not derive gross price from it.
                    payload_pm_proceeds = (exit_payload or {}).get("execution", {}).get("pm", {}).get(
                        "order_response_reported_proceeds"
                    )
                    if payload_pm_proceeds is None:
                        pm_exit_price = (
                            maybe_float(analysis.get("pm_exit_price"))
                            or maybe_float(analysis.get("pm_bid"))
                            or maybe_float((exit_payload or {}).get("pm_exit_price"))
                        )
                    else:
                        # preserve net proceeds separately and prefer pm_bid as a conservative gross price
                        analysis["pm_net_proceeds"] = maybe_float(payload_pm_proceeds)
                        analysis["pm_avg_net_price_after_fee"] = (
                            analysis["pm_net_proceeds"] / float(analysis.get("pm_filled_qty") or analysis.get("exit_shares") or 1.0)
                        )
                        pm_exit_price = maybe_float(analysis.get("pm_bid"))
                hl_exit_price = (
                    analysis.get("hl_exit_price")
                    or analysis.get("actual_hl_fill_price")
                    or analysis.get("hl_bid")
                    or (exit_payload or {}).get("hl_exit_price")
                )
                entry_pm_fee = (
                    analysis.get("entry_pm_fee")
                    if analysis.get("entry_pm_fee") is not None
                    else float(entry_bucket.get("pm_fee") or 0)
                )
                entry_hl_fee = (
                    analysis.get("entry_hl_fee")
                    if analysis.get("entry_hl_fee") is not None
                    else float(entry_bucket.get("hl_fee") or 0)
                )
                lifecycle_fields = s2_exit_lifecycle_pnl_fields(
                    entry_gross_cost=(
                        analysis.get("entry_gross_cost")
                        or analysis.get("original_entry_cost")
                        or entry_bucket.get("capital_deployed")
                    ),
                    exit_shares=exit_shares,
                    pm_exit_price=pm_exit_price,
                    hl_exit_price=hl_exit_price,
                    entry_pm_fee=entry_pm_fee,
                    entry_hl_fee=entry_hl_fee,
                )
                gross = float(lifecycle_fields.get("realized_gross_pnl") or 0)
                net = float(lifecycle_fields.get("realized_net_pnl_all_in") or 0)
                exit_pm_fee = float(lifecycle_fields.get("exit_pm_fee") or 0)
                exit_hl_fee = float(lifecycle_fields.get("exit_hl_fee") or 0)
                pm_fee_total = entry_pm_fee + exit_pm_fee
                hl_fee_total = entry_hl_fee + exit_hl_fee
                realized_bucket = {
                    "realized_gross_pnl": gross,
                    "realized_net_pnl": net,
                    "realized_net_pnl_all_in": net,
                    "total_expected_gross_pnl": gross,
                    "total_expected_net_pnl": net,
                    "pm_fee": pm_fee_total,
                    "hl_fee": hl_fee_total,
                    "entry_fee": float(lifecycle_fields.get("total_entry_fee") or 0),
                    "exit_fee": float(lifecycle_fields.get("total_exit_fee") or 0),
                    "total_fee": pm_fee_total + hl_fee_total,
                    "total_lifecycle_fee": float(lifecycle_fields.get("total_lifecycle_fee") or 0),
                    "exit_vs_hold_usd": float(lifecycle_fields.get("exit_vs_hold_usd") or 0),
                    "capital_deployed": float(analysis.get("original_entry_cost") or entry_bucket.get("capital_deployed") or 0),
                    "strategy_cycle_count": 1,
                    "venue_order_count": entry_bucket.get("venue_order_count", 0) + 2,
                }
                s2_exit_details.append(
                    {
                        "market": market,
                        "realized_gross_pnl": gross,
                        "entry_fee": realized_bucket["entry_fee"],
                        "exit_fee": realized_bucket["exit_fee"],
                        "total_lifecycle_fee": realized_bucket["total_lifecycle_fee"],
                        "realized_net_pnl_all_in": net,
                        "exit_vs_hold_usd": realized_bucket["exit_vs_hold_usd"],
                        "pnl_quality": analysis.get("pnl_quality")
                        or (exit_payload or {}).get("pnl_quality")
                        or "estimated",
                    }
                )
            else:
                realized_bucket = {
                    **entry_bucket,
                    "realized_gross_pnl": 0.0,
                    "realized_net_pnl": 0.0,
                    "realized_net_pnl_all_in": 0.0,
                    "open_locked_gross_pnl": 0.0,
                    "open_locked_net_pnl": 0.0,
                }
        else:
            realized_bucket = entry_bucket
        add_bucket(by_country[market], realized_bucket)
        add_bucket(by_strategy[S2_VARIANT], realized_bucket)
        add_bucket(total, realized_bucket)

    for path in sorted(LOG_DIR.glob("auto_entry_s1_*.json")):
        if in_date_range(path, from_date, to_date):
            market = path.name.split("_wc_")[-1].split("_20")[0] if "_wc_" in path.name else "unknown"
            # Full entry portfolio action count is represented by its S1 leg.
            for country in by_country:
                if market.replace("_", "-") in country.lower().replace("-", "_"):
                    by_country[country]["portfolio_action_count"] += 1
                    total["portfolio_action_count"] += 1
                    break
    for market_key in sorted(SUPPORTED_MARKETS):
        state = read_state_no_create(market_key)
        s1 = state.get("s1", {})
        if s1.get("status") != "active":
            continue
        if market_key in by_country:
            continue
        if "reconcile" not in str(s1.get("entry_log") or "").lower():
            continue
        reconcile_bucket = {
            "portfolio_action_count": 1,
            "strategy_cycle_count": 1,
            "venue_order_count": 2,
        }
        by_country.setdefault(market_key, zero_pnl_bucket())
        add_bucket(by_country[market_key], reconcile_bucket)
        add_bucket(by_strategy[S1_VARIANT], reconcile_bucket)
        add_bucket(total, reconcile_bucket)
    for path in sorted(LOG_DIR.glob("auto_exit_s2*.json")):
        if in_date_range(path, from_date, to_date):
            for country in by_country:
                if market_slug(country) in path.name:
                    by_country[country]["portfolio_action_count"] += 1
                    total["portfolio_action_count"] += 1
                    break

    def pct(bucket: dict[str, float], key: str) -> float:
        capital = float(bucket.get("capital_deployed") or 0)
        return float(bucket.get(key) or 0) / capital * 100 if capital > 0 else 0.0

    nav = collect_portfolio_nav_metrics()

    print_kv_block(
        "TOTAL PNL",
        [
            ("Realized gross", fmt_num(total.get("realized_gross_pnl"))),
            ("Realized net", fmt_num(total.get("realized_net_pnl"))),
            ("Open locked gross", fmt_num(total.get("open_locked_gross_pnl"))),
            ("Open locked net", fmt_num(total.get("open_locked_net_pnl"))),
            ("Total expected gross", fmt_num(total.get("total_expected_gross_pnl"))),
            ("Total expected net", fmt_num(total.get("total_expected_net_pnl"))),
            ("PM fee", fmt_num(total.get("pm_fee"))),
            ("HL fee", fmt_num(total.get("hl_fee"))),
            ("Entry fee", fmt_num(total.get("entry_fee"))),
            ("Exit fee", fmt_num(total.get("exit_fee"))),
            ("Total fee", fmt_num(bucket_total_fee(total))),
            ("Lifecycle fee", fmt_num(total.get("total_lifecycle_fee"))),
            ("Exit vs hold", fmt_num(total.get("exit_vs_hold_usd"))),
            ("Gross PnL", fmt_num(bucket_gross_pnl(total))),
            ("Net PnL", fmt_num(bucket_net_pnl(total))),
            ("Capital deployed", fmt_num(total.get("capital_deployed"))),
            ("Return on deployed", fmt_pct(pct(total, "total_expected_net_pnl"))),
        ],
    )

    if nav["nav_status"] == "ok":
        print_kv_block(
            "NAV",
            [
                ("PM NAV", fmt_num(nav.get("pm_nav"))),
                ("HL NAV", fmt_num(nav.get("hl_nav"))),
                ("Total NAV", fmt_num(nav.get("total_nav"))),
                ("NAV change", fmt_num(nav.get("nav_change"))),
                ("Cum return", fmt_pct(nav.get("cum_return_pct"))),
                ("NAV status", str(nav.get("nav_status"))),
            ],
        )
    else:
        print_kv_block(
            "NAV",
            [
                ("PM NAV", fmt_num(nav.get("pm_nav"))),
                ("HL NAV", fmt_num(nav.get("hl_nav"))),
                ("Total NAV", fmt_num(nav.get("total_nav"))),
                ("NAV change", fmt_num(nav.get("nav_change"))),
                ("Cum return", fmt_pct(nav.get("cum_return_pct"))),
                ("NAV status", "unavailable"),
            ],
        )

    print("BY COUNTRY")
    print()
    country_headers = ["Country", "Gross PnL", "PM Fee", "HL Fee", "Entry Fee", "Exit Fee", "Net PnL", "ExitVsHold", "Capital", "Return %"]
    country_widths = [10, 12, 10, 10, 11, 10, 12, 12, 12, 10]
    country_rows = [
        [
            portfolio_market_label(country),
            fmt_num(bucket_gross_pnl(bucket)),
            fmt_num(bucket.get("pm_fee")),
            fmt_num(bucket.get("hl_fee")),
            fmt_num(bucket.get("entry_fee")),
            fmt_num(bucket.get("exit_fee")),
            fmt_num(bucket_net_pnl(bucket)),
            fmt_num(bucket.get("exit_vs_hold_usd")),
            fmt_num(bucket.get("capital_deployed")),
            fmt_pct(pct(bucket, "total_expected_net_pnl")),
        ]
        for country, bucket in sorted(by_country.items())
    ]
    print_ascii_table(country_headers, country_rows, country_widths)
    print()

    print("BY STRATEGY")
    print()
    strategy_headers = ["Strategy", "Gross PnL", "PM Fee", "HL Fee", "Entry Fee", "Exit Fee", "Net PnL", "ExitVsHold", "Capital", "Return %"]
    strategy_widths = [22, 12, 10, 10, 11, 10, 12, 12, 12, 10]
    strategy_rows = [
        [
            strategy,
            fmt_num(bucket_gross_pnl(bucket)),
            fmt_num(bucket.get("pm_fee")),
            fmt_num(bucket.get("hl_fee")),
            fmt_num(bucket.get("entry_fee")),
            fmt_num(bucket.get("exit_fee")),
            fmt_num(bucket_net_pnl(bucket)),
            fmt_num(bucket.get("exit_vs_hold_usd")),
            fmt_num(bucket.get("capital_deployed")),
            fmt_pct(pct(bucket, "total_expected_net_pnl")),
        ]
        for strategy, bucket in by_strategy.items()
    ]
    print_ascii_table(strategy_headers, strategy_rows, strategy_widths)
    print()

    if s2_exit_details:
        print("S2 EXIT REALIZED DETAILS")
        print()
        detail_headers = ["Market", "Gross", "Entry Fee", "Exit Fee", "Lifecycle Fee", "All-in Net", "ExitVsHold", "Quality"]
        detail_widths = [10, 10, 11, 10, 14, 12, 12, 12]
        detail_rows = [
            [
                portfolio_market_label(detail["market"]),
                fmt_num(detail.get("realized_gross_pnl")),
                fmt_num(detail.get("entry_fee")),
                fmt_num(detail.get("exit_fee")),
                fmt_num(detail.get("total_lifecycle_fee")),
                fmt_num(detail.get("realized_net_pnl_all_in")),
                fmt_num(detail.get("exit_vs_hold_usd")),
                str(detail.get("pnl_quality") or "unknown"),
            ]
            for detail in sorted(s2_exit_details, key=lambda item: str(item.get("market")))
        ]
        print_ascii_table(detail_headers, detail_rows, detail_widths)
        print()

    print("TRADE COUNT ANALYSIS")
    print(f"total_portfolio_action_count: {int(total.get('portfolio_action_count', 0))}")
    print(f"total_strategy_cycle_count: {int(total.get('strategy_cycle_count', 0))}")
    print(f"total_venue_order_count: {int(total.get('venue_order_count', 0))}")
    print("by_country:")
    for country, bucket in sorted(by_country.items()):
        print(
            f"  {portfolio_market_label(country)}: portfolio_action_count={int(bucket.get('portfolio_action_count', 0))} "
            f"strategy_cycle_count={int(bucket.get('strategy_cycle_count', 0))} "
            f"venue_order_count={int(bucket.get('venue_order_count', 0))}"
        )
    print("by_strategy:")
    for strategy, bucket in by_strategy.items():
        print(
            f"  {strategy}: strategy_cycle_count={int(bucket.get('strategy_cycle_count', 0))} "
            f"venue_order_count={int(bucket.get('venue_order_count', 0))}"
        )
    return 0


def reset_s2_for_new_cycle(s2: dict[str, Any]) -> None:
    s2["current_cycle_id"] = int(s2.get("current_cycle_id") or 0) + 1
    s2["entry_log"] = None
    s2["exit_log"] = None
    s2["original_entry_cost"] = None
    s2["pm_token"] = None
    s2["hl_coin"] = None
    s2["matched_shares"] = 0.0
    s2["status"] = "none"


def write_s2_cycle_log(market_key: str, payload: dict[str, Any]) -> str:
    return write_json_log(market_key, "auto_s2_cycle", payload)


def execute_portfolio_full_entry(candidate: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    market_key = str(candidate["market"])
    row = next(item for item in summary["per_market"] if item["market"] == market_key)
    if row["s1_status"] != "none" or row["s2_status"] != "none":
        raise HaltedError("FULL_ENTRY requires s1.status=none and s2.status=none")
    if row.get("pm_position_unavailable") or row.get("pm_position") is None:
        raise HaltedError("FULL_ENTRY blocked: PM position unavailable")
    if row["pm_position"] > FILL_TOLERANCE or row["hl_position"] > FILL_TOLERANCE:
        raise HaltedError("FULL_ENTRY requires no existing PM/HL position")
    if summary["active_s1_count"] >= 4:
        raise HaltedError("FULL_ENTRY blocked: active_s1_count >= 4")
    state = read_state_no_create(market_key)
    market = get_watchlist_market(market_key)
    plans = build_entry_plans(market)
    ok, failures = hl_pre_order_health_check(
        market_key=market_key,
        hl_coin=str(plans[0]["hl_coin"]),
        context="full_entry_pre_order_health",
    )
    if not ok:
        print_and_log_hl_unhealthy_skip(
            context="full_entry_pre_order_health",
            failures=failures,
            candidate=candidate,
        )
        raise HaltedError(f"SKIP_ACTION_HL_UNHEALTHY: {'; '.join(failures)}")
    result: dict[str, Any] = {"orders": [], "logs": []}
    append_event(
        {
            "event": "portfolio_live_action_started",
            "market": market_key,
            "action_type": "FULL_ENTRY",
            "plan": plans[0],
            "pm_direct_ask_price": plans[0]["selected"]["pm_direct_ask"],
            "hl_direct_ask_price": plans[0]["selected"]["hl_direct_ask"],
            "entry_cost": plans[0]["entry_cost"],
        }
    )
    try:
        s1_result = execute_entry_legged(plans[0], action_type="FULL_ENTRY", strategy_slot="s1")
        s1_log = write_json_log(market_key, "auto_entry_s1", {"plan": plans[0], "execution": s1_result, "status": "confirmed"})
        update_slot_after_entry(state, "s1", plans[0], s1_log, s1_result)
        result["orders"].append({"slot": "s1", "execution": s1_result})
        result["logs"].append(s1_log)

        s2_result = execute_entry_legged(plans[1], action_type="FULL_ENTRY", strategy_slot="s2")
        s2_log = write_json_log(market_key, "auto_entry_s2", {"plan": plans[1], "execution": s2_result, "status": "confirmed"})
        update_slot_after_entry(state, "s2", plans[1], s2_log, s2_result)
        state["state"] = STATE_ACTIVE
        write_state(state)
        result["orders"].append({"slot": "s2", "execution": s2_result})
        result["logs"].append(s2_log)
    except Exception as exc:
        halt(state, str(exc))
        raise
    return result


def execute_portfolio_s2_reentry(candidate: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    market_key = str(candidate["market"])
    row = next(item for item in summary["per_market"] if item["market"] == market_key)
    if not row["s2_reentry_eligible"]:
        raise HaltedError("S2_REENTRY requires active S1 and idle/exited S2")
    if row.get("pm_position_unavailable") or row.get("pm_position") is None:
        raise HaltedError("S2_REENTRY blocked: PM position unavailable")
    expected_s1 = float(row["state_obj"].get("s1", {}).get("matched_shares") or 0)
    if not approx_equal(row["pm_position"], expected_s1) or not approx_equal(row["hl_position"], expected_s1):
        raise HaltedError("S2_REENTRY requires balanced S1-only PM/HL position")
    state = read_state_no_create(market_key)
    market = get_watchlist_market(market_key)
    plan = calculate_plan(market, MAX_TOTAL_NOTIONAL_PER_STRATEGY, S2_VARIANT, box_shares=BOX_SHARES)
    ok, failures = hl_pre_order_health_check(
        market_key=market_key,
        hl_coin=str(plan["hl_coin"]),
        context="s2_reentry_pre_order_health",
    )
    if not ok:
        print_and_log_hl_unhealthy_skip(
            context="s2_reentry_pre_order_health",
            failures=failures,
            candidate=candidate,
        )
        raise HaltedError(f"SKIP_ACTION_HL_UNHEALTHY: {'; '.join(failures)}")
    reset_s2_for_new_cycle(state["s2"])
    cycle_id = int(state["s2"].get("current_cycle_id") or 0)
    append_event(
        {
            "event": "portfolio_live_action_started",
            "market": market_key,
            "action_type": "S2_REENTRY",
            "plan": plan,
            "pm_direct_ask_price": plan["selected"]["pm_direct_ask"],
            "hl_direct_ask_price": plan["selected"]["hl_direct_ask"],
            "entry_cost": plan["entry_cost"],
        }
    )
    try:
        s2_result = execute_entry_legged(plan, action_type="S2_REENTRY", strategy_slot="s2")
        s2_log = write_json_log(market_key, "auto_entry_s2", {"cycle_id": cycle_id, "plan": plan, "execution": s2_result, "status": "confirmed"})
        update_slot_after_entry(state, "s2", plan, s2_log, s2_result)
        state["state"] = STATE_ACTIVE
        cycle_log = write_s2_cycle_log(market_key, {"cycle_id": cycle_id, "entry_log": s2_log, "status": "active"})
        state["s2"]["cycle_log"] = cycle_log
        write_state(state)
    except Exception as exc:
        halt(state, str(exc))
        raise
    return {"orders": [{"slot": "s2", "execution": s2_result}], "logs": [s2_log]}


def execute_portfolio_s2_exit(candidate: dict[str, Any]) -> dict[str, Any]:
    market_key = str(candidate["market"])
    state = read_state_no_create(market_key)
    if state.get("s2", {}).get("status") != "active":
        raise HaltedError("S2_EXIT requires active S2")
    return maybe_exit_s2(state, argparse.Namespace(live=True))


def execute_portfolio_candidate(candidate: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    action_type = candidate.get("action_type")
    if action_type == "FULL_ENTRY":
        return execute_portfolio_full_entry(candidate, summary)
    if action_type == "S2_REENTRY":
        return execute_portfolio_s2_reentry(candidate, summary)
    if action_type == "S2_EXIT":
        return execute_portfolio_s2_exit(candidate)
    raise HaltedError(f"Unsupported portfolio action type: {action_type}")


def portfolio_execution_status(result: dict[str, Any]) -> dict[str, Any]:
    executions: list[dict[str, Any]] = []
    if result.get("orders") and isinstance(result.get("orders"), list):
        for order in result["orders"]:
            execution = order.get("execution") if isinstance(order, dict) else None
            if isinstance(execution, dict):
                executions.append(execution)
    if result.get("confirmation"):
        executions.append(result)
    confirmations = [execution.get("confirmation", {}) for execution in executions]
    pm_submitted = any(conf.get("pm", {}).get("order_submitted") for conf in confirmations)
    hl_submitted = any(conf.get("hl", {}).get("order_submitted") for conf in confirmations)
    pm_confirmed = bool(confirmations) and all(conf.get("pm", {}).get("confirmed") for conf in confirmations)
    hl_confirmed = bool(confirmations) and all(conf.get("hl", {}).get("confirmed") for conf in confirmations)
    trade_confirmed = bool(confirmations) and all(conf.get("trade_confirmed") for conf in confirmations)
    state_update_allowed = bool(confirmations) and all(conf.get("state_update_allowed") for conf in confirmations)
    auth_warnings = sum(len(conf.get("auth_diagnostics", []) or []) for conf in confirmations)
    requires_manual_review = any(conf.get("requires_manual_review") for conf in confirmations)
    confirmation_statuses = [conf.get("confirmation_status") for conf in confirmations if conf.get("confirmation_status")]
    return {
        "pm_order_submitted": pm_submitted,
        "pm_fill_confirmed": pm_confirmed,
        "hl_order_submitted": hl_submitted,
        "hl_fill_confirmed": hl_confirmed,
        "trade_confirmed": trade_confirmed,
        "state_update_allowed": state_update_allowed,
        "confirmation_source": "position_delta" if trade_confirmed else None,
        "confirmation_status": ",".join(str(status) for status in confirmation_statuses) if confirmation_statuses else None,
        "requires_manual_review": requires_manual_review,
        "auth_warnings": auth_warnings,
        "auth_blocks_execution": any(
            diag.get("blocks_execution")
            for conf in confirmations
            for diag in (conf.get("auth_diagnostics", []) or [])
        ),
    }


def print_portfolio_live_single_action(candidate: dict[str, Any], max_actions: int) -> None:
    print_selected_action_summary(candidate)
    print(f"Max actions:   {max_actions}")
    print("Entry scan:    enabled")
    print()


def print_no_action(reason: str) -> None:
    print("PORTFOLIO NO ACTION")
    print(f"reason: {reason}")
    print("orders_placed: no")


def portfolio_live_guard_status(candidate: dict[str, Any] | None, args: argparse.Namespace) -> dict[str, Any]:
    if not candidate:
        return {
            "ok": False,
            "intent_guard_status": "FAIL",
            "profit_guard_status": "PASS",
            "edge_guard_status": "PASS",
            "failures": ["no selected candidate"],
        }
    failures: list[str] = []
    intent_ok = True
    if args.require_action and candidate.get("action_type") != args.require_action:
        intent_ok = False
        failures.append(f"required action {args.require_action}, got {candidate.get('action_type')}")
    if args.require_market and candidate.get("market") != args.require_market:
        intent_ok = False
        failures.append(f"required market {args.require_market}, got {candidate.get('market')}")

    action_type = candidate.get("action_type")
    is_entry = action_type in {"FULL_ENTRY", "S2_REENTRY"}
    profit_ok = True
    if is_entry and args.min_live_expected_profit is not None:
        profit_ok = float(candidate.get("expected_profit") or 0) >= float(args.min_live_expected_profit)
        if not profit_ok:
            failures.append(
                f"expected_profit {candidate.get('expected_profit')} < min {args.min_live_expected_profit}"
            )
    edge_ok = True
    if is_entry and args.min_live_net_edge_bps is not None:
        edge_ok = float(candidate.get("net_edge_bps") or 0) >= float(args.min_live_net_edge_bps)
        if not edge_ok:
            failures.append(f"net_edge_bps {candidate.get('net_edge_bps')} < min {args.min_live_net_edge_bps}")

    return {
        "ok": intent_ok and profit_ok and edge_ok,
        "intent_guard_status": "PASS" if intent_ok else "FAIL",
        "profit_guard_status": "PASS" if profit_ok else "FAIL",
        "edge_guard_status": "PASS" if edge_ok else "FAIL",
        "failures": failures,
    }


def print_and_log_portfolio_guard_failure(candidate: dict[str, Any] | None, status: dict[str, Any]) -> None:
    event_payload = {"candidate": candidate, "failures": status["failures"]}
    if status["intent_guard_status"] == "FAIL":
        print("PORTFOLIO LIVE INTENT MISMATCH")
        append_event({"event": "portfolio_live_intent_mismatch", **event_payload})
    elif status["profit_guard_status"] == "FAIL":
        print("PORTFOLIO LIVE PROFIT GUARD FAILED")
        append_event({"event": "portfolio_live_profit_guard_failed", **event_payload})
    elif status["edge_guard_status"] == "FAIL":
        print("PORTFOLIO LIVE EDGE GUARD FAILED")
        append_event({"event": "portfolio_live_edge_guard_failed", **event_payload})
    for failure in status["failures"]:
        print(f"  - {failure}")
    print("orders_placed: no")


def run_portfolio_live_preview_only(markets: list[str], args: argparse.Namespace) -> int:
    summary = portfolio_summary(markets)
    selected_candidate, candidates = choose_portfolio_candidate(summary)
    annotate_candidates(candidates, selected_candidate)
    append_pm_hl_spread_snapshots(candidates, run_context="portfolio_live_preview")
    write_portfolio_state(summary, selected_candidate)
    preflight_ok, preflight_failures, _lock_eval = portfolio_live_preflight(markets)
    guard_status = portfolio_live_guard_status(selected_candidate, args)
    would_place = bool(selected_candidate and preflight_ok and guard_status["ok"])
    print("PORTFOLIO LIVE PREVIEW ONLY")
    print_threshold_profile()
    print_candidate_table(candidates)
    print_selected_candidate(selected_candidate, candidates)
    print(f"selected_action_type: {selected_candidate.get('action_type') if selected_candidate else None}")
    print(f"selected_market: {selected_candidate.get('market') if selected_candidate else None}")
    print(f"expected_profit: {selected_candidate.get('expected_profit') if selected_candidate else None}")
    print(f"net_edge_bps: {selected_candidate.get('net_edge_bps') if selected_candidate else None}")
    print(f"required_shares: {selected_candidate.get('required_shares') if selected_candidate else None}")
    print(f"preflight_status: {'PASS' if preflight_ok else 'FAIL'}")
    print(f"preflight_failures: {preflight_failures}")
    print(f"intent_guard_status: {guard_status['intent_guard_status']}")
    print(f"profit_guard_status: {guard_status['profit_guard_status']}")
    print(f"edge_guard_status: {guard_status['edge_guard_status']}")
    print(f"guard_failures: {guard_status['failures']}")
    print(f"would_place_orders: {'yes' if would_place else 'no'}")
    print("orders_placed: no")
    return 0


def run_portfolio_manager(markets: list[str], args: argparse.Namespace) -> int:
    selected_candidate: dict[str, Any] | None = None
    allowed_actions = parse_allowed_actions(args.allowed_actions)
    if args.max_loops is not None:
        max_loops = args.max_loops
    elif args.run_until_stop:
        max_loops = None
    else:
        max_loops = 1 if args.live else 1
    if args.live:
        ok, failures, _lock_eval = portfolio_live_preflight(markets)
        if not ok:
            if failures_include_hl_unhealthy(failures):
                print_and_log_hl_unhealthy_skip(context="initial_live_preflight", failures=failures)
                sleep_for_hl_backoff(args.interval_seconds)
            else:
                raise SystemExit(f"portfolio live preflight failed: {failures}")
    actions_executed = 0
    loop_index = 0
    exit_reason = "completed"
    summary_status_override: str | None = None
    while True:
        loop_index += 1
        if stop_file_exists():
            print("STOP file detected; portfolio manager exiting gracefully")
            exit_reason = "stop_file"
            break
        try:
            summary = portfolio_summary(markets, context="portfolio_manager")
        except HL_API_ERRORS as exc:
            log_hl_api_warning(context="portfolio_manager_summary", exc=exc, blocks_execution=False)
            print_and_log_hl_unhealthy_skip(
                context="portfolio_manager_summary",
                failures=[f"HL summary unavailable: reason={hl_error_reason(exc)}"],
            )
            print("decision: no_action")
            print("orders_placed: no")
            if max_loops is not None and loop_index >= max_loops:
                exit_reason = "max_loops"
                break
            sleep_for_hl_backoff(args.interval_seconds)
            continue
        if args.live and summary.get("hl_unavailable"):
            write_portfolio_state(summary, None)
            print_portfolio_loop_scan_info(loop_index, max_loops)
            print_threshold_profile()
            print(f"loop: {loop_index}")
            print(f"active_s1_count: {summary['active_s1_count']}")
            print(f"active_s2_count: {summary['active_s2_count']}")
            print(f"portfolio_state: {summary['portfolio_state']}")
            print_and_log_hl_unhealthy_skip(
                context="portfolio_manager_summary",
                failures=["HL position unavailable during portfolio summary"],
            )
            print("decision: no_action")
            print("orders_placed: no")
            if max_loops is not None and loop_index >= max_loops:
                exit_reason = "max_loops"
                break
            sleep_for_hl_backoff(args.interval_seconds)
            continue
        selected_candidate, candidates = choose_portfolio_candidate(summary)
        annotate_candidates(candidates, selected_candidate)
        append_pm_hl_spread_snapshots(candidates, loop_index=loop_index, run_context="portfolio_manager")
        write_portfolio_state(summary, selected_candidate)
        print_portfolio_loop_scan_info(loop_index, max_loops)
        print_threshold_profile()
        print(f"loop: {loop_index}")
        print(f"active_s1_count: {summary['active_s1_count']}")
        print(f"active_s2_count: {summary['active_s2_count']}")
        print(f"portfolio_state: {summary['portfolio_state']}")
        for row in summary["per_market"]:
            print(
                f"market={row['market']} s1_status={row['s1_status']} s2_status={row['s2_status']} "
                f"portfolio_view={row['portfolio_view']} s2_reentry_eligible={str(row['s2_reentry_eligible']).lower()}"
            )
        if args.verbose:
            print_candidate_table(candidates)
            print_selected_candidate(selected_candidate, candidates)
            print(f"portfolio selected candidate: {json.dumps(selected_candidate, sort_keys=True, default=str)}")
        else:
            print_selected_action_summary(selected_candidate)
            print_s2_exit_scan_logs(candidates)
        print(f"candidate_counts: exits={len(candidates['s2_exit_candidates'])} "
              f"reentries={len(candidates['s2_reentry_candidates'])} full_entries={len(candidates['full_entry_candidates'])}")
        action_type = selected_candidate.get("action_type") if selected_candidate else None
        if args.verbose:
            print(f"selected_action: {action_type}")
            print(f"selected_market: {selected_candidate.get('market') if selected_candidate else None}")
            print(
                "expected_profit / realized_profit: "
                f"{selected_candidate.get('expected_profit') or selected_candidate.get('realized_profit_if_exit') if selected_candidate else None}"
            )
        decision = "no_action"
        orders_placed_this_loop = "no"
        if selected_candidate and action_type not in allowed_actions:
            decision = "skip"
            print(f"skipped_by_allowed_actions: {action_type} not in {sorted(allowed_actions)}")
            if args.live:
                append_event({"event": "portfolio_action_skipped_by_allowed_actions", "candidate": selected_candidate})
        elif selected_candidate:
            decision = "execute" if args.live else "dry_run_select"
        if args.live:
            if not selected_candidate:
                print_no_action("no eligible portfolio candidate")
            elif action_type not in allowed_actions:
                print("orders_placed: no")
            if actions_executed >= args.max_actions_per_run:
                print_no_action("max_actions reached")
                exit_reason = "max_actions_reached"
                break
            if selected_candidate and action_type in allowed_actions:
                ok, failures, _lock_eval = portfolio_live_preflight(markets)
                if not ok:
                    if failures_include_hl_unhealthy(failures):
                        print_and_log_hl_unhealthy_skip(
                            context="portfolio_live_preflight",
                            failures=failures,
                            candidate=selected_candidate,
                        )
                        decision = "no_action"
                        selected_candidate = None
                    else:
                        raise SystemExit(f"portfolio live preflight failed: {failures}")
                if not selected_candidate:
                    print("orders_placed: no")
                    if max_loops is not None and loop_index >= max_loops:
                        exit_reason = "max_loops"
                        break
                    sleep_for_hl_backoff(args.interval_seconds)
                    continue
                guard_status = portfolio_live_guard_status(selected_candidate, args)
                if not guard_status["ok"]:
                    print_and_log_portfolio_guard_failure(selected_candidate, guard_status)
                    exit_reason = "guard_failure"
                    break
                print_portfolio_live_single_action(selected_candidate, args.max_actions_per_run)
                try:
                    result = execute_portfolio_candidate(selected_candidate, summary)
                except HaltedError as exc:
                    if "SKIP_ACTION_HL_UNHEALTHY" in str(exc):
                        print_and_log_hl_unhealthy_skip(
                            context="portfolio_execute_pre_order_health",
                            failures=[str(exc)],
                            candidate=selected_candidate,
                        )
                        decision = "no_action"
                        print("orders_placed: no")
                        if max_loops is not None and loop_index >= max_loops:
                            exit_reason = "max_loops"
                            break
                        sleep_for_hl_backoff(args.interval_seconds)
                        continue
                    raise
                actions_executed += 1
                orders_placed_this_loop = "yes"
                state_after = read_state_no_create(str(selected_candidate["market"])).get("state")
                execution_status = portfolio_execution_status(result)
                print_action_result_summary(selected_candidate, str(state_after) if state_after is not None else None, execution_status)
                if args.verbose:
                    print(f"execution_status: {json.dumps(execution_status, sort_keys=True, default=str)}")
                append_event({"event": "portfolio_action_executed", "candidate": selected_candidate, "result": result})
                if result.get("partial_fill_requires_review"):
                    summary_status_override = "halted"
                    exit_reason = "partial_fill_outside_tolerance"
                    print("requires_manual_review: true")
                    break
                if not args.run_until_stop or actions_executed >= args.max_actions_per_run:
                    if actions_executed >= args.max_actions_per_run:
                        print("max_actions_per_run reached; portfolio manager exiting")
                        exit_reason = "max_actions_reached"
                    break
        print(f"decision: {decision}")
        print(f"orders_placed: {orders_placed_this_loop}")
        if max_loops is not None and loop_index >= max_loops:
            exit_reason = "max_loops"
            break
        if args.max_loops is not None and not args.run_until_stop and loop_index >= args.max_loops:
            exit_reason = "max_loops"
            break
        time.sleep(args.interval_seconds)
    final_summary = portfolio_summary(markets, context="portfolio_manager_final")
    print("SUMMARY")
    if args.verbose:
        print(f"selected_candidate: {json.dumps(selected_candidate, sort_keys=True, default=str)}")
    elif selected_candidate:
        print_selected_action_summary(selected_candidate)
    else:
        print("selected_candidate: none")
    print(f"live_run: {'yes' if args.live else 'no'}")
    print(f"orders_placed: {'yes' if actions_executed else 'no'}")
    print(f"summary_status: {summary_status_override or final_summary.get('summary_status', 'ok')}")
    if int(final_summary.get("position_read_warnings") or 0) > 0:
        print(f"position_read_warnings: {final_summary['position_read_warnings']}")
    print(f"exit_reason: {exit_reason}")
    return 0


def require_live_preflight(markets: list[str]) -> None:
    lock_eval = resolve_stale_active_lock_if_needed()
    if lock_eval.get("active_lock_error"):
        raise HaltedError(lock_eval["active_lock_error"])
    active = read_active_market()
    if active and active.get("market") is not None:
        active_market = str(active.get("market"))
        active_lock_state = active.get("state")
        if active_lock_state == STATE_HALTED:
            raise HaltedError(f"active market lock is HALTED: {active}")
        if active_market not in SUPPORTED_MARKETS:
            raise HaltedError(f"active market lock invalid: {active}")
        if active_market not in markets:
            raise HaltedError(f"active market {active_market} is not in requested markets")
        active_state = load_state(active_market)
        if active_state["state"] == STATE_HALTED:
            raise HaltedError(f"{active_market} is HALTED: {active_state.get('halt_reason')}")
        if active_state["state"] not in {STATE_ACTIVE, STATE_S2_EXITED}:
            raise HaltedError(f"active market state requires manual check: {active_state['state']}")
    try:
        result = check_pm_auth_cash()
    except Exception as exc:
        raise HaltedError(f"PM authenticated API/cash/auth preflight failed: {exc}") from exc
    if result.get("final_auth_status") != "PASS":
        raise HaltedError("PM authenticated API/cash/auth preflight failed: cash unavailable")


def handle_live_preflight_failure(exc: Exception) -> None:
    message = str(exc)
    print("LIVE PREFLIGHT FAILED")
    print(message)
    append_event({"event": "live_preflight_failed", "error": message, "live": True})
    sys.exit(1)


def evaluate_market(
    market_key: str,
    args: argparse.Namespace,
    balances: dict[str, Any],
) -> dict[str, Any]:
    state = load_state(market_key)
    market = get_watchlist_market(market_key)
    if state["state"] == STATE_HALTED:
        raise HaltedError(f"{market_key} is HALTED: {state.get('halt_reason')}")
    if state["state"] in ACTIVE_STATES:
        return {"market": market_key, "state": state, "active": True}
    snapshot = wc_position_snapshot(market)
    plans = build_entry_plans(market)
    selected = plans[0]["selected"]
    threshold_walk_combined_executable_size = walk_combined_executable_size_with_threshold(plans[0])
    display_combined_executable_size = direct_combined_executable_size(plans[0])
    failures = entry_failures(plans, balances, threshold_walk_combined_executable_size, has_wc_position(snapshot))
    if args.live:
        failures.extend(live_gate_failures(args, market_key))
    status = "entry_ready" if not failures else "entry_not_ready"
    row = {
        "event": "entry_check",
        "market": market_key,
        "direction": selected["direction"],
        "pm_direct_ask": selected["pm_direct_ask"],
        "hl_direct_ask": selected["hl_direct_ask"],
        "entry_cost": plans[0]["entry_cost"],
        "expected_profit": plans[0]["expected_profit"],
        "net_edge_bps": net_edge_bps(plans[0]),
        "combined_required_shares": COMBINED_REQUIRED_SHARES,
        "combined_executable_size": display_combined_executable_size,
        "threshold_walk_combined_executable_size": threshold_walk_combined_executable_size,
        "status": status,
        "failures": failures,
        "dry_run": not args.live,
    }
    append_event(row)
    print(
        f"ENTRY_CHECK market={market_key} status={status} direction={selected['direction']} "
        f"net_edge_bps={row['net_edge_bps']:.6f} expected_profit={plans[0]['expected_profit']:.6f} "
        f"combined_executable_size={display_combined_executable_size:.6f}"
    )
    return {
        **row,
        "state": state,
        "market_config": market,
        "plans": plans,
        "positions": snapshot,
        "would_trigger_entry": status == "entry_ready",
        "active": False,
    }


def choose_entry_candidate(evaluations: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in evaluations if row.get("would_trigger_entry")]
    return max(candidates, key=lambda row: float(row.get("expected_profit") or 0), default=None)


def live_entry_safety_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    plan = candidate["plans"][0]
    selected = plan["selected"]
    market = candidate["market_config"]
    pm_asks, hl_asks = selected_ask_books(plan)
    pm_ask_size = pm_asks[0][1] if pm_asks else None
    hl_ask_size = hl_asks[0][1] if hl_asks else None
    return {
        "event": "live_entry_pre_order_safety",
        "selected_market": candidate["market"],
        "direction": selected["direction"],
        "pm_outcome": selected["pm_leg"],
        "pm_token": plan["pm_token"],
        "pm_direct_ask_price": selected["pm_direct_ask"],
        "pm_direct_ask_size": pm_ask_size,
        "hl_outcome": selected["hl_leg"],
        "hl_coin": plan["hl_coin"],
        "hl_direct_ask_price": selected["hl_direct_ask"],
        "hl_direct_ask_size": hl_ask_size,
        "combined_required_shares": COMBINED_REQUIRED_SHARES,
        "combined_executable_size": candidate["combined_executable_size"],
        "entry_cost": plan["entry_cost"],
        "expected_profit": plan["expected_profit"],
        "net_edge_bps": candidate["net_edge_bps"],
        "pm_market_name": market.get("pm_market_name"),
        "hl_market_name": market.get("hl_market_name"),
    }


def log_live_entry_safety(candidate: dict[str, Any]) -> None:
    payload = live_entry_safety_payload(candidate)
    append_event(payload)
    print("LIVE ENTRY PRE-ORDER SAFETY")
    print(f"selected_market: {payload['selected_market']}")
    print(f"direction: {payload['direction']}")
    print(f"PM outcome/token: {payload['pm_outcome']} token={payload['pm_token']}")
    print(f"PM direct ask: price={payload['pm_direct_ask_price']} size={payload['pm_direct_ask_size']}")
    print(f"HL outcome/coin: {payload['hl_outcome']} coin={payload['hl_coin']}")
    print(f"HL direct ask: price={payload['hl_direct_ask_price']} size={payload['hl_direct_ask_size']}")
    print(f"combined_required_shares: {payload['combined_required_shares']}")
    print(f"combined_executable_size: {payload['combined_executable_size']}")
    print(f"entry_cost: {payload['entry_cost']}")
    print(f"expected_profit: {payload['expected_profit']}")
    print(f"net_edge_bps: {payload['net_edge_bps']}")


def assert_live_entry_quotes_fresh(plan: dict[str, Any]) -> None:
    selected = plan["selected"]
    required_size = float(plan["shares"])
    pm_selected_price = float(selected["pm_direct_ask"])
    hl_selected_price = float(selected["hl_direct_ask"])
    _, pm_asks, _ = pm.book(str(plan["pm_token"]))
    hl_book, hl_warning = safe_hl_coin_book(
        str(plan["hl_coin"]),
        context="live_pre_order_quote_check",
        market_key=str(plan["market"]["market"]),
        blocks_execution=True,
    )
    if hl_book is None:
        reason = hl_warning.get("reason") if hl_warning else "unavailable"
        status = hl_warning.get("status") if hl_warning else None
        print_and_log_hl_unhealthy_skip(
            context="live_pre_order_quote_check",
            failures=[f"HL orderbook unavailable: reason={reason} status={status}"],
        )
        raise HaltedError(f"SKIP_ACTION_HL_UNHEALTHY: HL orderbook unavailable reason={reason} status={status}")
    _, hl_asks = hl_book
    pm_current_best_ask_price = pm_asks[0][0] if pm_asks else None
    pm_current_best_ask_size = pm_asks[0][1] if pm_asks else None
    hl_current_best_ask_price = hl_asks[0][0] if hl_asks else None
    hl_current_best_ask_size = hl_asks[0][1] if hl_asks else None
    stale = (
        pm_current_best_ask_price != pm_selected_price
        or pm_current_best_ask_size is None
        or float(pm_current_best_ask_size) < required_size
        or hl_current_best_ask_price != hl_selected_price
        or hl_current_best_ask_size is None
        or float(hl_current_best_ask_size) < required_size
    )
    if not stale:
        return
    payload = {
        "event": "live_pre_order_quote_stale",
        "market": plan["market"]["market"],
        "pm_token": plan["pm_token"],
        "pm_selected_ask_price": pm_selected_price,
        "pm_current_best_ask_price": pm_current_best_ask_price,
        "pm_current_best_ask_size": pm_current_best_ask_size,
        "hl_coin": plan["hl_coin"],
        "hl_selected_ask_price": hl_selected_price,
        "hl_current_best_ask_price": hl_current_best_ask_price,
        "hl_current_best_ask_size": hl_current_best_ask_size,
        "required_order_size": required_size,
    }
    append_event(payload)
    print("LIVE PRE-ORDER QUOTE STALE")
    print(f"pm_selected_ask_price: {pm_selected_price}")
    print(f"pm_current_best_ask_price: {pm_current_best_ask_price}")
    print(f"pm_current_best_ask_size: {pm_current_best_ask_size}")
    print(f"hl_selected_ask_price: {hl_selected_price}")
    print(f"hl_current_best_ask_price: {hl_current_best_ask_price}")
    print(f"hl_current_best_ask_size: {hl_current_best_ask_size}")
    print(f"required_order_size: {required_size}")
    raise HaltedError("live pre-order quote stale; no PM or HL order sent")


def hl_pre_order_health_check(
    *,
    market_key: str,
    hl_coin: str,
    context: str,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    spot, spot_warning = safe_hl_spot_balances(
        context=f"{context}_spot",
        market_key=market_key,
        coin=hl_coin,
        blocks_execution=True,
    )
    if spot is None:
        reason = spot_warning.get("reason") if spot_warning else "unavailable"
        status = spot_warning.get("status") if spot_warning else None
        failures.append(f"HL spot unavailable: reason={reason} status={status}")
    book, book_warning = safe_hl_coin_book(
        str(hl_coin),
        context=f"{context}_orderbook",
        market_key=market_key,
        blocks_execution=True,
    )
    if book is None:
        reason = book_warning.get("reason") if book_warning else "unavailable"
        status = book_warning.get("status") if book_warning else None
        failures.append(f"HL orderbook unavailable: reason={reason} status={status}")
    return not failures, failures


def assert_hl_pre_order_health(*, market_key: str, hl_coin: str, context: str) -> None:
    ok, failures = hl_pre_order_health_check(market_key=market_key, hl_coin=hl_coin, context=context)
    if ok:
        return
    print_and_log_hl_unhealthy_skip(context=context, failures=failures)
    raise HaltedError(f"SKIP_ACTION_HL_UNHEALTHY: {'; '.join(failures)}")


def execute_entry_legged(plan: dict[str, Any], action_type: str = "ENTRY", strategy_slot: str | None = None) -> dict[str, Any]:
    selected = plan["selected"]
    assert_hl_pre_order_health(
        market_key=str(plan["market"]["market"]),
        hl_coin=str(plan["hl_coin"]),
        context=f"{action_type.lower()}_pre_order_health",
    )
    assert_live_entry_quotes_fresh(plan)
    pm_client = build_pm_client_for_execution()
    hl_exchange, agent_address, account = hl.build_exchange()
    result: dict[str, Any] = {"agent_address": agent_address, "hl_account": account, "orders": []}
    pm_before = pm_position_size(str(plan["pm_token"]))
    hl_before = hl_position_size(str(plan["hl_coin"]))
    for order_index, venue in enumerate(plan["order_sequence"]):
        try:
            if venue == "PM":
                response = pm_ioc_buy(pm_client, plan["pm_token"], float(selected["pm_direct_ask"]), BOX_SHARES)
            else:
                response = direct_hl_ioc_buy(hl_exchange, plan["hl_coin"], float(selected["hl_direct_ask"]), BOX_SHARES)
            result["orders"].append({"venue": venue, "response": response})
            if response_indicates_failure(venue, response):
                raise HaltedError(f"{venue} entry response indicates failure")
        except Exception as exc:
            result["orders"].append({"venue": venue, "error": str(exc)})
            reason = "entry first leg failed" if order_index == 0 else "entry one leg failed"
            raise HaltedError(f"{reason}: {exc}") from exc
    pm_after = pm_before
    hl_after = hl_before
    pm_filled = 0.0
    hl_filled = 0.0
    ok = False
    reason = "position delta unavailable"
    confirmation_attempts: list[dict[str, Any]] = []
    for attempt in range(1, ENTRY_CONFIRM_ATTEMPTS + 1):
        pm_after = pm_position_size(str(plan["pm_token"]))
        hl_after = hl_position_size(str(plan["hl_coin"]))
        pm_filled = pm_after - pm_before
        hl_filled = hl_after - hl_before
        ok, reason = filled_ok(pm_filled, hl_filled)
        confirmation_attempts.append(
            {
                "attempt": attempt,
                "pm_position_before": pm_before,
                "pm_position_after": pm_after,
                "pm_delta": pm_filled,
                "hl_position_before": hl_before,
                "hl_position_after": hl_after,
                "hl_delta": hl_filled,
                "ok": ok,
                "reason": reason,
                "read_at": now_iso(),
            }
        )
        if ok:
            break
        if attempt < ENTRY_CONFIRM_ATTEMPTS:
            time.sleep(ENTRY_CONFIRM_DELAY_SECONDS)
    result["pm_filled_shares"] = pm_filled
    result["hl_filled_shares"] = hl_filled
    result["matched_shares"] = min(pm_filled, hl_filled)
    result["position_delta"] = {
        "pm_before": pm_before,
        "pm_after": pm_after,
        "hl_before": hl_before,
        "hl_after": hl_after,
    }
    result["confirmation"] = build_trade_confirmation(
        market_key=str(plan["market"]["market"]),
        action_type=action_type,
        strategy_slot=strategy_slot or str(plan.get("strategy_variant") or "entry"),
        pm_token=str(plan["pm_token"]),
        hl_coin=str(plan["hl_coin"]),
        intended_shares=BOX_SHARES,
        pm_before=pm_before,
        pm_after=pm_after,
        hl_before=hl_before,
        hl_after=hl_after,
        orders=result["orders"],
        pm_filled=pm_filled,
        hl_filled=hl_filled,
        confirmed=ok,
    )
    result["confirmation"]["position_read_attempts"] = confirmation_attempts
    ok = bool(result["confirmation"]["trade_confirmed"])
    if ok:
        reason = "filled_ok"
        result["pm_filled_shares"] = float(result["confirmation"]["pm"]["confirmed_filled_shares"])
        result["hl_filled_shares"] = float(result["confirmation"]["hl"]["confirmed_filled_shares"])
        result["matched_shares"] = min(float(result["pm_filled_shares"]), float(result["hl_filled_shares"]))
    append_event(
        {
            "event": "trade_confirmation" if ok else "trade_confirmation_failed",
            "market": plan["market"]["market"],
            "strategy_slot": strategy_slot or str(plan.get("strategy_variant") or "entry"),
            "confirmation": result["confirmation"],
            "reason": None if ok else reason,
        }
    )
    print_trade_confirmation(result["confirmation"], None if ok else reason)
    if not ok:
        pm_confirmed = bool(result["confirmation"]["pm"]["confirmed"])
        hl_confirmed = bool(result["confirmation"]["hl"]["confirmed"])
        if not pm_confirmed and not hl_confirmed and approx_equal(pm_after, hl_after):
            print("UNKNOWN_CONFIRMATION_BUT_BALANCED")
            print("recommended_reconcile: mark_s1_active_if_balanced")
        raise HaltedError(reason)
    return result


def update_slot_after_entry(state: dict[str, Any], slot: str, plan: dict[str, Any], log_path: str, result: dict[str, Any]) -> None:
    if not execution_is_confirmed(result):
        raise HaltedError("entry fill confirmation missing; state update blocked")
    state[slot].update(
        {
            "entry_log": log_path,
            "pm_token": plan["pm_token"],
            "hl_coin": plan["hl_coin"],
            "matched_shares": min(float(result["pm_filled_shares"]), float(result["hl_filled_shares"])),
            "status": "active",
        }
    )
    if slot == "s2":
        state[slot]["original_entry_cost"] = float(plan["entry_cost"]) * float(state[slot]["matched_shares"])
    write_state(state)


def enter_selected(candidate: dict[str, Any], args: argparse.Namespace) -> None:
    market_key = candidate["market"]
    if not args.live:
        print(f"DRY-RUN: selected_entry_market={market_key}; no orders placed.")
        return
    log_live_entry_safety(candidate)
    active = read_active_market()
    if active:
        raise HaltedError(f"active market lock exists: {active}")
    state = load_state(market_key)
    plans = candidate["plans"]
    transition(state, STATE_ENTERING_S1, "entry conditions passed")
    try:
        s1_result = execute_entry_legged(plans[0], action_type="FULL_ENTRY", strategy_slot="s1")
        s1_log = write_json_log(market_key, "auto_entry_s1", {"plan": plans[0], "execution": s1_result, "status": "confirmed"})
        update_slot_after_entry(state, "s1", plans[0], s1_log, s1_result)
        transition(state, STATE_ENTERING_S2, "S1 entry filled")
        s2_result = execute_entry_legged(plans[1], action_type="FULL_ENTRY", strategy_slot="s2")
        s2_log = write_json_log(market_key, "auto_entry_s2", {"plan": plans[1], "execution": s2_result, "status": "confirmed"})
        update_slot_after_entry(state, "s2", plans[1], s2_log, s2_result)
        transition(state, STATE_ACTIVE, "S1 and S2 entry filled")
    except Exception as exc:
        halt(state, str(exc))
        raise


def confirm_active_s2(state: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    s1 = state.get("s1", {})
    s2 = state.get("s2", {})
    required = float(s1.get("matched_shares") or 0) + float(s2.get("matched_shares") or 0)
    if not s2.get("entry_log") or not s2.get("pm_token") or not s2.get("hl_coin"):
        raise HaltedError("active S2 cannot be confirmed: missing S2 state fields")
    pm_total = pm_position_size(str(s2["pm_token"]))
    hl_total = hl_position_size(str(s2["hl_coin"]))
    snapshot = {"pm_total": pm_total, "hl_total": hl_total, "required_s1_s2": required}
    if pm_total + FILL_TOLERANCE < required or hl_total + FILL_TOLERANCE < required:
        raise HaltedError(f"position/log inconsistent: active S1/S2 not fully present {snapshot}")
    exit_shares = min(float(s2.get("matched_shares") or 0), BOX_SHARES)
    if exit_shares <= 0:
        raise HaltedError("active S2 cannot be confirmed: matched shares <= 0")
    return exit_shares, snapshot


def analyze_s2_exit(state: dict[str, Any]) -> dict[str, Any]:
    exit_shares, position_snapshot = confirm_active_s2(state)
    s2 = state["s2"]
    pm_bids, _, _ = pm.book(str(s2["pm_token"]))
    hl_bids, _ = hl.coin_book(str(s2["hl_coin"]))
    pm_bid = pm_bids[0][0] if pm_bids else None
    pm_bid_size = pm_bids[0][1] if pm_bids else None
    hl_bid = hl_bids[0][0] if hl_bids else None
    hl_bid_size = hl_bids[0][1] if hl_bids else None
    original_entry_cost = s2.get("original_entry_cost")
    entry_fee_fields = s2_entry_fee_fields_from_state(state, exit_shares)
    lifecycle_fields = s2_exit_lifecycle_pnl_fields(
        entry_gross_cost=original_entry_cost,
        exit_shares=exit_shares,
        pm_exit_price=pm_bid,
        hl_exit_price=hl_bid,
        entry_pm_fee=entry_fee_fields["entry_pm_fee"],
        entry_hl_fee=entry_fee_fields["entry_hl_fee"],
    )
    realized_profit = lifecycle_fields.get("realized_net_pnl_all_in")
    realized_bps = lifecycle_fields.get("net_edge_bps_all_in")
    exit_vs_hold = lifecycle_fields.get("exit_vs_hold_usd")
    disable_exit_vs_hold = exit_vs_hold_check_disabled()
    status = "data_incomplete"
    exit_failures: list[str] = []
    if pm_bid is not None and hl_bid is not None and original_entry_cost is not None:
        if realized_profit is None or realized_profit < threshold_value("exit_min_profit_usd"):
            exit_failures.append(
                f"realized_net_pnl_all_in {realized_profit} < {threshold_value('exit_min_profit_usd'):.6f}"
            )
        if realized_bps is None or realized_bps < threshold_value("exit_min_profit_bps"):
            exit_failures.append(
                f"net_edge_bps_all_in {realized_bps} < {threshold_value('exit_min_profit_bps'):.6f}"
            )
        if not disable_exit_vs_hold and (exit_vs_hold is None or exit_vs_hold < 0):
            exit_failures.append(f"exit_vs_hold_usd {exit_vs_hold} < 0")
        status = "early_exit_candidate" if not exit_failures else "no_early_exit"
    return {
        "market": state["market"],
        "status": status,
        "exit_allowed": status == "early_exit_candidate",
        "exit_shares": exit_shares,
        "pm_token": s2["pm_token"],
        "hl_coin": s2["hl_coin"],
        "pm_bid": pm_bid,
        "pm_bid_size": pm_bid_size,
        "hl_bid": hl_bid,
        "hl_bid_size": hl_bid_size,
        "scan_pm_bid": pm_bid,
        "scan_hl_bid": hl_bid,
        "revalidation_pm_bid": None,
        "revalidation_hl_bid": None,
        "actual_pm_fill_price": None,
        "actual_hl_fill_price": None,
        "pm_price_decay_scan_to_revalidation": None,
        "pm_price_decay_revalidation_to_fill": None,
        "hl_price_decay_scan_to_revalidation": None,
        "hl_price_decay_revalidation_to_fill": None,
        "actual_fill_source": "unavailable",
        "pnl_quality": "estimated",
        "entry_fee_source": entry_fee_fields["entry_fee_source"],
        **lifecycle_fields,
        "exit_failures": exit_failures,
        "min_early_exit_profit_bps": threshold_value("exit_min_profit_bps"),
        "min_early_exit_profit_usd": threshold_value("exit_min_profit_usd"),
        "threshold_profile": CURRENT_THRESHOLD_PROFILE,
        "disable_exit_vs_hold_check": disable_exit_vs_hold,
        "exit_vs_hold_check": "disabled_by_profile" if disable_exit_vs_hold else "enabled",
        "exit_eligibility_rule": (
            "realized_net_pnl_all_in >= exit_min_profit_usd AND net_edge_bps_all_in >= exit_min_profit_bps"
            if disable_exit_vs_hold
            else "realized_net_pnl_all_in >= exit_min_profit_usd AND "
            "net_edge_bps_all_in >= exit_min_profit_bps AND exit_vs_hold_usd >= 0"
        ),
        "position_snapshot": position_snapshot,
        "rules": {
            "uses_direct_bids_only": True,
            "uses_mid": False,
            "uses_one_minus_opposite_book": False,
            "no_short": True,
            "no_auto_chase": True,
            "no_auto_repair": True,
            "no_auto_scale": True,
        },
    }


def s2_exit_stage_fields(
    analysis: dict[str, Any],
    *,
    pm_exit_price: Any,
    hl_exit_price: Any,
    pm_size: Any = None,
    hl_size: Any = None,
) -> dict[str, Any]:
    fields = s2_exit_lifecycle_pnl_fields(
        entry_gross_cost=analysis.get("entry_gross_cost") or analysis.get("original_entry_cost"),
        exit_shares=float(analysis.get("exit_shares") or 0),
        pm_exit_price=pm_exit_price,
        hl_exit_price=hl_exit_price,
        entry_pm_fee=analysis.get("entry_pm_fee"),
        entry_hl_fee=analysis.get("entry_hl_fee"),
    )
    available_size = None
    if pm_size is not None and hl_size is not None:
        available_size = min(float(pm_size or 0), float(hl_size or 0))
    failures: list[str] = []
    realized_profit = fields.get("realized_net_pnl_all_in")
    realized_bps = fields.get("net_edge_bps_all_in")
    exit_vs_hold = fields.get("exit_vs_hold_usd")
    disable_exit_vs_hold = exit_vs_hold_check_disabled()
    if realized_profit is None or realized_profit < threshold_value("exit_min_profit_usd"):
        failures.append(
            f"realized_net_pnl_all_in {realized_profit} < {threshold_value('exit_min_profit_usd'):.6f}"
        )
    if realized_bps is None or realized_bps < threshold_value("exit_min_profit_bps"):
        failures.append(f"net_edge_bps_all_in {realized_bps} < {threshold_value('exit_min_profit_bps'):.6f}")
    if not disable_exit_vs_hold and (exit_vs_hold is None or exit_vs_hold < 0):
        failures.append(f"exit_vs_hold_usd {exit_vs_hold} < 0")
    return {
        **fields,
        "available_size": available_size,
        "failures": failures,
        "candidate_eligible": not failures,
        "disable_exit_vs_hold_check": disable_exit_vs_hold,
        "exit_vs_hold_check": "disabled_by_profile" if disable_exit_vs_hold else "enabled",
    }


def price_decay_usd(
    *,
    exit_shares: Any,
    from_pm_price: Any,
    from_hl_price: Any,
    to_pm_price: Any,
    to_hl_price: Any,
) -> float | None:
    shares = maybe_float(exit_shares)
    from_pm = maybe_float(from_pm_price)
    from_hl = maybe_float(from_hl_price)
    to_pm = maybe_float(to_pm_price)
    to_hl = maybe_float(to_hl_price)
    if None in (shares, from_pm, from_hl, to_pm, to_hl):
        return None
    return ((from_pm + from_hl) - (to_pm + to_hl)) * shares


def print_s2_exit_revalidation_log(analysis: dict[str, Any]) -> None:
    print(
        "S2_EXIT_REVALIDATION "
        f"market={analysis.get('market')} "
        f"threshold_profile={analysis.get('threshold_profile') or CURRENT_THRESHOLD_PROFILE} "
        f"disable_exit_vs_hold_check={str(bool(analysis.get('disable_exit_vs_hold_check'))).lower()} "
        f"exit_vs_hold_check={analysis.get('reval_exit_vs_hold_check') or analysis.get('exit_vs_hold_check') or exit_vs_hold_check_label()} "
        f"reval_pm_bid={analysis.get('revalidation_pm_bid')} "
        f"reval_hl_bid={analysis.get('revalidation_hl_bid')} "
        f"reval_exit_net_edge_bps={analysis.get('reval_exit_net_edge_bps')} "
        f"reval_realized_net_pnl_all_in={analysis.get('reval_realized_net_pnl_all_in')} "
        f"reval_exit_vs_hold_usd={analysis.get('reval_exit_vs_hold_usd')} "
        f"reval_available_size={analysis.get('reval_available_size')} "
        f"reval_candidate_eligible={str(bool(analysis.get('reval_candidate_eligible'))).lower()} "
        f"reval_skip_reason={analysis.get('reval_skip_reason')} "
        f"reason={analysis.get('reval_reason')}"
    )


def print_s2_exit_fill_log(analysis: dict[str, Any]) -> None:
    print(
        "S2_EXIT_FILL "
        f"market={analysis.get('market')} "
        f"threshold_profile={analysis.get('threshold_profile') or CURRENT_THRESHOLD_PROFILE} "
        f"disable_exit_vs_hold_check={str(bool(analysis.get('disable_exit_vs_hold_check'))).lower()} "
        f"exit_vs_hold_check={analysis.get('exit_vs_hold_check') or exit_vs_hold_check_label()} "
        f"actual_pm_fill_price={analysis.get('actual_pm_fill_price')} "
        f"actual_hl_fill_price={analysis.get('actual_hl_fill_price')} "
        f"target_qty={analysis.get('target_qty')} "
        f"tolerance_pct={analysis.get('tolerance_pct')} "
        f"pm_filled_qty={analysis.get('pm_filled_qty')} "
        f"hl_filled_qty={analysis.get('hl_filled_qty')} "
        f"pm_fill_error_qty={analysis.get('pm_fill_error_qty')} "
        f"hl_fill_error_qty={analysis.get('hl_fill_error_qty')} "
        f"pm_fill_error_pct={analysis.get('pm_fill_error_pct')} "
        f"hl_fill_error_pct={analysis.get('hl_fill_error_pct')} "
        f"confirmation_status={analysis.get('confirmation_status')} "
        f"requires_manual_review={str(bool(analysis.get('requires_manual_review'))).lower()} "
        f"actual_pm_fee={analysis.get('exit_pm_fee')} "
        f"actual_hl_fee={analysis.get('exit_hl_fee')} "
        f"actual_realized_gross_pnl={analysis.get('realized_gross_pnl')} "
        f"actual_realized_net_pnl_all_in={analysis.get('realized_net_pnl_all_in')} "
        f"actual_exit_vs_hold_usd={analysis.get('exit_vs_hold_usd')} "
        f"scan_to_reval_decay_usd={analysis.get('scan_to_reval_decay_usd')} "
        f"reval_to_fill_decay_usd={analysis.get('reval_to_fill_decay_usd')} "
        f"scan_to_fill_decay_usd={analysis.get('scan_to_fill_decay_usd')}"
    )


def execute_s2_exit(state: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    assert_hl_pre_order_health(
        market_key=str(analysis["market"]),
        hl_coin=str(analysis["hl_coin"]),
        context="s2_exit_pre_order_health",
    )
    pm_client = build_pm_client_for_execution()
    hl_exchange, agent_address, account = hl.build_exchange()
    shares = min(float(analysis["exit_shares"]), BOX_SHARES)
    result: dict[str, Any] = {"agent_address": agent_address, "hl_account": account, "orders": []}
    pm_before = pm_position_size(str(analysis["pm_token"]))
    hl_before = hl_position_size(str(analysis["hl_coin"]))
    for order_index, venue in enumerate(("PM", "HL")):
        try:
            if venue == "PM":
                response = direct_pm_fak_sell(pm_client, str(analysis["pm_token"]), float(analysis["pm_bid"]), shares)
            else:
                response = direct_hl_ioc_sell(hl_exchange, str(analysis["hl_coin"]), float(analysis["hl_bid"]), shares)
            result["orders"].append({"venue": venue, "response": response})
            if response_indicates_failure(venue, response):
                raise HaltedError(f"{venue} exit response indicates failure")
        except Exception as exc:
            result["orders"].append({"venue": venue, "error": str(exc)})
            reason = "exit first leg failed" if order_index == 0 else "exit one leg failed"
            raise HaltedError(f"{reason}: {exc}") from exc
    pm_order = next((order for order in result["orders"] if order.get("venue") == "PM"), {})
    hl_order = next((order for order in result["orders"] if order.get("venue") == "HL"), {})
    actual_pm_fill_price = order_response_fill_price("PM", pm_order.get("response"), shares)
    actual_hl_fill_price = order_response_fill_price("HL", hl_order.get("response"), shares)
    result["scan_pm_bid"] = analysis.get("scan_pm_bid") or analysis.get("pm_bid")
    result["scan_hl_bid"] = analysis.get("scan_hl_bid") or analysis.get("hl_bid")
    result["revalidation_pm_bid"] = analysis.get("revalidation_pm_bid")
    result["revalidation_hl_bid"] = analysis.get("revalidation_hl_bid")
    result["actual_pm_fill_price"] = actual_pm_fill_price
    result["actual_hl_fill_price"] = actual_hl_fill_price
    result["actual_fill_source"] = (
        "order_response" if actual_pm_fill_price is not None and actual_hl_fill_price is not None else "unavailable"
    )
    result["pm_price_decay_scan_to_revalidation"] = analysis.get("pm_price_decay_scan_to_revalidation")
    result["hl_price_decay_scan_to_revalidation"] = analysis.get("hl_price_decay_scan_to_revalidation")
    result["pm_price_decay_revalidation_to_fill"] = (
        float(analysis["revalidation_pm_bid"]) - actual_pm_fill_price
        if analysis.get("revalidation_pm_bid") is not None and actual_pm_fill_price is not None
        else None
    )
    result["hl_price_decay_revalidation_to_fill"] = (
        float(analysis["revalidation_hl_bid"]) - actual_hl_fill_price
        if analysis.get("revalidation_hl_bid") is not None and actual_hl_fill_price is not None
        else None
    )
    pm_after = pm_before
    hl_after = hl_before
    pm_filled = 0.0
    hl_filled = 0.0
    ok = False
    reason = "position delta unavailable"
    confirmation_attempts: list[dict[str, Any]] = []
    for attempt in range(1, ENTRY_CONFIRM_ATTEMPTS + 1):
        pm_after = pm_position_size(str(analysis["pm_token"]))
        hl_after = hl_position_size(str(analysis["hl_coin"]))
        pm_filled = pm_before - pm_after
        hl_filled = hl_before - hl_after
        confirmation = build_trade_confirmation(
            market_key=str(analysis["market"]),
            action_type="S2_EXIT",
            strategy_slot="s2",
            pm_token=str(analysis["pm_token"]),
            hl_coin=str(analysis["hl_coin"]),
            intended_shares=shares,
            pm_before=pm_before,
            pm_after=pm_after,
            hl_before=hl_before,
            hl_after=hl_after,
            orders=result["orders"],
            pm_filled=pm_filled,
            hl_filled=hl_filled,
            confirmed=False,
        )
        position_ok, position_reason, fill_status = s2_exit_fills_ok(
            float(confirmation.get("pm_filled_qty") or pm_filled),
            float(confirmation.get("hl_filled_qty") or hl_filled),
            intended=shares,
        )
        ok = bool(confirmation["trade_confirmed"])
        reason = "filled_ok" if ok else position_reason
        confirmation_attempts.append(
            {
                "attempt": attempt,
                "pm_position_before": pm_before,
                "pm_position_after": pm_after,
                "pm_delta": pm_filled,
                "hl_position_before": hl_before,
                "hl_position_after": hl_after,
                "hl_delta": hl_filled,
                "position_delta_ok": position_ok,
                "trade_confirmed": ok,
                "confirmation_status": confirmation.get("confirmation_status"),
                "requires_manual_review": confirmation.get("requires_manual_review"),
                "fill_warnings": confirmation.get("fill_warnings") or [],
                "reason": None if ok else position_reason,
                "read_at": now_iso(),
            }
        )
        result["confirmation"] = confirmation
        if ok:
            result["pm_filled_shares"] = float(confirmation["pm"]["confirmed_filled_shares"])
            result["hl_filled_shares"] = float(confirmation["hl"]["confirmed_filled_shares"])
            break
        if attempt < ENTRY_CONFIRM_ATTEMPTS:
            time.sleep(ENTRY_CONFIRM_DELAY_SECONDS)
    result["pm_filled_shares"] = pm_filled
    result["hl_filled_shares"] = hl_filled
    result["position_delta"] = {
        "pm_before": pm_before,
        "pm_after": pm_after,
        "hl_before": hl_before,
        "hl_after": hl_after,
    }
    result["confirmation"]["position_read_attempts"] = confirmation_attempts
    if ok:
        result["pm_filled_shares"] = float(result["confirmation"]["pm"]["confirmed_filled_shares"])
        result["hl_filled_shares"] = float(result["confirmation"]["hl"]["confirmed_filled_shares"])
    append_event(
        {
            "event": "trade_confirmation" if ok else "trade_confirmation_failed",
            "market": analysis["market"],
            "strategy_slot": "s2",
            "confirmation": result["confirmation"],
            "reason": None if ok else reason,
        }
    )
    print_trade_confirmation(result["confirmation"], None if ok else reason)
    if not ok:
        if result["confirmation"].get("requires_manual_review"):
            raise PartialFillRequiresReview(reason, result["confirmation"])
        raise HaltedError(reason)
    expected_s1_remaining = float(state.get("s1", {}).get("matched_shares") or 0)
    pm_leg = result["confirmation"]["pm"]
    hl_leg = result["confirmation"]["hl"]
    confirmed_pm_after = pm_after
    confirmed_hl_after = hl_after
    if pm_leg.get("confirmed"):
        confirmed_pm_after = pm_before - float(pm_leg.get("confirmed_filled_shares") or 0)
    if hl_leg.get("confirmed"):
        confirmed_hl_after = hl_before - float(hl_leg.get("confirmed_filled_shares") or 0)
    result["position_delta"]["pm_after_confirmed_or_inferred"] = confirmed_pm_after
    result["position_delta"]["hl_after_confirmed_or_inferred"] = confirmed_hl_after
    remaining_tolerance = max(FILL_TOLERANCE, shares * S2_EXIT_FILL_TOLERANCE_PCT)
    if (
        abs(confirmed_pm_after - expected_s1_remaining) > remaining_tolerance
        or abs(confirmed_hl_after - expected_s1_remaining) > remaining_tolerance
    ):
        raise HaltedError(
            "S1 remaining position imbalance after S2 exit: "
            f"pm_after={pm_after:.6f}, hl_after={hl_after:.6f}, "
            f"pm_after_confirmed_or_inferred={confirmed_pm_after:.6f}, "
            f"hl_after_confirmed_or_inferred={confirmed_hl_after:.6f}, "
            f"expected={expected_s1_remaining:.6f}"
        )
    return result


def apply_actual_exit_fill_prices_to_analysis(analysis: dict[str, Any], execution: dict[str, Any]) -> None:
    actual_pm = execution.get("actual_pm_fill_price")
    actual_hl = execution.get("actual_hl_fill_price")
    confirmation = execution.get("confirmation") or {}
    analysis["actual_pm_fill_price"] = actual_pm
    analysis["actual_hl_fill_price"] = actual_hl
    analysis["actual_fill_source"] = execution.get("actual_fill_source") or "unavailable"
    analysis["pm_price_decay_revalidation_to_fill"] = execution.get("pm_price_decay_revalidation_to_fill")
    analysis["hl_price_decay_revalidation_to_fill"] = execution.get("hl_price_decay_revalidation_to_fill")
    for key in (
        "target_qty",
        "tolerance_pct",
        "pm_filled_qty",
        "hl_filled_qty",
        "pm_fill_error_qty",
        "hl_fill_error_qty",
        "pm_fill_error_pct",
        "hl_fill_error_pct",
        "confirmation_status",
        "requires_manual_review",
        "state_after",
    ):
        if key in confirmation:
            analysis[key] = confirmation[key]
    if actual_pm is None or actual_hl is None:
        analysis["pnl_quality"] = "estimated"
        analysis["reval_to_fill_decay_usd"] = None
        analysis["scan_to_fill_decay_usd"] = None
        return
    lifecycle_fields = s2_exit_actual_fill_pnl_fields(
        entry_gross_cost=analysis.get("entry_gross_cost") or analysis.get("original_entry_cost"),
        target_shares=float(analysis.get("exit_shares") or 0),
        pm_filled_qty=confirmation.get("pm_filled_qty"),
        hl_filled_qty=confirmation.get("hl_filled_qty"),
        pm_exit_price=actual_pm,
        hl_exit_price=actual_hl,
        entry_pm_fee=analysis.get("entry_pm_fee"),
        entry_hl_fee=analysis.get("entry_hl_fee"),
    )
    if lifecycle_fields:
        analysis.update(lifecycle_fields)
    analysis["pnl_quality"] = "order_response"
    analysis["reval_to_fill_decay_usd"] = price_decay_usd(
        exit_shares=analysis.get("exit_shares"),
        from_pm_price=analysis.get("revalidation_pm_bid"),
        from_hl_price=analysis.get("revalidation_hl_bid"),
        to_pm_price=actual_pm,
        to_hl_price=actual_hl,
    )
    analysis["scan_to_fill_decay_usd"] = price_decay_usd(
        exit_shares=analysis.get("exit_shares"),
        from_pm_price=analysis.get("scan_pm_bid") or analysis.get("pm_bid"),
        from_hl_price=analysis.get("scan_hl_bid") or analysis.get("hl_bid"),
        to_pm_price=actual_pm,
        to_hl_price=actual_hl,
    )


def live_exit_quotes_fresh(analysis: dict[str, Any]) -> bool:
    required_shares = float(analysis["exit_shares"])
    pm_bids, _, _ = pm.book(str(analysis["pm_token"]))
    hl_book, hl_warning = safe_hl_coin_book(
        str(analysis["hl_coin"]),
        context="live_pre_exit_quote_check",
        market_key=str(analysis["market"]),
        blocks_execution=True,
    )
    if hl_book is None:
        reason = hl_warning.get("reason") if hl_warning else "unavailable"
        status = hl_warning.get("status") if hl_warning else None
        print_and_log_hl_unhealthy_skip(
            context="live_pre_exit_quote_check",
            failures=[f"HL orderbook unavailable: reason={reason} status={status}"],
            candidate={"action_type": "S2_EXIT", "market": analysis.get("market")},
        )
        return False
    hl_bids, _ = hl_book
    pm_current_bid = pm_bids[0][0] if pm_bids else None
    pm_current_size = pm_bids[0][1] if pm_bids else None
    hl_current_bid = hl_bids[0][0] if hl_bids else None
    hl_current_size = hl_bids[0][1] if hl_bids else None
    analysis["revalidation_pm_bid"] = pm_current_bid
    analysis["revalidation_hl_bid"] = hl_current_bid
    analysis["pm_price_decay_scan_to_revalidation"] = (
        float(analysis["pm_bid"]) - float(pm_current_bid) if pm_current_bid is not None else None
    )
    analysis["hl_price_decay_scan_to_revalidation"] = (
        float(analysis["hl_bid"]) - float(hl_current_bid) if hl_current_bid is not None else None
    )
    reval_fields = s2_exit_stage_fields(
        analysis,
        pm_exit_price=pm_current_bid,
        hl_exit_price=hl_current_bid,
        pm_size=pm_current_size,
        hl_size=hl_current_size,
    )
    analysis["reval_exit_net_edge_bps"] = reval_fields.get("net_edge_bps_all_in")
    analysis["reval_realized_net_pnl_all_in"] = reval_fields.get("realized_net_pnl_all_in")
    analysis["reval_exit_vs_hold_usd"] = reval_fields.get("exit_vs_hold_usd")
    analysis["reval_available_size"] = reval_fields.get("available_size")
    analysis["reval_exit_vs_hold_check"] = reval_fields.get("exit_vs_hold_check")
    analysis["scan_to_reval_decay_usd"] = price_decay_usd(
        exit_shares=analysis.get("exit_shares"),
        from_pm_price=analysis.get("scan_pm_bid") or analysis.get("pm_bid"),
        from_hl_price=analysis.get("scan_hl_bid") or analysis.get("hl_bid"),
        to_pm_price=pm_current_bid,
        to_hl_price=hl_current_bid,
    )
    stale = (
        pm_current_bid != analysis["pm_bid"]
        or pm_current_size is None
        or float(pm_current_size) < required_shares
        or hl_current_bid != analysis["hl_bid"]
        or hl_current_size is None
        or float(hl_current_size) < required_shares
    )
    reval_failures = list(reval_fields.get("failures") or [])
    if stale:
        reval_failures.append("quote_or_size_changed_from_scan")
    analysis["reval_candidate_eligible"] = not reval_failures
    analysis["reval_skip_reason"] = "; ".join(str(item) for item in reval_failures) if reval_failures else None
    analysis["reval_reason"] = "fresh" if not reval_failures else "not eligible after revalidation"
    print_s2_exit_revalidation_log(analysis)
    if not reval_failures:
        return True
    if not stale:
        append_event(
            {
                "event": "live_pre_exit_revalidation_failed",
                "market": analysis["market"],
                "failures": reval_failures,
                "revalidation_pm_bid": pm_current_bid,
                "revalidation_hl_bid": hl_current_bid,
            }
        )
        return False
    payload = {
        "event": "live_pre_exit_quote_stale",
        "market": analysis["market"],
        "pm_token": analysis["pm_token"],
        "pm_selected_bid_price": analysis["pm_bid"],
        "pm_selected_bid_size": analysis.get("pm_bid_size"),
        "pm_current_bid_price": pm_current_bid,
        "pm_current_bid_size": pm_current_size,
        "hl_coin": analysis["hl_coin"],
        "hl_selected_bid_price": analysis["hl_bid"],
        "hl_selected_bid_size": analysis.get("hl_bid_size"),
        "hl_current_bid_price": hl_current_bid,
        "hl_current_bid_size": hl_current_size,
        "required_exit_shares": required_shares,
    }
    append_event(payload)
    print("LIVE PRE-EXIT QUOTE STALE")
    print(f"pm_selected_bid_price: {payload['pm_selected_bid_price']}")
    print(f"pm_selected_bid_size: {payload['pm_selected_bid_size']}")
    print(f"pm_current_bid_price: {payload['pm_current_bid_price']}")
    print(f"pm_current_bid_size: {payload['pm_current_bid_size']}")
    print(f"hl_selected_bid_price: {payload['hl_selected_bid_price']}")
    print(f"hl_selected_bid_size: {payload['hl_selected_bid_size']}")
    print(f"hl_current_bid_price: {payload['hl_current_bid_price']}")
    print(f"hl_current_bid_size: {payload['hl_current_bid_size']}")
    print(f"required_exit_shares: {required_shares}")
    return False


def is_transient_network_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "http error 408" in text
        or "request timeout" in text
        or "timeout" in text
        or "temporary network error" in text
    )


def handle_s2_exit_monitor_transient_error(state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    count = int(state.get("s2_exit_transient_error_count") or 0) + 1
    state["s2_exit_transient_error_count"] = count
    state["last_s2_exit_transient_error"] = str(exc)[:500]
    write_state(state)
    append_event(
        {
            "event": "s2_exit_monitor_transient_error",
            "market": state["market"],
            "error": str(exc)[:500],
            "consecutive_count": count,
        }
    )
    print("S2 EXIT MONITOR TRANSIENT ERROR")
    print(f"consecutive_count: {count}")
    print(f"error: {str(exc)[:500]}")
    if count >= 3:
        halt(state, f"S2 exit monitor transient errors reached {count}; manual check required")
        raise HaltedError(state["halt_reason"])
    return {"exit_triggered": False, "transient_error": True, "consecutive_count": count}


def maybe_exit_s2(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    try:
        analysis = analyze_s2_exit(state)
    except Exception as exc:
        if is_hl_api_error(exc):
            log_hl_api_warning(
                context="s2_exit_analysis",
                exc=exc,
                market_key=str(state.get("market")),
                coin=str(state.get("s2", {}).get("hl_coin") or ""),
                blocks_execution=bool(args.live),
            )
            print_and_log_hl_unhealthy_skip(
                context="s2_exit_analysis",
                failures=[f"HL unavailable: reason={hl_error_reason(exc)}"],
                candidate={"action_type": "S2_EXIT", "market": state.get("market")},
            )
            return {"exit_triggered": False, "hl_unhealthy": True, "failures": [str(exc)[:200]]}
        if is_transient_network_error(exc):
            return handle_s2_exit_monitor_transient_error(state, exc)
        halt(state, str(exc))
        raise
    if state.get("s2_exit_transient_error_count"):
        state["s2_exit_transient_error_count"] = 0
        state["last_s2_exit_transient_error"] = None
        write_state(state)
    append_event({"event": "s2_exit_check", "market": state["market"], "dry_run": not args.live, "analysis": analysis})
    print(
        f"S2_EXIT_CHECK market={state['market']} status={analysis['status']} "
        f"exit_allowed={str(analysis['exit_allowed']).lower()} "
        f"all_in_net={analysis['realized_net_pnl_all_in']} "
        f"incremental_exit_net={analysis['incremental_exit_net_pnl']} "
        f"bps={analysis['net_edge_bps_all_in']} "
        f"exit_vs_hold_usd={analysis['exit_vs_hold_usd']}"
    )
    if not analysis["exit_allowed"]:
        return {"exit_triggered": False, "analysis": analysis}
    if not args.live:
        print("DRY-RUN: S2 exit conditions are ready, but no orders placed.")
        return {"exit_triggered": True, "analysis": analysis}
    gate_failures = live_gate_failures(args, str(state["market"]))
    if gate_failures:
        print("LIVE GATE CHECK FAILED:")
        for failure in gate_failures:
            print(f"  - {failure}")
        return {"exit_triggered": False, "analysis": analysis, "failures": gate_failures}
    if not live_exit_quotes_fresh(analysis):
        return {"exit_triggered": False, "analysis": analysis, "quote_stale": True}
    ok, failures = hl_pre_order_health_check(
        market_key=str(state["market"]),
        hl_coin=str(analysis["hl_coin"]),
        context="s2_exit_pre_order_health",
    )
    if not ok:
        print_and_log_hl_unhealthy_skip(
            context="s2_exit_pre_order_health",
            failures=failures,
            candidate={"action_type": "S2_EXIT", "market": state.get("market")},
        )
        return {"exit_triggered": False, "analysis": analysis, "hl_unhealthy": True, "failures": failures}
    transition(state, STATE_EXITING_S2, "S2 early exit conditions passed")
    try:
        execution = execute_s2_exit(state, analysis)
        if not execution_is_confirmed(execution):
            raise HaltedError("S2 exit fill confirmation missing; state update blocked")
        apply_actual_exit_fill_prices_to_analysis(analysis, execution)
        print_s2_exit_fill_log(analysis)
        exit_log = write_json_log(str(state["market"]), "auto_exit_s2", {"analysis": analysis, "execution": execution, "status": "confirmed"})
        state["s2"]["exit_log"] = exit_log
        state["s2"]["status"] = "exited"
        write_state(state)
        transition(state, STATE_S2_EXITED, "S2 exit filled")
        write_active_market(str(state["market"]), state)
    except PartialFillRequiresReview as exc:
        halt(state, "partial_fill_outside_tolerance")
        append_event(
            {
                "event": "partial_fill_requires_review",
                "market": state["market"],
                "confirmation": exc.confirmation,
                "reason": str(exc),
                "requires_manual_review": True,
            }
        )
        print("PARTIAL FILL REQUIRES REVIEW")
        print("exit_reason: partial_fill_outside_tolerance")
        print("requires_manual_review: true")
        return {
            "exit_triggered": False,
            "analysis": analysis,
            "confirmation": exc.confirmation,
            "partial_fill_requires_review": True,
            "requires_manual_review": True,
            "exit_reason": "partial_fill_outside_tolerance",
        }
    except Exception as exc:
        halt(state, str(exc))
        raise
    return {"exit_triggered": True, "analysis": analysis}


def active_state_for_requested(markets: list[str]) -> tuple[str, dict[str, Any]] | None:
    active = read_active_market()
    if not active:
        return None
    active_market = active.get("market")
    if active.get("state") == STATE_HALTED:
        raise HaltedError(f"active market lock is HALTED: {active}")
    if active_market not in SUPPORTED_MARKETS:
        raise HaltedError(f"active market lock invalid: {active}")
    state = load_state(str(active_market))
    if state["state"] == STATE_HALTED:
        raise HaltedError(f"{active_market} is HALTED: {state.get('halt_reason')}")
    if state["state"] in ACTIVE_STATES:
        if active_market not in markets:
            print(f"Active market {active_market} overrides requested scan list.")
        return str(active_market), state
    if state["state"] == STATE_S2_EXITED:
        clear_active_market(str(active_market))
    return None


def require_active_manager_state(markets: list[str]) -> tuple[str, dict[str, Any]]:
    active = read_active_market()
    if not active or active.get("market") is None:
        raise HaltedError("manage-active-only requires auto_active_market.json")
    active_market = str(active.get("market"))
    if active.get("state") != STATE_ACTIVE:
        raise HaltedError(f"manage-active-only requires active state {STATE_ACTIVE}, got {active.get('state')}")
    if active_market not in markets:
        raise HaltedError(f"active market {active_market} is not in requested markets")
    state = load_state(active_market)
    if state["state"] != STATE_ACTIVE:
        raise HaltedError(f"manage-active-only state mismatch: {state['state']}")
    return active_market, state


def maybe_heartbeat(
    active_market: str,
    state: dict[str, Any],
    last_exit_check_status: str | None,
    last_heartbeat_at: float,
) -> float:
    now = time.time()
    if now - last_heartbeat_at < 300:
        return last_heartbeat_at
    transient_count = int(state.get("s2_exit_transient_error_count") or 0)
    print("ACTIVE MANAGER HEARTBEAT")
    print(f"active_market: {active_market}")
    print(f"state: {state['state']}")
    print(f"s2_status: {state.get('s2', {}).get('status')}")
    print(f"last_exit_check_status: {last_exit_check_status}")
    print(f"transient_error_count: {transient_count}")
    append_event(
        {
            "event": "active_manager_heartbeat",
            "market": active_market,
            "state": state["state"],
            "s2_status": state.get("s2", {}).get("status"),
            "last_exit_check_status": last_exit_check_status,
            "transient_error_count": transient_count,
        }
    )
    return now


def print_config(markets: list[str]) -> None:
    print("PM-HL AUTO EXECUTOR")
    print(f"markets: {','.join(markets)}")
    print(f"active_file: {ACTIVE_FILE}")
    print(f"event_log: {event_log_path()}")
    print_threshold_profile()
    print(f"fill_tolerance: {FILL_TOLERANCE:.2f} shares")
    print("rules: direct asks/bids only; no mid; no 1-opposite; no short; no retry/chase/repair/scale")


def print_summary(
    evaluations: dict[str, dict[str, Any]],
    selected: dict[str, Any] | None,
    exit_result: dict[str, Any] | None,
    args: argparse.Namespace,
) -> None:
    print("SUMMARY")
    for market_key, row in evaluations.items():
        print(
            f"market={market_key} best_net_edge_bps={float(row.get('net_edge_bps') or 0):.6f} "
            f"expected_profit={float(row.get('expected_profit') or 0):.6f} "
            f"combined_executable_size={float(row.get('combined_executable_size') or 0):.6f} "
            f"would_trigger_entry={str(bool(row.get('would_trigger_entry'))).lower()}"
        )
    print(f"any_market_would_trigger_entry: {str(any(row.get('would_trigger_entry') for row in evaluations.values())).lower()}")
    print(f"selected_entry_market: {selected['market'] if selected else None}")
    print(f"exit_would_trigger: {str(bool(exit_result and exit_result.get('exit_triggered'))).lower()}")
    print(f"live_run: {'yes' if args.live else 'no'}")
    print(f"orders_placed: {'no' if not args.live else 'see event log'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated PM-HL World Cup S1/S2 executor.")
    parser.add_argument("--market", default=None, help="Single market key, kept for backwards compatibility.")
    parser.add_argument("--markets", default=None, help="Comma-separated market keys to scan.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--pm-auth-check-only", action="store_true")
    parser.add_argument("--pm-token-book-check", default=None)
    parser.add_argument("--pm-hl-position-check", default=None)
    parser.add_argument("--mark-s2-exited-if-balanced", action="store_true")
    parser.add_argument("--mark-s1-active-if-balanced", default=None)
    parser.add_argument("--pnl-review", action="store_true")
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--portfolio-status", action="store_true")
    parser.add_argument("--portfolio-manager", action="store_true")
    parser.add_argument("--live-preflight-only", action="store_true")
    parser.add_argument("--portfolio-live-preview-only", action="store_true")
    parser.add_argument("--require-action", choices=("FULL_ENTRY", "S2_REENTRY", "S2_EXIT"), default=None)
    parser.add_argument("--require-market", default=None)
    parser.add_argument("--min-live-expected-profit", type=float, default=None)
    parser.add_argument("--min-live-net-edge-bps", type=float, default=None)
    parser.add_argument("--manage-active-only", action="store_true")
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--max-actions-per-run", type=int, default=1)
    parser.add_argument("--allowed-actions", default="FULL_ENTRY,S2_REENTRY,S2_EXIT")
    parser.add_argument("--run-until-stop", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--threshold-profile",
        choices=("normal", "validation", "micro_exit_test", "micro_exit_no_hold_test", "positive"),
        default="normal",
    )
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--max-loops", type=int, default=None)
    args = parser.parse_args()
    set_threshold_profile(args.threshold_profile)

    pm.load_env()
    if args.pm_auth_check_only:
        sys.exit(run_pm_auth_check_only())
    if args.pm_token_book_check:
        sys.exit(run_pm_token_book_check(args.pm_token_book_check))

    hl.load_env()
    if args.pm_hl_position_check:
        sys.exit(run_pm_hl_position_check(args.pm_hl_position_check))
    if args.mark_s2_exited_if_balanced:
        sys.exit(run_mark_s2_exited_if_balanced(args.require_market))
    if args.mark_s1_active_if_balanced:
        sys.exit(run_mark_s1_active_if_balanced(args.mark_s1_active_if_balanced))
    if args.pnl_review:
        sys.exit(run_pnl_review(args.from_date, args.to_date))
    if args.portfolio_status:
        sys.exit(run_portfolio_status())

    markets = parse_markets(args)
    if args.live_preflight_only:
        sys.exit(run_live_preflight_only(markets))
    if args.portfolio_live_preview_only:
        sys.exit(run_portfolio_live_preview_only(markets, args))
    if args.portfolio_manager:
        sys.exit(run_portfolio_manager(markets, args))
    print_config(markets)
    print(f"mode: {'live' if args.live else 'dry-run'}")
    if args.live:
        try:
            require_live_preflight(markets)
        except Exception as exc:
            handle_live_preflight_failure(exc)

    loops = 0
    evaluations: dict[str, dict[str, Any]] = {}
    selected: dict[str, Any] | None = None
    exit_result: dict[str, Any] | None = None
    last_exit_check_status: str | None = None
    last_heartbeat_at = time.time()
    try:
        if args.manage_active_only:
            if stop_file_exists():
                print("STOP file detected; active manager exiting gracefully")
                print_summary(evaluations, selected, exit_result, args)
                return
            active_market, state = require_active_manager_state(markets)
            print("ACTIVE POSITION MANAGER")
            print(f"active_market: {active_market}")
            print("entry_scan_enabled: false")
            print("s2_exit_monitor_enabled: true")
        while True:
            loops += 1
            if stop_file_exists():
                if args.manage_active_only:
                    print("STOP file detected; active manager exiting gracefully")
                    break
                raise HaltedError("STOP file exists")

            if args.manage_active_only:
                active_market, state = require_active_manager_state(markets)
                exit_result = maybe_exit_s2(state, args)
                last_exit_check_status = (
                    exit_result.get("analysis", {}).get("status")
                    if isinstance(exit_result.get("analysis"), dict)
                    else "transient_error" if exit_result.get("transient_error") else None
                )
                state = load_state(active_market)
                last_heartbeat_at = maybe_heartbeat(active_market, state, last_exit_check_status, last_heartbeat_at)
                if state["state"] == STATE_S2_EXITED:
                    print("S2_EXITED")
                    print("S1 remains active")
                    print("active manager exiting")
                    break
            else:
                active = active_state_for_requested(markets)
                if active:
                    active_market, state = active
                    print("ACTIVE MARKET MANAGEMENT MODE")
                    print(f"active_market: {active_market}")
                    print("entry_scan_enabled: false")
                    print(f"s2_exit_monitor_enabled: {str(state['state'] == STATE_ACTIVE).lower()}")
                    print(f"ACTIVE_MARKET market={active_market} state={state['state']}")
                    if state["state"] == STATE_ACTIVE:
                        exit_result = maybe_exit_s2(state, args)
                    elif state["state"] == STATE_S2_EXITED:
                        clear_active_market(active_market)
                        print("S2_EXITED: first version exits after S2 exit; no new cycle started.")
                        break
                    else:
                        halt(state, f"unexpected resumable state requires manual handling: {state['state']}")
                        raise HaltedError(f"unexpected active state {state['state']}")
                else:
                    balances = read_balances(dry_run=not args.live)
                    round_evaluations = [evaluate_market(market_key, args, balances) for market_key in markets]
                    evaluations = {row["market"]: row for row in round_evaluations if "market" in row}
                    selected = choose_entry_candidate(round_evaluations)
                    if selected:
                        enter_selected(selected, args)
                        if args.live:
                            break

            if args.max_loops is not None and loops >= args.max_loops:
                break
            time.sleep(args.interval_seconds)
    except Exception as exc:
        append_event({"event": "auto_executor_error", "error": str(exc), "live": args.live})
        print(f"HALTED: {exc}")

    print_summary(evaluations, selected, exit_result, args)


if __name__ == "__main__":
    main()
