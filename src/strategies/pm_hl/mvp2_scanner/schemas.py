from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BookTop:
    bid: float | None = None
    bid_size: float | None = None
    ask: float | None = None
    ask_size: float | None = None


@dataclass(frozen=True)
class ChampionMarket:
    market_key: str
    market_title: str
    outcome: str
    pm_yes_token: str
    pm_no_token: str
    hl_outcome_id: int
    hl_yes_coin: str
    hl_no_coin: str
    pm_slug: str | None = None
    pm_market_id: str | None = None
    settlement_date: str | None = None


@dataclass(frozen=True)
class ChampionUniverseOutcome:
    venue: str
    outcome: str
    normalized_outcome: str
    yes_token: str | None = None
    no_token: str | None = None
    outcome_id: int | None = None
    yes_coin: str | None = None
    no_coin: str | None = None
    market_id: str | None = None
    slug: str | None = None
    title: str | None = None
    is_other: bool = False
    is_placeholder: bool = False


@dataclass(frozen=True)
class MatchMarket:
    market_key: str
    market_title: str
    team_a: str
    team_b: str
    outcomes: tuple[str, ...]
    hl_outcome_ids: tuple[int, ...]
    pm_outcome_tokens: dict[str, str] = field(default_factory=dict)
    pm_market_ids: dict[str, str] = field(default_factory=dict)
    parse_status: str = "parsed"
    mapping_status: str = "unmatched"
    missing_pm_outcomes: tuple[str, ...] = ()
    failure_reason: str | None = None


@dataclass(frozen=True)
class OpportunityRow:
    timestamp: str
    strategy_type: str
    venue_a: str
    venue_b: str
    market_key: str
    market_title: str
    outcome: str
    price_a_bid: float | None
    price_a_ask: float | None
    price_b_bid: float | None
    price_b_ask: float | None
    gross_edge: float | None
    estimated_fee: float | None
    net_edge: float | None
    net_edge_bps: float | None
    depth: float | None
    capacity_usd: float | None
    rule_match_score: float
    execution_risk_score: float
    recommendation: str
    pm_subset_sum_yes: float | None = None
    pm_subset_sum_yes_deviation_from_1: float | None = None
    pm_subset_sum_no: float | None = None
    pm_subset_sum_no_deviation_from_n_minus_1: float | None = None
    hl_subset_sum_yes: float | None = None
    hl_subset_sum_yes_deviation_from_1: float | None = None
    hl_subset_sum_no: float | None = None
    hl_subset_sum_no_deviation_from_n_minus_1: float | None = None
    pm_full_outcome_count: int | None = None
    pm_full_sum_yes: float | None = None
    pm_full_sum_yes_deviation_from_1: float | None = None
    pm_full_sum_no: float | None = None
    pm_full_sum_no_deviation_from_n_minus_1: float | None = None
    pm_full_has_other: bool | None = None
    pm_full_other_labels: list[str] = field(default_factory=list)
    pm_full_placeholder_count: int | None = None
    pm_full_completeness_flag: str = "unknown"
    pm_full_completeness_note: str = ""
    hl_full_outcome_count: int | None = None
    hl_full_sum_yes: float | None = None
    hl_full_sum_yes_deviation_from_1: float | None = None
    hl_full_sum_no: float | None = None
    hl_full_sum_no_deviation_from_n_minus_1: float | None = None
    hl_full_has_other: bool | None = None
    hl_full_other_labels: list[str] = field(default_factory=list)
    hl_full_placeholder_count: int | None = None
    hl_full_completeness_flag: str = "unknown"
    hl_full_completeness_note: str = ""
    pm_sum_yes: float | None = None
    pm_sum_yes_deviation_from_1: float | None = None
    pm_sum_no: float | None = None
    pm_sum_no_deviation_from_n_minus_1: float | None = None
    hl_sum_yes: float | None = None
    hl_sum_yes_deviation_from_1: float | None = None
    hl_sum_no: float | None = None
    hl_sum_no_deviation_from_n_minus_1: float | None = None
    pm_sum_three_way: float | None = None
    pm_sum_three_way_deviation_from_1: float | None = None
    hl_sum_three_way: float | None = None
    hl_sum_three_way_deviation_from_1: float | None = None
    completeness_flag: str = "unknown"
    completeness_note: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_flat_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["raw"] = row.get("raw") or {}
        return row


@dataclass(frozen=True)
class ScanSummary:
    champion_candidates: int = 0
    champion_scanned: int = 0
    champion_failed: int = 0
    champion_matched_outcomes: int = 0
    champion_unmatched_outcomes: int = 0
    match_candidates: int = 0
    match_parsed: int = 0
    match_matched: int = 0
    match_failed: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeIntentSchema:
    """Future placeholder only; MVP2 scanner does not instantiate trade intents."""

    schema_status: str = "reserved_not_generated"


@dataclass(frozen=True)
class ExecutionResultSchema:
    """Future placeholder only; MVP2 scanner has no execution logic."""

    schema_status: str = "reserved_not_generated"

