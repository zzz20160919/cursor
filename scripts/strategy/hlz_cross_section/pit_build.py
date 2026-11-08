"""Memory-safe pilot assembly. DuckDB keeps the tapes; Python sees aggregates."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from hlz_paper import (
    endpoint_price,
    formation_epoch,
    formation_time,
    lor,
    replay_open_interest,
    traded_on_preceding_days,
    yes_payout,
)


RPC = "https://polygon-bor-rpc.publicnode.com"
ZERO = "0x" + "0" * 64
USDC = (
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # native USDC
    # Neg-risk wrapped collateral. On the 2024 Harris market this token is the
    # collateral for 458,398 of 458,400 PositionSplit rows; USDC.e is a 1-share dust row.
    "0x3a3bd7bb9528e159577f7c2e685cc81a765002e2",
)
ANCHOR_STEP = 500
BOUNDARY_SECONDS = 15 * 60


def iso_z(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rpc_blocks(blocks: list[int], cache_path: Path) -> dict[int, dict[str, Any]]:
    cache: dict[str, Any] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    missing = []
    for block in blocks:
        cached = cache.get(str(block))
        if isinstance(cached, dict) and cached.get("hash") and "timestamp" in cached:
            out[block] = cached
        else:
            missing.append(block)
    print(f"anchor blocks cached {len(out)} fetch {len(missing)}", flush=True)
    for start in range(0, len(missing), 40):
        chunk = missing[start : start + 40]
        payload = [
            {"jsonrpc": "2.0", "id": index, "method": "eth_getBlockByNumber", "params": [hex(block), False]}
            for index, block in enumerate(chunk)
        ]
        request = urllib.request.Request(
            RPC,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "hlz-step2"},
        )
        delay = 1.0
        body = None
        for _attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read().decode())
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503}:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 20)
        if body is None:
            raise SystemExit("Polygon RPC kept refusing block lookups")
        if isinstance(body, dict):
            body = [body]
        by_id = {item.get("id"): item for item in body}
        for index, block in enumerate(chunk):
            result = (by_id.get(index) or {}).get("result")
            if not isinstance(result, dict) or "timestamp" not in result:
                raise SystemExit(f"Polygon did not return block {block}")
            record = {"timestamp": int(result["timestamp"], 16), "hash": result["hash"]}
            previous = cache.get(str(block))
            if isinstance(previous, dict) and previous.get("hash") not in {None, record["hash"]}:
                raise SystemExit(f"block {block} hash changed")
            cache[str(block)] = record
            out[block] = record
        if start % 800 == 0:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            print(f"anchors {min(start + 40, len(missing))}/{len(missing)}", flush=True)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


def interpolate(block: int, anchors: list[tuple[int, int]]) -> int:
    if block <= anchors[0][0]:
        return anchors[0][1]
    if block >= anchors[-1][0]:
        return anchors[-1][1]
    lo = 0
    hi = len(anchors) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if anchors[mid][0] <= block:
            lo = mid
        else:
            hi = mid
    left_b, left_t = anchors[lo]
    right_b, right_t = anchors[hi]
    if right_b == left_b:
        return left_t
    weight = (block - left_b) / (right_b - left_b)
    return int(left_t + weight * (right_t - left_t))


def connect(pit: Path, universe: Path, start: date, end: date, max_conditions: int) -> duckdb.DuckDBPyConnection:
    first = start - timedelta(days=7)
    last = end + timedelta(days=1)
    files = []
    day = first
    while day <= last:
        stamp = day.strftime("%Y_%m_%d")
        for folder in ("daily_aligned", "daily_aligned_multi"):
            files.append(str(pit / folder / f"{stamp}.parquet"))
        day += timedelta(days=1)
    con = duckdb.connect()
    con.execute("set timezone = 'UTC'")
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
        create table fills as
        select
          lower(t.condition_id) as condition_id,
          t.block_timestamp::bigint as ts,
          t.p_event::double as price,
          t.category as category_raw,
          t.category_refined as category,
          t.neg_risk as neg_risk,
          u.market_id, u.question, u.event_id, u.event_title, u.open_date, u.expiry, u.closed
        from read_parquet(?) t
        join universe u on lower(t.market_slug) = u.slug
        where t.block_timestamp is not null and t.p_event > 0 and t.p_event < 1
        """,
        [files],
    )
    con.execute(
        """
        create table picked as
        select condition_id from (
          select condition_id, count(*) as n from fills group by 1 order by n desc limit ?
        )
        """,
        [max_conditions],
    )
    con.execute("delete from fills where condition_id not in (select condition_id from picked)")
    return con


def formation_frame(con: duckdb.DuckDBPyConnection, start: date, end: date) -> list[dict[str, Any]]:
    days = []
    cursor = start - timedelta(days=6)
    while cursor <= end + timedelta(days=1):
        days.append((cursor.isoformat(), formation_epoch(cursor)))
        cursor += timedelta(days=1)
    con.execute("create table days(day varchar, epoch bigint)")
    con.executemany("insert into days values (?, ?)", days)
    con.execute(
        """
        create table grid as
        select p.condition_id, d.day, d.epoch
        from picked p
        cross join days d
        """
    )
    rows = con.execute(
        """
        select g.condition_id, g.day, g.epoch, t.ts, t.price,
               t.category, t.category_raw, t.neg_risk, t.market_id, t.question,
               t.event_id, t.event_title, t.open_date, t.expiry, t.closed
        from grid g
        asof left join fills t
          on g.condition_id = t.condition_id and t.ts <= g.epoch
        """
    ).fetchall()
    columns = [
        "condition_id", "day", "epoch", "ts", "price", "category", "category_raw", "neg_risk",
        "market_id", "question", "event_id", "event_title", "open_date", "expiry", "closed",
    ]
    return [dict(zip(columns, row)) for row in rows]


def trade_dates(con: duckdb.DuckDBPyConnection) -> dict[str, set[date]]:
    rows = con.execute(
        """
        select condition_id,
               cast(timezone('America/New_York', to_timestamp(ts)) as date) as et_day
        from fills
        group by 1, 2
        """
    ).fetchall()
    out: dict[str, set[date]] = {}
    for condition, et_day in rows:
        out.setdefault(condition, set()).add(et_day)
    return out


def net_blocks(con: duckdb.DuckDBPyConnection, pit: Path) -> list[tuple[str, int, float]]:
    zero = ZERO
    usdc = ", ".join(f"'{item}'" for item in USDC)
    parts = []
    specs = [
        ("splits.parquet", "usdc_amount", "and list_sort(list_transform(partition, lambda x: cast(x as varchar))) = ['1', '2']"),
        ("merges.parquet", "-usdc_amount", "and list_sort(list_transform(partition, lambda x: cast(x as varchar))) = ['1', '2']"),
        (
            "redemptions.parquet",
            "-usdc_amount",
            "and len(index_sets) > 0",
        ),
    ]
    for filename, sign, extra in specs:
        parts.append(
            f"""
            select lower(condition_id) as condition_id,
                   cast(split_part(id, '_', 2) as bigint) as block,
                   {sign} as signed
            from read_parquet('{pit / "CTF" / filename}')
            where lower(condition_id) in (select condition_id from picked)
              and lower(parent_collection_id) = '{zero}'
              and lower(collateral_token) in ({usdc})
              {extra}
            """
        )
    sql = f"""
        select condition_id, block, sum(signed) as net
        from ({' union all '.join(parts)})
        group by 1, 2
        having sum(signed) <> 0
    """
    print("aggregate CTF nets", flush=True)
    return [(row[0], int(row[1]), float(row[2])) for row in con.execute(sql).fetchall()]


def resolution_rows(con: duckdb.DuckDBPyConnection, pit: Path) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        select id, lower(condition_id), payout_numerators
        from read_parquet(?)
        where lower(condition_id) in (select condition_id from picked)
        """,
        [str(pit / "CTF" / "resolutions.parquet")],
    ).fetchall()
    return [{"id": row[0], "condition_id": row[1], "payout": row[2]} for row in rows]


def timed_nets(
    nets: list[tuple[str, int, float]],
    resolutions: list[dict[str, Any]],
    formation_epochs: list[int],
    cache_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], float]:
    blocks = sorted({block for _condition, block, _net in nets} | {
        int(str(row["id"]).split("_")[1]) for row in resolutions if "_" in str(row["id"])
    })
    if not blocks:
        return {}, {}, 0.0
    anchors = list(range(blocks[0], blocks[-1] + 1, ANCHOR_STEP))
    if anchors[-1] != blocks[-1]:
        anchors.append(blocks[-1])
    exact = rpc_blocks(anchors, cache_path)
    anchor_pairs = sorted((block, exact[block]["timestamp"]) for block in anchors)
    rough = {block: interpolate(block, anchor_pairs) for block in blocks}
    boundaries = set(formation_epochs)
    refine = [
        block
        for block, stamp in rough.items()
        if any(abs(stamp - epoch) <= BOUNDARY_SECONDS for epoch in boundaries)
    ]
    if refine:
        exact.update(rpc_blocks(refine, cache_path))
    # Quality: exact versus interpolation on anchors is zero by construction.
    # Check a spread of non-anchor blocks that we fetched as boundary refinements.
    errors = [
        abs(exact[block]["timestamp"] - rough[block])
        for block in refine
        if block not in set(anchors)
    ]
    max_error = float(max(errors)) if errors else 0.0
    if max_error > 120:
        raise SystemExit(f"block-time interpolation error {max_error:.0f}s exceeds 120s")
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for condition, block, net in nets:
        stamp = exact[block]["timestamp"] if block in exact else rough[block]
        kind = "split" if net > 0 else "merge"
        by_condition.setdefault(condition, []).append(
            {
                "kind": kind,
                "timestamp": stamp,
                "amount": abs(net),
                "collateral": USDC[0],
                "parent": ZERO,
                "partition": ["1", "2"],
            }
        )
    resolved = {}
    for row in resolutions:
        block = int(str(row["id"]).split("_")[1])
        stamp = exact[block]["timestamp"] if block in exact else rough.get(block)
        resolved[row["condition_id"]] = {
            "timestamp": stamp,
            "value": yes_payout(row["payout"]),
        }
    return by_condition, resolved, max_error


def ensure_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assemble(
    marks: list[dict[str, Any]],
    trade_days: dict[str, set[date]],
    oi_events: dict[str, list[dict[str, Any]]],
    resolutions: dict[str, dict[str, Any]],
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from collections import defaultdict

    reasons: dict[str, int] = defaultdict(int)
    by_key = {(row["condition_id"], row["day"]): row for row in marks}
    conditions = sorted({row["condition_id"] for row in marks})
    panel = []
    day = start
    while day <= end:
        day_text = day.isoformat()
        for condition in conditions:
            row = by_key.get((condition, day_text))
            if row is None:
                continue
            opened = ensure_utc(row["open_date"])
            expiry = ensure_utc(row["expiry"])
            form_dt = formation_time(day)
            form = int(row["epoch"])
            if opened is not None and opened > form_dt:
                reasons["not_yet_open"] += 1
                continue
            if expiry is not None and expiry < form_dt:
                reasons["already_expired"] += 1
                continue
            reasons["alive_contract_days"] += 1
            price = None
            obs = None
            if row["ts"] is not None and row["price"] is not None and int(row["ts"]) <= form:
                age = form - int(row["ts"])
                if age <= 2 * 3600 and 0.0 < float(row["price"]) < 1.0:
                    price = float(row["price"])
                    obs = int(row["ts"])
                else:
                    reasons["stale_or_boundary_trade"] += 1
            else:
                reasons["no_trade_at_or_before_formation"] += 1
            traded = any(
                (day - timedelta(days=offset)) in trade_days.get(condition, set())
                for offset in range(1, 8)
            )
            if not traded:
                reasons["no_trade_in_prior_7_calendar_days"] += 1
            oi_value, oi_reason = replay_open_interest(oi_events.get(condition, []), form)
            if oi_value is None:
                reasons[oi_reason] += 1
            elif oi_value <= 0:
                reasons["nonpositive_open_interest"] += 1
            yesmv = price * oi_value if price is not None and oi_value is not None and oi_value > 0 else None
            lors = {}
            for horizon in range(1, 7):
                past = by_key.get((condition, (day - timedelta(days=horizon)).isoformat()))
                past_price = None
                if past is not None and past["ts"] is not None and past["price"] is not None:
                    past_epoch = int(past["epoch"])
                    if int(past["ts"]) <= past_epoch and past_epoch - int(past["ts"]) <= 2 * 3600:
                        past_price = float(past["price"])
                lors[horizon] = lor(price, past_price)
            resolution = resolutions.get(condition, {})
            next_row = by_key.get((condition, (day + timedelta(days=1)).isoformat()))
            next_trade = None
            next_epoch = formation_epoch(day + timedelta(days=1))
            if next_row is not None and next_row["ts"] is not None and next_row["price"] is not None:
                if int(next_row["ts"]) <= next_epoch and next_epoch - int(next_row["ts"]) <= 2 * 3600:
                    next_trade = {"timestamp": int(next_row["ts"]), "price": float(next_row["price"])}
            end_price, end_source = endpoint_price(
                next_epoch=next_epoch,
                settlement_time=resolution.get("timestamp"),
                settlement_value=resolution.get("value"),
                next_trade=next_trade,
            )
            r_pp = end_price - price if end_price is not None and price is not None else None
            category = row.get("category") or ""
            in_sample = bool(
                price is not None and traded and oi_value is not None and oi_value > 0 and r_pp is not None and category
            )
            if in_sample:
                reasons["portfolio_sample"] += 1
            panel.append(
                {
                    "date": day_text,
                    "market_id": row["market_id"],
                    "question": row["question"],
                    "event_id": row["event_id"],
                    "event_title": row["event_title"],
                    "condition_id": condition,
                    "category": category,
                    "category_raw": row.get("category_raw") or "",
                    "neg_risk": row.get("neg_risk") or "",
                    "closed_in_step1": row.get("closed"),
                    "p_form": "" if price is None else f"{price:.6f}",
                    "p_form_obs": "" if obs is None else iso_z(obs),
                    "p_form_age_hours": "" if obs is None else f"{(form - obs) / 3600:.4f}",
                    "price_source": "" if price is None else "timeseventeen_fill_p_event",
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
        day += timedelta(days=1)
    return panel, reasons
