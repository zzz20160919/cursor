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
REVALIDATION_JSON = OUTPUT_DIR / "usa_one_shot_revalidation.json"
INPUT_CSV = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun" / "mvp3_a3_winner_price_compare.csv"
AUDIT_MD = OUTPUT_DIR / "live_adapter_audit.md"
PREFLIGHT_JSON = OUTPUT_DIR / "live_preflight_report.json"
PREFLIGHT_SUMMARY_MD = OUTPUT_DIR / "live_preflight_summary.md"
TODO_MD = OUTPUT_DIR / "live_todo_checklist.md"

TEAM = "United States"
TARGET_DIRECTION = "pd_yes_pm_no"
COMBINED_SIZE_SHARES = 40.0
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


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_usa_row() -> dict[str, str]:
    try:
        with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("team") == TEAM and row.get("mapping_status") == "matched":
                    return row
    except FileNotFoundError:
        return {}
    return {}


def quote_has_required_fields(revalidation: dict[str, Any]) -> bool:
    pd_yes = revalidation.get("pd_yes")
    pm_no = revalidation.get("pm_no")
    return (
        isinstance(pd_yes, dict)
        and isinstance(pm_no, dict)
        and safe_float(pd_yes.get("ask")) is not None
        and safe_float(pd_yes.get("ask_size")) is not None
        and safe_float(pm_no.get("ask")) is not None
        and safe_float(pm_no.get("ask_size")) is not None
    )


def depth_ok(revalidation: dict[str, Any]) -> bool:
    pd_yes = revalidation.get("pd_yes") if isinstance(revalidation.get("pd_yes"), dict) else {}
    pm_no = revalidation.get("pm_no") if isinstance(revalidation.get("pm_no"), dict) else {}
    pd_depth = safe_float(pd_yes.get("ask_size"))
    pm_depth = safe_float(pm_no.get("ask_size"))
    return (
        pd_depth is not None
        and pm_depth is not None
        and pd_depth >= COMBINED_SIZE_SHARES
        and pm_depth >= COMBINED_SIZE_SHARES
    )


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


def read_pm_balance_and_position(pm_adapter: PolymarketLiveAdapter, token_id: str) -> dict[str, Any]:
    status: dict[str, Any] = {
        "pm_balance_readable": False,
        "pm_position_readable": False,
        "pm_balance_error": "",
        "pm_position_error": "",
    }
    try:
        balances = pm_adapter.get_balance()
        status["pm_balance_readable"] = isinstance(balances, dict) and bool(balances)
    except Exception as exc:
        status["pm_balance_error"] = str(exc)[:180]
    try:
        position = pm_adapter.get_position(token_id)
        status["pm_position_readable"] = isinstance(position, float | int)
    except Exception as exc:
        status["pm_position_error"] = str(exc)[:180]
    return status


def build_report() -> dict[str, Any]:
    pm.load_env()
    revalidation = read_json(REVALIDATION_JSON)
    usa_row = load_usa_row()
    pd_adapter = PredictFunLiveAdapter()
    pm_adapter = PolymarketLiveAdapter()
    pd_audit = pd_adapter.audit()
    pm_audit = pm_adapter.audit()

    pm_read_status = read_pm_balance_and_position(pm_adapter, PM_NO_TOKEN)
    pd_balance_readable = False
    pd_position_readable = False
    latest_quote_readable = quote_has_required_fields(revalidation)
    current_depth_ok = depth_ok(revalidation)
    net_edge = safe_float(revalidation.get("net_edge_pd_yes_pm_no"))
    combined_profit = safe_float(revalidation.get("combined_net_usd_profit_pd_yes_pm_no"))
    edge_profit_depth_passed = (
        latest_quote_readable
        and current_depth_ok
        and net_edge is not None
        and combined_profit is not None
        and net_edge > 0
        and combined_profit > 0
    )
    live_blockers = [
        "execution_v3_STOP_present" if STOP_FILE.exists() else "",
        "predict_fun_live_adapter_not_implemented_or_unverified",
        "polymarket_mvp3_live_adapter_not_implemented_or_unverified",
        "balance_check_not_fully_verified",
        "position_check_not_fully_verified",
        "exact_fill_verification_not_available",
    ]
    live_blockers = [blocker for blocker in live_blockers if blocker]

    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "scope": "MVP3 Execution v3 USA live preflight only; no orders submitted",
        "team": "USA / United States",
        "direction": TARGET_DIRECTION,
        "trade": "Buy Predict.fun USA YES 40 + Buy Polymarket USA NO 40",
        "order_sequence": [
            "PD USA YES 40 first",
            "PM USA NO 40 only after PD exact full fill",
        ],
        "HAS_PREDICT_KEY": bool(os.environ.get("PREDICT_API_KEY")),
        "polymarket_credentials_present": not pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")),
        "STOP_present": STOP_FILE.exists(),
        "live_blocked_by_stop": STOP_FILE.exists(),
        "PLACE_ORDER_DISABLED": PLACE_ORDER_DISABLED,
        "placement_gate_failures_if_called": placement_gate_failures(
            allow_live=False,
            manual_confirmation="",
        ),
        "predict_fun_live_adapter_status": pd_audit.live_adapter_status,
        "polymarket_live_adapter_status": pm_audit.live_adapter_status,
        "predict_fun_adapter_audit": asdict(pd_audit),
        "polymarket_adapter_audit": asdict(pm_audit),
        "balance_readable": bool(pm_read_status["pm_balance_readable"] and pd_balance_readable),
        "position_readable": bool(pm_read_status["pm_position_readable"] and pd_position_readable),
        "pm_balance_readable": pm_read_status["pm_balance_readable"],
        "pm_position_readable": pm_read_status["pm_position_readable"],
        "pd_balance_readable": pd_balance_readable,
        "pd_position_readable": pd_position_readable,
        "balance_check_status": "not_fully_verified",
        "position_check_status": "not_fully_verified",
        "pm_balance_error": pm_read_status["pm_balance_error"],
        "pm_position_error": pm_read_status["pm_position_error"],
        "PM_USA_NO_token_verified": verify_pm_no_token(usa_row, revalidation),
        "PD_USA_YES_market_outcome_verified": verify_pd_yes_market(usa_row, revalidation),
        "latest_fresh_quote_readable": latest_quote_readable,
        "latest_fresh_quote_source": str(REVALIDATION_JSON),
        "run_id": revalidation.get("run_id"),
        "checked_at": revalidation.get("checked_at"),
        "fresh_revalidation_passed": bool(revalidation.get("pass_flag")),
        "fresh_revalidation_fail_reasons": revalidation.get("fail_reasons") or [],
        "net_edge": net_edge,
        "combined_profit": combined_profit,
        "depth_ok": current_depth_ok,
        "edge_profit_depth_passed": edge_profit_depth_passed,
        "exact_fill_verification_available": False,
        "order_status_semantics_verified": False,
        "cancel_semantics_verified": False,
        "fok_ioc_limit_semantics_verified_for_mvp3": False,
        "orders_submitted": False,
        "real_order_sent": False,
        "live_readiness": "NOT_READY",
        "live_blockers": live_blockers,
        "remaining_todo_count": 5,
    }
    return report


def write_audit(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Execution v3 Live Adapter Audit",
        "",
        f"- generated_at: {report['generated_at']}",
        "- scope: adapter audit and preflight only; no live trade; no order placement",
        "- trade: Buy Predict.fun USA YES 40 + Buy Polymarket USA NO 40",
        f"- STOP_present: {str(report['STOP_present']).lower()}",
        f"- live_blocked_by_stop: {str(report['live_blocked_by_stop']).lower()}",
        f"- live_readiness: {report['live_readiness']}",
        "",
        "## Predict.fun",
        "",
        f"- predict_fun_live_adapter_status: {report['predict_fun_live_adapter_status']}",
        "- place limit buy YES: not implemented or unverified in local MVP3 code",
        "- get order status: not implemented or unverified",
        "- cancel order: not implemented or unverified",
        "- get balance: not implemented or unverified",
        "- get position: not implemented or unverified",
        "- FOK / IOC / GTC / limit semantics: not verified for MVP3",
        "- exact fill / partial fill semantics: not verified for MVP3",
        "- fees and order parameter format: not verified enough for live execution",
        "- conclusion: predict_fun_live_adapter_status = not_implemented_or_unverified",
        "",
        "## Polymarket",
        "",
        f"- polymarket_live_adapter_status: {report['polymarket_live_adapter_status']}",
        "- public docs indicate CLOB supports order placement, order queries, cancel, and GTC/GTD/FOK/FAK order types.",
        "- local PM helpers can fetch books and public balance/position data.",
        "- MVP3 PM NO place/status/cancel/exact-fill flow is not wired or audited.",
        f"- PM USA NO token verified: {str(report['PM_USA_NO_token_verified']).lower()}",
        "- conclusion: polymarket_live_adapter_status = not_implemented_or_unverified",
        "",
        "## Preflight Findings",
        "",
        f"- HAS_PREDICT_KEY: {str(report['HAS_PREDICT_KEY']).lower()}",
        f"- polymarket_credentials_present: {str(report['polymarket_credentials_present']).lower()}",
        f"- balance_readable: {str(report['balance_readable']).lower()}",
        f"- position_readable: {str(report['position_readable']).lower()}",
        f"- latest_fresh_quote_readable: {str(report['latest_fresh_quote_readable']).lower()}",
        f"- net_edge: {report['net_edge']}",
        f"- combined_profit: {report['combined_profit']}",
        f"- depth_ok: {str(report['depth_ok']).lower()}",
        f"- exact_fill_verification_available: {str(report['exact_fill_verification_available']).lower()}",
        f"- orders_submitted: {str(report['orders_submitted']).lower()}",
        f"- real_order_sent: {str(report['real_order_sent']).lower()}",
        "",
        "## Live Readiness",
        "",
        "- live_readiness: NOT_READY",
        "- reason: STOP exists; Predict.fun live adapter is not implemented or verified; Polymarket MVP3 live adapter is not implemented or verified; balance, position, order status, cancel, and exact-fill checks are not fully audited.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(path: Path, report: dict[str, Any]) -> None:
    blockers = ", ".join(report["live_blockers"]) if report["live_blockers"] else "none"
    lines = [
        "# Execution v3 Live Preflight Summary",
        "",
        f"- generated_at: {report['generated_at']}",
        "- mode: preflight_only",
        "- orders_submitted: false",
        "- real_order_sent: false",
        f"- live_blocked_by_stop: {str(report['live_blocked_by_stop']).lower()}",
        f"- predict_fun_live_adapter_status: {report['predict_fun_live_adapter_status']}",
        f"- polymarket_live_adapter_status: {report['polymarket_live_adapter_status']}",
        f"- balance_check_status: {report['balance_check_status']}",
        f"- position_check_status: {report['position_check_status']}",
        f"- exact_fill_verification_available: {str(report['exact_fill_verification_available']).lower()}",
        f"- latest_USA_net_edge: {report['net_edge']}",
        f"- latest_USA_combined_profit: {report['combined_profit']}",
        f"- depth_ok: {str(report['depth_ok']).lower()}",
        f"- live_readiness: {report['live_readiness']}",
        f"- live_blockers: {blockers}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_todo(path: Path) -> None:
    content = """# Execution v3 Live TODO

Completed:
- scanner 10m done
- USA review signal observed
- dry-run revalidation done

Remaining before live:
1. Predict.fun live adapter verified/implemented
2. Polymarket live adapter verified/implemented
3. Balance and position checks verified
4. Exact fill / order status / cancel semantics verified
5. Final one-shot live preflight passes with STOP manually reviewed

Current live_readiness: NOT_READY
"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    write_json(PREFLIGHT_JSON, report)
    write_audit(AUDIT_MD, report)
    write_summary(PREFLIGHT_SUMMARY_MD, report)
    write_todo(TODO_MD)
    print("Execution v3 live preflight completed")
    print(f"live_readiness={report['live_readiness']}")
    print(f"live_blocked_by_stop={str(report['live_blocked_by_stop']).lower()}")
    print(f"predict_fun_live_adapter_status={report['predict_fun_live_adapter_status']}")
    print(f"polymarket_live_adapter_status={report['polymarket_live_adapter_status']}")
    print(f"net_edge={report['net_edge']}")
    print(f"combined_profit={report['combined_profit']}")
    print("orders_submitted=false")
    print("real_order_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
