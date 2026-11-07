from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.execution_v3_adapters import (  # noqa: E402
    PLACE_ORDER_DISABLED,
    STOP_FILE,
    PolymarketLiveAdapter,
    PredictFunLiveAdapter,
    placement_gate_failures,
)
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


OUTPUT_DIR = PROJECT_ROOT / "data" / "execution_v3"
INPUT_CSV = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun" / "mvp3_a3_winner_price_compare.csv"
REVALIDATION_JSON = OUTPUT_DIR / "usa_one_shot_revalidation.json"
REPORT_JSON = OUTPUT_DIR / "adapter_capability_report.json"
SUMMARY_MD = OUTPUT_DIR / "adapter_capability_summary.md"
TODO_MD = OUTPUT_DIR / "live_todo_checklist.md"
LIVE_ADAPTER_AUDIT_MD = OUTPUT_DIR / "live_adapter_audit.md"

TEAM = "United States"
PM_NO_TOKEN = "45270201343463663182019040935560267543606888663369415494551943549463253748361"
PD_MARKET_ID = "1529"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def load_usa_row() -> dict[str, str]:
    try:
        with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("team") == TEAM and row.get("mapping_status") == "matched":
                    return row
    except FileNotFoundError:
        return {}
    return {}


def verify_pm_no_token(row: dict[str, str], revalidation: dict[str, Any]) -> bool:
    return (
        row.get("team") == TEAM
        and row.get("pm_outcome_name") == "USA"
        and row.get("pm_token_no") == PM_NO_TOKEN
        and str(revalidation.get("pm_no_token") or "") == PM_NO_TOKEN
    )


def verify_pd_yes_market(row: dict[str, str], revalidation: dict[str, Any]) -> bool:
    return (
        row.get("team") == TEAM
        and row.get("pd_outcome_name") == "USA"
        and row.get("pd_market_id") == PD_MARKET_ID
        and str(revalidation.get("pd_market_id") or "") == PD_MARKET_ID
    )


def build_report() -> dict[str, Any]:
    pm.load_env()
    revalidation = read_json(REVALIDATION_JSON)
    usa_row = load_usa_row()
    pd_adapter = PredictFunLiveAdapter()
    pm_adapter = PolymarketLiveAdapter()
    pd_audit = pd_adapter.audit()
    pm_audit = pm_adapter.audit()

    remaining_todo = [
        "Predict.fun live adapter verified/implemented",
        "Polymarket live adapter verified/implemented",
        "Balance and position checks verified",
        "Exact fill / order status / cancel semantics verified",
        "Final one-shot live preflight passes with STOP manually reviewed",
        "Manual tiny live approval",
    ]

    return {
        "generated_at": now_iso(),
        "scope": "Execution v3 Step 1-2 live adapter audit only; no orders submitted",
        "team": "USA / United States",
        "direction": "pd_yes_pm_no",
        "trade": "Buy Predict.fun USA YES 40 + Buy Polymarket USA NO 40",
        "orders_submitted": False,
        "real_order_sent": False,
        "STOP_present": STOP_FILE.exists(),
        "live_blocked_by_stop": STOP_FILE.exists(),
        "PLACE_ORDER_DISABLED": PLACE_ORDER_DISABLED,
        "placement_gate_failures_if_called": placement_gate_failures(
            allow_live=False,
            manual_confirmation="",
        ),
        "HAS_PREDICT_KEY": bool(os.environ.get("PREDICT_API_KEY")),
        "polymarket_credentials_present": not pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")),
        "predict_fun_live_adapter_status": pd_audit.live_adapter_status,
        "polymarket_live_adapter_status": pm_audit.live_adapter_status,
        "predict_fun_place_order_available": "unknown",
        "polymarket_place_order_available": True,
        "order_status_available": {
            "predict_fun": "unknown",
            "polymarket": True,
            "overall_mvp3": "unknown",
        },
        "cancel_available": {
            "predict_fun": "unknown",
            "polymarket": True,
            "overall_mvp3": "unknown",
        },
        "balance_available": {
            "predict_fun": "unknown",
            "polymarket": True,
            "overall_mvp3": "unknown",
        },
        "position_available": {
            "predict_fun": "unknown",
            "polymarket": True,
            "overall_mvp3": "unknown",
        },
        "exact_fill_verification_available": False,
        "partial_fill_behavior_verified": False,
        "pm_usa_no_token_verified": verify_pm_no_token(usa_row, revalidation),
        "pd_usa_yes_market_verified": verify_pd_yes_market(usa_row, revalidation),
        "pm_fee_status": "pm_fee_formula_present_but_market_feeRate_feesEnabled_not_audited_for_mvp3",
        "predict_fun_parameter_format_status": pd_audit.parameter_format_status,
        "polymarket_parameter_format_status": pm_audit.parameter_format_status,
        "predict_fun_tif_status": pd_audit.tif_status,
        "polymarket_tif_status": pm_audit.tif_status,
        "predict_fun_adapter_audit": asdict(pd_audit),
        "polymarket_adapter_audit": asdict(pm_audit),
        "official_capability_notes": {
            "predict_fun": [
                "Beta docs describe authenticated POST /v1/orders and SDK OrderBuilder signing.",
                "Docs mention JWT authentication for personal operations and signed order fields such as tokenId, makerAmount, takerAmount, side, feeRateBps, and signature.",
                "This repo has not wired Predict.fun signing, JWT, live placement, order status, cancel, balance, or position checks.",
            ],
            "polymarket": [
                "Official CLOB docs describe GTC/GTD/FOK/FAK, create/post order, get order, cancel, and balance/allowance capabilities.",
                "Local PM helper supports books, public positions, public USDC balance, and py_clob_client_v2 client construction.",
                "MVP3 PM NO order placement, order status, cancel, feeRate/feesEnabled, and exact-fill verification are not wired or audited.",
            ],
        },
        "latest_revalidation": {
            "run_id": revalidation.get("run_id"),
            "checked_at": revalidation.get("checked_at"),
            "net_edge_pd_yes_pm_no": revalidation.get("net_edge_pd_yes_pm_no"),
            "combined_profit": revalidation.get("combined_net_usd_profit_pd_yes_pm_no"),
            "pass_flag": revalidation.get("pass_flag"),
            "fail_reasons": revalidation.get("fail_reasons") or [],
        },
        "live_readiness": "NOT_READY",
        "remaining_todo_count": len(remaining_todo),
        "remaining_todo_list": remaining_todo,
        "can_run_live_now": "NO",
    }


def write_summary(path: Path, report: dict[str, Any]) -> None:
    remaining_lines = [f"{idx}. {item}" for idx, item in enumerate(report["remaining_todo_list"], start=1)]
    content = f"""# Execution v3 Step 1-2 Adapter Capability Summary

- generated_at: {report["generated_at"]}
- scope: adapter audit only; no live trade; no order placement
- trade: {report["trade"]}
- STOP_present: {str(report["STOP_present"]).lower()}
- orders_submitted: false
- real_order_sent: false

## Predict.fun

- predict_fun_live_adapter_status: {report["predict_fun_live_adapter_status"]}
- predict_fun_place_order_available: {report["predict_fun_place_order_available"]}
- order_status_available: {report["order_status_available"]["predict_fun"]}
- cancel_available: {report["cancel_available"]["predict_fun"]}
- balance_available: {report["balance_available"]["predict_fun"]}
- position_available: {report["position_available"]["predict_fun"]}
- TIF status: {report["predict_fun_tif_status"]}
- parameter format: {report["predict_fun_parameter_format_status"]}
- conclusion: official beta docs show a likely order path, but local MVP3 has not verified or implemented signing/JWT/order lifecycle.

## Polymarket

- polymarket_live_adapter_status: {report["polymarket_live_adapter_status"]}
- polymarket_place_order_available: {str(report["polymarket_place_order_available"]).lower()}
- order_status_available: {str(report["order_status_available"]["polymarket"]).lower()}
- cancel_available: {str(report["cancel_available"]["polymarket"]).lower()}
- balance_available: {str(report["balance_available"]["polymarket"]).lower()}
- position_available: {str(report["position_available"]["polymarket"]).lower()}
- PM USA NO token verified: {str(report["pm_usa_no_token_verified"]).lower()}
- TIF status: {report["polymarket_tif_status"]}
- parameter format: {report["polymarket_parameter_format_status"]}
- conclusion: general CLOB capabilities exist, but MVP3 PM NO place/status/cancel/exact-fill flow is not wired or audited.

## Live Readiness

- exact_fill_verification_available: {str(report["exact_fill_verification_available"]).lower()}
- live_readiness: {report["live_readiness"]}
- can_run_live_now: {report["can_run_live_now"]}
- reason: adapter skeletons are not live-ready; STOP is present; Predict.fun and Polymarket MVP3 exact-fill/order lifecycle checks remain unverified.

## Remaining TODO

{chr(10).join(remaining_lines)}
"""
    path.write_text(content, encoding="utf-8")


def write_live_adapter_audit(path: Path, report: dict[str, Any]) -> None:
    content = f"""# Execution v3 Live Adapter Audit

- generated_at: {report["generated_at"]}
- scope: Step 1-2 adapter audit only; no live trade; no order placement
- trade: {report["trade"]}
- STOP_present: {str(report["STOP_present"]).lower()}
- live_readiness: {report["live_readiness"]}

## Predict.fun Adapter

- predict_fun_live_adapter_status: {report["predict_fun_live_adapter_status"]}
- place limit buy YES: {report["predict_fun_place_order_available"]}
- get order status: {report["order_status_available"]["predict_fun"]}
- cancel order: {report["cancel_available"]["predict_fun"]}
- balance: {report["balance_available"]["predict_fun"]}
- position: {report["position_available"]["predict_fun"]}
- TIF / exact-fill: {report["predict_fun_tif_status"]}; exact fill not verified
- parameter format: {report["predict_fun_parameter_format_status"]}
- conclusion: not_implemented_or_unverified

## Polymarket Adapter

- polymarket_live_adapter_status: {report["polymarket_live_adapter_status"]}
- place limit buy NO: {str(report["polymarket_place_order_available"]).lower()} in official/local reference, not wired for MVP3
- get order status: {str(report["order_status_available"]["polymarket"]).lower()} in official/local reference, not wired for MVP3
- cancel order: {str(report["cancel_available"]["polymarket"]).lower()} in official/local reference, not wired for MVP3
- USDC balance: {str(report["balance_available"]["polymarket"]).lower()} via local helper, not a completed MVP3 balance gate
- NO token position: {str(report["position_available"]["polymarket"]).lower()} via local helper
- PM USA NO token verified: {str(report["pm_usa_no_token_verified"]).lower()}
- feeRate / feesEnabled: {report["pm_fee_status"]}
- TIF / exact-fill: {report["polymarket_tif_status"]}; exact fill not verified for MVP3
- conclusion: not_implemented_or_unverified

## Safety

- PLACE_ORDER_DISABLED: {str(report["PLACE_ORDER_DISABLED"]).lower()}
- placement_gate_failures_if_called: {", ".join(report["placement_gate_failures_if_called"])}
- orders_submitted: false
- real_order_sent: false
- fake_order_id_returned: false
- fake_fill_returned: false
"""
    path.write_text(content, encoding="utf-8")


def write_todo(path: Path, report: dict[str, Any]) -> None:
    remaining_lines = [f"{idx}. {item}" for idx, item in enumerate(report["remaining_todo_list"], start=1)]
    content = f"""# Execution v3 Live TODO

Completed:
- MVP3 scanner 10m done
- USA review signal observed
- Execution v3 dry-run revalidation done

This run:
- Predict.fun adapter audit
- Polymarket adapter audit
- Adapter skeleton / capability check

Remaining before live:
{chr(10).join(remaining_lines)}

Current live_readiness: NOT_READY
"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    write_json(REPORT_JSON, report)
    write_summary(SUMMARY_MD, report)
    write_live_adapter_audit(LIVE_ADAPTER_AUDIT_MD, report)
    write_todo(TODO_MD, report)
    print("Execution v3 adapter capability check completed")
    print(f"predict_fun_live_adapter_status={report['predict_fun_live_adapter_status']}")
    print(f"polymarket_live_adapter_status={report['polymarket_live_adapter_status']}")
    print(f"live_readiness={report['live_readiness']}")
    print(f"remaining_todo_count={report['remaining_todo_count']}")
    print("orders_submitted=false")
    print("real_order_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
