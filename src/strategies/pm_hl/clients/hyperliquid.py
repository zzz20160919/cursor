from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
INFO_URL = "https://api.hyperliquid.xyz/info"
PUBLIC_DEFAULT_MASTER = "0xf318b7c7f3dd6bbf3b651efd3DCb161BB9f47674"
PUBLIC_DEFAULT_ACCOUNT = "0x10c444c580db629bcffab84b73c77ba3b7323074"


def load_env(path: Path | None = None) -> bool:
    env_path = path or PROJECT_ROOT / ".env.local"
    if not env_path.exists():
        return False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = re.split(r"\s+#", value)[0].strip().strip('"').strip("'")
        os.environ[key.strip()] = value
    return True


def missing_env(required: tuple[str, ...]) -> list[str]:
    return [key for key in required if not os.environ.get(key)]


def get_account() -> str:
    return os.environ.get("HL_ACCOUNT", PUBLIC_DEFAULT_ACCOUNT)


def info(payload: dict[str, Any], timeout: int = 8) -> Any:
    req = urllib.request.Request(
        INFO_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "2026-strategy-lab-pm-hl",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def spot_balances(addr: str | None = None) -> list[tuple[str, float]]:
    data = info({"type": "spotClearinghouseState", "user": addr or get_account()})
    return [(row["coin"], float(row["total"])) for row in data.get("balances", [])]


def perp_state(addr: str | None = None) -> tuple[Any, list[Any]]:
    data = info({"type": "clearinghouseState", "user": addr or get_account()})
    return data.get("marginSummary", {}).get("accountValue"), data.get("assetPositions", [])


def open_orders(addr: str | None = None) -> Any:
    return info({"type": "openOrders", "user": addr or get_account()})


def coin_book(coin: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    data = info({"type": "l2Book", "coin": coin})
    levels = data.get("levels", [[], []])
    return (
        [(float(row["px"]), float(row["sz"])) for row in levels[0]],
        [(float(row["px"]), float(row["sz"])) for row in levels[1]],
    )


def yes_book(outcome_id: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    return coin_book(f"#{outcome_id * 10}")


def outcome_balances(addr: str | None = None) -> dict[str, float]:
    balances = {}
    for coin, total in spot_balances(addr):
        if coin.startswith("#") or coin.startswith("@") or coin.startswith("+"):
            balances[coin] = total
    return balances


def build_exchange(account_address: str | None = None) -> tuple[Any, str, str]:
    missing = missing_env(("HL_AGENT_KEY", "HL_ACCOUNT"))
    if missing:
        raise RuntimeError(f"Missing Hyperliquid env vars: {', '.join(missing)}")
    try:
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
    except ImportError as exc:
        raise RuntimeError("Missing dependency: hyperliquid-python-sdk and/or eth_account") from exc

    agent = Account.from_key(os.environ["HL_AGENT_KEY"])
    account = account_address or os.environ["HL_ACCOUNT"]
    exchange = Exchange(
        agent,
        constants.MAINNET_API_URL,
        vault_address=account,
        account_address=account,
    )

    try:
        meta = info({"type": "outcomeMeta"})
        for outcome in meta.get("outcomes", []):
            outcome_id = int(outcome["outcome"])
            for side in (0, 1):
                n = 10 * outcome_id + side
                coin = f"#{n}"
                asset_id = 100_000_000 + n
                exchange.info.coin_to_asset[coin] = asset_id
                exchange.info.name_to_coin[coin] = coin
    except Exception as exc:
        print(f"WARN: outcome map injection failed: {str(exc)[:80]}")

    return exchange, agent.address, account
