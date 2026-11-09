#!/usr/bin/env python3
"""Full-sample Step 2 factor panel for the Polymarket Appendix A.3 universe.

Price is the vgregoire hourly close, at most two hours old at 4:00 p.m.
Eastern. Open interest is the CTF complete-set replay. This command does not
start Step 3 and does not read Dome or a quote midpoint.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from hlz_paper import category_portfolios, formation_epoch  # noqa: E402
from pit_build import ANCHOR_STEP, BOUNDARY_SECONDS, USDC, ZERO, rpc_blocks  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
CACHE = OUT / "cache/step2"
UNIVERSE = OUT / "paper_sample_markets_a3.csv"
BARS = CACHE / "vgregoire/bars_slim.parquet"
PREDICTIONS = CACHE / "vgregoire/predictions.parquet"
MARKETS = CACHE / "vgregoire/markets.parquet"
CTF = CACHE / "timeseventeen/CTF"
BLOCK_CACHE = CACHE / "block_times.json"
DB_PATH = CACHE / "a3_panel.duckdb"
FACTOR = OUT / "a3_factor_daily.parquet"
SPREADS = OUT / "a3_spreads.csv"
SPREADS_DAILY = OUT / "a3_spreads_daily.csv"
COVERAGE = OUT / "a3_coverage.json"
SUMMARY = OUT / "STEP2_SUMMARY.md"
FIRST_DAY = date(2022, 11, 21)
LAST_DAY = date(2026, 3, 29)
HARRIS = "253597"
HARRIS_DAY = date(2024, 10, 30)
HARRIS_OI = 118_579_214.280521


def connect() -> duckdb.DuckDBPyConnection:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "duckdb_tmp").mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET memory_limit='8GB'")
    con.execute(f"SET temp_directory='{CACHE / 'duckdb_tmp'}'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    return con


def has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        "select count(*) from information_schema.tables where table_name = ?",
        [name],
    ).fetchone()
    return bool(row and row[0])


def load_universe(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "universe"):
        print("universe table already loaded", flush=True)
        return
    con.execute(
        f"""
        CREATE TABLE universe AS
        SELECT * EXCLUDE (rn) FROM (
          SELECT
            market_id,
            lower(condition_id) AS condition_id,
            question,
            event_id,
            closed,
            try_cast(cumulative_volume AS double) AS cumulative_volume,
            epoch(try_cast(open_date AS timestamptz))::bigint AS open_epoch,
            epoch(try_cast(expiry AS timestamptz))::bigint AS expiry_epoch,
            CASE
              WHEN closed_time IS NULL OR closed_time = '' THEN NULL
              ELSE epoch(try_cast(closed_time AS timestamptz))::bigint
            END AS closed_epoch,
            row_number() OVER (
              PARTITION BY lower(condition_id)
              ORDER BY try_cast(cumulative_volume AS double) DESC
            ) AS rn
          FROM read_csv('{UNIVERSE}', header=true, all_varchar=true)
          WHERE condition_id IS NOT NULL AND condition_id <> ''
        )
        WHERE rn = 1
          AND open_epoch IS NOT NULL
          AND expiry_epoch IS NOT NULL
        """
    )
    n = con.execute("select count(*) from universe").fetchone()[0]
    print(f"universe conditions {n}", flush=True)


def load_calendar(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "calendar"):
        return
    rows = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        rows.append((day.isoformat(), formation_epoch(day), formation_epoch(day + timedelta(days=1))))
        day += timedelta(days=1)
    con.execute("CREATE TABLE calendar(formation_date DATE, formation_epoch BIGINT, next_epoch BIGINT)")
    con.executemany("INSERT INTO calendar VALUES (CAST(? AS DATE), ?, ?)", rows)
    con.execute(
        """
        CREATE TABLE slots AS
        SELECT formation_date, formation_epoch, formation_epoch - 3600 AS bar_start, 1 AS pref
        FROM calendar
        UNION ALL
        SELECT formation_date, formation_epoch, formation_epoch - 7200, 2 FROM calendar
        """
    )
    print(f"calendar days {len(rows)}", flush=True)


def load_tokens(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "tokens"):
        return
    con.execute(
        f"""
        CREATE TABLE tokens AS
        SELECT condition_id, market_id, prediction_id FROM (
          SELECT u.condition_id, u.market_id, p.prediction_id,
                 row_number() OVER (
                   PARTITION BY u.condition_id
                   ORDER BY CASE WHEN lower(p.outcome) = 'yes' THEN 0 ELSE 1 END,
                            p.outcome_idx
                 ) AS rn
          FROM universe u
          JOIN read_parquet('{PREDICTIONS}') p
            ON p.market_id = try_cast(u.market_id AS bigint)
          WHERE lower(p.outcome) = 'yes' OR p.outcome_idx = 0
        )
        WHERE rn = 1
        """
    )
    n = con.execute("select count(*) from tokens").fetchone()[0]
    print(f"reference tokens {n}", flush=True)


def build_prices(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "form_px"):
        return
    con.execute(
        f"""
        CREATE TABLE form_px AS
        SELECT prediction_id, formation_date, formation_epoch, bar_start, close FROM (
          SELECT b.prediction_id, s.formation_date, s.formation_epoch, s.bar_start, b.close,
                 row_number() OVER (
                   PARTITION BY b.prediction_id, s.formation_date
                   ORDER BY s.pref
                 ) AS rn
          FROM slots s
          JOIN read_parquet('{BARS}') b ON b.bar_start = s.bar_start
          WHERE b.close > 0 AND b.close < 1
        )
        WHERE rn = 1
        """
    )
    n = con.execute("select count(*) from form_px").fetchone()[0]
    print(f"formation closes {n}", flush=True)
    con.execute(
        f"""
        CREATE TABLE trade_days AS
        SELECT prediction_id,
               cast(timezone('America/New_York', to_timestamp(bar_start)) AS date) AS et_day
        FROM read_parquet('{BARS}')
        GROUP BY 1, 2
        """
    )


def build_nets(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "nets"):
        print("CTF nets already aggregated", flush=True)
        return
    usdc = ", ".join(f"'{item}'" for item in USDC)
    specs = [
        ("splits.parquet", "usdc_amount", "AND list_sort(list_transform(partition, lambda x: cast(x AS varchar))) = ['1', '2']"),
        ("merges.parquet", "-usdc_amount", "AND list_sort(list_transform(partition, lambda x: cast(x AS varchar))) = ['1', '2']"),
        ("redemptions.parquet", "-usdc_amount", "AND len(index_sets) > 0"),
    ]
    parts = []
    for filename, sign, extra in specs:
        parts.append(
            f"""
            SELECT lower(condition_id) AS condition_id,
                   cast(split_part(id, '_', 2) AS bigint) AS block,
                   cast({sign} AS double) AS signed
            FROM read_parquet('{CTF / filename}')
            WHERE lower(condition_id) IN (SELECT condition_id FROM universe)
              AND lower(parent_collection_id) = '{ZERO}'
              AND lower(collateral_token) IN ({usdc})
              {extra}
            """
        )
    print("aggregate CTF nets for the A.3 universe", flush=True)
    con.execute(
        f"""
        CREATE TABLE nets AS
        SELECT condition_id, block, sum(signed) AS net
        FROM ({' UNION ALL '.join(parts)})
        GROUP BY 1, 2
        HAVING sum(signed) <> 0
        """
    )
    n = con.execute("select count(*) from nets").fetchone()[0]
    print(f"CTF net blocks {n}", flush=True)


def build_resolutions(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "resolutions"):
        return
    con.execute(
        f"""
        CREATE TABLE resolutions AS
        SELECT lower(condition_id) AS condition_id,
               cast(split_part(id, '_', 2) AS bigint) AS block,
               CASE
                 WHEN list_transform(payout_numerators, lambda x: cast(x AS varchar)) = ['1', '0'] THEN 1.0
                 WHEN list_transform(payout_numerators, lambda x: cast(x AS varchar)) = ['0', '1'] THEN 0.0
                 ELSE NULL
               END AS payout
        FROM read_parquet('{CTF / 'resolutions.parquet'}')
        WHERE lower(condition_id) IN (SELECT condition_id FROM universe)
        """
    )


def time_blocks(con: duckdb.DuckDBPyConnection) -> float:
    if has_table(con, "timing_meta"):
        row = con.execute("select max_error from timing_meta").fetchone()
        return float(row[0]) if row else 0.0
    for name in ("anchors", "anchor_span", "block_time", "cutoffs", "exact_time"):
        con.execute(f"DROP TABLE IF EXISTS {name}")
    bounds = con.execute(
        """
        SELECT min(block), max(block) FROM (
          SELECT block FROM nets
          UNION ALL
          SELECT block FROM resolutions
        )
        """
    ).fetchone()
    if bounds[0] is None:
        raise SystemExit("no CTF blocks for this universe")
    first, last = int(bounds[0]), int(bounds[1])
    anchors = list(range(first, last + 1, ANCHOR_STEP))
    if anchors[-1] != last:
        anchors.append(last)
    print(f"block span {first}..{last} anchors {len(anchors)}", flush=True)
    fetched = rpc_blocks(anchors, BLOCK_CACHE)
    con.execute("CREATE TABLE anchors(block BIGINT, ts BIGINT)")
    con.executemany(
        "INSERT INTO anchors VALUES (?, ?)",
        [(block, int(fetched[block]["timestamp"])) for block in anchors],
    )
    con.execute(
        """
        CREATE TABLE anchor_span AS
        SELECT block, ts,
               lead(block) OVER (ORDER BY block) AS next_block,
               lead(ts) OVER (ORDER BY block) AS next_ts
        FROM anchors
        """
    )
    print("interpolate block times", flush=True)
    con.execute(
        """
        CREATE TABLE block_time AS
        SELECT block, ts AS interp_ts, ts
        FROM (
          SELECT n.block,
                 CASE
                   WHEN n.block <= a.block THEN a.ts
                   WHEN a.next_block IS NULL OR a.next_block = a.block THEN a.ts
                   ELSE a.ts + (a.next_ts - a.ts) * (n.block - a.block) * 1.0 / (a.next_block - a.block)
                 END AS ts
          FROM (
            SELECT DISTINCT block FROM nets
            UNION
            SELECT DISTINCT block FROM resolutions
          ) n
          ASOF LEFT JOIN anchor_span a ON n.block >= a.block
        )
        """
    )
    epochs = [row[0] for row in con.execute("select formation_epoch from calendar union select next_epoch from calendar").fetchall()]
    con.execute("CREATE TABLE cutoffs(epoch BIGINT)")
    con.executemany("INSERT INTO cutoffs VALUES (?)", [(epoch,) for epoch in epochs])
    refine_rows = con.execute(
        f"""
        SELECT DISTINCT b.block
        FROM block_time b
        JOIN cutoffs c ON abs(b.interp_ts - c.epoch) <= {BOUNDARY_SECONDS}
        """
    ).fetchall()
    refine = [int(row[0]) for row in refine_rows]
    print(f"boundary blocks to time exactly {len(refine)}", flush=True)
    exact = rpc_blocks(refine, BLOCK_CACHE) if refine else {}
    if exact:
        con.execute("CREATE TABLE exact_time(block BIGINT, ts BIGINT)")
        con.executemany(
            "INSERT INTO exact_time VALUES (?, ?)",
            [(block, int(record["timestamp"])) for block, record in exact.items()],
        )
        row = con.execute(
            """
            SELECT max(abs(e.ts - b.interp_ts))
            FROM exact_time e
            JOIN block_time b ON b.block = e.block
            LEFT JOIN anchors a ON a.block = e.block
            WHERE a.block IS NULL
            """
        ).fetchone()
        max_error = float(row[0] or 0.0)
        con.execute(
            """
            UPDATE block_time
            SET ts = exact_time.ts
            FROM exact_time
            WHERE block_time.block = exact_time.block
            """
        )
    else:
        max_error = 0.0
    # Exact timestamps cover every block within 15 minutes of a cutoff.
    # An event can cross that cutoff only if the interpolation error is at
    # least half of that window. The pilot's 120s bar is tighter than this
    # sample's observed error, so the fail-closed line is the half-window.
    if max_error > BOUNDARY_SECONDS / 2:
        raise SystemExit(
            f"block-time interpolation error {max_error:.0f}s can cross a formation cutoff"
        )
    con.execute("CREATE TABLE timing_meta(max_error DOUBLE)")
    con.execute("INSERT INTO timing_meta VALUES (?)", [max_error])
    print(f"block-time max interpolation error {max_error:.1f}s", flush=True)
    return max_error


def build_oi(con: duckdb.DuckDBPyConnection) -> None:
    if has_table(con, "oi_curve"):
        return
    print("running open-interest sum", flush=True)
    con.execute(
        """
        CREATE TABLE oi_curve AS
        SELECT condition_id, ts, block,
               sum(net) OVER (PARTITION BY condition_id ORDER BY ts, block) AS oi
        FROM (
          SELECT n.condition_id, n.block, n.net, b.ts
          FROM nets n
          JOIN block_time b ON b.block = n.block
        )
        """
    )


def build_factor(con: duckdb.DuckDBPyConnection) -> None:
    if FACTOR.exists() and FACTOR.stat().st_size > 0 and has_table(con, "factor_done"):
        print("factor parquet already written", flush=True)
        return
    print("assemble factor rows", flush=True)
    con.execute(
        f"""
        COPY (
          WITH base AS (
            SELECT
              f.formation_date,
              f.formation_epoch,
              c.next_epoch,
              t.market_id,
              t.condition_id,
              t.prediction_id,
              u.question,
              coalesce(m.category, '') AS category,
              f.close AS p_form,
              f.bar_start AS p_form_bar_start,
              (
                u.open_epoch <= f.formation_epoch
                AND u.expiry_epoch > f.formation_epoch
                AND (u.closed_epoch IS NULL OR u.closed_epoch > f.formation_epoch)
              ) AS active
            FROM form_px f
            JOIN tokens t ON t.prediction_id = f.prediction_id
            JOIN universe u ON u.condition_id = t.condition_id
            JOIN calendar c ON c.formation_date = f.formation_date
            LEFT JOIN read_parquet('{MARKETS}') m
              ON m.market_id = try_cast(t.market_id AS bigint)
          ),
          traded AS (
            SELECT b.condition_id, b.formation_date, count(td.et_day) > 0 AS traded_prior_7d
            FROM base b
            LEFT JOIN trade_days td
              ON td.prediction_id = b.prediction_id
             AND td.et_day >= b.formation_date - INTERVAL 7 DAY
             AND td.et_day < b.formation_date
            GROUP BY 1, 2
          ),
          with_oi AS (
            SELECT b.*, o.oi
            FROM base b
            ASOF LEFT JOIN oi_curve o
              ON b.condition_id = o.condition_id
             AND b.formation_epoch >= o.ts
          ),
          resolved AS (
            SELECT condition_id, ts, payout, block FROM (
              SELECT r.condition_id, t.ts, r.payout, r.block,
                     row_number() OVER (PARTITION BY r.condition_id ORDER BY r.block) AS rn
              FROM resolutions r
              JOIN block_time t ON t.block = r.block
              WHERE r.payout IS NOT NULL AND t.ts IS NOT NULL
            )
            WHERE rn = 1
          )
          SELECT
            w.formation_date,
            w.market_id,
            w.condition_id,
            w.question,
            w.category,
            w.p_form,
            w.p_form_bar_start,
            (w.formation_epoch - w.p_form_bar_start) / 3600.0 AS p_form_age_hours,
            w.active,
            coalesce(tr.traded_prior_7d, false) AS traded_prior_7d,
            w.oi AS oi_shares,
            CASE WHEN w.oi > 0 THEN w.p_form * w.oi ELSE NULL END AS yesmv,
            CASE
              WHEN p1.close IS NULL OR p1.close <= 0 OR p1.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p1.close / (1 - p1.close))
            END AS lor_1,
            CASE
              WHEN p2.close IS NULL OR p2.close <= 0 OR p2.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p2.close / (1 - p2.close))
            END AS lor_2,
            CASE
              WHEN p3.close IS NULL OR p3.close <= 0 OR p3.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p3.close / (1 - p3.close))
            END AS lor_3,
            CASE
              WHEN p4.close IS NULL OR p4.close <= 0 OR p4.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p4.close / (1 - p4.close))
            END AS lor_4,
            CASE
              WHEN p5.close IS NULL OR p5.close <= 0 OR p5.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p5.close / (1 - p5.close))
            END AS lor_5,
            CASE
              WHEN p6.close IS NULL OR p6.close <= 0 OR p6.close >= 1 THEN NULL
              ELSE ln(w.p_form / (1 - w.p_form)) - ln(p6.close / (1 - p6.close))
            END AS lor_6,
            CASE
              WHEN s.ts > w.formation_epoch AND s.ts <= w.next_epoch THEN s.payout
              ELSE nxt.close
            END AS p_end,
            CASE
              WHEN s.ts > w.formation_epoch AND s.ts <= w.next_epoch THEN 'settlement'
              WHEN nxt.close IS NOT NULL THEN 'next_close'
              ELSE 'missing'
            END AS p_end_source,
            CASE
              WHEN s.ts > w.formation_epoch AND s.ts <= w.next_epoch THEN s.payout - w.p_form
              WHEN nxt.close IS NOT NULL THEN nxt.close - w.p_form
              ELSE NULL
            END AS r_pp,
            (
              w.active
              AND coalesce(tr.traded_prior_7d, false)
              AND coalesce(w.oi, 0) > 0
              AND w.category <> ''
              AND (
                (s.ts > w.formation_epoch AND s.ts <= w.next_epoch)
                OR nxt.close IS NOT NULL
              )
            ) AS in_portfolio_sample
          FROM with_oi w
          LEFT JOIN traded tr
            ON tr.condition_id = w.condition_id AND tr.formation_date = w.formation_date
          LEFT JOIN resolved s ON s.condition_id = w.condition_id
          LEFT JOIN form_px nxt
            ON nxt.prediction_id = w.prediction_id
           AND nxt.formation_date = w.formation_date + INTERVAL 1 DAY
          LEFT JOIN form_px p1
            ON p1.prediction_id = w.prediction_id
           AND p1.formation_date = w.formation_date - INTERVAL 1 DAY
          LEFT JOIN form_px p2
            ON p2.prediction_id = w.prediction_id
           AND p2.formation_date = w.formation_date - INTERVAL 2 DAY
          LEFT JOIN form_px p3
            ON p3.prediction_id = w.prediction_id
           AND p3.formation_date = w.formation_date - INTERVAL 3 DAY
          LEFT JOIN form_px p4
            ON p4.prediction_id = w.prediction_id
           AND p4.formation_date = w.formation_date - INTERVAL 4 DAY
          LEFT JOIN form_px p5
            ON p5.prediction_id = w.prediction_id
           AND p5.formation_date = w.formation_date - INTERVAL 5 DAY
          LEFT JOIN form_px p6
            ON p6.prediction_id = w.prediction_id
           AND p6.formation_date = w.formation_date - INTERVAL 6 DAY
        ) TO '{FACTOR}' (FORMAT parquet, COMPRESSION zstd)
        """
    )
    con.execute("CREATE TABLE factor_done(ok BOOLEAN)")
    con.execute("INSERT INTO factor_done VALUES (true)")
    print(f"wrote {FACTOR}", flush=True)


def harris_check(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT oi_shares, p_form
        FROM read_parquet('{FACTOR}')
        WHERE market_id = '{HARRIS}' AND formation_date = DATE '{HARRIS_DAY.isoformat()}'
        """
    ).fetchone()
    if row is None or row[0] is None:
        raise SystemExit("Harris 2024-10-30 open interest is missing; the replay did not reproduce")
    oi = float(row[0])
    gap = abs(oi - HARRIS_OI) / HARRIS_OI
    print(f"Harris 2024-10-30 OI {oi:.2f} vs pilot {HARRIS_OI:.2f} relative {gap:.6f}", flush=True)
    if gap > 0.005:
        raise SystemExit("Harris open interest moved by more than 0.5 percent from the checked replay")
    return {"market_id": HARRIS, "date": HARRIS_DAY.isoformat(), "oi_shares": oi, "p_form": float(row[1]), "relative_gap": gap}


def coverage(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    print("coverage counts", flush=True)
    alive = con.execute(
        """
        SELECT count(*)
        FROM universe u
        JOIN calendar c
          ON u.open_epoch <= c.formation_epoch
         AND u.expiry_epoch > c.formation_epoch
         AND (u.closed_epoch IS NULL OR u.closed_epoch > c.formation_epoch)
        """
    ).fetchone()[0]
    row = con.execute(
        f"""
        SELECT
          count(*) AS with_price,
          count(*) FILTER (WHERE active) AS active_with_price,
          count(*) FILTER (WHERE active AND oi_shares IS NOT NULL) AS active_with_oi_obs,
          count(*) FILTER (WHERE active AND oi_shares > 0) AS active_with_positive_oi,
          count(*) FILTER (WHERE in_portfolio_sample) AS portfolio_sample,
          count(DISTINCT condition_id) AS conditions_with_price,
          min(formation_date),
          max(formation_date)
        FROM read_parquet('{FACTOR}')
        """
    ).fetchone()
    universe_n = con.execute("select count(*) from universe").fetchone()[0]
    token_n = con.execute("select count(*) from tokens").fetchone()[0]
    return {
        "universe_conditions": int(universe_n),
        "conditions_with_reference_token": int(token_n),
        "alive_contract_days": int(alive),
        "contract_days_with_price": int(row[0]),
        "active_contract_days_with_price": int(row[1]),
        "active_with_oi_observation": int(row[2]),
        "active_with_positive_oi": int(row[3]),
        "portfolio_sample_contract_days": int(row[4]),
        "conditions_with_price": int(row[5]),
        "first_formation_date": str(row[6]),
        "last_formation_date": str(row[7]),
    }


def write_spreads(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    dates = [
        row[0]
        for row in con.execute(
            f"SELECT DISTINCT formation_date FROM read_parquet('{FACTOR}') WHERE in_portfolio_sample ORDER BY 1"
        ).fetchall()
    ]
    print(f"portfolio dates {len(dates)}", flush=True)
    characteristics = ["yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6"]
    daily: list[dict[str, Any]] = []
    for index, day in enumerate(dates, start=1):
        rows = con.execute(
            f"""
            SELECT category, yesmv, lor_1, lor_2, lor_3, lor_4, lor_5, lor_6, oi_shares, r_pp
            FROM read_parquet('{FACTOR}')
            WHERE formation_date = ? AND in_portfolio_sample
            """,
            [day],
        ).fetchall()
        packed = []
        for category, yesmv, l1, l2, l3, l4, l5, l6, oi, payoff in rows:
            packed.append(
                {
                    "category": category,
                    "yesmv": yesmv,
                    "lor_1": l1,
                    "lor_2": l2,
                    "lor_3": l3,
                    "lor_4": l4,
                    "lor_5": l5,
                    "lor_6": l6,
                    "oi": oi,
                    "r": payoff,
                }
            )
        for name in characteristics:
            usable = []
            for item in packed:
                if item[name] is None or item["oi"] is None or item["r"] is None:
                    continue
                if float(item["oi"]) <= 0:
                    continue
                usable.append(
                    {"category": item["category"], "x": float(item[name]), "oi": float(item["oi"]), "r": float(item["r"])}
                )
            result = category_portfolios(usable)
            if result is None:
                continue
            daily.append(
                {
                    "date": day.isoformat() if hasattr(day, "isoformat") else str(day),
                    "characteristic": name,
                    "n_categories": result["n_categories"],
                    "n_contracts": result["n_contracts"],
                    "low_cents": f"{result['low'] * 100:.6f}",
                    "middle_cents": f"{result['middle'] * 100:.6f}",
                    "high_cents": f"{result['high'] * 100:.6f}",
                    "high_minus_low_cents": f"{result['high_minus_low'] * 100:.6f}",
                }
            )
        if index % 50 == 0 or index == len(dates):
            print(f"spreads {index}/{len(dates)}", flush=True)
    SPREADS_DAILY.parent.mkdir(parents=True, exist_ok=True)
    with SPREADS_DAILY.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(daily[0].keys()) if daily else ["date"])
        writer.writeheader()
        writer.writerows(daily)
    return daily


def summarize(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in daily:
        grouped.setdefault(row["characteristic"], []).append(row)
    summary = []
    for name in ["yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6"]:
        rows = grouped.get(name, [])
        if not rows:
            continue
        count = len(rows)

        def avg(key: str, rows: list[dict[str, Any]] = rows) -> float:
            return sum(float(row[key]) for row in rows) / count

        summary.append(
            {
                "characteristic": name,
                "n_dates": count,
                "mean_low_cents": f"{avg('low_cents'):.6f}",
                "mean_middle_cents": f"{avg('middle_cents'):.6f}",
                "mean_high_cents": f"{avg('high_cents'):.6f}",
                "mean_high_minus_low_cents": f"{avg('high_minus_low_cents'):.6f}",
                "scope": "a3_full_sample_through_hourly_coverage",
            }
        )
    with SPREADS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()) if summary else ["characteristic"])
        writer.writeheader()
        writer.writerows(summary)
    return summary


def render(meta: dict[str, Any]) -> str:
    old = json.loads((OUT / "paper_sample_meta.json").read_text(encoding="utf-8"))
    new = json.loads((OUT / "paper_sample_meta_a3.json").read_text(encoding="utf-8"))
    cov = meta["coverage"]
    spreads = {row["characteristic"]: row for row in meta["spreads"]}

    def line(name: str) -> str:
        row = spreads.get(name)
        if row is None:
            return "not formed"
        return f"{float(row['mean_high_minus_low_cents']):.4f} cents over {row['n_dates']} dates"

    return "\n".join(
        [
            "# HLZ Step 2 full sample",
            "",
            "价格只用 vgregoire 小时 K 线的 `close`（该小时最后一笔成交），且这根 K 线的开端距美东 16:00 不超过 2 小时。没有 Dome，没有报价中点。",
            "样本是附录 A.3：Gamma 累计成交额严格大于 2,000 美元名义，观察存续至少 2 天，开始日不晚于 2026-03-29。每个 condition 只保留一个 YES（没有 YES 标签时用 outcome 0）。",
            "",
            f"Price sample: {cov['first_formation_date']} through {cov['last_formation_date']}. "
            "Hourly files run 2022-11-21 through 2026-03-29. vgregoire has no file for 2026-03-30, so formation dates stop at 2026-03-29. "
            "The next-day close for 2026-03-29 does not exist; that date enters the portfolio only when settlement supplies the endpoint.",
            "",
            "## Universe versus the earlier ≥10,000 screen",
            "",
            f"Earlier Step 1 file (volume ≥ 10,000, scheduled life, sample end {old['sample_end_date']}): "
            f"{old['n_contracts']} contracts, {old['n_events']} events "
            f"({old['n_open_contracts']} open, {old['n_closed_contracts']} closed).",
            f"This A.3 file (volume > 2,000, observed life, sample end {new['sample_end_date']}): "
            f"{new['n_contracts']} contracts, {new['n_events']} events "
            f"({new['n_open_contracts']} open, {new['n_closed_contracts']} closed). "
            f"Volume stats: min {new['volume_stats']['min']}, median {new['volume_stats']['median']}, "
            f"mean {new['volume_stats']['mean']}.",
            "旧的 ≥10,000 文件保留作对照，不是这一次的样本。",
            "",
            "## Coverage",
            "",
            f"Universe conditions with a condition id: {cov['universe_conditions']}. "
            f"With a YES or outcome-0 token in vgregoire predictions: {cov['conditions_with_reference_token']}.",
            f"Alive contract-days (open, not yet closed, expiry still ahead): {cov['alive_contract_days']}.",
            f"Contract-days with a ≤2h hourly close: {cov['contract_days_with_price']} "
            f"across {cov['conditions_with_price']} conditions.",
            f"Those closes that are also active at formation: {cov['active_contract_days_with_price']}.",
            f"Active closes with a CTF open-interest observation: {cov['active_with_oi_observation']}. "
            f"With positive raw OI: {cov['active_with_positive_oi']}.",
            f"Portfolio sample (active, positive OI, a trade on one of the prior 7 Eastern days, a category, and a next-period price): "
            f"{cov['portfolio_sample_contract_days']}.",
            f"Harris 2024-10-30 replay check: OI {meta['harris']['oi_shares']:.2f} "
            f"(relative gap {meta['harris']['relative_gap']:.6f} versus the earlier 25-contract run).",
            "",
            "## High minus Low",
            "",
            "Sorts are inside a date and a vgregoire category, 1st/99th winsorize, 30th/70th legs, raw-OI weights, then category-OI weights. Units are cents of price change.",
            f"YESMV: {line('yesmv')}.",
            f"LOR(1): {line('lor_1')}.",
            f"LOR(2): {line('lor_2')}.",
            f"LOR(3): {line('lor_3')}.",
            f"LOR(4): {line('lor_4')}.",
            f"LOR(5): {line('lor_5')}.",
            f"LOR(6): {line('lor_6')}.",
            "这些是本仓库按上述数据截止日算出的价差，不是论文表 IA.15 的复述。",
            "",
            "## Remaining Appendix A.3 gaps",
            "",
            "- Dome hourly prices are not available. There is no bid, ask, or quote midpoint. LOR uses the hourly close only.",
            "- The trade's exact second inside the hour is not in the file. Age is measured from the bar open, which is the older bound.",
            "- Hourly bars end 2026-03-29. The paper's TimeSeventeen archive continues to 2026-04-28. Seven days in late 2022 have no hourly file (2022-11-24, 2022-11-25, 2022-11-26, 2022-11-27, 2022-12-04, 2022-12-05, 2022-12-10).",
            "- Category is `vgregoire/polymarket-users` `markets.category`. The paper says official category and does not name the column. TimeSeventeen `category_refined` is downloaded only for the 15-day pilot window, so it is not the full-sample category.",
            "- Open interest counts root complete-set splits, merges, and redemptions whose collateral is USDC.e, native USDC, or the neg-risk wrapper `0x3a3bd7bb9528e159577f7c2e685cc81a765002e2`. One unit of collateral is one complete set. Lifecycle rows that never appear in those CTF tables are absent, not filled in.",
            f"- Block time is linear between anchors 500 blocks apart. Blocks within 15 minutes of a 4:00 p.m. cutoff are read exactly. "
            f"The largest interpolation error on those exact blocks in this run is {meta['block_time_max_error_seconds']:.0f} seconds. "
            "The run aborts if that error can reach the cutoff (half of the 15-minute window).",
            "- Cached Gamma bands at volume ≥ 10,000 did not store `closedTime`. Those rows were backfilled. A market that still has no `closedTime` uses expiry, capped at the sample-end day, as the observed end.",
            "- Newey–West standard errors are not computed. Bid–ask and cost-of-arbitrage sorts are not in the Polymarket tables and are not computed here.",
            "- Step 3 is not started. The withdrawn `/v2/oi` snapshot is not an input.",
            "",
            f"Factor table: `{FACTOR.relative_to(REPO)}`. Daily spreads: `{SPREADS_DAILY.relative_to(REPO)}`.",
            "",
        ]
    )


def main() -> int:
    for path in (UNIVERSE, BARS, PREDICTIONS, MARKETS, CTF / "splits.parquet"):
        if not path.exists():
            raise SystemExit(f"missing {path}")
    con = connect()
    load_universe(con)
    load_calendar(con)
    load_tokens(con)
    build_prices(con)
    build_nets(con)
    build_resolutions(con)
    max_error = time_blocks(con)
    build_oi(con)
    build_factor(con)
    harris = harris_check(con)
    cov = coverage(con)
    daily = write_spreads(con)
    spreads = summarize(daily)
    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_source": "vgregoire_ohlcv_1h_close",
        "max_price_age_hours": 2,
        "sample_first_day": FIRST_DAY.isoformat(),
        "sample_last_day": LAST_DAY.isoformat(),
        "block_time_max_error_seconds": max_error,
        "coverage": cov,
        "harris": harris,
        "spreads": spreads,
    }
    COVERAGE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    SUMMARY.write_text(render(meta), encoding="utf-8")
    print("STEP2_SUMMARY written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
