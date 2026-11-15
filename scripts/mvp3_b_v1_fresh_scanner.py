"""MVP3-B v1 dynamic fresh scanner for USA / France / Portugal.

Read-only only:
- reads existing A3 mapping CSV for token / market IDs
- fetches fresh PM and Predict.fun orderbooks
- computes review-only entry edges for 40 shares
- writes watcher CSV and summary
- never calls execution, never places orders, never generates trade candidates
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


INPUT_CSV = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun" / "mvp3_a3_winner_price_compare.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun"
WATCHER_CSV = OUTPUT_DIR / "mvp3_b_v1_fresh_scanner_usa_france_portugal_10m.csv"
SUMMARY_MD = OUTPUT_DIR / "mvp3_b_v1_fresh_scanner_usa_france_portugal_10m_summary.md"

TARGET_TEAMS = ("United States", "France", "Portugal")
TEAM_LABELS = {"United States": "USA", "France": "France", "Portugal": "Portugal"}
S1_SIZE_SHARES = 20.0
S2_SIZE_SHARES = 20.0
COMBINED_SIZE_SHARES = S1_SIZE_SHARES + S2_SIZE_SHARES
PM_FEE_RATE = 0.03
PD_FEE_RATE = 0.02
PD_FEE_DISCOUNT_MULTIPLIER = 1.0
EDGE_THRESHOLD = 0.0005
MIN_S1_PROFIT_USD = 0.01
MIN_S2_PROFIT_USD = 0.01
PD_API_BASE_ENV = "PREDICT_API_BASE"
PD_API_KEY_ENV = "PREDICT_API_KEY"
PD_DEFAULT_API_BASE = "https://api.predict.fun"
ROOT_STOP_FILE = PROJECT_ROOT / "STOP"
EXECUTION_V3_STOP_FILE = PROJECT_ROOT / "data" / "execution_v3" / "STOP"

CSV_FIELDS = [
    "run_id",
    "iteration",
    "timestamp",
    "team",
    "team_label",
    "mapping_status",
    "pm_market_id",
    "pd_market_id",
    "pm_token_yes",
    "pm_token_no",
    "pm_yes_bid1",
    "pm_yes_ask1",
    "pm_yes_bid_size1",
    "pm_yes_ask_size1",
    "pm_no_bid1",
    "pm_no_ask1",
    "pm_no_bid_size1",
    "pm_no_ask_size1",
    "pd_yes_bid1",
    "pd_yes_ask1",
    "pd_yes_bid_size1",
    "pd_yes_ask_size1",
    "pd_no_bid1",
    "pd_no_ask1",
    "pd_no_bid_size1",
    "pd_no_ask_size1",
    "pd_no_price_source",
    "gross_edge_pm_yes_pd_no",
    "pm_fee_pm_yes",
    "pd_fee_pd_no",
    "total_fee_pm_yes_pd_no",
    "net_edge_pm_yes_pd_no",
    "net_edge_pct_pm_yes_pd_no",
    "s1_profit_pm_yes_pd_no",
    "s2_profit_pm_yes_pd_no",
    "combined_profit_pm_yes_pd_no",
    "depth_pass_pm_yes_pd_no",
    "gross_edge_pd_yes_pm_no",
    "pd_fee_pd_yes",
    "pm_fee_pm_no",
    "total_fee_pd_yes_pm_no",
    "net_edge_pd_yes_pm_no",
    "net_edge_pct_pd_yes_pm_no",
    "s1_profit_pd_yes_pm_no",
    "s2_profit_pd_yes_pm_no",
    "combined_profit_pd_yes_pm_no",
    "depth_pass_pd_yes_pm_no",
    "best_direction_by_net_edge",
    "best_net_edge",
    "best_net_edge_pct",
    "best_combined_profit",
    "best_depth_pass",
    "status",
    "pm_orderbook_ok",
    "pd_orderbook_ok",
    "root_stop_present",
    "execution_v3_stop_present",
    "error",
    "notes",
]


@dataclass(frozen=True)
class TopBook:
    bid: float | None
    bid_size: float | None
    ask: float | None
    ask_size: float | None
    ok: bool
    error: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return "mvp3_b_v1_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def pd_api_base() -> str:
    return os.environ.get(PD_API_BASE_ENV, PD_DEFAULT_API_BASE).rstrip("/")


def pd_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "2026-strategy-lab-mvp3-b-v1-fresh-scanner",
    }
    api_key = os.environ.get(PD_API_KEY_ENV)
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def pd_auth_blocker() -> str:
    if pd_api_base() == PD_DEFAULT_API_BASE and not os.environ.get(PD_API_KEY_ENV):
        return f"missing_{PD_API_KEY_ENV}_for_predict_fun_mainnet"
    return ""


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


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
    raw = 1.0 - price
    return round(raw, decimal_precision) if decimal_precision is not None else raw


def pm_taker_fee(price: float) -> float:
    return PM_FEE_RATE * price * (1.0 - price)


def pd_taker_fee(price: float) -> float:
    return PD_FEE_RATE * PD_FEE_DISCOUNT_MULTIPLIER * min(price, 1.0 - price)


def load_target_rows() -> dict[str, dict[str, str]]:
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        rows = {row.get("team", ""): row for row in csv.DictReader(handle)}
    missing = [team for team in TARGET_TEAMS if team not in rows]
    if missing:
        raise RuntimeError(f"missing target teams in A3 CSV: {', '.join(missing)}")
    return {team: rows[team] for team in TARGET_TEAMS}


def fetch_pm_top(token_id: str) -> TopBook:
    try:
        bids, asks, _raw = pm.book(token_id)
    except Exception as exc:
        return TopBook(None, None, None, None, False, f"pm_book_error:{str(exc)[:160]}")
    bid = bids[0] if bids else (None, None)
    ask = asks[0] if asks else (None, None)
    return TopBook(
        bid=safe_float(bid[0]),
        bid_size=safe_float(bid[1]),
        ask=safe_float(ask[0]),
        ask_size=safe_float(ask[1]),
        ok=bool(bids and asks),
        error="" if bids and asks else "pm_book_missing_bid_or_ask",
    )


def fetch_pd_yes_no(pd_market_id: str) -> tuple[TopBook, TopBook, str, str]:
    blocker = pd_auth_blocker()
    if blocker:
        error_book = TopBook(None, None, None, None, False, blocker)
        return error_book, error_book, "UNKNOWN / NEEDS_RECHECK", blocker

    url = f"{pd_api_base()}/v1/markets/{urllib.parse.quote(pd_market_id)}/orderbook"
    try:
        raw = http_json(url, headers=pd_headers())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        error = f"pd_book_error:{str(exc)[:160]}"
        error_book = TopBook(None, None, None, None, False, error)
        return error_book, error_book, "UNKNOWN / NEEDS_RECHECK", error

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        error = "pd_book_missing_data_object"
        error_book = TopBook(None, None, None, None, False, error)
        return error_book, error_book, "UNKNOWN / NEEDS_RECHECK", error

    yes_bid, yes_bid_size = first_level(data.get("bids"), reverse=True)
    yes_ask, yes_ask_size = first_level(data.get("asks"), reverse=False)
    precision_raw = data.get("decimalPrecision") or raw.get("decimalPrecision")
    try:
        precision = int(precision_raw) if precision_raw is not None else 2
    except (TypeError, ValueError):
        precision = 2

    yes = TopBook(
        bid=yes_bid,
        bid_size=yes_bid_size,
        ask=yes_ask,
        ask_size=yes_ask_size,
        ok=bool(yes_bid is not None and yes_ask is not None),
        error="" if yes_bid is not None and yes_ask is not None else "pd_yes_book_missing_bid_or_ask",
    )
    no = TopBook(
        bid=complement(yes_ask, precision),
        bid_size=yes_ask_size,
        ask=complement(yes_bid, precision),
        ask_size=yes_bid_size,
        ok=bool(yes_bid is not None and yes_ask is not None),
        error="" if yes_bid is not None and yes_ask is not None else "pd_no_derived_missing_yes_book",
    )
    return yes, no, "derived_from_yes_book", yes.error


def compute_row(
    *,
    run: str,
    iteration: int,
    timestamp: str,
    source_row: dict[str, str],
    pm_yes: TopBook,
    pm_no: TopBook,
    pd_yes: TopBook,
    pd_no: TopBook,
    pd_no_source: str,
    error: str,
) -> dict[str, Any]:
    team = source_row["team"]
    notes = ["review_only_not_tradeable", "no_execution_called", "no_trade_candidate_generated"]
    status = "fresh_quote_error" if error else "negative_or_zero_after_fee"

    values: dict[str, float | bool | str] = {
        "gross_a": "",
        "pm_fee_a": "",
        "pd_fee_a": "",
        "total_fee_a": "",
        "net_a": "",
        "s1_a": "",
        "s2_a": "",
        "combined_a": "",
        "depth_a": False,
        "gross_b": "",
        "pd_fee_b": "",
        "pm_fee_b": "",
        "total_fee_b": "",
        "net_b": "",
        "s1_b": "",
        "s2_b": "",
        "combined_b": "",
        "depth_b": False,
        "best_direction": "",
        "best_net": "",
        "best_combined": "",
        "best_depth": False,
    }

    if not error and all(
        value is not None for value in (pm_yes.ask, pm_no.ask, pd_yes.ask, pd_no.ask)
    ):
        gross_a = 1.0 - float(pm_yes.ask) - float(pd_no.ask)
        pm_fee_a = pm_taker_fee(float(pm_yes.ask))
        pd_fee_a = pd_taker_fee(float(pd_no.ask))
        total_fee_a = pm_fee_a + pd_fee_a
        net_a = gross_a - total_fee_a
        s1_a = net_a * S1_SIZE_SHARES
        s2_a = net_a * S2_SIZE_SHARES
        combined_a = net_a * COMBINED_SIZE_SHARES
        depth_a = bool(
            (pm_yes.ask_size or 0.0) >= COMBINED_SIZE_SHARES
            and (pd_no.ask_size or 0.0) >= COMBINED_SIZE_SHARES
        )

        gross_b = 1.0 - float(pd_yes.ask) - float(pm_no.ask)
        pd_fee_b = pd_taker_fee(float(pd_yes.ask))
        pm_fee_b = pm_taker_fee(float(pm_no.ask))
        total_fee_b = pd_fee_b + pm_fee_b
        net_b = gross_b - total_fee_b
        s1_b = net_b * S1_SIZE_SHARES
        s2_b = net_b * S2_SIZE_SHARES
        combined_b = net_b * COMBINED_SIZE_SHARES
        depth_b = bool(
            (pd_yes.ask_size or 0.0) >= COMBINED_SIZE_SHARES
            and (pm_no.ask_size or 0.0) >= COMBINED_SIZE_SHARES
        )

        if net_a >= net_b:
            best_direction = "pm_yes_pd_no"
            best_net = net_a
            best_combined = combined_a
            best_depth = depth_a
        else:
            best_direction = "pd_yes_pm_no"
            best_net = net_b
            best_combined = combined_b
            best_depth = depth_b

        positive_a = net_a >= EDGE_THRESHOLD and s1_a >= MIN_S1_PROFIT_USD and s2_a >= MIN_S2_PROFIT_USD
        positive_b = net_b >= EDGE_THRESHOLD and s1_b >= MIN_S1_PROFIT_USD and s2_b >= MIN_S2_PROFIT_USD
        if (positive_a and depth_a) or (positive_b and depth_b):
            status = "positive_review_signal_depth_ok"
        elif positive_a or positive_b:
            status = "positive_review_signal_depth_short"

        values.update(
            {
                "gross_a": gross_a,
                "pm_fee_a": pm_fee_a,
                "pd_fee_a": pd_fee_a,
                "total_fee_a": total_fee_a,
                "net_a": net_a,
                "s1_a": s1_a,
                "s2_a": s2_a,
                "combined_a": combined_a,
                "depth_a": depth_a,
                "gross_b": gross_b,
                "pd_fee_b": pd_fee_b,
                "pm_fee_b": pm_fee_b,
                "total_fee_b": total_fee_b,
                "net_b": net_b,
                "s1_b": s1_b,
                "s2_b": s2_b,
                "combined_b": combined_b,
                "depth_b": depth_b,
                "best_direction": best_direction,
                "best_net": best_net,
                "best_combined": best_combined,
                "best_depth": best_depth,
            }
        )
    elif not error:
        error = "missing_one_or_more_top_asks"
        status = "fresh_quote_error"

    return {
        "run_id": run,
        "iteration": iteration,
        "timestamp": timestamp,
        "team": team,
        "team_label": TEAM_LABELS[team],
        "mapping_status": source_row.get("mapping_status", ""),
        "pm_market_id": source_row.get("pm_market_id", ""),
        "pd_market_id": source_row.get("pd_market_id", ""),
        "pm_token_yes": source_row.get("pm_token_yes", ""),
        "pm_token_no": source_row.get("pm_token_no", ""),
        "pm_yes_bid1": fmt(pm_yes.bid),
        "pm_yes_ask1": fmt(pm_yes.ask),
        "pm_yes_bid_size1": fmt(pm_yes.bid_size, 4),
        "pm_yes_ask_size1": fmt(pm_yes.ask_size, 4),
        "pm_no_bid1": fmt(pm_no.bid),
        "pm_no_ask1": fmt(pm_no.ask),
        "pm_no_bid_size1": fmt(pm_no.bid_size, 4),
        "pm_no_ask_size1": fmt(pm_no.ask_size, 4),
        "pd_yes_bid1": fmt(pd_yes.bid),
        "pd_yes_ask1": fmt(pd_yes.ask),
        "pd_yes_bid_size1": fmt(pd_yes.bid_size, 4),
        "pd_yes_ask_size1": fmt(pd_yes.ask_size, 4),
        "pd_no_bid1": fmt(pd_no.bid),
        "pd_no_ask1": fmt(pd_no.ask),
        "pd_no_bid_size1": fmt(pd_no.bid_size, 4),
        "pd_no_ask_size1": fmt(pd_no.ask_size, 4),
        "pd_no_price_source": pd_no_source,
        "gross_edge_pm_yes_pd_no": fmt(values["gross_a"] if isinstance(values["gross_a"], float) else None),
        "pm_fee_pm_yes": fmt(values["pm_fee_a"] if isinstance(values["pm_fee_a"], float) else None),
        "pd_fee_pd_no": fmt(values["pd_fee_a"] if isinstance(values["pd_fee_a"], float) else None),
        "total_fee_pm_yes_pd_no": fmt(values["total_fee_a"] if isinstance(values["total_fee_a"], float) else None),
        "net_edge_pm_yes_pd_no": fmt(values["net_a"] if isinstance(values["net_a"], float) else None),
        "net_edge_pct_pm_yes_pd_no": fmt(values["net_a"] * 100 if isinstance(values["net_a"], float) else None, 4),
        "s1_profit_pm_yes_pd_no": fmt(values["s1_a"] if isinstance(values["s1_a"], float) else None, 4),
        "s2_profit_pm_yes_pd_no": fmt(values["s2_a"] if isinstance(values["s2_a"], float) else None, 4),
        "combined_profit_pm_yes_pd_no": fmt(values["combined_a"] if isinstance(values["combined_a"], float) else None, 4),
        "depth_pass_pm_yes_pd_no": values["depth_a"],
        "gross_edge_pd_yes_pm_no": fmt(values["gross_b"] if isinstance(values["gross_b"], float) else None),
        "pd_fee_pd_yes": fmt(values["pd_fee_b"] if isinstance(values["pd_fee_b"], float) else None),
        "pm_fee_pm_no": fmt(values["pm_fee_b"] if isinstance(values["pm_fee_b"], float) else None),
        "total_fee_pd_yes_pm_no": fmt(values["total_fee_b"] if isinstance(values["total_fee_b"], float) else None),
        "net_edge_pd_yes_pm_no": fmt(values["net_b"] if isinstance(values["net_b"], float) else None),
        "net_edge_pct_pd_yes_pm_no": fmt(values["net_b"] * 100 if isinstance(values["net_b"], float) else None, 4),
        "s1_profit_pd_yes_pm_no": fmt(values["s1_b"] if isinstance(values["s1_b"], float) else None, 4),
        "s2_profit_pd_yes_pm_no": fmt(values["s2_b"] if isinstance(values["s2_b"], float) else None, 4),
        "combined_profit_pd_yes_pm_no": fmt(values["combined_b"] if isinstance(values["combined_b"], float) else None, 4),
        "depth_pass_pd_yes_pm_no": values["depth_b"],
        "best_direction_by_net_edge": values["best_direction"],
        "best_net_edge": fmt(values["best_net"] if isinstance(values["best_net"], float) else None),
        "best_net_edge_pct": fmt(values["best_net"] * 100 if isinstance(values["best_net"], float) else None, 4),
        "best_combined_profit": fmt(values["best_combined"] if isinstance(values["best_combined"], float) else None, 4),
        "best_depth_pass": values["best_depth"],
        "status": status,
        "pm_orderbook_ok": bool(pm_yes.ok and pm_no.ok),
        "pd_orderbook_ok": bool(pd_yes.ok and pd_no.ok),
        "root_stop_present": ROOT_STOP_FILE.exists(),
        "execution_v3_stop_present": EXECUTION_V3_STOP_FILE.exists(),
        "error": error,
        "notes": ";".join(notes),
    }


def scan_iteration(run: str, iteration: int, rows_by_team: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    timestamp = now_iso()
    output_rows: list[dict[str, Any]] = []
    for team in TARGET_TEAMS:
        source = rows_by_team[team]
        if source.get("mapping_status") != "matched":
            empty = TopBook(None, None, None, None, False, "mapping_not_matched")
            output_rows.append(
                compute_row(
                    run=run,
                    iteration=iteration,
                    timestamp=timestamp,
                    source_row=source,
                    pm_yes=empty,
                    pm_no=empty,
                    pd_yes=empty,
                    pd_no=empty,
                    pd_no_source="UNKNOWN / NEEDS_RECHECK",
                    error="mapping_not_matched",
                )
            )
            continue

        pm_yes = fetch_pm_top(source["pm_token_yes"])
        pm_no = fetch_pm_top(source["pm_token_no"])
        pd_yes, pd_no, pd_no_source, pd_error = fetch_pd_yes_no(source["pd_market_id"])
        errors = [item for item in (pm_yes.error, pm_no.error, pd_error) if item]
        output_rows.append(
            compute_row(
                run=run,
                iteration=iteration,
                timestamp=timestamp,
                source_row=source,
                pm_yes=pm_yes,
                pm_no=pm_no,
                pd_yes=pd_yes,
                pd_no=pd_no,
                pd_no_source=pd_no_source,
                error=";".join(errors),
            )
        )
    return output_rows


def append_rows(path: Path, rows: list[dict[str, Any]], *, write_header: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def load_watcher_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_summary(
    *,
    path: Path,
    run: str,
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    interval_seconds: float,
    rows: list[dict[str, str]],
) -> None:
    status_counts = Counter(row.get("status", "") for row in rows)
    iterations = sorted({row.get("iteration", "") for row in rows if row.get("iteration", "")})
    error_rows = [row for row in rows if row.get("error")]
    positive_rows = [
        row for row in rows if str(row.get("status", "")).startswith("positive_review_signal")
    ]
    depth_ok_positive_rows = [
        row for row in positive_rows if row.get("best_depth_pass", "").lower() == "true"
    ]
    best_rows = [row for row in rows if to_float(row.get("best_net_edge", "")) is not None]
    best_row = max(best_rows, key=lambda row: to_float(row["best_net_edge"]) or -999) if best_rows else None

    per_team: dict[str, dict[str, Any]] = defaultdict(dict)
    for team in TARGET_TEAMS:
        team_rows = [row for row in rows if row.get("team") == team]
        numeric_edges = [to_float(row.get("best_net_edge", "")) for row in team_rows]
        numeric_edges = [edge for edge in numeric_edges if edge is not None]
        per_team[team] = {
            "rows": len(team_rows),
            "positive": sum(1 for row in team_rows if str(row.get("status", "")).startswith("positive_review_signal")),
            "depth_ok_positive": sum(
                1
                for row in team_rows
                if str(row.get("status", "")).startswith("positive_review_signal")
                and row.get("best_depth_pass", "").lower() == "true"
            ),
            "max_edge": max(numeric_edges) if numeric_edges else None,
            "min_edge": min(numeric_edges) if numeric_edges else None,
            "last_status": team_rows[-1].get("status", "") if team_rows else "",
            "last_best_direction": team_rows[-1].get("best_direction_by_net_edge", "") if team_rows else "",
        }

    lines = [
        "# MVP3-B v1 Fresh Scanner Summary",
        "",
        f"- run_id: {run}",
        f"- started_at: {started_at}",
        f"- ended_at: {ended_at}",
        f"- requested_duration_seconds: {duration_seconds}",
        f"- interval_seconds: {interval_seconds}",
        f"- input_csv: `{INPUT_CSV.relative_to(PROJECT_ROOT)}`",
        f"- watcher_csv: `{WATCHER_CSV.relative_to(PROJECT_ROOT)}`",
        "- universe: USA, France, Portugal",
        "- live_allowed: false",
        "- orders_submitted: false",
        "- execution_v3_called: false",
        "- formal_trade_candidates_generated: false",
        "- stop_files_deleted: false",
        "",
        "## API Paths",
        "",
        "- PM fresh quote: `https://clob.polymarket.com/book?token_id=<token_id>`",
        f"- Predict.fun fresh quote: `{pd_api_base()}/v1/markets/<market_id>/orderbook`",
        "",
        "## Fee And Size Assumptions",
        "",
        f"- PM fee rate: {PM_FEE_RATE}",
        "- PM fee uses default sports fee rate 0.03 and still needs market-level verification.",
        f"- PD fee rate: {PD_FEE_RATE}",
        f"- PD fee discount multiplier: {PD_FEE_DISCOUNT_MULTIPLIER}",
        f"- S1 size: {S1_SIZE_SHARES} shares",
        f"- S2 size: {S2_SIZE_SHARES} shares",
        f"- Combined depth requirement: {COMBINED_SIZE_SHARES} shares",
        "",
        "## Run Results",
        "",
        f"- iterations_completed: {len(iterations)}",
        f"- watcher_rows: {len(rows)}",
        f"- fresh_quote_error_rows: {len(error_rows)}",
        f"- positive_review_signal_rows: {len(positive_rows)}",
        f"- positive_review_signal_depth_ok_rows: {len(depth_ok_positive_rows)}",
        f"- status_counts: {dict(status_counts)}",
    ]

    if best_row:
        lines.extend(
            [
                f"- max_best_net_edge: {best_row['team']} / {best_row['best_direction_by_net_edge']} / {best_row['best_net_edge']} ({best_row['best_net_edge_pct']}%)",
                f"- max_best_combined_profit: {best_row['best_combined_profit']}",
                f"- max_best_depth_pass: {best_row['best_depth_pass']}",
            ]
        )
    else:
        lines.append("- max_best_net_edge: unavailable")

    lines.extend(["", "## Per-Team Summary", "", "| team | rows | positive | depth_ok_positive | max_edge | min_edge | last_direction | last_status |", "|---|---:|---:|---:|---:|---:|---|---|"])
    for team in TARGET_TEAMS:
        item = per_team[team]
        lines.append(
            f"| {TEAM_LABELS[team]} | {item['rows']} | {item['positive']} | {item['depth_ok_positive']} | "
            f"{fmt(item['max_edge'])} | {fmt(item['min_edge'])} | {item['last_best_direction']} | {item['last_status']} |"
        )

    lines.extend(["", "## Errors", ""])
    if error_rows:
        error_counts = Counter(row.get("error", "") for row in error_rows)
        for error, count in error_counts.most_common():
            lines.append(f"- {count}x {error}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Review Conclusion",
            "",
            "- This is watcher output only, not a trade candidate file.",
            "- MVP3 agent boundary remains scanner / fresh quote / opportunity review only.",
            "- Live trade readiness: NOT_READY",
            "- Reason: no execution, no live adapter, no exact fill verification, no balance/position handling, and PM/PD fee/freshness/settlement still need verification.",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP3-B v1 USA/France/Portugal fresh scanner.")
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration_seconds <= 0:
        raise SystemExit("--duration-seconds must be positive")
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")

    pm.load_env()
    rows_by_team = load_target_rows()
    run = run_id()
    started_at = now_iso()
    start_monotonic = time.monotonic()
    iteration = 0
    if WATCHER_CSV.exists():
        WATCHER_CSV.unlink()

    while True:
        iteration += 1
        rows = scan_iteration(run, iteration, rows_by_team)
        append_rows(WATCHER_CSV, rows, write_header=iteration == 1)
        print(
            f"iteration={iteration} rows={len(rows)} "
            f"statuses={dict(Counter(row['status'] for row in rows))}",
            flush=True,
        )

        elapsed = time.monotonic() - start_monotonic
        if elapsed >= args.duration_seconds:
            break
        sleep_for = min(args.interval_seconds, max(0.0, args.duration_seconds - elapsed))
        if sleep_for > 0:
            time.sleep(sleep_for)

    ended_at = now_iso()
    watcher_rows = load_watcher_rows(WATCHER_CSV)
    write_summary(
        path=SUMMARY_MD,
        run=run,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
        rows=watcher_rows,
    )
    print(f"wrote={WATCHER_CSV}")
    print(f"wrote={SUMMARY_MD}")
    print("live_allowed=false orders_submitted=false execution_v3_called=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
