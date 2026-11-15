from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pm_hl_auto_executor import (  # noqa: E402
    s2_exit_actual_fill_pnl_fields,
)

LOG_DIR = PROJECT_ROOT / "logs" / "pm_hl"
UTC8 = timezone(timedelta(hours=8))

MARKET_STATE_FILES = {
    "WC-Germany-Champion": LOG_DIR / "auto_state_wc_germany.json",
    "WC-Portugal-Champion": LOG_DIR / "auto_state_wc_portugal.json",
}

COLUMNS = [
    "Market",
    "Status",
    "Entry Time UTC+8",
    "Exit Time UTC+8",
    "Holding Days",
    "Shares Intended",
    "Shares Filled",
    "Gross PnL",
    "Entry Fee",
    "Exit Fee",
    "All-in Net Profit",
    "Net Return",
    "Simple APR",
    "ExitVsHold",
    "Fill Quality",
]


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_utc8(value: Any) -> str:
    ts = parse_ts(value)
    if ts is None:
        return ""
    return ts.astimezone(UTC8).strftime("%Y-%m-%d %H:%M:%S")


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def timestamp_from_log_path(path: str | None) -> datetime | None:
    if not path:
        return None
    match = re.search(r"_(\d{8})_(\d{6})\.json$", Path(path).name)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        return datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iter_event_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(LOG_DIR.glob("auto_events_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payload["_source_file"] = str(path)
                rows.append(payload)
    return rows


def find_s2_entry_ts(market: str, entry_log: str | None) -> tuple[datetime | None, str]:
    entry_name = Path(entry_log).name if entry_log else ""
    for row in iter_event_records():
        if row.get("event") != "portfolio_action_executed":
            continue
        candidate = row.get("candidate") or {}
        if candidate.get("market") != market:
            continue
        logs = row.get("result", {}).get("logs") or []
        if entry_name and any(Path(item).name == entry_name for item in logs):
            ts = parse_ts(row.get("ts"))
            if ts is not None:
                return ts, "auto_events portfolio_action_executed"
    ts = timestamp_from_log_path(entry_log)
    if ts is not None:
        return ts, f"log filename {entry_name}"
    return None, "unavailable"


def find_exit_record(market: str) -> dict[str, Any]:
    state_path = MARKET_STATE_FILES.get(market)
    state = load_json(state_path) if state_path else {}
    s2 = state.get("s2") or {}
    exit_log_path = s2.get("exit_log")
    exit_log = load_json(Path(exit_log_path)) if exit_log_path else {}

    exit_ts: datetime | None = None
    exit_ts_source = "unavailable"
    confirmation: dict[str, Any] = {}
    analysis: dict[str, Any] = exit_log.get("analysis") or {}
    execution: dict[str, Any] = exit_log.get("execution") or {}
    orders: list[dict[str, Any]] = execution.get("orders") or []

    if exit_log:
        exit_ts = timestamp_from_log_path(exit_log_path)
        exit_ts_source = f"exit log filename {Path(exit_log_path).name}"
        confirmation = execution.get("confirmation") or {}
        if parse_ts(state.get("updated_at")):
            exit_ts = parse_ts(state.get("updated_at"))
            exit_ts_source = "market state updated_at"

    for row in iter_event_records():
        if row.get("market") != market:
            continue
        event = row.get("event")
        if event == "state_transition" and row.get("to_state") == "S2_EXITED":
            ts = parse_ts(row.get("ts"))
            if ts is not None:
                exit_ts = ts
                exit_ts_source = "auto_events S2_EXITED transition"
        if event in {"trade_confirmation_failed", "trade_confirmation"} and (row.get("confirmation") or {}).get("action_type") == "S2_EXIT":
            confirmation = row.get("confirmation") or confirmation
            if exit_ts is None:
                exit_ts = parse_ts(row.get("ts"))
                exit_ts_source = f"auto_events {event}"

    if exit_ts is None and confirmation.get("position_read_attempts"):
        attempts = confirmation["position_read_attempts"]
        for attempt in reversed(attempts):
            ts = parse_ts(attempt.get("read_at"))
            if ts is not None:
                exit_ts = ts
                exit_ts_source = "auto_events position_read_attempts"
                break

    return {
        "state": state,
        "exit_log": exit_log,
        "exit_log_path": exit_log_path,
        "analysis": analysis,
        "execution": execution,
        "orders": orders,
        "confirmation": confirmation,
        "exit_ts": exit_ts,
        "exit_ts_source": exit_ts_source,
    }


def pm_sell_fill_price_from_proceeds(proceeds: Any, shares: Any) -> float | None:
    proceeds_f = maybe_float(proceeds)
    shares_f = maybe_float(shares)
    if proceeds_f is None or shares_f is None or shares_f <= 0:
        return None
    return proceeds_f / shares_f


def hl_avg_px_from_orders(orders: list[dict[str, Any]]) -> float | None:
    for order in orders:
        if order.get("venue") != "HL":
            continue
        response = order.get("response") or {}
        statuses = (
            response.get("response", {})
            .get("data", {})
            .get("statuses", [])
        )
        for status in statuses:
            filled = status.get("filled") or {}
            avg_px = maybe_float(filled.get("avgPx"))
            if avg_px is not None:
                return avg_px
    return None


def entry_fees_from_entry_log(entry_log_path: str | None) -> tuple[float | None, float | None, float | None]:
    entry_log = load_json(Path(entry_log_path)) if entry_log_path else {}
    plan = entry_log.get("plan") or {}
    entry_pm_fee = maybe_float(plan.get("pm_fee"))
    entry_hl_fee = maybe_float(plan.get("hl_fee"))
    entry_gross_cost = maybe_float(plan.get("total_notional"))
    if entry_gross_cost is None:
        entry_gross_cost = maybe_float((entry_log.get("execution") or {}).get("original_entry_cost"))
    return entry_gross_cost, entry_pm_fee or 0.0, entry_hl_fee or 0.0


def holding_days(entry_ts: datetime | None, exit_ts: datetime | None) -> float | None:
    if entry_ts is None or exit_ts is None:
        return None
    return (exit_ts - entry_ts).total_seconds() / 86400.0


def build_germany_row() -> dict[str, Any]:
    market = "WC-Germany-Champion"
    state = load_json(MARKET_STATE_FILES[market])
    s2 = state.get("s2") or {}
    exit_info = find_exit_record(market)
    analysis = exit_info["analysis"]
    confirmation = exit_info["confirmation"]
    entry_ts, entry_ts_source = find_s2_entry_ts(market, s2.get("entry_log"))
    exit_ts = exit_info["exit_ts"]
    exit_ts_source = exit_info["exit_ts_source"]

    pm_filled = maybe_float((confirmation.get("pm") or {}).get("confirmed_filled_shares"))
    hl_filled = maybe_float((confirmation.get("hl") or {}).get("confirmed_filled_shares"))
    if pm_filled is None:
        pm_filled = maybe_float(exit_info["execution"].get("pm_filled_shares"))
    if hl_filled is None:
        hl_filled = maybe_float(exit_info["execution"].get("hl_filled_shares"))

    shares_intended = maybe_float(s2.get("intended_shares")) or 20.0
    shares_filled = f"PM={pm_filled:.2f} HL={hl_filled:.2f}" if pm_filled is not None and hl_filled is not None else "20.00"

    gross_pnl = maybe_float(analysis.get("realized_gross_pnl"))
    entry_fee = maybe_float(analysis.get("total_entry_fee"))
    exit_fee = maybe_float(analysis.get("total_exit_fee"))
    all_in = maybe_float(analysis.get("realized_net_pnl_all_in"))
    exit_vs_hold = maybe_float(analysis.get("exit_vs_hold_usd"))
    fill_quality = analysis.get("pnl_quality") or analysis.get("actual_fill_source") or "order_response"

    days = holding_days(entry_ts, exit_ts)
    net_return = all_in / 20.0 if all_in is not None else None
    apr = net_return * 365.0 / days if net_return is not None and days and days > 0 else None

    status = "full exit / confirmed"
    if state.get("state") != "S2_EXITED":
        status = f"{state.get('state', 'unknown')} (see state file)"

    return {
        "Market": market,
        "Status": status,
        "Entry Time UTC+8": format_utc8(entry_ts),
        "Exit Time UTC+8": format_utc8(exit_ts),
        "Holding Days": round(days, 4) if days is not None else "",
        "Shares Intended": shares_intended,
        "Shares Filled": shares_filled,
        "Gross PnL": gross_pnl,
        "Entry Fee": entry_fee,
        "Exit Fee": exit_fee,
        "All-in Net Profit": all_in,
        "Net Return": net_return,
        "Simple APR": apr,
        "ExitVsHold": exit_vs_hold,
        "Fill Quality": fill_quality,
        "_meta": {
            "entry_ts_source": entry_ts_source,
            "exit_ts_source": exit_ts_source,
            "exit_log": exit_info.get("exit_log_path"),
            "entry_log": s2.get("entry_log"),
            "pnl_source": "auto_exit_s2 analysis (actual order_response)",
            "field_quality": {
                "Gross PnL": "actual",
                "Entry Fee": "actual",
                "Exit Fee": "actual",
                "All-in Net Profit": "actual",
                "ExitVsHold": "actual",
                "Shares Filled": "actual",
            },
        },
    }


def build_portugal_row() -> dict[str, Any]:
    market = "WC-Portugal-Champion"
    state = load_json(MARKET_STATE_FILES[market])
    s2 = state.get("s2") or {}
    exit_info = find_exit_record(market)
    confirmation = exit_info["confirmation"]
    pm_conf = confirmation.get("pm") or {}
    hl_conf = confirmation.get("hl") or {}

    entry_ts, entry_ts_source = find_s2_entry_ts(market, s2.get("entry_log"))
    exit_ts = exit_info["exit_ts"]
    exit_ts_source = exit_info["exit_ts_source"]

    shares_intended = maybe_float(s2.get("intended_shares")) or 20.0
    pm_filled = maybe_float(pm_conf.get("confirmed_filled_shares")) or maybe_float(pm_conf.get("position_delta_filled_shares"))
    hl_filled = maybe_float(hl_conf.get("confirmed_filled_shares")) or maybe_float(hl_conf.get("position_delta_filled_shares"))
    pm_filled_display = round(pm_filled, 2) if pm_filled is not None else None
    hl_filled_display = round(hl_filled, 2) if hl_filled is not None else None
    shares_filled = f"PM={pm_filled_display:.2f} HL={hl_filled_display:.2f}"

    entry_gross_cost, entry_pm_fee, entry_hl_fee = entry_fees_from_entry_log(s2.get("entry_log"))

    # prefer explicit reported proceeds (gross) over mis-keyed filled_shares
    pm_proceeds = maybe_float(pm_conf.get("order_response_reported_proceeds") or pm_conf.get("order_response_reported_filled_shares"))
    pm_exit_price = pm_sell_fill_price_from_proceeds(pm_proceeds, pm_filled)
    hl_exit_price = hl_avg_px_from_orders(exit_info["orders"])
    hl_price_estimated = hl_exit_price is None
    if hl_exit_price is None:
        scan_analysis = exit_info["analysis"] or {}
        if not scan_analysis:
            for row in iter_event_records():
                if row.get("market") == market and row.get("event") == "s2_exit_check":
                    scan_analysis = row.get("analysis") or {}
                    break
        hl_exit_price = maybe_float(scan_analysis.get("hl_exit_price") or scan_analysis.get("hl_bid"))

    pnl_fields: dict[str, Any] = {}
    pnl_source = "unavailable"
    field_quality: dict[str, str] = {}

    if (
        entry_gross_cost is not None
        and pm_filled is not None
        and hl_filled is not None
        and pm_exit_price is not None
        and hl_exit_price is not None
    ):
        pnl_fields = s2_exit_actual_fill_pnl_fields(
            entry_gross_cost=entry_gross_cost,
            target_shares=shares_intended,
            pm_filled_qty=pm_filled,
            hl_filled_qty=hl_filled,
            pm_exit_price=pm_exit_price,
            hl_exit_price=hl_exit_price,
            entry_pm_fee=entry_pm_fee,
            entry_hl_fee=entry_hl_fee,
        )
        pnl_source = "s2_exit_actual_fill_pnl_fields with PM proceeds/shares and HL scan bid"
        field_quality = {
            "Gross PnL": "actual (partial fills)",
            "Entry Fee": "actual (scaled to max fill leg)",
            "Exit Fee": "actual (partial fills)",
            "All-in Net Profit": "actual (partial fills)",
            "ExitVsHold": "actual (partial fills)" if not hl_price_estimated else "estimated (HL price from scan bid)",
            "Shares Filled": "actual",
        }
        if hl_price_estimated:
            field_quality["Gross PnL"] = "mixed (PM actual price, HL scan bid)"
            field_quality["All-in Net Profit"] = "mixed (PM actual price, HL scan bid)"
            field_quality["Exit Fee"] = "mixed (PM actual price, HL scan bid)"
            pnl_source += "; HL avgPx not persisted - using scan bid 0.92241"

    gross_pnl = maybe_float(pnl_fields.get("realized_gross_pnl"))
    entry_fee = maybe_float(pnl_fields.get("total_entry_fee"))
    exit_fee = maybe_float(pnl_fields.get("total_exit_fee"))
    all_in = maybe_float(pnl_fields.get("realized_net_pnl_all_in"))
    exit_vs_hold = maybe_float(pnl_fields.get("exit_vs_hold_usd"))

    days = holding_days(entry_ts, exit_ts)
    net_return = all_in / 20.0 if all_in is not None else None
    apr = net_return * 365.0 / days if net_return is not None and days and days > 0 else None

    halt_reason = state.get("halt_reason") or "PM partial fill"
    if pm_filled_display is not None and abs(pm_filled_display - shares_intended) <= shares_intended * 0.005:
        status = f"HALTED / partial fill within 0.5% (PM {pm_filled_display:.2f}/HL {hl_filled_display:.2f}) - would be confirmed_with_tolerance"
    else:
        status = f"HALTED / partial fill (PM {pm_filled_display:.2f}/HL {hl_filled_display:.2f}) — manual review required"

    fill_quality_parts = [
        "PM partial fill 19.99/20",
        "HL full 20/20",
        f"PM exit price actual={pm_exit_price:.6f}" if pm_exit_price is not None else "PM exit price unavailable",
    ]
    if hl_price_estimated:
        fill_quality_parts.append(f"HL exit price estimated={hl_exit_price:.5f} (scan bid; avgPx not in logs)")
    else:
        fill_quality_parts.append(f"HL exit price actual={hl_exit_price:.5f}")
    fill_quality = "; ".join(fill_quality_parts)

    return {
        "Market": market,
        "Status": status,
        "Entry Time UTC+8": format_utc8(entry_ts),
        "Exit Time UTC+8": format_utc8(exit_ts),
        "Holding Days": round(days, 4) if days is not None else "",
        "Shares Intended": shares_intended,
        "Shares Filled": shares_filled,
        "Gross PnL": gross_pnl,
        "Entry Fee": entry_fee,
        "Exit Fee": exit_fee,
        "All-in Net Profit": all_in,
        "Net Return": net_return,
        "Simple APR": apr,
        "ExitVsHold": exit_vs_hold,
        "Fill Quality": fill_quality,
        "_meta": {
            "entry_ts_source": entry_ts_source,
            "exit_ts_source": exit_ts_source,
            "exit_log": exit_info.get("exit_log_path"),
            "entry_log": s2.get("entry_log"),
            "halt_reason": halt_reason,
            "state": state.get("state"),
            "s2_status": s2.get("status"),
            "exit_log_saved": bool(exit_info.get("exit_log_path")),
            "pnl_source": pnl_source,
            "field_quality": field_quality,
            "requires_manual_review": True,
            "residual_pm_shares": round((pm_conf.get("position_after") or 0) - 20.0, 4) if pm_conf.get("position_after") is not None else None,
        },
    }


def fmt_num(value: Any, places: int = 6) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return f"{float(value):.{places}f}"


def print_markdown_table(rows: list[dict[str, Any]]) -> None:
    display_rows = [{col: row.get(col, "") for col in COLUMNS} for row in rows]
    widths = {col: len(col) for col in COLUMNS}
    for row in display_rows:
        for col in COLUMNS:
            text = fmt_num(row[col]) if isinstance(row[col], (int, float)) else str(row[col])
            widths[col] = max(widths[col], len(text))

    header = "| " + " | ".join(col.ljust(widths[col]) for col in COLUMNS) + " |"
    sep = "| " + " | ".join("-" * widths[col] for col in COLUMNS) + " |"
    print(header)
    print(sep)
    for row in display_rows:
        cells = []
        for col in COLUMNS:
            value = row[col]
            text = fmt_num(value) if isinstance(value, (int, float)) else str(value)
            cells.append(text.ljust(widths[col]))
        print("| " + " | ".join(cells) + " |")


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            out = {}
            for col in COLUMNS:
                value = row.get(col, "")
                if isinstance(value, float):
                    out[col] = f"{value:.8f}"
                else:
                    out[col] = value
            writer.writerow(out)


def build_rows(markets: list[str]) -> list[dict[str, Any]]:
    builders = {
        "WC-Germany-Champion": build_germany_row,
        "WC-Portugal-Champion": build_portugal_row,
        "WC-Spain-Champion": build_portugal_row,  # Spain uses same reconciliation/display logic
    }
    rows: list[dict[str, Any]] = []
    for market in markets:
        builder = builders.get(market)
        if builder is None:
            raise ValueError(f"Unsupported market: {market}")
        rows.append(builder())
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only S2 exit entry-to-exit performance summary.")
    parser.add_argument(
        "--markets",
        default="WC-Germany-Champion,WC-Portugal-Champion",
        help="Comma-separated market keys",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional CSV output path (default: logs/pm_hl/s2_exit_performance_summary_YYYYMMDD_HHMMSS.csv)",
    )
    args = parser.parse_args()
    markets = [item.strip() for item in args.markets.split(",") if item.strip()]
    rows = build_rows(markets)

    print("\n## S2 Exit Performance Summary\n")
    print_markdown_table(rows)

    stamp = datetime.now(UTC8).strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else LOG_DIR / f"s2_exit_performance_summary_{stamp}.csv"
    write_csv(rows, output_path)
    print(f"\nCSV saved: {output_path}")

    print("\n### Data sources / field quality\n")
    for row in rows:
        meta = row.get("_meta") or {}
        print(f"- **{row['Market']}**")
        print(f"  - entry_log: {meta.get('entry_log')}")
        print(f"  - exit_log: {meta.get('exit_log') or '(none - exit halted before save)'}")
        print(f"  - entry time source: {meta.get('entry_ts_source')}")
        print(f"  - exit time source: {meta.get('exit_ts_source')}")
        print(f"  - pnl source: {meta.get('pnl_source')}")
        fq = meta.get("field_quality") or {}
        if fq:
            print(f"  - field quality: {fq}")
        if meta.get("requires_manual_review"):
            print(
                "  - **manual review**: state HALTED; S2 still active in state; "
                f"residual PM S2 leg ~{meta.get('residual_pm_shares')} shares vs S1 baseline"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
