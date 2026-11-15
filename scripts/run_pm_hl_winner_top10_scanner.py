from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.mvp2_scanner.market_mapper import (  # noqa: E402
    discover_pm_champion_markets,
    normalize_name,
)
from src.strategies.pm_hl.opportunity_model import HL_TAKER_FEE, pm_fee  # noqa: E402


TOP10_TEAMS = [
    "France",
    "Argentina",
    "Spain",
    "England",
    "Portugal",
    "Brazil",
    "Netherlands",
    "Germany",
    "Colombia",
    "USA",
]

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_winner_top10"
HL_CHAMPION_MARKET_NAME = "2026 World Cup Champion"
S1_SIZE_SHARES = 20.0
S2_SIZE_SHARES = 20.0
COMBINED_SIZE_SHARES = S1_SIZE_SHARES + S2_SIZE_SHARES

MAPPING_FIELDS = [
    "team",
    "pm_market_slug",
    "hl_market_name",
    "pm_outcome",
    "hl_outcome",
    "rule_match_score",
    "can_compare",
    "blocked_reason",
    "checked_at",
]

QUOTE_FIELDS = [
    "team",
    "pm_yes_bid",
    "pm_yes_ask",
    "pm_no_bid",
    "pm_no_ask",
    "pm_yes_depth",
    "pm_no_depth",
    "hl_yes_bid",
    "hl_yes_ask",
    "hl_no_bid",
    "hl_no_ask",
    "hl_yes_depth",
    "hl_no_depth",
    "no_side_available",
    "synthetic_no_used",
    "quote_ok",
    "quote_error",
    "checked_at",
]

EDGE_FIELDS = [
    "candidate_id",
    "iteration",
    "team",
    "direction",
    "pm_leg",
    "hl_leg",
    "pm_price",
    "hl_price",
    "pm_depth",
    "hl_depth",
    "gross_edge",
    "fee",
    "net_edge",
    "capacity_shares",
    "capacity_usd",
    "estimated_profit_usd",
    "candidate_flag",
    "excluded_flag",
    "excluded_reason",
    "blocked_reason",
    "checked_at",
]


@dataclass(frozen=True)
class BookQuote:
    bid: float | None = None
    bid_size: float | None = None
    ask: float | None = None
    ask_size: float | None = None
    error: str = ""

    @property
    def readable(self) -> bool:
        return not self.error and (
            self.bid is not None
            or self.ask is not None
            or self.bid_size is not None
            or self.ask_size is not None
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_exclude_teams(raw: str) -> set[str]:
    return {normalize_name(item.strip()) for item in raw.split(",") if item.strip()}


def hl_champion_question() -> tuple[dict[str, Any] | None, dict[int, dict[str, Any]]]:
    meta = hl.info({"type": "outcomeMeta"})
    outcomes = {
        int(row["outcome"]): row
        for row in meta.get("outcomes", [])
        if isinstance(row, dict) and row.get("outcome") is not None
    }
    for question in meta.get("questions", []):
        if str(question.get("name") or "").lower() == HL_CHAMPION_MARKET_NAME.lower():
            return question, outcomes
    return None, outcomes


def hl_champion_outcomes_by_norm(
    question: dict[str, Any] | None,
    outcomes: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not question:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for outcome_id in question.get("namedOutcomes", []):
        outcome = outcomes.get(int(outcome_id))
        if not outcome:
            continue
        label = str(outcome.get("name") or "")
        rows[normalize_name(label)] = {
            "outcome_id": int(outcome_id),
            "label": label,
            "yes_coin": f"#{int(outcome_id) * 10}",
            "no_coin": f"#{int(outcome_id) * 10 + 1}",
            "description": str(outcome.get("description") or question.get("description") or ""),
        }
    return rows


def top_pm_book(token: str) -> BookQuote:
    try:
        bids, asks, _raw = pm.book(token)
        bid, bid_size = bids[0] if bids else (None, None)
        ask, ask_size = asks[0] if asks else (None, None)
        return BookQuote(bid=bid, bid_size=bid_size, ask=ask, ask_size=ask_size)
    except Exception as exc:
        return BookQuote(error=f"pm_book_error:{str(exc)[:160]}")


def top_hl_book(coin: str) -> BookQuote:
    try:
        bids, asks = hl.coin_book(coin)
        bid, bid_size = bids[0] if bids else (None, None)
        ask, ask_size = asks[0] if asks else (None, None)
        return BookQuote(bid=bid, bid_size=bid_size, ask=ask, ask_size=ask_size)
    except Exception as exc:
        return BookQuote(error=f"hl_book_error:{str(exc)[:160]}")


def blocked_reason_for(
    *,
    pm_row: dict[str, Any] | None,
    hl_row: dict[str, Any] | None,
    hl_question: dict[str, Any] | None,
) -> str:
    reasons: list[str] = []
    if not pm_row:
        reasons.append("pm_world_cup_winner_market_not_found")
    if not hl_question:
        reasons.append("hl_2026_world_cup_champion_market_not_found")
    if not hl_row:
        reasons.append("hl_country_outcome_not_found")
    if pm_row:
        question = str(pm_row.get("question") or "").lower()
        if "world cup" not in question or "win" not in question:
            reasons.append("pm_rule_not_world_cup_winner")
        for forbidden in ("round of 32", "advance", "qualify", "90 minutes", "moneyline"):
            if forbidden in question:
                reasons.append(f"pm_rule_blocked_{forbidden.replace(' ', '_')}")
    if hl_question:
        name = str(hl_question.get("name") or "").lower()
        if name != HL_CHAMPION_MARKET_NAME.lower():
            reasons.append("hl_rule_not_2026_world_cup_champion")
    return ",".join(reasons)


def snapshot(top_n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    checked_at = now_iso()
    teams = TOP10_TEAMS[:top_n]
    pm.load_env()
    hl.load_env()

    pm_markets = discover_pm_champion_markets(pages=20)
    hl_question, hl_outcomes = hl_champion_question()
    hl_markets = hl_champion_outcomes_by_norm(hl_question, hl_outcomes)

    mapping_rows: list[dict[str, Any]] = []
    quote_rows: list[dict[str, Any]] = []

    for team in teams:
        key = normalize_name(team)
        pm_row = pm_markets.get(key)
        hl_row = hl_markets.get(key)
        blocked = blocked_reason_for(pm_row=pm_row, hl_row=hl_row, hl_question=hl_question)
        can_compare = not blocked
        rule_match_score = 0.95 if can_compare else 0.0

        mapping_rows.append(
            {
                "team": team,
                "pm_market_slug": str((pm_row or {}).get("slug") or ""),
                "hl_market_name": HL_CHAMPION_MARKET_NAME if hl_question else "",
                "pm_outcome": str((pm_row or {}).get("outcome") or ""),
                "hl_outcome": str((hl_row or {}).get("label") or ""),
                "rule_match_score": rule_match_score,
                "can_compare": can_compare,
                "blocked_reason": blocked,
                "checked_at": checked_at,
            }
        )

        pm_yes = top_pm_book(str(pm_row.get("yes_token"))) if pm_row and can_compare else BookQuote()
        pm_no = top_pm_book(str(pm_row.get("no_token"))) if pm_row and can_compare else BookQuote()
        hl_yes = top_hl_book(str(hl_row.get("yes_coin"))) if hl_row and can_compare else BookQuote()
        hl_no = top_hl_book(str(hl_row.get("no_coin"))) if hl_row and can_compare else BookQuote()

        no_side_available = can_compare and not hl_no.readable
        quote_errors = [book.error for book in (pm_yes, pm_no, hl_yes, hl_no) if book.error]
        if not can_compare and blocked:
            quote_errors.append(blocked)

        quote_ok = can_compare and pm_yes.readable and pm_no.readable and hl_yes.readable and hl_no.readable
        quote_rows.append(
            {
                "team": team,
                "pm_yes_bid": pm_yes.bid,
                "pm_yes_ask": pm_yes.ask,
                "pm_no_bid": pm_no.bid,
                "pm_no_ask": pm_no.ask,
                "pm_yes_depth": pm_yes.ask_size,
                "pm_no_depth": pm_no.ask_size,
                "hl_yes_bid": hl_yes.bid,
                "hl_yes_ask": hl_yes.ask,
                "hl_no_bid": hl_no.bid,
                "hl_no_ask": hl_no.ask,
                "hl_yes_depth": hl_yes.ask_size,
                "hl_no_depth": hl_no.ask_size,
                "no_side_available": no_side_available,
                "synthetic_no_used": False,
                "quote_ok": quote_ok,
                "quote_error": ",".join(quote_errors),
                "checked_at": checked_at,
            }
        )

    summary = {
        "checked_at": checked_at,
        "pm_winner_market_found": any(row.get("pm_market_slug") for row in mapping_rows),
        "hl_champion_market_found": bool(hl_question),
        "top_n": len(teams),
        "mapping_success_count": sum(1 for row in mapping_rows if row["can_compare"]),
        "mapping_failed": [row["team"] for row in mapping_rows if not row["can_compare"]],
        "pm_book_readable_count": sum(
            1
            for row in quote_rows
            if row["pm_yes_ask"] not in ("", None) and row["pm_no_ask"] not in ("", None)
        ),
        "hl_book_readable_count": sum(
            1
            for row in quote_rows
            if row["hl_yes_ask"] not in ("", None) and row["hl_no_ask"] not in ("", None)
        ),
        "hl_no_side_missing_count": sum(1 for row in quote_rows if bool(row["no_side_available"])),
        "quote_ok_count": sum(1 for row in quote_rows if bool(row["quote_ok"])),
    }
    return mapping_rows, quote_rows, summary


def write_step1_summary(path: Path, summary: dict[str, Any], mapping_rows: list[dict[str, Any]]) -> None:
    can_step2 = (
        summary["mapping_success_count"] == summary["top_n"]
        and summary["quote_ok_count"] == summary["top_n"]
        and summary["hl_no_side_missing_count"] == 0
    )
    failed_lines = "\n".join(
        f"- {row['team']}: {row['blocked_reason']}"
        for row in mapping_rows
        if not row["can_compare"]
    ) or "- none"
    content = f"""# MVP2-C Winner Top10 Step 1 Summary

- checked_at: {summary['checked_at']}
- mode: snapshot_only
- live_allowed: false
- submit_order_called: false

## Discovery

- PM Winner market found: {str(summary['pm_winner_market_found']).lower()}
- HL Champion market found: {str(summary['hl_champion_market_found']).lower()}
- Top10 requested: {summary['top_n']}
- Top10 matched successfully: {summary['mapping_success_count']}

## Mapping Failures

{failed_lines}

## Quote Readability

- PM yes/no book readable: {summary['pm_book_readable_count']}/{summary['top_n']}
- HL yes/no book readable: {summary['hl_book_readable_count']}/{summary['top_n']}
- HL NO side missing: {str(summary['hl_no_side_missing_count'] > 0).lower()} ({summary['hl_no_side_missing_count']}/{summary['top_n']})
- synthetic_no_used: false

## Step 2 Readiness

- can_enter_step2_edge_scanner: {str(can_step2).lower()}

## Notes

- This is not 1v1 Moneyline.
- This is not round-of-32, advance, qualify, or 90-minute market logic.
- No live process was started.
- No orders were submitted.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_edge_row(
    *,
    team: str,
    direction: str,
    pm_leg: str,
    hl_leg: str,
    pm_price: float | None,
    hl_price: float | None,
    pm_depth: float | None,
    hl_depth: float | None,
    threshold: float,
    checked_at: str,
    base_blockers: list[str],
    iteration: int,
) -> dict[str, Any]:
    blockers = list(base_blockers)
    if pm_price is None:
        blockers.append("missing_pm_price")
    if hl_price is None:
        blockers.append("missing_hl_price")
    if pm_depth is None:
        blockers.append("missing_pm_depth")
    if hl_depth is None:
        blockers.append("missing_hl_depth")

    if pm_price is None or hl_price is None:
        gross_edge = None
        fee = None
        net_edge = None
        capacity_shares = None
        capacity_usd = None
        estimated_profit_usd = None
    else:
        gross_edge = 1.0 - pm_price - hl_price
        fee = pm_fee(pm_price) + HL_TAKER_FEE
        net_edge = gross_edge - fee
        capacity_shares = min(pm_depth or 0.0, hl_depth or 0.0)
        capacity_usd = capacity_shares * (pm_price + hl_price)
        estimated_profit_usd = net_edge * capacity_shares

    candidate_flag = bool(net_edge is not None and net_edge >= threshold and not blockers)
    return {
        "candidate_id": f"{team}|{direction}|{checked_at}",
        "iteration": iteration,
        "team": team,
        "direction": direction,
        "pm_leg": pm_leg,
        "hl_leg": hl_leg,
        "pm_price": pm_price,
        "hl_price": hl_price,
        "pm_depth": pm_depth,
        "hl_depth": hl_depth,
        "gross_edge": gross_edge,
        "fee": fee,
        "net_edge": net_edge,
        "capacity_shares": capacity_shares,
        "capacity_usd": capacity_usd,
        "estimated_profit_usd": estimated_profit_usd,
        "candidate_flag": candidate_flag,
        "excluded_flag": False,
        "excluded_reason": "",
        "blocked_reason": ",".join(blockers),
        "checked_at": checked_at,
    }


def build_edge_rows_from_files(
    mapping_path: Path,
    quotes_path: Path,
    threshold: float,
    iteration: int,
) -> list[dict[str, Any]]:
    mappings = {row["team"]: row for row in read_csv(mapping_path)}
    rows: list[dict[str, Any]] = []
    for quote in read_csv(quotes_path):
        team = quote["team"]
        mapping = mappings.get(team, {})
        base_blockers: list[str] = []
        if not truthy(mapping.get("can_compare")):
            base_blockers.append(mapping.get("blocked_reason") or "mapping_not_comparable")
        if not truthy(quote.get("quote_ok")):
            base_blockers.append(quote.get("quote_error") or "quote_not_ok")
        if truthy(quote.get("synthetic_no_used")):
            base_blockers.append("synthetic_no_used")
        if truthy(quote.get("no_side_available")):
            base_blockers.append("hl_no_side_unavailable")

        checked_at = quote.get("checked_at") or now_iso()
        rows.append(
            build_edge_row(
                team=team,
                direction="buy_pm_yes_buy_hl_no",
                pm_leg="PM YES",
                hl_leg="HL NO",
                pm_price=as_float(quote.get("pm_yes_ask")),
                hl_price=as_float(quote.get("hl_no_ask")),
                pm_depth=as_float(quote.get("pm_yes_depth")),
                hl_depth=as_float(quote.get("hl_no_depth")),
                threshold=threshold,
                checked_at=checked_at,
                base_blockers=base_blockers,
                iteration=iteration,
            )
        )
        rows.append(
            build_edge_row(
                team=team,
                direction="buy_hl_yes_buy_pm_no",
                pm_leg="PM NO",
                hl_leg="HL YES",
                pm_price=as_float(quote.get("pm_no_ask")),
                hl_price=as_float(quote.get("hl_yes_ask")),
                pm_depth=as_float(quote.get("pm_no_depth")),
                hl_depth=as_float(quote.get("hl_yes_depth")),
                threshold=threshold,
                checked_at=checked_at,
                base_blockers=base_blockers,
                iteration=iteration,
            )
        )
    return rows


def apply_exclusions(rows: list[dict[str, Any]], exclude_norm: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if normalize_name(str(row.get("team") or "")) in exclude_norm:
            copied["excluded_flag"] = True
            copied["excluded_reason"] = "existing_mvp1_position"
        else:
            copied["excluded_flag"] = False
            copied["excluded_reason"] = ""
        out.append(copied)
    return out


def sorted_by_net(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: row["net_edge"] if row["net_edge"] is not None else -999.0,
        reverse=True,
    )


def write_edge_summary(
    path: Path,
    *,
    threshold: float,
    top_n: int,
    edge_rows: list[dict[str, Any]],
    quote_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = sorted_by_net([row for row in edge_rows if row["candidate_flag"]])
    near_miss = sorted_by_net([row for row in edge_rows if not row["candidate_flag"]])
    best_candidate = candidates[0] if candidates else None
    best_near_miss = near_miss[0] if near_miss else None
    real_books = all(
        bool(row.get("quote_ok"))
        and not bool(row.get("synthetic_no_used"))
        and not bool(row.get("no_side_available"))
        for row in quote_rows
    )
    can_step3 = bool(candidates) and real_books
    content = f"""# MVP2-C Winner Top10 Step 2 Edge Summary

- threshold: {threshold}
- threshold_bps: {threshold * 10000}
- fee_assumption: PM fee = 0.03 * price * (1 - price); HL fee = {HL_TAKER_FEE}
- mode: edge_snapshot_only
- live_allowed: false
- submit_order_called: false

## Results

- Top10 total: {top_n}
- edge_rows_count: {len(edge_rows)}
- candidate_count: {len(candidates)}
- near_miss_count: {len(near_miss)}
- best_candidate: {f"{best_candidate['team']} / {best_candidate['direction']} / net_edge={best_candidate['net_edge']}" if best_candidate else "none"}
- best_near_miss_if_no_candidate: {f"{best_near_miss['team']} / {best_near_miss['direction']} / net_edge={best_near_miss['net_edge']}" if best_near_miss and not best_candidate else "not_applicable_candidates_found"}

## Book Source

- PM/HL all using real YES/NO book: {str(real_books).lower()}
- synthetic_no_used: false
- no_fake_price_or_depth: true

## Step 3 Readiness

- can_enter_step3_execution_v1_dry_run: {str(can_step3).lower()}
- recommendation: {"Can proceed to a separate dry-run design review only; do not connect live execution automatically." if can_step3 else "Do not proceed to Execution v1 dry-run unless a real-book candidate exists."}

## Notes

- Direction A: Buy PM YES + Buy HL NO.
- Direction B: Buy HL YES + Buy PM NO.
- No live process was started.
- No orders were submitted.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "candidate_count": len(candidates),
        "near_miss_count": len(near_miss),
        "best_candidate": best_candidate,
        "best_near_miss": best_near_miss,
        "real_books": real_books,
        "can_step3": can_step3,
    }


def write_watch_summary(
    path: Path,
    *,
    threshold: float,
    top_n: int,
    planned_iterations: int,
    completed_iterations: int,
    watch_minutes: float,
    interval_seconds: float,
    exclude_teams: str,
    all_candidates: list[dict[str, Any]],
    tradable_candidates: list[dict[str, Any]],
    near_miss: list[dict[str, Any]],
) -> None:
    best_all = sorted_by_net(all_candidates)[0] if all_candidates else None
    best_tradable = sorted_by_net(tradable_candidates)[0] if tradable_candidates else None
    content = f"""# MVP2-C Winner Top10 Watch Summary

- mode: watch_snapshot_only
- watch_minutes: {watch_minutes}
- interval_seconds: {interval_seconds}
- planned_iterations: {planned_iterations}
- completed_iterations: {completed_iterations}
- threshold: {threshold}
- threshold_bps: {threshold * 10000}
- top_n: {top_n}
- exclude_teams: {exclude_teams or "none"}
- live_allowed: false
- submit_order_called: false
- real_order_sent: false

## Results

- all_top10_candidates_count: {len(all_candidates)}
- tradable_candidates_after_exclude_count: {len(tradable_candidates)}
- near_miss_count: {len(near_miss)}
- best_all_candidate: {f"{best_all['team']} / {best_all['direction']} / net_edge={best_all['net_edge']}" if best_all else "none"}
- best_tradable_candidate: {f"{best_tradable['team']} / {best_tradable['direction']} / net_edge={best_tradable['net_edge']}" if best_tradable else "none"}

## Safety

- synthetic_no_used: false
- fake_price_or_depth_used: false
- execution_v1_connected: false
- adapter_submit_enabled: false
- predict_fun_touched: false
- mvp1_modified: false
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def dry_run_payload_from_revalidated(
    candidate: dict[str, Any] | None,
    revalidated_rows: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    if candidate is None:
        return {
            "payloads": [],
            "payload_generated": False,
            "blocked_reason": "no_tradable_candidate",
            "submit_order_called": False,
            "real_order_sent": False,
            "combined_size_shares": COMBINED_SIZE_SHARES,
        }

    match = next(
        (
            row
            for row in revalidated_rows
            if row.get("team") == candidate.get("team")
            and row.get("direction") == candidate.get("direction")
        ),
        None,
    )
    if match is None:
        return {
            "payloads": [],
            "payload_generated": False,
            "blocked_reason": "candidate_not_found_in_revalidation",
            "submit_order_called": False,
            "real_order_sent": False,
            "combined_size_shares": COMBINED_SIZE_SHARES,
        }

    blocked: list[str] = []
    if bool(match.get("excluded_flag")):
        blocked.append(str(match.get("excluded_reason") or "excluded"))
    if (match.get("net_edge") or -999.0) < threshold:
        blocked.append("revalidated_net_edge_below_threshold")
    if (match.get("pm_depth") or 0.0) < COMBINED_SIZE_SHARES:
        blocked.append("pm_depth_below_40")
    if (match.get("hl_depth") or 0.0) < COMBINED_SIZE_SHARES:
        blocked.append("hl_depth_below_40")
    if match.get("blocked_reason"):
        blocked.append(str(match["blocked_reason"]))

    payload = {
        "candidate_id": match["candidate_id"],
        "team": match["team"],
        "direction": match["direction"],
        "pm_leg": match["pm_leg"],
        "hl_leg": match["hl_leg"],
        "pm_price": match["pm_price"],
        "hl_price": match["hl_price"],
        "pm_depth": match["pm_depth"],
        "hl_depth": match["hl_depth"],
        "s1_size_shares": S1_SIZE_SHARES,
        "s2_size_shares": S2_SIZE_SHARES,
        "combined_size_shares": COMBINED_SIZE_SHARES,
        "gross_edge": match["gross_edge"],
        "fee": match["fee"],
        "net_edge": match["net_edge"],
        "estimated_profit_usd": (match["net_edge"] or 0.0) * COMBINED_SIZE_SHARES,
        "excluded_flag": match["excluded_flag"],
        "excluded_reason": match["excluded_reason"],
        "revalidation_pass": not blocked,
        "order_type": "limit",
        "time_in_force": "FOK",
        "submit_order_called": False,
        "real_order_sent": False,
        "blocked_reason": ",".join(blocked),
    }
    return {
        "payloads": [payload],
        "payload_generated": True,
        "blocked_reason": payload["blocked_reason"],
        "submit_order_called": False,
        "real_order_sent": False,
        "combined_size_shares": COMBINED_SIZE_SHARES,
    }


def write_dry_run_summary(path: Path, payload_preview: dict[str, Any]) -> None:
    payloads = payload_preview.get("payloads") or []
    first = payloads[0] if payloads else {}
    content = f"""# MVP2-C Winner Top10 Dry-Run Summary

- payload_generated: {str(bool(payload_preview.get("payload_generated"))).lower()}
- combined_size_shares: {payload_preview.get("combined_size_shares")}
- submit_order_called: {str(bool(payload_preview.get("submit_order_called"))).lower()}
- real_order_sent: {str(bool(payload_preview.get("real_order_sent"))).lower()}
- revalidation_pass: {str(bool(first.get("revalidation_pass"))).lower() if first else "false"}
- blocked_reason: {payload_preview.get("blocked_reason") or "none"}

## Selected Payload

- candidate_id: {first.get("candidate_id", "")}
- team: {first.get("team", "")}
- direction: {first.get("direction", "")}
- net_edge: {first.get("net_edge", "")}
- pm_depth: {first.get("pm_depth", "")}
- hl_depth: {first.get("hl_depth", "")}
- order_type: {first.get("order_type", "")}
- time_in_force: {first.get("time_in_force", "")}

## Safety

- live_allowed: false
- adapter_submit_enabled: false
- fake_price_or_depth_used: false
- synthetic_no_used: false
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MVP2-C Winner Top10 scanner: PM Winner vs HL Champion quotes and dry-run preview.",
    )
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.0005)
    parser.add_argument("--watch-minutes", type=float, default=0.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--exclude-teams", default="")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--report", action="store_true")
    return parser.parse_args()


def run_iteration(args: argparse.Namespace, iteration: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    mapping_rows, quote_rows, summary = snapshot(max(0, min(args.top_n, len(TOP10_TEAMS))))
    mapping_path = args.output_dir / "winner_top10_mapping.csv"
    quotes_path = args.output_dir / "winner_top10_quotes.csv"
    summary_path = args.output_dir / "winner_top10_summary.md"
    write_csv(mapping_path, MAPPING_FIELDS, mapping_rows)
    write_csv(quotes_path, QUOTE_FIELDS, quote_rows)
    write_step1_summary(summary_path, summary, mapping_rows)
    return build_edge_rows_from_files(mapping_path, quotes_path, args.threshold, iteration), quote_rows, summary


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    top_n = max(0, min(args.top_n, len(TOP10_TEAMS)))
    planned_iterations = (
        max(1, int((args.watch_minutes * 60 + args.interval_seconds - 1) // args.interval_seconds))
        if args.watch_minutes > 0
        else 1
    )
    exclude_norm = parse_exclude_teams(args.exclude_teams)

    all_edge_rows: list[dict[str, Any]] = []
    latest_quote_rows: list[dict[str, Any]] = []
    latest_summary: dict[str, Any] = {}
    for iteration in range(1, planned_iterations + 1):
        edge_rows, quote_rows, summary = run_iteration(args, iteration)
        all_edge_rows.extend(apply_exclusions(edge_rows, exclude_norm))
        latest_quote_rows = quote_rows
        latest_summary = summary
        if args.report:
            candidates_now = [row for row in edge_rows if row["candidate_flag"]]
            print(
                f"iteration {iteration}/{planned_iterations}: "
                f"candidates={len(candidates_now)} checked_at={summary['checked_at']}"
            )
        if iteration < planned_iterations:
            time.sleep(args.interval_seconds)

    candidates = sorted_by_net([row for row in all_edge_rows if row["candidate_flag"]])
    candidates_after_exclude = sorted_by_net([row for row in candidates if not bool(row["excluded_flag"])])
    near_miss = sorted_by_net([row for row in all_edge_rows if not row["candidate_flag"]])

    edges_path = args.output_dir / "winner_top10_edges.csv"
    watch_log_path = args.output_dir / "winner_top10_watch_log.csv"
    candidates_path = args.output_dir / "winner_top10_candidates.csv"
    candidates_after_exclude_path = args.output_dir / "winner_top10_candidates_after_exclude.csv"
    near_miss_path = args.output_dir / "winner_top10_near_miss.csv"
    edge_summary_path = args.output_dir / "winner_top10_edge_summary.md"
    watch_summary_path = args.output_dir / "winner_top10_watch_summary.md"
    dry_run_payload_path = args.output_dir / "winner_top10_dry_run_payload_preview.json"
    dry_run_summary_path = args.output_dir / "winner_top10_dry_run_summary.md"

    write_csv(edges_path, EDGE_FIELDS, all_edge_rows)
    write_csv(watch_log_path, EDGE_FIELDS, all_edge_rows)
    write_csv(candidates_path, EDGE_FIELDS, candidates)
    write_csv(candidates_after_exclude_path, EDGE_FIELDS, candidates_after_exclude)
    write_csv(near_miss_path, EDGE_FIELDS, near_miss)
    edge_summary = write_edge_summary(
        edge_summary_path,
        threshold=args.threshold,
        top_n=latest_summary["top_n"],
        edge_rows=all_edge_rows,
        quote_rows=latest_quote_rows,
    )
    write_watch_summary(
        watch_summary_path,
        threshold=args.threshold,
        top_n=top_n,
        planned_iterations=planned_iterations,
        completed_iterations=planned_iterations,
        watch_minutes=args.watch_minutes,
        interval_seconds=args.interval_seconds,
        exclude_teams=args.exclude_teams,
        all_candidates=candidates,
        tradable_candidates=candidates_after_exclude,
        near_miss=near_miss,
    )

    reval_edges, _reval_quotes, _reval_summary = run_iteration(args, planned_iterations + 1)
    reval_edges = apply_exclusions(reval_edges, exclude_norm)
    payload_preview = dry_run_payload_from_revalidated(
        candidates_after_exclude[0] if candidates_after_exclude else None,
        reval_edges,
        args.threshold,
    )
    dry_run_payload_path.write_text(json.dumps(payload_preview, indent=2, sort_keys=True), encoding="utf-8")
    write_dry_run_summary(dry_run_summary_path, payload_preview)

    if args.report:
        print("MVP2-C Winner Top10 Step 1+2+3 watcher (READ ONLY)")
        print(f"PM Winner market found: {latest_summary['pm_winner_market_found']}")
        print(f"HL Champion market found: {latest_summary['hl_champion_market_found']}")
        print(f"Top10 matched: {latest_summary['mapping_success_count']}/{latest_summary['top_n']}")
        print(f"PM yes/no readable: {latest_summary['pm_book_readable_count']}/{latest_summary['top_n']}")
        print(f"HL yes/no readable: {latest_summary['hl_book_readable_count']}/{latest_summary['top_n']}")
        print(f"HL NO side missing: {latest_summary['hl_no_side_missing_count']}/{latest_summary['top_n']}")
        print(f"threshold: {args.threshold}")
        print(f"all_top10_candidates: {len(candidates)}")
        print(f"tradable_candidates_after_exclude: {len(candidates_after_exclude)}")
        best = candidates_after_exclude[0] if candidates_after_exclude else (edge_summary["best_candidate"] or edge_summary["best_near_miss"])
        if best:
            print(f"best edge: {best['team']} {best['direction']} net_edge={best['net_edge']}")
        print(f"CSV candidates: {candidates_path}")
        print(f"CSV candidates after exclude: {candidates_after_exclude_path}")
        print(f"CSV near_miss: {near_miss_path}")
        print(f"Watch log: {watch_log_path}")
        print(f"Watch summary: {watch_summary_path}")
        print(f"Dry-run payload: {dry_run_payload_path}")
        print(f"Dry-run summary: {dry_run_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
