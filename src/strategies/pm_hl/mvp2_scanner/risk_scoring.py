from __future__ import annotations


def rule_match_score(strategy_type: str, has_cross_venue_mapping: bool) -> float:
    if strategy_type == "champion_cross_venue":
        return 0.95 if has_cross_venue_mapping else 0.55
    if strategy_type == "match_3way":
        return 0.75 if has_cross_venue_mapping else 0.35
    return 0.50


def rule_match_note(strategy_type: str, has_cross_venue_mapping: bool) -> str:
    if strategy_type == "champion_cross_venue":
        return (
            "PM yes/no tokens matched to HL yes/no outcome coins for the same normalized champion outcome."
            if has_cross_venue_mapping
            else "Champion outcome exists on only one venue or mapping is incomplete."
        )
    if strategy_type == "match_3way":
        return (
            "PM and HL 3-way outcomes matched by normalized teams/draw; still research-only."
            if has_cross_venue_mapping
            else "HL 3-way candidate found; PM 3-way mapping missing or partial."
        )
    return "No strategy-specific rule match note."


def execution_risk_score(
    *,
    strategy_type: str,
    depth: float | None,
    capacity_usd: float | None,
    missing_price_count: int,
) -> float:
    score = 0.25
    if strategy_type == "match_3way":
        score += 0.20
    if missing_price_count:
        score += min(0.35, missing_price_count * 0.10)
    if depth is None or depth <= 0:
        score += 0.20
    elif depth < 25:
        score += 0.12
    if capacity_usd is None or capacity_usd <= 0:
        score += 0.10
    elif capacity_usd < 50:
        score += 0.08
    return min(score, 1.0)


def recommendation(net_edge: float | None, capacity_usd: float | None, risk_score: float) -> str:
    edge = net_edge or 0.0
    capacity = capacity_usd or 0.0
    if edge <= 0:
        return "ignore"
    if edge < 0.001:
        return "observe"
    if edge < 0.003 or capacity < 25:
        return "paper"
    if edge >= 0.006 and capacity >= 100 and risk_score < 0.45:
        return "live_ready_later"
    return "manual_review"


def match_recommendation(discrepancy: float | None, risk_score: float) -> str:
    if discrepancy is None:
        return "ignore"
    if abs(discrepancy) < 0.01:
        return "observe"
    if risk_score >= 0.7:
        return "observe"
    return "manual_review"

