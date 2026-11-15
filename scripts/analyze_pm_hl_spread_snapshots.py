from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs" / "pm_hl"

PROFILE_EXIT_MIN_PROFIT_USD = {
    "normal": 0.03,
    "validation": 0.01,
    "positive": 0.0001,
}


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


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def snapshot_paths(date: str | None, inputs: list[str] | None) -> list[Path]:
    if inputs:
        return [Path(item) for item in inputs]
    pattern = f"orderbook_snapshots_{date}.jsonl" if date else "orderbook_snapshots_*.jsonl"
    return sorted(LOG_DIR.glob(pattern))


def iter_snapshots(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
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


def filter_rows(rows: list[dict[str, Any]], hours: float | None) -> list[dict[str, Any]]:
    if hours is None:
        return rows
    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    filtered = []
    for row in rows:
        ts = parse_ts(row.get("timestamp"))
        if ts is not None and ts >= cutoff:
            filtered.append(row)
    return filtered


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def fmt(value: Any, decimals: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def positive_entry(row: dict[str, Any]) -> bool:
    edge = maybe_float(row.get("entry_net_edge_bps"))
    if edge is not None:
        return edge > 0
    spread = maybe_float(row.get("entry_spread_raw"))
    return bool(spread is not None and spread < 0)


def positive_exit(row: dict[str, Any]) -> bool:
    edge = maybe_float(row.get("exit_net_edge_bps"))
    if edge is not None:
        return edge > 0
    spread = maybe_float(row.get("exit_spread_raw"))
    return bool(spread is not None and spread > 0)


def edge_bps_hit(row: dict[str, Any], threshold_bps: float) -> bool:
    for key in ("entry_net_edge_bps", "exit_net_edge_bps"):
        value = maybe_float(row.get(key))
        if value is not None and value >= threshold_bps:
            return True
    return False


def exit_min_profit_usd_for_row(row: dict[str, Any]) -> tuple[float | None, str]:
    explicit = maybe_float(row.get("exit_min_profit_usd"))
    if explicit is not None:
        return explicit, "snapshot_field"
    profile = str(row.get("threshold_profile") or "")
    inferred = PROFILE_EXIT_MIN_PROFIT_USD.get(profile)
    if inferred is not None:
        return inferred, "inferred_from_profile"
    return None, "missing"


def profit_hit(row: dict[str, Any]) -> bool | None:
    pnl = maybe_float(row.get("realized_net_pnl_all_in"))
    if pnl is None:
        return None
    threshold, _ = exit_min_profit_usd_for_row(row)
    if threshold is None:
        return None
    return pnl >= threshold


def exit_vs_hold_hit(row: dict[str, Any]) -> bool | None:
    value = maybe_float(row.get("exit_vs_hold_usd"))
    if value is None:
        return None
    return value >= 0


def near_miss(row: dict[str, Any], threshold_bps: float) -> bool:
    return edge_bps_hit(row, threshold_bps) and not bool(row.get("candidate_eligible"))


def dataset_field_notes(rows: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if not rows:
        return notes
    has_exit_min_profit_usd = any("exit_min_profit_usd" in row for row in rows)
    has_realized_pnl = any(maybe_float(row.get("realized_net_pnl_all_in")) is not None for row in rows)
    has_exit_vs_hold = any(maybe_float(row.get("exit_vs_hold_usd")) is not None for row in rows)
    if not has_exit_min_profit_usd:
        notes.append(
            "exit_min_profit_usd is not stored in current snapshots; "
            "profit_hit_count uses threshold_profile inference when available."
        )
    if not has_realized_pnl:
        notes.append("realized_net_pnl_all_in missing from snapshots; profit_hit_count will be n/a.")
    if not has_exit_vs_hold:
        notes.append("exit_vs_hold_usd missing from snapshots; exit_vs_hold_hit_count will be n/a.")
    return notes


def summarize(rows: list[dict[str, Any]], threshold_bps: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        market = str(row.get("market") or "unknown")
        grouped.setdefault(market, []).append(row)

    summaries: list[dict[str, Any]] = []
    for market, market_rows in sorted(grouped.items()):
        entry_spreads = [value for row in market_rows if (value := maybe_float(row.get("entry_spread_raw"))) is not None]
        exit_spreads = [value for row in market_rows if (value := maybe_float(row.get("exit_spread_raw"))) is not None]

        profit_hits = [profit_hit(row) for row in market_rows]
        exit_vs_hold_hits = [exit_vs_hold_hit(row) for row in market_rows]
        profit_evaluable = [value for value in profit_hits if value is not None]
        exit_vs_hold_evaluable = [value for value in exit_vs_hold_hits if value is not None]

        summaries.append(
            {
                "market": market,
                "sample_count": len(market_rows),
                "mean_entry_spread_raw": mean(entry_spreads),
                "stdev_entry_spread_raw": stdev(entry_spreads),
                "min_entry_spread_raw": min(entry_spreads) if entry_spreads else None,
                "max_entry_spread_raw": max(entry_spreads) if entry_spreads else None,
                "mean_exit_spread_raw": mean(exit_spreads),
                "stdev_exit_spread_raw": stdev(exit_spreads),
                "min_exit_spread_raw": min(exit_spreads) if exit_spreads else None,
                "max_exit_spread_raw": max(exit_spreads) if exit_spreads else None,
                "positive_entry_edge_count": sum(1 for row in market_rows if positive_entry(row)),
                "positive_exit_edge_count": sum(1 for row in market_rows if positive_exit(row)),
                "edge_bps_hit_count": sum(1 for row in market_rows if edge_bps_hit(row, threshold_bps)),
                "near_miss_count": sum(1 for row in market_rows if near_miss(row, threshold_bps)),
                "profit_hit_count": sum(1 for value in profit_evaluable if value),
                "profit_hit_evaluable_count": len(profit_evaluable),
                "exit_vs_hold_hit_count": sum(1 for value in exit_vs_hold_evaluable if value),
                "exit_vs_hold_evaluable_count": len(exit_vs_hold_evaluable),
                "eligible_count": sum(1 for row in market_rows if bool(row.get("candidate_eligible"))),
            }
        )
    return summaries


def format_count(value: int | None, evaluable: int | None = None) -> str:
    if evaluable is not None and evaluable == 0:
        return "n/a"
    return str(value if value is not None else 0)


def print_table(summaries: list[dict[str, Any]]) -> None:
    headers = [
        "Market",
        "Samples",
        "EntryMean",
        "EntryStd",
        "EntryMin",
        "EntryMax",
        "ExitMean",
        "ExitStd",
        "ExitMin",
        "ExitMax",
        "PosEntry",
        "PosExit",
        "EdgeBpsHit",
        "NearMiss",
        "ProfitHit",
        "ExitVsHold",
        "Eligible",
    ]
    widths = [22, 8, 11, 10, 10, 10, 11, 10, 10, 10, 9, 8, 11, 9, 10, 11, 9]
    print("".join(header.ljust(width) for header, width in zip(headers, widths)))
    for row in summaries:
        values = [
            row["market"],
            row["sample_count"],
            fmt(row["mean_entry_spread_raw"]),
            fmt(row["stdev_entry_spread_raw"]),
            fmt(row["min_entry_spread_raw"]),
            fmt(row["max_entry_spread_raw"]),
            fmt(row["mean_exit_spread_raw"]),
            fmt(row["stdev_exit_spread_raw"]),
            fmt(row["min_exit_spread_raw"]),
            fmt(row["max_exit_spread_raw"]),
            row["positive_entry_edge_count"],
            row["positive_exit_edge_count"],
            row["edge_bps_hit_count"],
            row["near_miss_count"],
            format_count(row["profit_hit_count"], row["profit_hit_evaluable_count"]),
            format_count(row["exit_vs_hold_hit_count"], row["exit_vs_hold_evaluable_count"]),
            row["eligible_count"],
        ]
        print("".join(str(value).ljust(width) for value, width in zip(values, widths)))


def print_rankings(summaries: list[dict[str, Any]]) -> None:
    if not summaries:
        return

    true_opportunity_rank = sorted(
        summaries,
        key=lambda row: (int(row["eligible_count"]), int(row["sample_count"])),
        reverse=True,
    )
    near_miss_rank = sorted(
        summaries,
        key=lambda row: (int(row["near_miss_count"]), int(row["edge_bps_hit_count"])),
        reverse=True,
    )
    volatility_rank = sorted(
        summaries,
        key=lambda row: max(
            float(row.get("stdev_entry_spread_raw") or 0),
            float(row.get("stdev_exit_spread_raw") or 0),
        ),
        reverse=True,
    )

    print()
    print("RANKINGS")
    print(
        "true_opportunity_ranking: markets with the most candidate_eligible=true snapshots "
        "(complete tradable opportunities only)"
    )
    print(f"  top: {true_opportunity_rank[0]['market']} (eligible_count={true_opportunity_rank[0]['eligible_count']})")
    print(
        "near_miss_ranking: markets with the most edge_bps_hit but candidate_eligible=false "
        "(single-condition edge hits that failed full eligibility)"
    )
    print(f"  top: {near_miss_rank[0]['market']} (near_miss_count={near_miss_rank[0]['near_miss_count']})")
    print("volatility_ranking: markets with the largest spread stdev (entry or exit)")
    print(
        f"  top: {volatility_rank[0]['market']} "
        f"(max_stdev={max(float(volatility_rank[0].get('stdev_entry_spread_raw') or 0), float(volatility_rank[0].get('stdev_exit_spread_raw') or 0)):.6f})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze PM-HL orderbook/spread snapshots.")
    parser.add_argument("--hours", type=float, default=None, help="Only include snapshots from the last N hours.")
    parser.add_argument("--date", default=None, help="Read one UTC date, format YYYYMMDD.")
    parser.add_argument("--threshold-bps", type=float, default=10.0, help="Net edge bps threshold for edge_bps_hit counts.")
    parser.add_argument("--input", action="append", help="Explicit jsonl input file; may be passed multiple times.")
    args = parser.parse_args()

    paths = snapshot_paths(args.date, args.input)
    rows = filter_rows(iter_snapshots(paths), args.hours)
    print("PM-HL SPREAD SNAPSHOT ANALYSIS")
    print(f"files: {len(paths)}")
    print(f"samples: {len(rows)}")
    print(f"threshold_bps: {args.threshold_bps:g}")
    print("edge_bps_hit_count is a single-condition signal, not a tradable opportunity.")
    print("eligible_count reflects full candidate_eligible=true from the live executor.")
    for note in dataset_field_notes(rows):
        print(f"note: {note}")
    print()
    if not rows:
        print("No snapshots found.")
        return 0
    summaries = summarize(rows, args.threshold_bps)
    print_table(summaries)
    print_rankings(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
