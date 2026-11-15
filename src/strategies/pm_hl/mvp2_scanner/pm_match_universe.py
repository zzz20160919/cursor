from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.pm_hl.mvp2_scanner.market_mapper import (
    _gamma_markets,
    _parse_json_list,
    discover_match_markets,
    normalize_name,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _text_for_market(market: dict[str, Any]) -> str:
    return " ".join(
        str(market.get(key) or "")
        for key in (
            "question",
            "title",
            "description",
            "slug",
            "groupItemTitle",
        )
    )


def _parse_teams(title: str) -> tuple[str | None, str | None, str]:
    cleaned = re.sub(r"\s+", " ", title).strip(" ?")
    cleaned = re.sub(r"^(?:fifa\s+)?world cup\s+", "", cleaned, flags=re.I)
    patterns = (
        (r"^World Cup:\s*(.+?)\s+(?:vs\.?|v\.?|-)\s+(.+)$", "world_cup_colon_vs"),
        (r"^(.+?)\s+(?:vs\.?|v\.?)\s+(.+)$", "plain_vs"),
        (r"^(.+?)\s+-\s+(.+)$", "dash_vs"),
    )
    for pattern, label in patterns:
        match = re.search(pattern, cleaned, re.I)
        if match:
            return match.group(1).strip(), match.group(2).strip(), label
    return None, None, "unparsed"


def _parse_teams_from_market(market: dict[str, Any]) -> tuple[str | None, str | None, str]:
    candidates = [
        str(market.get("question") or market.get("title") or ""),
        str(market.get("groupTitle") or market.get("eventTitle") or ""),
        str(market.get("slug") or "").replace("-", " "),
    ]
    for candidate in candidates:
        team_a, team_b, pattern = _parse_teams(candidate)
        if team_a and team_b:
            return team_a, team_b, pattern
    return None, None, "unparsed"


def _event_ids(market: dict[str, Any]) -> str:
    events = market.get("events")
    if isinstance(events, list):
        ids = [str(event.get("id")) for event in events if isinstance(event, dict) and event.get("id")]
        return ",".join(ids)
    return str(market.get("eventId") or market.get("event_id") or "")


def _event_start_time(market: dict[str, Any]) -> str:
    events = market.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                value = event.get("startDate") or event.get("startTime")
                if value:
                    return str(value)
    return str(market.get("startDate") or "")


def _status(market: dict[str, Any]) -> str:
    if market.get("closed"):
        return "closed"
    if market.get("active"):
        return "active"
    if market.get("archived"):
        return "archived"
    return "unknown"


def _is_world_cup_match_candidate(market: dict[str, Any]) -> bool:
    text = _text_for_market(market)
    normalized = normalize_name(text)
    if "worldcup" not in normalized and "fifa" not in normalized:
        return False
    if not any(marker in text.lower() for marker in (" vs ", " v ", " v. ", " vs. ", "draw")) and "vs" not in normalized:
        return False
    team_a, team_b, _ = _parse_teams_from_market(market)
    outcomes = [str(item) for item in _parse_json_list(market.get("outcomes"))]
    has_draw = any(normalize_name(outcome) == "draw" for outcome in outcomes)
    return bool(team_a and team_b) or has_draw or "three possible outcomes" in text.lower()


def build_pm_match_universe_rows(pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern_counts: Counter[str] = Counter()
    for market in _gamma_markets(pages):
        if not _is_world_cup_match_candidate(market):
            continue
        title = str(market.get("question") or market.get("title") or "")
        team_a, team_b, pattern = _parse_teams_from_market(market)
        pattern_counts[pattern] += 1
        outcomes = [str(item) for item in _parse_json_list(market.get("outcomes"))]
        normalized_team_a = normalize_name(team_a or "")
        normalized_team_b = normalize_name(team_b or "")
        has_draw = any(normalize_name(outcome) == "draw" for outcome in outcomes)
        text = _text_for_market(market)
        is_three_way_like = (len(outcomes) == 3 and has_draw) or "three possible outcomes" in text.lower()
        notes = []
        if not normalized_team_a or not normalized_team_b:
            notes.append("team_parse_incomplete")
        if has_draw:
            notes.append("has_draw")
        if is_three_way_like:
            notes.append("three_way_like")
        rows.append(
            {
                "pm_event_id": _event_ids(market),
                "pm_market_id": str(market.get("id") or ""),
                "pm_slug": str(market.get("slug") or ""),
                "pm_title": title,
                "normalized_title": normalize_name(title),
                "normalized_team_a": normalized_team_a,
                "normalized_team_b": normalized_team_b,
                "outcome_names": json.dumps(outcomes, ensure_ascii=False),
                "has_draw": has_draw,
                "is_three_way_like": is_three_way_like,
                "event_start_time": _event_start_time(market),
                "close_time": str(market.get("endDate") or market.get("endDateIso") or ""),
                "resolution_source_or_rule_text": str(
                    market.get("resolutionSource") or market.get("description") or ""
                ),
                "status": _status(market),
                "notes": ";".join(notes) if notes else "candidate",
                "title_pattern": pattern,
            }
        )

    parsed_count = sum(1 for row in rows if row["normalized_team_a"] and row["normalized_team_b"])
    summary = {
        "pm_candidate_count": len(rows),
        "clearly_parsed_count": parsed_count,
        "has_draw_count": sum(1 for row in rows if row["has_draw"]),
        "is_three_way_like_count": sum(1 for row in rows if row["is_three_way_like"]),
        "title_normalization_success_count": parsed_count,
        "top_title_patterns": dict(pattern_counts.most_common(10)),
    }
    return rows, summary


def build_crosswalk_template_rows(pages: int) -> list[dict[str, Any]]:
    hl_markets, _ = discover_match_markets(pages)
    return [
        {
            "hl_market_key": market.market_key,
            "hl_title": market.market_title,
            "pm_market_id": "",
            "pm_title": "",
            "match_status": "",
            "notes": "manual_crosswalk_required",
        }
        for market in hl_markets
    ]


def _write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def export_pm_match_universe(output_dir: Path, pages: int) -> dict[str, Any]:
    stamp = _stamp()
    universe_rows, summary = build_pm_match_universe_rows(pages)
    crosswalk_rows = build_crosswalk_template_rows(pages)

    universe_fields = [
        "pm_event_id",
        "pm_market_id",
        "pm_slug",
        "pm_title",
        "normalized_title",
        "normalized_team_a",
        "normalized_team_b",
        "outcome_names",
        "has_draw",
        "is_three_way_like",
        "event_start_time",
        "close_time",
        "resolution_source_or_rule_text",
        "status",
        "notes",
        "title_pattern",
    ]
    crosswalk_fields = [
        "hl_market_key",
        "hl_title",
        "pm_market_id",
        "pm_title",
        "match_status",
        "notes",
    ]
    csv_path = _write_dict_csv(
        output_dir / f"pm_world_cup_match_universe_{stamp}.csv",
        universe_rows,
        universe_fields,
    )
    json_path = output_dir / f"pm_world_cup_match_universe_{stamp}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"summary": summary, "rows": universe_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    crosswalk_path = _write_dict_csv(
        output_dir / f"pm_hl_world_cup_match_crosswalk_template_{stamp}.csv",
        crosswalk_rows,
        crosswalk_fields,
    )
    return {
        "summary": summary,
        "csv_path": csv_path,
        "json_path": json_path,
        "crosswalk_template_path": crosswalk_path,
        "crosswalk_template_count": len(crosswalk_rows),
    }

