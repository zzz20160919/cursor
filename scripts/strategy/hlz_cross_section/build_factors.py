#!/usr/bin/env python3
"""Strict HLZ Step 2 panel.

Reads the Step 1 universe and the public TimeSeventeen/Polymarket-v1 files
(Appendix A.3's transaction and CTF sources). Open interest is the replay of
root USDC complete-set splits, merges, and redemptions whose block time is
at or before formation. There is no current-OI snapshot and no volume proxy.

If those files are not on disk, the command stops and writes the blocker.
It does not estimate the missing input.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from hlz_paper import (
    EASTERN,
    category_portfolios,
    endpoint_price,
    event_counts_as_complete_set,
    formation_epoch,
    formation_time,
    last_trade_at_or_before,
    lor,
    parse_block_id,
    replay_open_interest,
    self_test,
    traded_on_preceding_days,
    yes_payout,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "strategy" / "hlz_cross_section"
DEFAULT_UNIVERSE = OUTPUT_DIR / "paper_sample_markets.csv"
DEFAULT_PIT = OUTPUT_DIR / "cache" / "step2" / "timeseventeen"
DEFAULT_FACTORS = OUTPUT_DIR / "factor_daily.csv"
DEFAULT_SPREADS = OUTPUT_DIR / "portfolio_spreads.csv"
DEFAULT_DAILY = OUTPUT_DIR / "portfolio_spreads_daily.csv"
DEFAULT_META = OUTPUT_DIR / "step2_meta.json"
DEFAULT_SUMMARY = OUTPUT_DIR / "STEP2_SUMMARY.md"
RPC = "https://polygon-bor-rpc.publicnode.com"
PILOT_START = date(2024, 10, 30)
PILOT_END = date(2024, 11, 5)


def ensure_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        if text.endswith("+00"):
            text += ":00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_stamp(day: date) -> str:
    return day.strftime("%Y_%m_%d")


def iter_days(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def required_paths(pit: Path, start: date, end: date) -> list[Path]:
    paths = [
        pit / "CTF" / "splits.parquet",
        pit / "CTF" / "merges.parquet",
        pit / "CTF" / "redemptions.parquet",
        pit / "CTF" / "resolutions.parquet",
    ]
    first = start - timedelta(days=7)
    last = end + timedelta(days=1)
    for day in iter_days(first, last):
        paths.append(pit / "daily_aligned" / f"{day_stamp(day)}.parquet")
        paths.append(pit / "daily_aligned_multi" / f"{day_stamp(day)}.parquet")
    return paths


def write_blocker(path: Path, missing: list[Path], pit: Path) -> None:
    lines = [
        "# HLZ Step 2 strict status",
        "",
        "The previous Step 2 numbers that used the Data API `/v2/oi` snapshot are not valid. "
        "That snapshot was taken after formation, so it cannot rank or weight the paper portfolios.",
        "",
        "This command did not write a substitute open-interest panel.",
        "",
        "Appendix A.3 (PDF page 70) takes transactions from `TimeSeventeen/Polymarket-v1` and "
        "reconstructs 4:00 p.m. Eastern open interest from Polygon CTF and negative-risk lifecycle events. "
        "The public Hugging Face release of that dataset is the source this command reads. "
        "Dome hourly prices were requested without an API key and returned HTTP 503, so they are not used. "
        "The paused Polymarket Goldsky subgraphs refuse queries. `vgregoire/polymarket-users` daily open interest "
        "is an end-of-UTC-day position sum, not the 4:00 p.m. complete-set stock, so it is not used.",
        "",
        "Missing local files:",
        "",
    ]
    for item in missing:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "Download them with:",
            "",
            "```bash",
            "bash scripts/strategy/hlz_cross_section/download_pit.sh",
            "```",
            "",
            f"Expected directory: `{pit}`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def rpc_blocks(blocks: list[int], cache_path: Path) -> dict[int, dict[str, Any]]:
    cache: dict[str, Any] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    missing: list[int] = []
    for block in blocks:
        cached = cache.get(str(block))
        if isinstance(cached, dict) and "timestamp" in cached and "hash" in cached:
            out[block] = cached
        else:
            missing.append(block)
    print(f"blocks cached {len(out)} fetch {len(missing)}", flush=True)
    for start in range(0, len(missing), 40):
        chunk = missing[start : start + 40]
        payload = [
            {
                "jsonrpc": "2.0",
                "id": index,
                "method": "eth_getBlockByNumber",
                "params": [hex(block), False],
            }
            for index, block in enumerate(chunk)
        ]
        request = urllib.request.Request(
            RPC,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "hlz-step2"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode())
        if isinstance(body, dict):
            body = [body]
        by_id = {item.get("id"): item for item in body}
        for index, block in enumerate(chunk):
            result = (by_id.get(index) or {}).get("result")
            if not isinstance(result, dict) or "timestamp" not in result or "hash" not in result:
                raise SystemExit(f"Polygon block {block} did not return a hash and timestamp")
            record = {"timestamp": int(result["timestamp"], 16), "hash": result["hash"]}
            previous = cache.get(str(block))
            if isinstance(previous, dict) and previous.get("hash") and previous["hash"] != record["hash"]:
                raise SystemExit(f"block {block} hash changed; refusing a possible reorg")
            cache[str(block)] = record
            out[block] = record
        if start % 400 == 0:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            print(f"blocks {min(start + 40, len(missing))}/{len(missing)}", flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


def load_joined_trades(pit: Path, universe: Path, start: date, end: date) -> list[dict[str, Any]]:
    first = start - timedelta(days=7)
    last = end + timedelta(days=1)
    files = []
    for folder in ("daily_aligned", "daily_aligned_multi"):
        for day in iter_days(first, last):
            files.append(str(pit / folder / f"{day_stamp(day)}.parquet"))
    con = duckdb.connect()
    con.execute(
        """
        create table universe as
        select market_id, lower(slug) as slug, question, event_id, event_title,
               open_date, expiry, closed
        from read_csv_auto(?)
        where slug is not null and slug <> ''
        """,
        [str(universe)],
    )
    con.execute(
        """
        create table trades as
        select
          lower(t.condition_id) as condition_id,
          t.block_timestamp::bigint as block_timestamp,
          t.p_event::double as price,
          t.market_slug as slug,
          t.category as category_raw,
          t.category_refined as category,
          t.neg_risk as neg_risk,
          t.outcome_seq::integer as outcome_seq,
          u.market_id,
          u.question,
          u.event_id,
          u.event_title,
          u.open_date,
          u.expiry,
          u.closed
        from read_parquet(?) t
        join universe u on lower(t.market_slug) = u.slug
        where t.block_timestamp is not null and t.p_event is not null
        """,
        [files],
    )
    rows = con.execute(
        """
        select * from trades
        order by condition_id, block_timestamp
        """
    ).fetchall()
    columns = [item[0] for item in con.execute("describe trades").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def load_events(pit: Path, conditions: set[str]) -> list[dict[str, Any]]:
    con = duckdb.connect()
    con.execute("create table want(condition_id varchar)")
    con.executemany("insert into want values (?)", [(item,) for item in conditions])
    frames = []
    specs = [
        ("split", pit / "CTF" / "splits.parquet"),
        ("merge", pit / "CTF" / "merges.parquet"),
        ("redemption", pit / "CTF" / "redemptions.parquet"),
    ]
    for kind, path in specs:
        print(f"scan {path.name}", flush=True)
        frame = con.execute(
            f"""
            select
              '{kind}' as kind,
              id,
              lower(condition_id) as condition_id,
              lower(collateral_token) as collateral,
              lower(parent_collection_id) as parent,
              partition,
              usdc_amount as amount
            from read_parquet(?)
            where lower(condition_id) in (select condition_id from want)
            """,
            [str(path)],
        ).fetchall()
        frames.extend(frame)
        print(f"  rows {len(frame)}", flush=True)
    resolutions = con.execute(
        """
        select id, lower(condition_id) as condition_id, payout_numerators
        from read_parquet(?)
        where lower(condition_id) in (select condition_id from want)
        """,
        [str(pit / "CTF" / "resolutions.parquet")],
    ).fetchall()
    events = [
        {
            "kind": kind,
            "id": record_id,
            "condition_id": condition_id,
            "collateral": collateral,
            "parent": parent,
            "partition": partition,
            "amount": amount,
        }
        for kind, record_id, condition_id, collateral, parent, partition, amount in frames
    ]
    resolution_rows = [
        {"id": record_id, "condition_id": condition_id, "payout_numerators": payout}
        for record_id, condition_id, payout in resolutions
    ]
    return events, resolution_rows


def attach_times(records: list[dict[str, Any]], blocks: dict[int, dict[str, Any]]) -> None:
    for record in records:
        block = parse_block_id(str(record["id"]))
        info = blocks.get(block) if block is not None else None
        record["block"] = block
        record["timestamp"] = None if info is None else int(info["timestamp"])
        record["block_hash"] = None if info is None else info["hash"]


def build_panel(
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_condition_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    meta: dict[str, dict[str, Any]] = {}
    for trade in trades:
        condition = trade["condition_id"]
        by_condition_trades[condition].append(trade)
        meta.setdefault(condition, trade)
    by_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_events[event["condition_id"]].append(event)
    by_resolution = {row["condition_id"]: row for row in resolutions}
    reasons: dict[str, int] = defaultdict(int)
    panel: list[dict[str, Any]] = []
    days = iter_days(start, end)
    for condition, condition_trades in by_condition_trades.items():
        info = meta[condition]
        opened = info["open_date"]
        expiry = info["expiry"]
        resolution = by_resolution.get(condition)
        settlement_time = None if resolution is None else resolution.get("timestamp")
        settlement_value = None if resolution is None else yes_payout(resolution.get("payout_numerators"))
        if resolution is not None and resolution.get("timestamp") is None:
            reasons["resolution_missing_timestamp"] += 1
            settlement_time = None
            settlement_value = None
        stamps = [int(trade["block_timestamp"]) for trade in condition_trades]
        usable_events = []
        dropped_shape = 0
        for event in by_events.get(condition, []):
            if event.get("timestamp") is None:
                reasons["event_missing_timestamp"] += 1
                usable_events = []
                dropped_shape = -1
                break
            if event_counts_as_complete_set(event):
                usable_events.append(event)
            else:
                dropped_shape += 1
        if dropped_shape < 0:
            oi_events: list[dict[str, Any]] = []
            oi_blocked = True
        else:
            oi_events = usable_events
            oi_blocked = False
        if dropped_shape > 0:
            reasons["ignored_nonstandard_ctf_rows"] += dropped_shape
        for day in days:
            form = formation_epoch(day)
            form_dt = formation_time(day)
            if opened is not None and opened > form_dt:
                reasons["not_yet_open"] += 1
                continue
            if expiry is not None and expiry < form_dt:
                reasons["already_expired"] += 1
                continue
            reasons["alive_contract_days"] += 1
            trade = last_trade_at_or_before(
                [{"timestamp": item["block_timestamp"], "price": item["price"], "id": item["condition_id"]} for item in condition_trades],
                form,
            )
            # last_trade uses id only for tests; keep the original row via timestamp match
            if trade is not None:
                trade = max(
                    (item for item in condition_trades if int(item["block_timestamp"]) <= form),
                    key=lambda item: int(item["block_timestamp"]),
                )
                age = form - int(trade["block_timestamp"])
                if age > 2 * 3600 or not 0.0 < float(trade["price"]) < 1.0:
                    trade = None
                    reasons["stale_or_invalid_trade"] += 1
            else:
                reasons["no_trade_at_or_before_formation"] += 1
            traded = traded_on_preceding_days(stamps, day)
            if not traded:
                reasons["no_trade_in_prior_7_calendar_days"] += 1
            oi_value = None
            oi_reason = "no_ctf_history"
            if oi_blocked:
                oi_reason = "ctf_timestamp_incomplete"
                reasons["ctf_timestamp_incomplete"] += 1
            else:
                oi_value, oi_reason = replay_open_interest(oi_events, form)
                if oi_value is None:
                    reasons[oi_reason] += 1
                elif oi_value <= 0:
                    reasons["nonpositive_open_interest"] += 1
            price = None if trade is None else float(trade["price"])
            yesmv = price * oi_value if price is not None and oi_value is not None and oi_value > 0 else None
            lors = {}
            for horizon in range(1, 7):
                past_epoch = formation_epoch(day - timedelta(days=horizon))
                past = last_trade_at_or_before(
                    [{"timestamp": item["block_timestamp"], "price": item["price"]} for item in condition_trades],
                    past_epoch,
                )
                lors[horizon] = lor(price, None if past is None else float(past["price"]))
            next_epoch = formation_epoch(day + timedelta(days=1))
            next_trade = last_trade_at_or_before(
                [{"timestamp": item["block_timestamp"], "price": item["price"]} for item in condition_trades],
                next_epoch,
            )
            end_price, end_source = endpoint_price(
                next_epoch=next_epoch,
                settlement_time=settlement_time,
                settlement_value=settlement_value,
                next_trade=next_trade,
            )
            r_pp = end_price - price if end_price is not None and price is not None else None
            in_sample = (
                price is not None
                and traded
                and oi_value is not None
                and oi_value > 0
                and yesmv is not None
                and r_pp is not None
                and bool(info.get("category"))
            )
            if in_sample:
                reasons["portfolio_sample"] += 1
            panel.append(
                {
                    "date": day.isoformat(),
                    "market_id": info["market_id"],
                    "question": info["question"],
                    "event_id": info["event_id"],
                    "event_title": info["event_title"],
                    "condition_id": condition,
                    "category": info.get("category") or "",
                    "category_raw": info.get("category_raw") or "",
                    "neg_risk": info.get("neg_risk") or "",
                    "p_form": "" if price is None else f"{price:.6f}",
                    "p_form_obs": "" if trade is None else iso_z(datetime.fromtimestamp(int(trade["block_timestamp"]), tz=timezone.utc)),
                    "p_form_age_hours": "" if trade is None else f"{(form - int(trade['block_timestamp'])) / 3600:.4f}",
                    "price_source": "" if trade is None else "timeseventeen_fill_p_event",
                    "traded_prior_7d": "true" if traded else "false",
                    "oi_shares": "" if oi_value is None else f"{oi_value:.6f}",
                    "oi_reason": oi_reason,
                    "oi_timing": "ctf_replay_at_or_before_formation" if oi_value is not None else "",
                    "yesmv": "" if yesmv is None else f"{yesmv:.6f}",
                    **{f"lor_{horizon}": "" if lors[horizon] is None else f"{lors[horizon]:.6f}" for horizon in range(1, 7)},
                    "p_end": "" if end_price is None else f"{end_price:.6f}",
                    "p_end_source": end_source,
                    "r_pp": "" if r_pp is None else f"{r_pp:.6f}",
                    "in_portfolio_sample": "true" if in_sample else "false",
                    "verified_pilot": "true",
                }
            )
    return panel, reasons


def portfolios_from_panel(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in panel:
        if row["in_portfolio_sample"] == "true":
            by_date[row["date"]].append(row)
    daily = []
    characteristics = ["yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6"]
    for day in sorted(by_date):
        for name in characteristics:
            usable = []
            for row in by_date[day]:
                try:
                    value = float(row[name])
                    oi = float(row["oi_shares"])
                    payoff = float(row["r_pp"])
                except ValueError:
                    continue
                if oi <= 0:
                    continue
                usable.append({"category": row["category"], "x": value, "oi": oi, "r": payoff})
            result = category_portfolios(usable)
            if result is None:
                continue
            daily.append(
                {
                    "date": day,
                    "characteristic": name,
                    "n_categories": result["n_categories"],
                    "n_contracts": result["n_contracts"],
                    "low_cents": f"{result['low'] * 100:.6f}",
                    "middle_cents": f"{result['middle'] * 100:.6f}",
                    "high_cents": f"{result['high'] * 100:.6f}",
                    "high_minus_low_cents": f"{result['high_minus_low'] * 100:.6f}",
                }
            )
    return daily


def summarize(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily:
        grouped[row["characteristic"]].append(row)
    summary = []
    for name in ["yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6"]:
        rows = grouped.get(name, [])
        if not rows:
            continue
        count = len(rows)

        def avg(key: str) -> float:
            return sum(float(row[key]) for row in rows) / count

        summary.append(
            {
                "characteristic": name,
                "n_dates": count,
                "mean_low_cents": f"{avg('low_cents'):.6f}",
                "mean_middle_cents": f"{avg('middle_cents'):.6f}",
                "mean_high_cents": f"{avg('high_cents'):.6f}",
                "mean_high_minus_low_cents": f"{avg('high_minus_low_cents'):.6f}",
                "scope": "verified_pilot_not_full_sample",
            }
        )
    return summary


def render_summary(meta: dict[str, Any]) -> str:
    spreads = {row["characteristic"]: row for row in meta["spreads"]}

    def line(name: str) -> str:
        row = spreads.get(name)
        if row is None:
            return "not formed"
        return f"{float(row['mean_high_minus_low_cents']):.4f} cents over {row['n_dates']} verified date(s)"

    return "\n".join(
        [
            "# HLZ Step 2 strict pilot",
            "",
            "The Data API `/v2/oi` snapshot used in the earlier Step 2 run is **invalid for inference**. "
            "It was observed after 4:00 p.m. Eastern formation, so those YESMV ranks and open-interest weights are not the paper's.",
            "",
            "This file is a **pilot**, not the full Polymarket sample in Appendix A.3.",
            "",
            f"Formation window: {meta['start_date']} through {meta['end_date']}, 4:00 p.m. America/New_York.",
            f"Step 1 contracts with at least one TimeSeventeen fill in the loaded days: {meta['n_conditions']}.",
            f"Factor rows: {meta['n_factor_rows']}. Portfolio-sample rows: {meta['n_portfolio_rows']}.",
            f"Mean High−Low YESMV: {line('yesmv')}.",
            f"Mean High−Low LOR(1): {line('lor_1')}.",
            "",
            "## What the paper says",
            "",
            "Section 3.2 (PDF page 7): formation is 4:00 p.m. Eastern, daylight-saving aware. "
            "The price is the most recent valid hourly observation at or before that time: the closing trade when one exists, otherwise the midpoint of a valid two-sided quote. "
            "Lookbacks end at formation. The portfolio sample also requires the price source to be no more than two hours old and a trade on at least one of the preceding seven calendar days. "
            "Open interest is the latest observation at or before formation and is never filled from the future. The two-hour limit does not apply to that stock variable.",
            "",
            "Section 3.3 equations (1) and (2), PDF page 8: `YESMV = P^form × OI` and `R^pp = P^end − P^form`. "
            "The holding period ends at settlement or at 4:00 p.m. the next Eastern day, whichever is first.",
            "",
            "Section 3.4 equations (3) and (4), PDF page 9: within a category, weight by formation-time raw open interest; "
            "across categories, use the matched set and presort category open interest.",
            "",
            "Section 4.1 equation (5), PDF page 10: `LOR(h) = logit(P^form_t) − logit(P^form_{t−h})` for h = 1..6, "
            "with characteristics winsorized at the 1st and 99th percentiles of the date–category cell and split at the 30th and 70th.",
            "",
            "Appendix A.3, PDF page 70: Polymarket definitions and settlements come from official metadata; "
            "transactions come from `TimeSeventeen/Polymarket-v1`; Dome hourly prices are primary and `vgregoire/polymarket-users` hourly OHLCV is the fallback; "
            "4:00 p.m. open interest is reconstructed from Polygon CTF and negative-risk lifecycle events via Dune and TimeSeventeen. "
            "The appendix sample uses cumulative volume above 2,000, life of at least two days, and a start date no later than April 28, 2026, "
            "keeps one outcome per condition (typically YES), and includes standard and negative-risk binaries. "
            "It then requires a fresh price, an active contract, positive raw open interest, a trade in the prior seven calendar days, and a next price change.",
            "",
            "Table IA.15 notes, PDF page 66: sort within formation date and official category at the 30th and 70th percentiles, weight by raw open interest, then aggregate with presort category open interest.",
            "",
            "## Interfaces actually used",
            "",
            "- Trades: `daily_aligned/` and `daily_aligned_multi/` from `TimeSeventeen/Polymarket-v1` (CC-BY-4.0). "
            "Each row is a cleaned `OrderFilled` with `block_timestamp` in Unix seconds. Relayers are already removed. "
            "`p_event` is the outcome_seq=1 probability: it equals the fill price on seq 1 and `1 - price` on seq 2. "
            "Checked on 2024-11-05: seq 1 is the reference leg (Yes, or the first named outcome); seq 2 is the complement.",
            "- Open interest: `CTF/splits.parquet`, `merges.parquet`, and `redemptions.parquet`. "
            "`usdc_amount` is the dataset's USDC.e collateral notional. On Polymarket, one unit of that collateral mints one complete set, so the net is the raw complete-set count. "
            "Only root positions (`parent_collection_id` all zeros), collateral USDC.e or native USDC, and partition `{1,2}` enter the sum. "
            "Split adds, merge and redemption subtract. The block number is parsed from `chainId_blockNumber_logIndex` because these tables have no timestamp column. "
            "Block time and hash come from Polygon `eth_getBlockByNumber` on `polygon-bor-rpc.publicnode.com`. A changed hash aborts the run.",
            "- Settlement: `CTF/resolutions.parquet` `payout_numerators`. `['1','0']` pays 1 on the reference outcome and `['0','1']` pays 0. "
            "The resolution counts only when its block time is at or before the next 4:00 p.m. `resolved_at` on the trade file is not used; it is frozen metadata and can post-date the fill.",
            "- Universe: every Step 1 contract, open or settled, whose slug matches `market_slug` in the loaded days. "
            "Step 1's 10,000 volume screen is stricter than the appendix's 2,000 cutoff. This pilot does not rebuild the appendix's 3,507,194 contract-days.",
            "- Category: `category_refined` (Politics, Sports, Crypto, and the other cleaned buckets). "
            "The raw `category` field is a fine label such as Trump or Mentions. The paper says official category and does not name this column. Sorts use the refined field and keep the raw label beside it.",
            "",
            "## Not used",
            "",
            "Current `/v2/oi`, Gamma `openInterest`, cumulative volume, liquidity, CLOB `prices-history` as a trade, and Dome. "
            "A price-history point is not counted as a trade. Quote midpoints are unavailable in TimeSeventeen, so a formation with no fill inside two hours is missing rather than filled.",
            "",
            "## Coverage",
            "",
            "```",
            json.dumps(meta["reasons"], indent=2, ensure_ascii=False),
            "```",
            "",
            "Rebuild:",
            "",
            "```bash",
            "bash scripts/strategy/hlz_cross_section/download_pit.sh",
            "python3 scripts/strategy/hlz_cross_section/hlz_paper.py",
            "python3 scripts/strategy/hlz_cross_section/build_factors.py",
            "```",
            "",
        ]
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    from pit_build import assemble, connect, formation_frame, net_blocks, resolution_rows, timed_nets, trade_dates

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    missing = [path for path in required_paths(args.pit_dir, start, end) if not path.is_file() or path.stat().st_size == 0]
    if missing:
        write_blocker(args.summary, missing, args.pit_dir)
        print(f"missing {len(missing)} PIT files; wrote {args.summary}", flush=True)
        return 2
    con = connect(args.pit_dir, args.universe, start, end, args.max_conditions)
    n_fills = con.execute("select count(*) from fills").fetchone()[0]
    n_conditions = con.execute("select count(*) from picked").fetchone()[0]
    print(f"pilot fills {n_fills} conditions {n_conditions}", flush=True)
    marks = formation_frame(con, start, end)
    days = trade_dates(con)
    nets = net_blocks(con, args.pit_dir)
    print(f"ctf net blocks {len(nets)}", flush=True)
    resolutions = resolution_rows(con, args.pit_dir)
    epochs = sorted({int(row["epoch"]) for row in marks})
    oi_events, resolved, max_error = timed_nets(nets, resolutions, epochs, args.pit_dir / "block_times.json")
    panel, reasons = assemble(marks, days, oi_events, resolved, start, end)
    reasons["block_time_max_abs_error_seconds"] = int(max_error)
    daily = portfolios_from_panel(panel)
    spreads = summarize(daily)
    meta = {
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "scope": "verified_pilot_not_full_sample",
        "invalid_prior_run": "commit 60f85fb used a post-formation /v2/oi snapshot and is not for inference",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "n_fills": int(n_fills),
        "n_conditions": int(n_conditions),
        "max_conditions": args.max_conditions,
        "block_time_max_abs_error_seconds": max_error,
        "n_factor_rows": len(panel),
        "n_portfolio_rows": sum(row["in_portfolio_sample"] == "true" for row in panel),
        "reasons": dict(reasons),
        "spreads": spreads,
    }
    write_csv(args.factors, panel)
    write_csv(args.daily, daily)
    write_csv(args.spreads, spreads)
    args.meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    args.summary.write_text(render_summary(meta), encoding="utf-8")
    print(
        f"rows {meta['n_factor_rows']} portfolio {meta['n_portfolio_rows']} "
        f"spreads {len(spreads)}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a strict HLZ Step 2 pilot from TimeSeventeen CTF and fills.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--pit-dir", type=Path, default=DEFAULT_PIT)
    parser.add_argument("--start-date", default=PILOT_START.isoformat())
    parser.add_argument("--end-date", default=PILOT_END.isoformat())
    parser.add_argument("--max-conditions", type=int, default=25)
    parser.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    parser.add_argument("--spreads", type=Path, default=DEFAULT_SPREADS)
    parser.add_argument("--daily", type=Path, default=DEFAULT_DAILY)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
