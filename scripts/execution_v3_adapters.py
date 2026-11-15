from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


OUTPUT_DIR = PROJECT_ROOT / "data" / "execution_v3"
STOP_FILE = OUTPUT_DIR / "STOP"
ROOT_STOP_FILE = PROJECT_ROOT / "STOP"
EXPECTED_CONFIRMATION = "EXECUTE MVP3 USA PD YES PM NO 40"

# Conservative default: this module is an interface skeleton, not a live adapter.
PLACE_ORDER_DISABLED = True


class AdapterGateError(RuntimeError):
    """Raised before any live placement path can reach venue code."""


@dataclass(frozen=True)
class AdapterAudit:
    name: str
    live_adapter_status: str
    place_order_available: str
    balance_reader_status: str
    position_reader_status: str
    order_status_reader_status: str
    cancel_status: str
    exact_fill_status: str
    tif_status: str
    parameter_format_status: str
    notes: list[str]


def bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def placement_gate_failures(*, allow_live: bool, manual_confirmation: str) -> list[str]:
    failures: list[str] = []
    if PLACE_ORDER_DISABLED:
        failures.append("PLACE_ORDER_DISABLED_true")
    if ROOT_STOP_FILE.exists():
        failures.append("root_STOP_present")
    if STOP_FILE.exists():
        failures.append("execution_v3_STOP_present")
    if not allow_live:
        failures.append("explicit_live_flag_missing")
    if manual_confirmation != EXPECTED_CONFIRMATION:
        failures.append("manual_confirmation_missing_or_mismatch")
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED_not_true")
    if bool_env("DRY_RUN", True):
        failures.append("DRY_RUN_not_false")
    return failures


def raise_if_placement_blocked(*, allow_live: bool, manual_confirmation: str) -> None:
    failures = placement_gate_failures(
        allow_live=allow_live,
        manual_confirmation=manual_confirmation,
    )
    if failures:
        raise AdapterGateError(";".join(failures))


class PredictFunLiveAdapter:
    """Predict.fun live adapter skeleton. No live methods are implemented."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        allow_live: bool = False,
        manual_confirmation: str = "",
    ) -> None:
        self.api_key = api_key or os.environ.get("PREDICT_API_KEY")
        self.allow_live = allow_live
        self.manual_confirmation = manual_confirmation

    def audit(self) -> AdapterAudit:
        return AdapterAudit(
            name="predict.fun",
            live_adapter_status="not_implemented_or_unverified",
            place_order_available="true_in_beta_docs_not_wired_locally",
            balance_reader_status="not_implemented_or_unverified",
            position_reader_status="not_implemented_or_unverified",
            order_status_reader_status="not_implemented_or_unverified",
            cancel_status="not_implemented_or_unverified",
            exact_fill_status="not_implemented_or_unverified",
            tif_status="limit_strategy_documented_fok_market_only_needs_verification",
            parameter_format_status="signed_order_token_amount_fields_documented_not_wired",
            notes=[
                "Local MVP3 code only fetches Predict.fun market/orderbook data.",
                "Official beta docs describe POST /v1/orders with JWT authentication and signed order fields, but this repo does not build or sign those orders.",
                "Live signing, order placement, order status, cancel, balance, and position semantics are not wired or audited.",
                "No Predict.fun live order API is called by this skeleton.",
            ],
        )

    def get_balance(self) -> Any:
        raise NotImplementedError("predict_fun_balance_not_implemented_or_unverified")

    def get_position(self, market_id: str, outcome_id: str) -> Any:
        raise NotImplementedError("predict_fun_position_not_implemented_or_unverified")

    def place_limit_buy_yes(
        self,
        market_id: str,
        outcome_id: str,
        price: float,
        size: float,
        tif: str,
    ) -> Any:
        if not market_id or not outcome_id or price <= 0 or size <= 0:
            raise ValueError("invalid_predict_fun_order_parameters")
        raise_if_placement_blocked(
            allow_live=self.allow_live,
            manual_confirmation=self.manual_confirmation,
        )
        raise NotImplementedError("predict_fun_live_order_adapter_not_implemented")

    def get_order_status(self, order_id: str) -> Any:
        raise NotImplementedError("predict_fun_order_status_not_implemented_or_unverified")

    def cancel_order(self, order_id: str) -> Any:
        raise NotImplementedError("predict_fun_cancel_not_implemented_or_unverified")


class PolymarketLiveAdapter:
    """Polymarket MVP3 adapter skeleton with read-only helpers only."""

    def __init__(
        self,
        *,
        allow_live: bool = False,
        manual_confirmation: str = "",
    ) -> None:
        self.allow_live = allow_live
        self.manual_confirmation = manual_confirmation

    def audit(self) -> AdapterAudit:
        return AdapterAudit(
            name="polymarket",
            live_adapter_status="not_implemented_or_unverified",
            place_order_available="true_in_official_clob_sdk_not_wired_for_mvp3",
            balance_reader_status="read_only_public_helper_available",
            position_reader_status="read_only_public_helper_available",
            order_status_reader_status="not_implemented_or_unverified_for_mvp3",
            cancel_status="not_implemented_or_unverified_for_mvp3",
            exact_fill_status="not_implemented_or_unverified_for_mvp3",
            tif_status="GTC_GTD_FOK_FAK_documented_but_mvp3_exact_fill_unverified",
            parameter_format_status="token_id_price_size_side_documented_pm_no_flow_unwired",
            notes=[
                "Polymarket CLOB/SDK supports live orders, order queries, and cancel in general, but MVP3 PM NO exact-fill flow is not wired.",
                "This adapter exposes no live placement path and does not submit signed orders.",
                "Read-only balance/position checks use existing public helpers only.",
            ],
        )

    def get_balance(self) -> dict[str, float]:
        funder = os.environ.get("PM_FUNDER")
        if not funder:
            raise RuntimeError("missing_PM_FUNDER")
        return pm.get_usdc_balance(funder)

    def get_position(self, token_id: str) -> float:
        funder = os.environ.get("PM_FUNDER")
        if not funder:
            raise RuntimeError("missing_PM_FUNDER")
        return pm.positions_size(funder, token_id)

    def place_limit_buy_no(self, token_id: str, price: float, size: float, tif: str) -> Any:
        if not token_id or price <= 0 or size <= 0:
            raise ValueError("invalid_polymarket_order_parameters")
        if tif.upper() not in {"FOK", "FAK", "IOC", "GTC", "GTD"}:
            raise ValueError(f"unsupported_polymarket_tif:{tif}")
        raise_if_placement_blocked(
            allow_live=self.allow_live,
            manual_confirmation=self.manual_confirmation,
        )
        raise NotImplementedError("polymarket_mvp3_live_order_adapter_not_implemented")

    def get_order_status(self, order_id: str) -> Any:
        raise NotImplementedError("polymarket_mvp3_order_status_not_implemented_or_unverified")

    def cancel_order(self, order_id: str) -> Any:
        raise NotImplementedError("polymarket_mvp3_cancel_not_implemented_or_unverified")
