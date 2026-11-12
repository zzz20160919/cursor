from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.clients import polymarket as pm


MONEYLINE_TYPE = "moneyline"


@dataclass(frozen=True)
class TokenBookTop:
    token_id: str
    bid: float | None = None
    bid_size: float | None = None
    ask: float | None = None
    ask_size: float | None = None
    tick_size: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MoneylineMarket:
    label: str
    market_id: str
    market_slug: str
    question: str
    sports_market_type: str
    group_item_title: str
    outcomes: list[str]
    clob_token_ids: list[str]
    outcome_prices: list[str]
    description: str
    resolution_source: str
    yes_book_top: TokenBookTop | None = None
    no_book_top: TokenBookTop | None = None


@dataclass(frozen=True)
class ParentEvent:
    event_id: str
    slug: str
    title: str
    game_id: str | None
    series: str | None
    sport: str | None
    start_time: str | None
    end_date: str | None
    neg_risk: bool
    neg_risk_market_id: str | None
    resolution_source: str | None


@dataclass(frozen=True)
class SportsMoneylineDiscovery:
    discovered_at: str
    parent_event: ParentEvent
    moneyline_markets: list[MoneylineMarket]
    sanity_checks: dict[str, Any] = field(default_factory=dict)
    raw_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _moneyline_label(market: dict[str, Any]) -> str:
    title = str(market.get("groupItemTitle") or "").strip()
    if title.lower().startswith("draw"):
        return "Draw"
    return title


def _expected_moneyline_outcomes(raw_event: dict[str, Any]) -> tuple[str, ...]:
    teams = raw_event.get("teams")
    if isinstance(teams, list) and len(teams) >= 2:
        labels = [str(teams[0].get("name") or ""), "Draw", str(teams[1].get("name") or "")]
        if all(labels):
            return tuple(labels)
    title = str(raw_event.get("title") or "")
    if " vs. " in title:
        left, right = title.split(" vs. ", 1)
        return (left.strip(), "Draw", right.strip())
    if " vs " in title:
        left, right = title.split(" vs ", 1)
        return (left.strip(), "Draw", right.strip())
    return tuple()


def _top_for_token(token_id: str) -> TokenBookTop:
    try:
        bids, asks, raw = pm.book(token_id)
        bid, bid_size = bids[0] if bids else (None, None)
        ask, ask_size = asks[0] if asks else (None, None)
        return TokenBookTop(
            token_id=token_id,
            bid=bid,
            bid_size=bid_size,
            ask=ask,
            ask_size=ask_size,
            tick_size=str(raw.get("tick_size") or "") or None,
        )
    except Exception as exc:
        return TokenBookTop(token_id=token_id, error=str(exc)[:200])


def _parent_event(raw_event: dict[str, Any]) -> ParentEvent:
    series = raw_event.get("series")
    sport = raw_event.get("sport")
    return ParentEvent(
        event_id=str(raw_event.get("id") or ""),
        slug=str(raw_event.get("slug") or ""),
        title=str(raw_event.get("title") or ""),
        game_id=str(raw_event.get("gameId")) if raw_event.get("gameId") is not None else None,
        series=str((series[0] or {}).get("slug") or "") if isinstance(series, list) and series else None,
        sport=str((sport or {}).get("sport") or "") if isinstance(sport, dict) else None,
        start_time=str(raw_event.get("startTime") or raw_event.get("startDate") or "") or None,
        end_date=str(raw_event.get("endDate") or "") or None,
        neg_risk=bool(raw_event.get("negRisk")),
        neg_risk_market_id=str(raw_event.get("negRiskMarketID") or "") or None,
        resolution_source=str(raw_event.get("resolutionSource") or "") or None,
    )


def _moneyline_market(raw_market: dict[str, Any]) -> MoneylineMarket:
    token_ids = _parse_json_list(raw_market.get("clobTokenIds"))
    yes_book = _top_for_token(token_ids[0]) if len(token_ids) >= 1 else None
    no_book = _top_for_token(token_ids[1]) if len(token_ids) >= 2 else None
    return MoneylineMarket(
        label=_moneyline_label(raw_market),
        market_id=str(raw_market.get("id") or ""),
        market_slug=str(raw_market.get("slug") or ""),
        question=str(raw_market.get("question") or ""),
        sports_market_type=str(raw_market.get("sportsMarketType") or ""),
        group_item_title=str(raw_market.get("groupItemTitle") or ""),
        outcomes=_parse_json_list(raw_market.get("outcomes")),
        clob_token_ids=token_ids,
        outcome_prices=_parse_json_list(raw_market.get("outcomePrices")),
        description=str(raw_market.get("description") or ""),
        resolution_source=str(raw_market.get("resolutionSource") or ""),
        yes_book_top=yes_book,
        no_book_top=no_book,
    )


def discover_moneyline(event_slug: str) -> SportsMoneylineDiscovery:
    raw_event = pm.gamma_event_by_slug(event_slug)
    if not raw_event:
        raise ValueError(f"PM sports event not found for slug: {event_slug}")

    raw_moneyline = [
        market
        for market in raw_event.get("markets", [])
        if str(market.get("sportsMarketType") or "") == MONEYLINE_TYPE
    ]
    markets = [_moneyline_market(market) for market in raw_moneyline]
    expected_outcomes = _expected_moneyline_outcomes(raw_event)
    order = {label: index for index, label in enumerate(expected_outcomes)}
    markets = sorted(markets, key=lambda market: order.get(market.label, 99))
    labels = [market.label for market in markets]
    expected = set(expected_outcomes)
    detected = set(labels)
    checks = {
        "moneyline_market_count": len(markets),
        "has_exactly_3_moneyline_markets": len(markets) == 3,
        "moneyline_outcomes_detected": labels,
        "contains_expected_outcomes": expected.issubset(detected),
        "missing_expected_outcomes": sorted(expected - detected),
        "all_markets_have_market_id": all(bool(market.market_id) for market in markets),
        "all_markets_have_clob_token_ids": all(len(market.clob_token_ids) >= 2 for market in markets),
        "all_markets_have_rule_text": all(bool(market.description) for market in markets),
        "all_markets_have_orderbook_top": all(
            market.yes_book_top is not None
            and market.no_book_top is not None
            and not market.yes_book_top.error
            and not market.no_book_top.error
            for market in markets
        ),
    }
    notes = [
        "Only parent-event Moneyline markets are discovered.",
        "Child events such as Exact Score, Totals, Spread, Halftime, and Second Half are intentionally ignored.",
    ]
    return SportsMoneylineDiscovery(
        discovered_at=_now_iso(),
        parent_event=_parent_event(raw_event),
        moneyline_markets=markets,
        sanity_checks=checks,
        raw_notes=notes,
    )


def write_discovery_json(output_dir: Path, discovery: SportsMoneylineDiscovery) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"pm_sports_moneyline_{discovery.parent_event.slug}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(discovery.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_discovery(discovery: SportsMoneylineDiscovery) -> None:
    parent = discovery.parent_event
    checks = discovery.sanity_checks
    print("PM sports Moneyline discovery (READ ONLY)")
    print(
        f"parent_event_slug={parent.slug} "
        f"parent_event_id={parent.event_id} "
        f"game_id={parent.game_id} "
        f"series={parent.series} "
        f"sport={parent.sport}"
    )
    print(
        f"moneyline_market_count={checks.get('moneyline_market_count')} "
        f"moneyline_outcomes_detected={checks.get('moneyline_outcomes_detected')}"
    )
    print(
        "sanity: "
        f"three_way={checks.get('has_exactly_3_moneyline_markets')} "
        f"expected_outcomes={checks.get('contains_expected_outcomes')} "
        f"market_ids={checks.get('all_markets_have_market_id')} "
        f"clob_tokens={checks.get('all_markets_have_clob_token_ids')} "
        f"rules={checks.get('all_markets_have_rule_text')} "
        f"orderbooks={checks.get('all_markets_have_orderbook_top')}"
    )
    for market in discovery.moneyline_markets:
        yes = market.yes_book_top
        no = market.no_book_top
        yes_quote = f"yes_bid={yes.bid} yes_ask={yes.ask}" if yes else "yes_book=missing"
        no_quote = f"no_bid={no.bid} no_ask={no.ask}" if no else "no_book=missing"
        print(
            f"- {market.label}: market_id={market.market_id} slug={market.market_slug} "
            f"tokens={market.clob_token_ids} {yes_quote} {no_quote}"
        )

