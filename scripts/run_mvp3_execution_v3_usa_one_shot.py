from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


TEAM = "United States"
PM_OUTCOME_NAME = "USA"
PD_OUTCOME_NAME = "USA"
TARGET_DIRECTION = "pd_yes_pm_no"
S1_SIZE_SHARES = 20.0
S2_SIZE_SHARES = 20.0
COMBINED_SIZE_SHARES = S1_SIZE_SHARES + S2_SIZE_SHARES
EDGE_THRESHOLD = 0.0005
MIN_S1_PROFIT_USD = 0.01
MIN_S2_PROFIT_USD = 0.01
PM_FEE_RATE = 0.03
PD_FEE_RATE = 0.02
PD_FEE_DISCOUNT_MULTIPLIER = 1.0
CONFIRMATION_TEXT = "EXECUTE MVP3 USA PD YES PM NO 40"

INPUT_CSV = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun" / "mvp3_a3_winner_price_compare.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "execution_v3"
LOG_DIR = PROJECT_ROOT / "logs" / "execution_v3"
ROOT_STOP_FILE = PROJECT_ROOT / "STOP"
STOP_FILE = OUTPUT_DIR / "STOP"
REVALIDATION_JSON = OUTPUT_DIR / "usa_one_shot_revalidation.json"
ORDER_INTENTS_CSV = OUTPUT_DIR / "usa_one_shot_order_intents.csv"
RISK_EVENTS_CSV = OUTPUT_DIR / "usa_one_shot_risk_events.csv"
RISK_REPORT_MD = OUTPUT_DIR / "usa_one_shot_risk_report.md"
SUMMARY_MD = OUTPUT_DIR / "usa_one_shot_summary.md"

PD_API_BASE_ENV = "PREDICT_API_BASE"
PD_API_KEY_ENV = "PREDICT_API_KEY"
PD_DEFAULT_API_BASE = "https://api.predict.fun"

ORDER_INTENT_FIELDS = [
    "run_id",
    "created_at",
    "team",
    "direction",
    "leg",
    "sequence",
    "venue",
    "side",
    "instrument",
    "order_type",
    "time_in_force",
    "shares",
    "limit_price",
    "required_depth",
    "fresh_depth",
    "exact_fill_required",
    "status",
    "notes",
]

RISK_EVENT_FIELDS = [
    "run_id",
    "event_at",
    "severity",
    "event_type",
    "message",
]


@dataclass(frozen=True)
class LegQuote:
    bid: float | None
    bid_size: float | None
    ask: float | None
    ask_size: float | None
    raw: dict[str, Any]
    quote_age_sec: float | None


@dataclass(frozen=True)
class Revalidation:
    run_id: str
    checked_at: str
    source_row: dict[str, str]
    pm_yes: LegQuote
    pm_no: LegQuote
    pd_yes: LegQuote
    pd_no: LegQuote
    gross_edge_a: float
    net_edge_a: float
    gross_edge_b: float
    net_edge_b: float
    best_direction: str
    fail_reasons: list[str]
    warnings: list[str]

    @property
    def pass_flag(self) -> bool:
        return not self.fail_reasons


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return "mvp3_exec_v3_usa_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def pd_api_base() -> str:
    return os.environ.get(PD_API_BASE_ENV, PD_DEFAULT_API_BASE).rstrip("/")


def pd_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "2026-strategy-lab-mvp3-execution-v3-usa-one-shot",
    }
    api_key = os.environ.get(PD_API_KEY_ENV)
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def risk_event(run: str, severity: str, event_type: str, message: str) -> dict[str, Any]:
    return {
        "run_id": run,
        "event_at": now_iso(),
        "severity": severity,
        "event_type": event_type,
        "message": message,
    }


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_level(levels: Any, *, reverse: bool) -> tuple[float | None, float | None]:
    parsed: list[tuple[float, float]] = []
    for level in levels if isinstance(levels, list) else []:
        if isinstance(level, dict):
            price = safe_float(level.get("price"))
            size = safe_float(level.get("size") or level.get("quantity"))
        elif isinstance(level, list | tuple) and len(level) >= 2:
            price = safe_float(level[0])
            size = safe_float(level[1])
        else:
            continue
        if price is not None and size is not None:
            parsed.append((price, size))
    if not parsed:
        return None, None
    parsed.sort(key=lambda item: item[0], reverse=reverse)
    return parsed[0]


def complement(price: float | None, decimal_precision: int | None) -> float | None:
    if price is None:
        return None
    value = 1.0 - price
    return round(value, decimal_precision) if decimal_precision is not None else value


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_timestamp(float(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def quote_age(raw: dict[str, Any], fetched_at: datetime) -> float | None:
    candidates = [
        raw.get("updateTimestampMs"),
        raw.get("updatedTimestampMs"),
        raw.get("timestampMs"),
        raw.get("updatedAt"),
        raw.get("timestamp"),
        raw.get("createdAt"),
    ]
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    candidates.extend(
        [
            data.get("updateTimestampMs"),
            data.get("updatedTimestampMs"),
            data.get("timestampMs"),
            data.get("updatedAt"),
            data.get("timestamp"),
        ]
    )
    for candidate in candidates:
        parsed = parse_timestamp(candidate)
        if parsed is not None:
            return max(0.0, (fetched_at - parsed).total_seconds())
    return None


def pm_taker_fee_per_share(price: float) -> float:
    return PM_FEE_RATE * price * (1.0 - price)


def pd_taker_fee_per_share(price: float) -> float:
    return PD_FEE_RATE * PD_FEE_DISCOUNT_MULTIPLIER * min(price, 1.0 - price)


def load_usa_source_row() -> dict[str, str]:
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("team") == TEAM and row.get("mapping_status") == "matched":
                return row
    raise RuntimeError(f"USA matched row not found in {INPUT_CSV}")


def fetch_pm_leg(token_id: str) -> LegQuote:
    fetched_at = datetime.now(timezone.utc)
    bids, asks, raw = pm.book(token_id)
    bid = bids[0] if bids else (None, None)
    ask = asks[0] if asks else (None, None)
    age = quote_age(raw, fetched_at)
    # PM CLOB book responses often do not include exchange update timestamps.
    if age is None:
        age = 0.0
    return LegQuote(
        bid=safe_float(bid[0]),
        bid_size=safe_float(bid[1]),
        ask=safe_float(ask[0]),
        ask_size=safe_float(ask[1]),
        raw=raw,
        quote_age_sec=age,
    )


def fetch_pd_yes_no(pd_market_id: str) -> tuple[LegQuote, LegQuote]:
    if pd_api_base() == PD_DEFAULT_API_BASE and not os.environ.get(PD_API_KEY_ENV):
        raise RuntimeError(f"missing_{PD_API_KEY_ENV}_for_predict_fun_mainnet")
    url = f"{pd_api_base()}/v1/markets/{urllib.parse.quote(pd_market_id)}/orderbook"
    fetched_at = datetime.now(timezone.utc)
    raw = http_json(url, headers=pd_headers())
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("predict_fun_orderbook_missing_data_object")

    yes_bid, yes_bid_size = first_level(data.get("bids"), reverse=True)
    yes_ask, yes_ask_size = first_level(data.get("asks"), reverse=False)
    precision_raw = data.get("decimalPrecision") or raw.get("decimalPrecision")
    try:
        precision = int(precision_raw) if precision_raw is not None else 2
    except (TypeError, ValueError):
        precision = 2
    age = quote_age(raw, fetched_at)

    yes = LegQuote(
        bid=yes_bid,
        bid_size=yes_bid_size,
        ask=yes_ask,
        ask_size=yes_ask_size,
        raw=raw,
        quote_age_sec=age,
    )
    no = LegQuote(
        bid=complement(yes_ask, precision),
        bid_size=yes_ask_size,
        ask=complement(yes_bid, precision),
        ask_size=yes_bid_size,
        raw={"source": "derived_from_yes_book", "yes_book_raw": raw},
        quote_age_sec=age,
    )
    return yes, no


def calculate_direction_edges(
    pm_yes: LegQuote,
    pm_no: LegQuote,
    pd_yes: LegQuote,
    pd_no: LegQuote,
) -> tuple[float, float, float, float]:
    if pm_yes.ask is None or pm_no.ask is None or pd_yes.ask is None or pd_no.ask is None:
        raise RuntimeError("missing_top_of_book_ask")
    gross_a = 1.0 - pm_yes.ask - pd_no.ask
    net_a = gross_a - pm_taker_fee_per_share(pm_yes.ask) - pd_taker_fee_per_share(pd_no.ask)
    gross_b = 1.0 - pd_yes.ask - pm_no.ask
    net_b = gross_b - pd_taker_fee_per_share(pd_yes.ask) - pm_taker_fee_per_share(pm_no.ask)
    return gross_a, net_a, gross_b, net_b


def revalidate(run: str, max_quote_age_sec: float) -> Revalidation:
    source_row = load_usa_source_row()
    warnings: list[str] = []
    fail_reasons: list[str] = []

    if ROOT_STOP_FILE.exists():
        fail_reasons.append("root_stop_file_present")
    if STOP_FILE.exists():
        fail_reasons.append("execution_v3_stop_file_present")
    if source_row.get("team") != TEAM or source_row.get("mapping_status") != "matched":
        fail_reasons.append("usa_source_row_not_matched")
    if source_row.get("pm_outcome_name") != PM_OUTCOME_NAME:
        fail_reasons.append("pm_outcome_name_not_usa")
    if source_row.get("pd_outcome_name") != PD_OUTCOME_NAME:
        fail_reasons.append("pd_outcome_name_not_usa")

    pm_yes = fetch_pm_leg(source_row["pm_token_yes"])
    pm_no = fetch_pm_leg(source_row["pm_token_no"])
    pd_yes, pd_no = fetch_pd_yes_no(source_row["pd_market_id"])
    gross_a, net_a, gross_b, net_b = calculate_direction_edges(pm_yes, pm_no, pd_yes, pd_no)
    best_direction = "pm_yes_pd_no" if net_a >= net_b else "pd_yes_pm_no"

    if best_direction != TARGET_DIRECTION:
        fail_reasons.append(f"best_direction_changed:{best_direction}")
    if net_b < EDGE_THRESHOLD:
        fail_reasons.append("target_direction_edge_below_threshold")
    if net_b * S1_SIZE_SHARES < MIN_S1_PROFIT_USD:
        fail_reasons.append("s1_profit_below_min")
    if net_b * S2_SIZE_SHARES < MIN_S2_PROFIT_USD:
        fail_reasons.append("s2_profit_below_min")
    if pd_yes.ask is None or pd_yes.ask_size is None:
        fail_reasons.append("pd_yes_ask_missing")
    elif pd_yes.ask_size < COMBINED_SIZE_SHARES:
        fail_reasons.append("pd_yes_depth_below_40")
    if pm_no.ask is None or pm_no.ask_size is None:
        fail_reasons.append("pm_no_ask_missing")
    elif pm_no.ask_size < COMBINED_SIZE_SHARES:
        fail_reasons.append("pm_no_depth_below_40")

    for venue, leg in (("PM_YES", pm_yes), ("PM_NO", pm_no), ("PD_YES", pd_yes), ("PD_NO", pd_no)):
        if leg.quote_age_sec is None:
            fail_reasons.append(f"{venue.lower()}_quote_age_unknown")
        elif leg.quote_age_sec > max_quote_age_sec:
            fail_reasons.append(f"{venue.lower()}_quote_stale:{leg.quote_age_sec:.3f}s")

    warnings.append("PM fee uses default sports fee rate 0.03 and still needs market-level verification")
    warnings.append("Predict.fun live order adapter is not implemented in this repo")
    warnings.append("No chase, no retry, no market order; exact fill is required for each leg")

    return Revalidation(
        run_id=run,
        checked_at=now_iso(),
        source_row=source_row,
        pm_yes=pm_yes,
        pm_no=pm_no,
        pd_yes=pd_yes,
        pd_no=pd_no,
        gross_edge_a=gross_a,
        net_edge_a=net_a,
        gross_edge_b=gross_b,
        net_edge_b=net_b,
        best_direction=best_direction,
        fail_reasons=fail_reasons,
        warnings=warnings,
    )


def leg_to_dict(leg: LegQuote) -> dict[str, Any]:
    return {
        "bid": leg.bid,
        "bid_size": leg.bid_size,
        "ask": leg.ask,
        "ask_size": leg.ask_size,
        "quote_age_sec": leg.quote_age_sec,
    }


def revalidation_payload(check: Revalidation) -> dict[str, Any]:
    pd_leg_cost = (check.pd_yes.ask or 0.0) * COMBINED_SIZE_SHARES
    pm_leg_cost = (check.pm_no.ask or 0.0) * COMBINED_SIZE_SHARES
    return {
        "run_id": check.run_id,
        "checked_at": check.checked_at,
        "team": TEAM,
        "target_direction": TARGET_DIRECTION,
        "s1_size_shares": S1_SIZE_SHARES,
        "s2_size_shares": S2_SIZE_SHARES,
        "combined_size_shares": COMBINED_SIZE_SHARES,
        "input_csv": str(INPUT_CSV),
        "pm_market_id": check.source_row.get("pm_market_id"),
        "pd_market_id": check.source_row.get("pd_market_id"),
        "pm_yes_token": check.source_row.get("pm_token_yes"),
        "pm_no_token": check.source_row.get("pm_token_no"),
        "pm_yes": leg_to_dict(check.pm_yes),
        "pm_no": leg_to_dict(check.pm_no),
        "pd_yes": leg_to_dict(check.pd_yes),
        "pd_no_derived": leg_to_dict(check.pd_no),
        "gross_edge_pm_yes_pd_no": check.gross_edge_a,
        "net_edge_pm_yes_pd_no": check.net_edge_a,
        "gross_edge_pd_yes_pm_no": check.gross_edge_b,
        "net_edge_pd_yes_pm_no": check.net_edge_b,
        "s1_net_usd_profit_pd_yes_pm_no": check.net_edge_b * S1_SIZE_SHARES,
        "s2_net_usd_profit_pd_yes_pm_no": check.net_edge_b * S2_SIZE_SHARES,
        "combined_net_usd_profit_pd_yes_pm_no": check.net_edge_b * COMBINED_SIZE_SHARES,
        "best_direction": check.best_direction,
        "target_direction_still_best": check.best_direction == TARGET_DIRECTION,
        "pd_leg_cost_usd": pd_leg_cost,
        "pm_leg_cost_usd": pm_leg_cost,
        "combined_cost_usd": pd_leg_cost + pm_leg_cost,
        "pass_flag": check.pass_flag,
        "fail_reasons": check.fail_reasons,
        "warnings": check.warnings,
    }


def order_intents(run: str, check: Revalidation) -> list[dict[str, Any]]:
    created_at = now_iso()
    source = check.source_row
    return [
        {
            "run_id": run,
            "created_at": created_at,
            "team": TEAM,
            "direction": TARGET_DIRECTION,
            "leg": "leg1",
            "sequence": 1,
            "venue": "predict.fun",
            "side": "BUY_YES",
            "instrument": source.get("pd_market_id"),
            "order_type": "limit",
            "time_in_force": "FOK_OR_EQUIVALENT_EXACT_FILL_ONLY",
            "shares": COMBINED_SIZE_SHARES,
            "limit_price": check.pd_yes.ask,
            "required_depth": COMBINED_SIZE_SHARES,
            "fresh_depth": check.pd_yes.ask_size,
            "exact_fill_required": True,
            "status": "ready_after_revalidation" if check.pass_flag else "blocked",
            "notes": "buy cheap leg first; no chase; no retry; no market order",
        },
        {
            "run_id": run,
            "created_at": created_at,
            "team": TEAM,
            "direction": TARGET_DIRECTION,
            "leg": "leg2",
            "sequence": 2,
            "venue": "polymarket",
            "side": "BUY_NO",
            "instrument": source.get("pm_token_no"),
            "order_type": "limit",
            "time_in_force": "FOK_OR_EQUIVALENT_EXACT_FILL_ONLY",
            "shares": COMBINED_SIZE_SHARES,
            "limit_price": check.pm_no.ask,
            "required_depth": COMBINED_SIZE_SHARES,
            "fresh_depth": check.pm_no.ask_size,
            "exact_fill_required": True,
            "status": "ready_after_leg1_exact_fill" if check.pass_flag else "blocked",
            "notes": "submit only after PD leg exact fill; no chase; no retry; no market order",
        },
    ]


def validate_live_gates(args: argparse.Namespace, check: Revalidation) -> list[str]:
    failures: list[str] = []
    if not args.live:
        return failures
    if not bool_env("TRADING_ENABLED", False):
        failures.append("TRADING_ENABLED_not_true")
    if bool_env("DRY_RUN", True):
        failures.append("DRY_RUN_env_not_false")
    if not bool_env("REQUIRE_MANUAL_CONFIRMATION", True):
        failures.append("REQUIRE_MANUAL_CONFIRMATION_not_true")
    if os.environ.get("EXECUTION_V3_ALLOW_LIVE_USA_ONE_SHOT") != "true":
        failures.append("EXECUTION_V3_ALLOW_LIVE_USA_ONE_SHOT_not_true")
    if args.confirmation != CONFIRMATION_TEXT:
        failures.append("cli_confirmation_text_missing_or_mismatch")
    if pm.missing_env(("PM_FUNDER", "PM_PRIVATE_KEY")):
        failures.append("missing_pm_live_env")
    if not os.environ.get(PD_API_KEY_ENV):
        failures.append("missing_predict_fun_api_key")
    failures.append("predict_fun_live_adapter_not_implemented")
    if not check.pass_flag:
        failures.append("fresh_revalidation_failed")
    return failures


def read_balance_snapshot(live: bool) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "checked_at": now_iso(),
        "live_mode": live,
        "pm_cash": None,
        "pm_cash_raw": None,
        "pd_cash": None,
        "errors": [],
        "notes": [],
    }
    if live:
        try:
            client = pm.build_client()
            cash, raw = pm.get_cash(client)
            snapshot["pm_cash"] = cash
            snapshot["pm_cash_raw"] = raw
        except Exception as exc:
            snapshot["errors"].append(f"pm_cash_unavailable:{str(exc)[:180]}")
    else:
        snapshot["notes"].append("dry_run_skips_private_pm_cash_read")
    snapshot["notes"].append("predict_fun_balance_adapter_not_implemented")
    return snapshot


def write_risk_report(
    path: Path,
    *,
    check: Revalidation | None,
    live_gate_failures: list[str],
    events: list[dict[str, Any]],
    live: bool,
    status: str,
) -> None:
    lines = [
        "# MVP3 Execution v3 USA One-Shot Risk Report",
        "",
        f"- generated_at: {now_iso()}",
        f"- mode: {'live_requested' if live else 'dry_run'}",
        f"- status: {status}",
        "- scope: USA only, one-shot only, no loop, no retry, no chase, no market order",
        "- target: Buy Predict.fun USA YES 40 shares, then buy Polymarket USA NO 40 shares",
        "",
        "## Revalidation",
        "",
    ]
    if check is None:
        lines.append("- fresh_revalidation: failed before quote object was available")
    else:
        lines.extend(
            [
                f"- pass_flag: {str(check.pass_flag).lower()}",
                f"- best_direction: {check.best_direction}",
                f"- target_direction: {TARGET_DIRECTION}",
                f"- net_edge_pd_yes_pm_no: {check.net_edge_b:.6f}",
                f"- s1_profit: {check.net_edge_b * S1_SIZE_SHARES:.4f}",
                f"- s2_profit: {check.net_edge_b * S2_SIZE_SHARES:.4f}",
                f"- combined_profit: {check.net_edge_b * COMBINED_SIZE_SHARES:.4f}",
                f"- pd_yes_ask/depth: {check.pd_yes.ask} / {check.pd_yes.ask_size}",
                f"- pm_no_ask/depth: {check.pm_no.ask} / {check.pm_no.ask_size}",
                f"- fail_reasons: {', '.join(check.fail_reasons) if check.fail_reasons else 'none'}",
            ]
        )
    lines.extend(["", "## Live Gates", ""])
    if live_gate_failures:
        lines.extend(f"- {failure}" for failure in live_gate_failures)
    else:
        lines.append("- none")
    lines.extend(["", "## Risk Events", ""])
    if events:
        lines.extend(f"- {event['severity']} / {event['event_type']}: {event['message']}" for event in events)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Live Trade Readiness",
            "",
            "- Live trade readiness: NOT_READY",
            "- Reason: Predict.fun live order adapter is not implemented; this skeleton does not prove exact fill, depth persistence, quote freshness, settlement equivalence, or live balance handling.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(
    path: Path,
    *,
    check: Revalidation | None,
    balance_snapshot: dict[str, Any],
    live_gate_failures: list[str],
    status: str,
    live: bool,
) -> None:
    lines = [
        "# MVP3 Execution v3 USA One-Shot Summary",
        "",
        f"- generated_at: {now_iso()}",
        f"- input_csv: `{INPUT_CSV.relative_to(PROJECT_ROOT)}`",
        f"- mode: {'live_requested' if live else 'dry_run'}",
        "- team: United States / USA",
        "- target_direction: pd_yes_pm_no",
        "- S1 shares: 20",
        "- S2 shares: 20",
        "- combined shares: 40",
        "- order_sequence: Predict.fun USA YES first, then Polymarket USA NO only after exact fill",
        "- chase_allowed: false",
        "- retry_allowed: false",
        "- market_order_allowed: false",
        f"- status: {status}",
        "",
        "## Fresh Revalidation",
        "",
    ]
    if check is None:
        lines.append("- result: failed")
    else:
        lines.extend(
            [
                f"- result: {'pass' if check.pass_flag else 'fail'}",
                f"- best_direction: {check.best_direction}",
                f"- gross_edge_pd_yes_pm_no: {check.gross_edge_b:.6f}",
                f"- net_edge_pd_yes_pm_no: {check.net_edge_b:.6f}",
                f"- net_edge_pct_pd_yes_pm_no: {check.net_edge_b * 100:.3f}%",
                f"- s1_net_usd_profit: {check.net_edge_b * S1_SIZE_SHARES:.4f}",
                f"- s2_net_usd_profit: {check.net_edge_b * S2_SIZE_SHARES:.4f}",
                f"- combined_s1s2_net_usd_profit: {check.net_edge_b * COMBINED_SIZE_SHARES:.4f}",
                f"- PD USA YES ask/depth/age_sec: {check.pd_yes.ask} / {check.pd_yes.ask_size} / {check.pd_yes.quote_age_sec}",
                f"- PM USA NO ask/depth/age_sec: {check.pm_no.ask} / {check.pm_no.ask_size} / {check.pm_no.quote_age_sec}",
                f"- fail_reasons: {', '.join(check.fail_reasons) if check.fail_reasons else 'none'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Fees",
            "",
            f"- PM taker fee rate: {PM_FEE_RATE}",
            "- PM fee uses default sports fee rate 0.03 and still needs market-level verification.",
            f"- PD taker fee rate: {PD_FEE_RATE}",
            f"- PD fee discount multiplier: {PD_FEE_DISCOUNT_MULTIPLIER}",
            "",
            "## Balances",
            "",
            f"- PM cash: {balance_snapshot.get('pm_cash')}",
            f"- PD cash: {balance_snapshot.get('pd_cash')}",
            f"- balance_notes: {'; '.join(balance_snapshot.get('notes', []))}",
            f"- balance_errors: {'; '.join(balance_snapshot.get('errors', [])) or 'none'}",
            "",
            "## Live Gates",
            "",
        ]
    )
    if live_gate_failures:
        lines.extend(f"- {failure}" for failure in live_gate_failures)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Readiness",
            "",
            "- Live trade readiness: NOT_READY",
            "- Reason: this is a conservative USA-only one-shot skeleton; Predict.fun live adapter is not implemented, and exact fill / freshness / settlement / balance checks still require verification before any real order.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_log(payload: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{payload['run_id']}.json"
    write_json(path, payload)
    return path


def execute_live_skeleton(_check: Revalidation) -> dict[str, Any]:
    raise NotImplementedError("predict_fun_live_adapter_not_implemented")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP3 Execution v3 USA-only one-shot live skeleton.")
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--live", action="store_true", help="Request live mode. Still blocked until all gates pass.")
    parser.add_argument("--confirmation", default="", help="Must match the confirmation text in live mode.")
    parser.add_argument("--max-quote-age-sec", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pm.load_env()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_id()
    events: list[dict[str, Any]] = []
    check: Revalidation | None = None
    status = "unknown"

    try:
        check = revalidate(run, args.max_quote_age_sec)
        write_json(REVALIDATION_JSON, revalidation_payload(check))
        write_csv(ORDER_INTENTS_CSV, ORDER_INTENT_FIELDS, order_intents(run, check))
        if not check.pass_flag:
            events.append(
                risk_event(
                    run,
                    "warning",
                    "fresh_revalidation_failed",
                    ",".join(check.fail_reasons),
                )
            )
    except (urllib.error.URLError, RuntimeError, ValueError, KeyError) as exc:
        events.append(risk_event(run, "critical", "fresh_revalidation_exception", str(exc)[:500]))
        status = "aborted_revalidation_exception"
        write_json(
            REVALIDATION_JSON,
            {
                "run_id": run,
                "checked_at": now_iso(),
                "team": TEAM,
                "target_direction": TARGET_DIRECTION,
                "pass_flag": False,
                "error": str(exc)[:500],
                "submit_order_called": False,
                "real_order_sent": False,
            },
        )
        write_csv(ORDER_INTENTS_CSV, ORDER_INTENT_FIELDS, [])
        write_csv(RISK_EVENTS_CSV, RISK_EVENT_FIELDS, events)
        balance_snapshot = read_balance_snapshot(live=False)
        write_risk_report(
            RISK_REPORT_MD,
            check=check,
            live_gate_failures=[],
            events=events,
            live=args.live,
            status=status,
        )
        write_summary(
            SUMMARY_MD,
            check=check,
            balance_snapshot=balance_snapshot,
            live_gate_failures=[],
            status=status,
            live=args.live,
        )
        write_log({"run_id": run, "status": status, "events": events})
        print(f"ABORT: {status}")
        print(f"risk_report={RISK_REPORT_MD}")
        return 1

    dry_run = not args.live
    balance_snapshot = read_balance_snapshot(live=args.live)
    live_gate_failures = validate_live_gates(args, check)

    if dry_run:
        status = "dry_run_no_orders"
        events.append(risk_event(run, "info", "dry_run", "No orders submitted."))
    elif live_gate_failures:
        status = "aborted_live_gates_failed"
        events.append(risk_event(run, "critical", "live_gates_failed", ",".join(live_gate_failures)))
    elif check is not None and check.pass_flag:
        typed = input(f'Type "{CONFIRMATION_TEXT}" to execute live one-shot: ')
        if typed != CONFIRMATION_TEXT:
            status = "aborted_manual_confirmation_mismatch"
            events.append(
                risk_event(run, "critical", "manual_confirmation_mismatch", "No orders submitted.")
            )
        else:
            try:
                execution_result = execute_live_skeleton(check)
                status = "submitted"
                events.append(risk_event(run, "info", "live_execution_result", json.dumps(execution_result)))
            except Exception as exc:
                status = "aborted_or_risk_after_leg1_block"
                events.append(risk_event(run, "critical", "live_execution_blocked", str(exc)[:500]))
    else:
        status = "aborted_revalidation_failed"
        events.append(risk_event(run, "critical", "revalidation_failed_no_orders", ",".join(check.fail_reasons)))

    write_csv(RISK_EVENTS_CSV, RISK_EVENT_FIELDS, events)
    write_risk_report(
        RISK_REPORT_MD,
        check=check,
        live_gate_failures=live_gate_failures,
        events=events,
        live=args.live,
        status=status,
    )
    write_summary(
        SUMMARY_MD,
        check=check,
        balance_snapshot=balance_snapshot,
        live_gate_failures=live_gate_failures,
        status=status,
        live=args.live,
    )
    log_path = write_log(
        {
            "run_id": run,
            "status": status,
            "dry_run": dry_run,
            "live_gate_failures": live_gate_failures,
            "events": events,
            "balance_snapshot": balance_snapshot,
            "revalidation": revalidation_payload(check),
            "submit_order_called": False,
            "real_order_sent": False,
        }
    )

    print(f"status={status}")
    print(f"run_id={run}")
    print(f"best_direction={check.best_direction}")
    print(f"net_edge_pd_yes_pm_no={check.net_edge_b:.6f}")
    print(f"pass_flag={str(check.pass_flag).lower()}")
    print(f"fail_reasons={','.join(check.fail_reasons) if check.fail_reasons else 'none'}")
    print(f"submit_order_called=false")
    print(f"real_order_sent=false")
    print(f"revalidation={REVALIDATION_JSON}")
    print(f"order_intents={ORDER_INTENTS_CSV}")
    print(f"risk_report={RISK_REPORT_MD}")
    print(f"summary={SUMMARY_MD}")
    print(f"log={log_path}")
    return 0 if dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
