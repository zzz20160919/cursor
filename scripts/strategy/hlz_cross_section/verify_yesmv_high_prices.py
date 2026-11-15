#!/usr/bin/env python3
"""Check the 20 YESMV High contract-days against the raw hourly files.

This does not change the portfolio. It only reports whether each jump is
the hourly close in the vgregoire file.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from diagnose_yesmv_high import assign, load_rows  # noqa: E402
from hlz_paper import formation_epoch, formation_time  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
TOP = OUT / "diagnostic_yesmv_high_top.csv"
FACTOR = OUT / "a3_factor_daily.parquet"
PRED = OUT / "cache/step2/vgregoire/predictions.parquet"
BARS = OUT / "cache/step2/vgregoire/ohlcv_1h"
DB = OUT / "cache/step2/a3_panel.duckdb"
REPORT_CSV = OUT / "diagnostic_yesmv_high_price_check.csv"


def iso(epoch: int | None) -> str:
    if epoch is None:
        return ""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_bars(con: duckdb.DuckDBPyConnection, day: date, token_ids: list[str]) -> list[tuple]:
    path = BARS / f"{day.strftime('%Y_%m_%d')}.parquet"
    if not path.exists() or not token_ids:
        return []
    placeholders = ", ".join("?" for _ in token_ids)
    return con.execute(
        f"""
        SELECT prediction_id,
               cast(epoch(cast(timestamp AS timestamptz)) AS bigint),
               close,
               trade_count
        FROM read_parquet('{path}')
        WHERE prediction_id IN ({placeholders})
          AND trade_count > 0
          AND close > 0 AND close < 1
        """,
        token_ids,
    ).fetchall()


def eligible(bars: list[tuple], token: str, formation: int) -> list[tuple]:
    slots = {formation - 3600, formation - 7200}
    return [bar for bar in bars if bar[0] == token and int(bar[1]) in slots]


def clob_near(token: str, start: int, end: int) -> tuple[float | None, str]:
    query = urllib.parse.urlencode(
        {"market": token, "startTs": start, "endTs": end, "fidelity": 60}
    )
    url = f"https://clob.polymarket.com/prices-history?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "hlz-price-check"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:  # network is optional
        return None, type(exc).__name__
    history = payload.get("history") if isinstance(payload, dict) else None
    if not history:
        return None, "empty"
    nearest = min(history, key=lambda point: abs(int(point.get("t", 0)) - start))
    try:
        return float(nearest.get("p")), "ok"
    except (TypeError, ValueError):
        return None, "bad_point"


def main() -> int:
    wanted = []
    with TOP.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["leg"] == "high" and int(row["rank_by_contribution"]) <= 20:
                wanted.append(row)
    if len(wanted) != 20:
        raise SystemExit(f"expected 20 high rows, found {len(wanted)}")
    grouped = load_rows()
    assigned, n_dates = assign(grouped)
    weight_of: dict[tuple[str, str], dict[str, Any]] = {}
    names_on: dict[str, int] = {}
    for row in assigned:
        if row["leg"] != "high":
            continue
        names_on[row["date"]] = names_on.get(row["date"], 0) + 1
        weight_of[(row["date"], row["market_id"])] = row
    con = duckdb.connect()
    con.execute(f"ATTACH '{DB}' AS saved (READ_ONLY)")
    market_ids = sorted({row["market_id"] for row in wanted})
    tokens = con.execute(
        f"""
        SELECT cast(market_id AS varchar), prediction_id, outcome, outcome_idx
        FROM read_parquet('{PRED}')
        WHERE market_id IN ({", ".join("?" for _ in market_ids)})
        """,
        [int(item) for item in market_ids],
    ).fetchall()
    by_market: dict[str, list[tuple]] = {}
    for market_id, prediction_id, outcome, outcome_idx in tokens:
        by_market.setdefault(str(market_id), []).append((prediction_id, outcome, int(outcome_idx)))
    panel = {
        (str(day), market_id): (condition, bar_start, age, p_end, source, payoff, price)
        for day, market_id, condition, bar_start, age, p_end, source, payoff, price in con.execute(
            f"""
            SELECT formation_date, market_id, condition_id, p_form_bar_start,
                   p_form_age_hours, p_end, p_end_source, r_pp, p_form
            FROM read_parquet('{FACTOR}')
            WHERE market_id IN ({", ".join("?" for _ in market_ids)})
            """,
            market_ids,
        ).fetchall()
    }
    resolutions = {
        condition: (payout, int(stamp) if stamp is not None else None)
        for condition, payout, stamp in con.execute(
            """
            SELECT condition_id, payout, ts FROM (
              SELECT r.condition_id, r.payout, b.ts,
                     row_number() OVER (PARTITION BY r.condition_id ORDER BY r.block) AS rn
              FROM saved.resolutions r
              JOIN saved.block_time b ON b.block = r.block
              WHERE r.payout IS NOT NULL
            ) WHERE rn = 1
            """
        ).fetchall()
    }
    out_rows = []
    for row in wanted:
        day = date.fromisoformat(row["date"])
        panel_row = panel[(row["date"], row["market_id"])]
        condition, bar_start, age, p_end, source, payoff, price = panel_row
        formation = formation_epoch(day)
        nxt = formation_epoch(day + timedelta(days=1))
        token_rows = by_market.get(row["market_id"], [])
        yes = sorted(token_rows, key=lambda item: (0 if str(item[1]).lower() == "yes" else 1, item[2]))
        yes = [item for item in yes if str(item[1]).lower() == "yes" or item[2] == 0]
        token = yes[0][0] if yes else ""
        outcome = yes[0][1] if yes else ""
        no = next((item[0] for item in token_rows if str(item[1]).lower() == "no"), "")
        ids = [item for item in (token, no) if item]
        bars_today = raw_bars(con, day, ids)
        bars_next = raw_bars(con, day + timedelta(days=1), ids)
        chosen = [bar for bar in eligible(bars_today, token, formation)]
        chosen.sort(key=lambda bar: int(bar[1]))
        used = next((bar for bar in chosen if int(bar[1]) == int(bar_start)), None)
        latest = chosen[-1] if chosen else None
        no_same = next((bar[2] for bar in bars_today if bar[0] == no and int(bar[1]) == int(bar_start)), None)
        next_chosen = eligible(bars_next, token, nxt)
        next_chosen.sort(key=lambda bar: int(bar[1]))
        next_bar = next_chosen[-1] if next_chosen else None
        resolved = resolutions.get(str(condition).lower())
        settle_payout, settle_ts = resolved if resolved else (None, None)
        settle_in = (
            settle_ts is not None
            and settle_payout is not None
            and formation < int(settle_ts) <= nxt
        )
        raw_ok = used is not None and abs(float(used[2]) - float(price)) < 1e-4
        latest_ok = latest is not None and int(latest[1]) == int(bar_start)
        fresh_ok = used is not None and 0 < (formation - int(used[1])) <= 2 * 3600 and int(used[1]) + 3600 <= formation
        token_ok = bool(token) and (str(outcome).lower() == "yes" or (yes and yes[0][2] == 0))
        complement_ok = no_same is None or abs((float(used[2]) + float(no_same)) - 1) <= 0.05 if used else False
        if source == "next_close":
            end_ok = next_bar is not None and abs(float(next_bar[2]) - float(p_end)) < 1e-4
            end_stamp = int(next_bar[1]) if next_bar else None
        elif source == "settlement":
            end_ok = settle_in and abs(float(settle_payout) - float(p_end)) < 1e-6
            end_stamp = int(settle_ts) if settle_ts is not None else None
        else:
            end_ok = False
            end_stamp = None
        recomputed = (float(p_end) - float(price)) * 100
        return_ok = abs(recomputed - float(row["return_cents"])) < 0.01
        held = weight_of[(row["date"], row["market_id"])]
        day_weight = held["day_weight"]
        n_names = names_on[row["date"]]
        single = n_names == 1 and abs(day_weight - 1) < 1e-9
        clob_p, clob_note = clob_near(token, int(bar_start), int(bar_start) + 3600) if token else (None, "no_token")
        clob_gap = "" if clob_p is None else f"{abs(clob_p - float(price)):.4f}"
        fails = []
        if not raw_ok:
            fails.append("raw_close")
        if not fresh_ok:
            fails.append("two_hour_rule")
        if not latest_ok:
            fails.append("not_latest_bar")
        if not token_ok:
            fails.append("token")
        if not end_ok:
            fails.append("endpoint")
        if not return_ok:
            fails.append("return_cents")
        notes = []
        if used and no_same is not None and not complement_ok:
            notes.append("yes_and_no_hourly_closes_do_not_sum_to_1")
        if used and int(used[3]) == 1:
            notes.append("single_trade_in_formation_bar")
        if used and float(used[2]) >= 0 and abs(float(clob_p) - float(price)) > 0.05 if clob_p is not None else False:
            notes.append("clob_sample_differs_by_more_than_5c")
        data_pass = not fails
        out_rows.append(
            {
                "rank": row["rank_by_contribution"],
                "market_id": row["market_id"],
                "condition_id": condition,
                "question": row["question"],
                "category": row["category"],
                "formation_date": row["date"],
                "formation_et": formation_time(day).strftime("%Y-%m-%d %H:%M %Z"),
                "outcome": outcome,
                "p_form": f"{float(price):.6f}",
                "bar_start_utc": iso(int(bar_start)),
                "bar_age_hours": f"{float(age):.4f}",
                "raw_close": "" if used is None else f"{float(used[2]):.6f}",
                "raw_trade_count": "" if used is None else str(int(used[3])),
                "two_hour_ok": str(fresh_ok).lower(),
                "latest_eligible_bar": str(latest_ok).lower(),
                "raw_matches_panel": str(raw_ok).lower(),
                "no_close_same_bar": "" if no_same is None else f"{float(no_same):.6f}",
                "yes_no_complement_ok": str(complement_ok).lower() if no_same is not None else "",
                "p_end": f"{float(p_end):.6f}",
                "p_end_source": source,
                "p_end_time_utc": iso(end_stamp),
                "next_close_if_any": "" if next_bar is None else f"{float(next_bar[2]):.6f}",
                "settlement_payout": "" if settle_payout is None else f"{float(settle_payout):.0f}",
                "settlement_time_utc": iso(None if settle_ts is None else int(settle_ts)),
                "settlement_inside_holding_window": str(bool(settle_in)).lower(),
                "return_cents": f"{recomputed:.6f}",
                "return_matches_table": str(return_ok).lower(),
                "oi_shares": row["oi_shares"],
                "yesmv": row["yesmv"],
                "day_high_weight": f"{day_weight:.6f}",
                "n_high_names_that_day": str(n_names),
                "single_name_day": str(single).lower(),
                "clob_price_near_bar": "" if clob_p is None else f"{clob_p:.4f}",
                "clob_abs_gap": clob_gap,
                "clob_note": clob_note,
                "data_check": "pass" if data_pass else "fail",
                "fail_reasons": ",".join(fails),
                "notes": ";".join(notes),
                "jump_in_source_data": str(data_pass).lower(),
            }
        )
        print(
            f"{row['rank_by_contribution']} {row['date']} {row['market_id']} "
            f"{'PASS' if data_pass else 'FAIL'} {fails} clob {clob_note} {clob_gap}",
            flush=True,
        )
    with REPORT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {REPORT_CSV} dates {n_dates}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
