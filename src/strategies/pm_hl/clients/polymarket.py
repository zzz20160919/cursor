from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
CLOB_HOST = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
POLYGON_RPCS = (
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
)
PUBLIC_DEFAULT_FUNDER = "0x9d335b39104631B7d5D495c04c3dFB1fB789ebd5"
PUBLIC_DEFAULT_SIGNER = "0xBF59AFAAbe7F723f62b8586f9BcDe1d8642f06b5"


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


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 8) -> Any:
    headers = {"User-Agent": "2026-strategy-lab-pm-hl", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def get_funder() -> str:
    return os.environ.get("PM_FUNDER", PUBLIC_DEFAULT_FUNDER)


def get_signer() -> str:
    return os.environ.get("PM_SIGNER", PUBLIC_DEFAULT_SIGNER)


def get_positions(funder: str | None = None) -> Any:
    return http_json(f"{DATA_API}/positions?user={funder or get_funder()}")


def get_value(funder: str | None = None) -> float:
    data = http_json(f"{DATA_API}/value?user={funder or get_funder()}")
    if isinstance(data, list) and data:
        return float(data[0].get("value") or 0)
    return 0.0


def _gamma_list(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    data = http_json(f"{GAMMA_API}{path}?{query}")
    return data if isinstance(data, list) else []


def gamma_event_by_slug(slug: str) -> dict[str, Any] | None:
    events = _gamma_list("/events", {"slug": slug})
    return events[0] if events else None


def gamma_event_by_id(event_id: int | str) -> dict[str, Any] | None:
    events = _gamma_list("/events", {"id": str(event_id)})
    return events[0] if events else None


def gamma_market_by_slug(slug: str) -> dict[str, Any] | None:
    markets = _gamma_list("/markets", {"slug": slug})
    return markets[0] if markets else None


def gamma_market_by_id(market_id: int | str) -> dict[str, Any] | None:
    markets = _gamma_list("/markets", {"id": str(market_id)})
    return markets[0] if markets else None


def get_usdc_balance(addr: str) -> dict[str, float]:
    tokens = {
        "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359",
    }
    suffix = addr.lower().replace("0x", "").rjust(64, "0")
    balances: dict[str, float] = {}
    for name, token in tokens.items():
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": token, "data": "0x70a08231" + suffix}, "latest"],
        }
        for rpc in POLYGON_RPCS:
            try:
                result = http_json(rpc, payload=payload)
                raw = result.get("result", "0x0")
                if raw and raw != "0x":
                    balances[name] = int(raw, 16) / 1e6
                    break
            except Exception:
                continue
    return balances


def book(token_id: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]], dict[str, Any]]:
    data = http_json(f"{CLOB_HOST}/book?token_id={token_id}")
    bids = sorted(
        ((float(row["price"]), float(row["size"])) for row in data.get("bids", [])),
        reverse=True,
    )
    asks = sorted((float(row["price"]), float(row["size"])) for row in data.get("asks", []))
    return bids, asks, data


def top(token_id: str) -> tuple[tuple[float, float], tuple[float, float], str, bool]:
    bids, asks, raw = book(token_id)
    return (
        bids[0] if bids else (0.0, 0.0),
        asks[0] if asks else (1.0, 0.0),
        str(raw.get("tick_size", "0.001")),
        bool(raw.get("neg_risk", False)),
    )


def positions_size(funder: str, token_id: str) -> float:
    positions = get_positions(funder)
    for position in positions if isinstance(positions, list) else []:
        if str(position.get("asset")) == token_id:
            return float(position.get("size", 0) or 0)
    return 0.0


def build_client() -> Any:
    missing = missing_env(("PM_FUNDER", "PM_PRIVATE_KEY"))
    if missing:
        raise RuntimeError(f"Missing Polymarket env vars: {', '.join(missing)}")
    try:
        from py_clob_client_v2 import ClobClient, SignatureTypeV2
    except ImportError as exc:
        raise RuntimeError("Missing dependency: py_clob_client_v2") from exc

    private_key = os.environ["PM_PRIVATE_KEY"]
    signature_type = int(os.environ.get("PM_SIGNATURE_TYPE", "2"))
    sig_map = {
        1: SignatureTypeV2.POLY_PROXY,
        2: SignatureTypeV2.POLY_GNOSIS_SAFE,
        3: SignatureTypeV2.POLY_1271,
    }
    sig = sig_map.get(signature_type, SignatureTypeV2.POLY_GNOSIS_SAFE)
    funder = os.environ["PM_FUNDER"]
    client = ClobClient(
        host=CLOB_HOST,
        chain_id=137,
        key=private_key,
        signature_type=sig,
        funder=funder,
    )
    creds = client.create_or_derive_api_key()
    return ClobClient(
        host=CLOB_HOST,
        chain_id=137,
        key=private_key,
        creds=creds,
        signature_type=sig,
        funder=funder,
    )


def get_cash(client: Any | None = None) -> tuple[float | None, Any]:
    try:
        from py_clob_client_v2 import AssetType, BalanceAllowanceParams
    except ImportError as exc:
        raise RuntimeError("Missing dependency: py_clob_client_v2") from exc

    active_client = client or build_client()
    raw = active_client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    balance = raw.get("balance") if isinstance(raw, dict) else getattr(raw, "balance", None)
    try:
        value = float(balance)
        return (value / 1e6 if value > 1000 else value), raw
    except (TypeError, ValueError):
        return None, raw
