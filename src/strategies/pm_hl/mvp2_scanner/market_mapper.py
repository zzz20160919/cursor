from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlencode

from src.strategies.pm_hl.clients import hyperliquid as hl
from src.strategies.pm_hl.clients import polymarket as pm
from src.strategies.pm_hl.mvp2_scanner.scanner_config import (
    GAMMA_API,
    GAMMA_PAGE_SIZE,
)
from src.strategies.pm_hl.mvp2_scanner.schemas import (
    ChampionMarket,
    ChampionUniverseOutcome,
    MatchMarket,
)


ALIASES = {
    "usa": "unitedstates",
    "us": "unitedstates",
    "u s a": "unitedstates",
    "united states": "unitedstates",
    "united states of america": "unitedstates",
    "saudi": "saudiarabia",
    "saudi arabia": "saudiarabia",
    "cote divoire": "ivorycoast",
    "cotedivoire": "ivorycoast",
    "ivory coast": "ivorycoast",
    "korea republic": "southkorea",
    "republic of korea": "southkorea",
    "south korea": "southkorea",
    "new zealand": "newzealand",
    "bosnia herzegovina": "bosniaandherzegovina",
    "curaçao": "curacao",
    "curacao": "curacao",
}


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = ALIASES.get(text, text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _gamma_markets(pages: int) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    for page in range(max(pages, 1)):
        query = urlencode(
            {
                "limit": GAMMA_PAGE_SIZE,
                "offset": page * GAMMA_PAGE_SIZE,
                "active": "true",
                "closed": "false",
                "enableOrderBook": "true",
            }
        )
        batch = pm.http_json(f"{GAMMA_API}/markets?{query}")
        if not isinstance(batch, list) or not batch:
            break
        markets.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < GAMMA_PAGE_SIZE:
            break
    return markets


def _outcome_from_champion_question(market: dict[str, Any]) -> str | None:
    question = str(market.get("question") or "")
    match = re.search(r"^Will\s+(.+?)\s+win the 2026 FIFA World Cup\??$", question, re.I)
    return match.group(1).strip() if match else None


def _is_other_label(label: str) -> bool:
    normalized = normalize_name(label)
    return normalized in {"other", "restofthefield", "field", "fallback", "noneoftheabove"}


def _is_placeholder_label(label: str) -> bool:
    normalized = normalize_name(label)
    return any(marker in normalized for marker in ("tbd", "placeholder", "unknown", "fallback"))


def discover_pm_champion_markets(pages: int) -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for market in _gamma_markets(pages):
        outcome = _outcome_from_champion_question(market)
        token_ids = [str(token) for token in _parse_json_list(market.get("clobTokenIds"))]
        outcomes = [str(item).lower() for item in _parse_json_list(market.get("outcomes"))]
        if not outcome or len(token_ids) < 2:
            continue
        yes_index = outcomes.index("yes") if "yes" in outcomes else 0
        no_index = outcomes.index("no") if "no" in outcomes else 1
        discovered[normalize_name(outcome)] = {
            "outcome": outcome,
            "yes_token": token_ids[yes_index],
            "no_token": token_ids[no_index],
            "slug": market.get("slug"),
            "market_id": str(market.get("id") or ""),
            "question": market.get("question"),
            "end_date": market.get("endDate"),
        }
    return discovered


def discover_pm_champion_universe(pages: int) -> list[ChampionUniverseOutcome]:
    outcomes: list[ChampionUniverseOutcome] = []
    for market in _gamma_markets(pages):
        outcome = _outcome_from_champion_question(market)
        token_ids = [str(token) for token in _parse_json_list(market.get("clobTokenIds"))]
        market_outcomes = [str(item).lower() for item in _parse_json_list(market.get("outcomes"))]
        if not outcome or len(token_ids) < 2:
            continue
        yes_index = market_outcomes.index("yes") if "yes" in market_outcomes else 0
        no_index = market_outcomes.index("no") if "no" in market_outcomes else 1
        outcomes.append(
            ChampionUniverseOutcome(
                venue="polymarket",
                outcome=outcome,
                normalized_outcome=normalize_name(outcome),
                yes_token=token_ids[yes_index],
                no_token=token_ids[no_index],
                market_id=str(market.get("id") or ""),
                slug=str(market.get("slug") or ""),
                title=str(market.get("question") or ""),
                is_other=_is_other_label(outcome),
                is_placeholder=_is_placeholder_label(outcome),
            )
        )
    return outcomes


def _hl_meta() -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    meta = hl.info({"type": "outcomeMeta"})
    outcomes = {
        int(row["outcome"]): row
        for row in meta.get("outcomes", [])
        if isinstance(row, dict) and row.get("outcome") is not None
    }
    questions = [row for row in meta.get("questions", []) if isinstance(row, dict)]
    return outcomes, questions


def _hl_champion_question(questions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            question
            for question in questions
            if str(question.get("name") or "").lower() == "2026 world cup champion"
        ),
        None,
    )


def discover_hl_champion_universe() -> list[ChampionUniverseOutcome]:
    hl_outcomes, questions = _hl_meta()
    champion_question = _hl_champion_question(questions)
    if not champion_question:
        return []
    outcome_ids = [int(item) for item in champion_question.get("namedOutcomes", [])]
    fallback = champion_question.get("fallbackOutcome")
    if fallback is not None:
        fallback_id = int(fallback)
        if fallback_id not in outcome_ids:
            outcome_ids.append(fallback_id)

    outcomes: list[ChampionUniverseOutcome] = []
    for outcome_id in outcome_ids:
        row = hl_outcomes.get(outcome_id)
        if not row:
            continue
        label = str(row.get("name") or "")
        outcomes.append(
            ChampionUniverseOutcome(
                venue="hyperliquid",
                outcome=label,
                normalized_outcome=normalize_name(label),
                outcome_id=outcome_id,
                yes_coin=f"#{outcome_id * 10}",
                no_coin=f"#{outcome_id * 10 + 1}",
                title="2026 World Cup Champion",
                is_other=_is_other_label(label),
                is_placeholder=_is_placeholder_label(label),
            )
        )
    return outcomes


def discover_champion_universes(
    pages: int,
) -> tuple[list[ChampionUniverseOutcome], list[ChampionUniverseOutcome]]:
    return discover_pm_champion_universe(pages), discover_hl_champion_universe()


def discover_champion_markets(pages: int) -> tuple[list[ChampionMarket], dict[str, int]]:
    pm_markets = discover_pm_champion_markets(pages)
    hl_outcomes, questions = _hl_meta()
    champion_question = _hl_champion_question(questions)
    if not champion_question:
        return [], {"pm_active": len(pm_markets), "hl_active": 0, "intersection": 0}

    markets: list[ChampionMarket] = []
    for outcome_id in champion_question.get("namedOutcomes", []):
        row = hl_outcomes.get(int(outcome_id))
        if not row:
            continue
        hl_name = str(row.get("name") or "")
        pm_row = pm_markets.get(normalize_name(hl_name))
        if not pm_row:
            continue
        markets.append(
            ChampionMarket(
                market_key=f"WC-{hl_name}-Champion",
                market_title="2026 World Cup Champion",
                outcome=hl_name,
                pm_yes_token=str(pm_row["yes_token"]),
                pm_no_token=str(pm_row["no_token"]),
                hl_outcome_id=int(outcome_id),
                hl_yes_coin=f"#{int(outcome_id) * 10}",
                hl_no_coin=f"#{int(outcome_id) * 10 + 1}",
                pm_slug=str(pm_row.get("slug") or ""),
                pm_market_id=str(pm_row.get("market_id") or ""),
                settlement_date=str(pm_row.get("end_date") or ""),
            )
        )
    stats = {
        "pm_active": len(pm_markets),
        "hl_active": len(champion_question.get("namedOutcomes", [])),
        "intersection": len(markets),
        "pm_unmatched": max(len(pm_markets) - len(markets), 0),
        "hl_unmatched": max(len(champion_question.get("namedOutcomes", [])) - len(markets), 0),
    }
    return markets, stats


def _parse_match_name(name: str) -> tuple[str, str] | None:
    match = re.search(r"World Cup:\s*(.+?)\s+(?:vs|v|-)\s+(.+)$", name, re.I)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _normalized_match_haystack(market: dict[str, Any]) -> str:
    return normalize_name(
        " ".join(
            str(market.get(key) or "")
            for key in ("question", "description", "slug", "groupItemTitle")
        )
    )


def _is_match_candidate(market: dict[str, Any], team_a: str, team_b: str) -> bool:
    haystack = _normalized_match_haystack(market)
    team_a_key = normalize_name(team_a)
    team_b_key = normalize_name(team_b)
    has_teams = team_a_key in haystack and team_b_key in haystack
    has_world_cup = "worldcup" in haystack or "fifa" in haystack or "wc" in haystack
    has_match_marker = any(marker in haystack for marker in ("vs", "versus", "match", "game"))
    return has_teams and has_world_cup and has_match_marker


def _pm_match_token_map(
    pm_markets: list[dict[str, Any]],
    team_a: str,
    team_b: str,
) -> tuple[dict[str, str], dict[str, str]]:
    tokens: dict[str, str] = {}
    market_ids: dict[str, str] = {}
    wanted = {
        normalize_name(team_a): team_a,
        normalize_name("Draw"): "Draw",
        normalize_name(team_b): team_b,
    }
    for market in pm_markets:
        if not _is_match_candidate(market, team_a, team_b):
            continue
        token_ids = [str(token) for token in _parse_json_list(market.get("clobTokenIds"))]
        market_outcomes = [str(item) for item in _parse_json_list(market.get("outcomes"))]
        normalized_outcomes = [normalize_name(item) for item in market_outcomes]

        # Some PM 3-way markets expose one token per outcome directly.
        if len(token_ids) >= 3:
            for idx, normalized in enumerate(normalized_outcomes):
                canonical = wanted.get(normalized)
                if canonical and idx < len(token_ids):
                    tokens[canonical] = token_ids[idx]
                    market_ids[canonical] = str(market.get("id") or "")
            if len(tokens) == 3:
                return tokens, market_ids

        # Grouped binary markets expose Yes/No tokens per outcome; use the Yes token.
        outcome = str(market.get("groupItemTitle") or "").strip()
        if not outcome:
            for normalized, label in wanted.items():
                if normalized in normalize_name(str(market.get("question") or "")):
                    outcome = label
                    break
        if not outcome or len(token_ids) < 2:
            continue
        lower_outcomes = [item.lower() for item in market_outcomes]
        yes_index = lower_outcomes.index("yes") if "yes" in lower_outcomes else 0
        canonical = wanted.get(normalize_name(outcome))
        if canonical:
            tokens[canonical] = token_ids[yes_index]
            market_ids[canonical] = str(market.get("id") or "")
    return tokens, market_ids


def discover_match_markets(pages: int) -> tuple[list[MatchMarket], dict[str, int]]:
    pm_markets = _gamma_markets(pages)
    hl_outcomes, questions = _hl_meta()
    match_questions = [
        question
        for question in questions
        if _parse_match_name(str(question.get("name") or "")) is not None
    ]
    markets: list[MatchMarket] = []
    failures: dict[str, int] = {}
    for question in match_questions:
        name = str(question.get("name") or "")
        parsed = _parse_match_name(name)
        if not parsed:
            continue
        team_a, team_b = parsed
        outcome_ids = tuple(int(item) for item in question.get("namedOutcomes", []))
        outcome_names = tuple(str(hl_outcomes.get(item, {}).get("name") or "") for item in outcome_ids)
        if len(outcome_ids) != 3 or normalize_name("Draw") not in {normalize_name(x) for x in outcome_names}:
            reason = "not_three_way"
            failures[reason] = failures.get(reason, 0) + 1
            markets.append(
                MatchMarket(
                    name,
                    name,
                    team_a,
                    team_b,
                    outcome_names,
                    outcome_ids,
                    parse_status="failed",
                    mapping_status="unmatched",
                    missing_pm_outcomes=outcome_names,
                    failure_reason=reason,
                )
            )
            continue
        pm_tokens, pm_ids = _pm_match_token_map(pm_markets, team_a, team_b)
        missing = [outcome for outcome in outcome_names if outcome not in pm_tokens]
        mapping_status = "matched" if not missing else "partial" if pm_tokens else "unmatched"
        reason = None
        if missing:
            reason = "pm_match_partial" if pm_tokens else "pm_match_not_found"
        if reason:
            failures[reason] = failures.get(reason, 0) + 1
        markets.append(
            MatchMarket(
                market_key=name,
                market_title=name,
                team_a=team_a,
                team_b=team_b,
                outcomes=outcome_names,
                hl_outcome_ids=outcome_ids,
                pm_outcome_tokens=pm_tokens,
                pm_market_ids=pm_ids,
                parse_status="parsed",
                mapping_status=mapping_status,
                missing_pm_outcomes=tuple(missing),
                failure_reason=reason,
            )
        )
    stats = {
        "candidates": len(match_questions),
        "parsed": sum(1 for market in markets if market.parse_status == "parsed"),
        "matched": sum(1 for market in markets if market.mapping_status == "matched"),
        "failed": sum(1 for market in markets if market.mapping_status != "matched"),
        **failures,
    }
    return markets, stats

