#!/usr/bin/env python3
"""Diagnostics for the Step 2 High-Low gap versus Table IA.15.

Reads the checked-in A.3 factor panel. Does not rebuild prices, the universe,
or open interest, and does not start Step 3.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from hlz_paper import category_portfolios, percentile  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
FACTOR = OUT / "a3_factor_daily.parquet"
DB = OUT / "cache/step2/a3_panel.duckdb"
BARS = OUT / "cache/step2/vgregoire/bars_slim.parquet"
PREVIOUS = OUT / "a3_spreads.csv"
PAPER_RAW = 3_507_194
PAPER_PORTFOLIO = 898_019
MISSING_HOURLY = (
    "2022-11-24",
    "2022-11-25",
    "2022-11-26",
    "2022-11-27",
    "2022-12-04",
    "2022-12-05",
    "2022-12-10",
)
CHARS = ["yesmv", "lor_1", "lor_2", "lor_3", "lor_4", "lor_5", "lor_6"]
PAPER_HL = {
    "yesmv": {"low": 0.084, "middle": -0.020, "high": -0.171, "hl": -0.255, "t": -5.81},
    "lor_1": {"low": 0.121, "middle": -0.086, "high": -0.604, "hl": -0.725, "t": -5.29},
    "lor_2": {"low": 0.151, "middle": -0.147, "high": -0.452, "hl": -0.603, "t": -4.39},
    "lor_3": {"low": 0.046, "middle": -0.106, "high": -0.492, "hl": -0.538, "t": -4.22},
    "lor_4": {"low": 0.133, "middle": -0.112, "high": -0.420, "hl": -0.553, "t": -4.40},
    "lor_5": {"low": 0.180, "middle": -0.171, "high": -0.387, "hl": -0.566, "t": -4.87},
    "lor_6": {"low": 0.125, "middle": -0.099, "high": -0.376, "hl": -0.501, "t": -3.96},
}


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    return con


def newey_west_t(values: list[float], lags: int = 7) -> float | None:
    """t-statistic of the mean, Bartlett kernel, `lags` Newey-West lags."""
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    errors = [value - mean for value in values]
    lag_cap = min(lags, count - 1)

    def gamma(lag: int) -> float:
        return sum(errors[index] * errors[index - lag] for index in range(lag, count)) / count

    variance = gamma(0)
    for lag in range(1, lag_cap + 1):
        weight = 1.0 - lag / (lag_cap + 1.0)
        variance += 2.0 * weight * gamma(lag)
    if variance <= 0:
        return None
    return mean / ((variance / count) ** 0.5)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def price_age(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Classify alive contract-days by the age of the last ended hourly close."""
    print("price-age join", flush=True)
    con.execute(f"ATTACH '{DB}' AS saved (READ_ONLY)")
    missing = ", ".join(f"DATE '{day}'" for day in MISSING_HOURLY)
    con.execute(
        f"""
        CREATE TABLE alive AS
        SELECT t.prediction_id, c.formation_date, c.formation_epoch,
               c.formation_date IN ({missing}) AS missing_file_date
        FROM saved.universe u
        JOIN saved.tokens t ON t.condition_id = u.condition_id
        JOIN saved.calendar c
          ON u.open_epoch <= c.formation_epoch
         AND u.expiry_epoch > c.formation_epoch
         AND (u.closed_epoch IS NULL OR u.closed_epoch > c.formation_epoch)
        """
    )
    alive_n = con.execute("SELECT count(*) FROM alive").fetchone()[0]
    alive_all = con.execute(
        """
        SELECT count(*)
        FROM saved.universe u
        JOIN saved.calendar c
          ON u.open_epoch <= c.formation_epoch
         AND u.expiry_epoch > c.formation_epoch
         AND (u.closed_epoch IS NULL OR u.closed_epoch > c.formation_epoch)
        """
    ).fetchone()[0]
    print(f"alive with token {alive_n} alive all {alive_all}", flush=True)
    con.execute(
        f"""
        CREATE TABLE last_bar AS
        SELECT a.prediction_id, a.formation_date, a.missing_file_date,
               b.bar_start,
               (a.formation_epoch - b.bar_start) / 3600.0 AS age_hours
        FROM alive a
        ASOF LEFT JOIN (
          SELECT prediction_id, bar_start
          FROM read_parquet('{BARS}')
        ) b
          ON a.prediction_id = b.prediction_id
         AND a.formation_epoch - 3600 >= b.bar_start
        """
    )
    rows = con.execute(
        """
        SELECT
          CASE
            WHEN missing_file_date THEN 'missing_hourly_file_date'
            WHEN bar_start IS NULL THEN 'no_hourly_close_before_formation'
            WHEN age_hours <= 2 THEN 'close_within_2h'
            WHEN age_hours <= 6 THEN 'stale_close_2h_to_6h'
            WHEN age_hours <= 24 THEN 'stale_close_6h_to_24h'
            WHEN age_hours <= 168 THEN 'stale_close_1d_to_7d'
            ELSE 'stale_close_older_than_7d'
          END AS bucket,
          count(*) AS contract_days
        FROM last_bar
        GROUP BY 1
        ORDER BY 2 DESC
        """
    ).fetchall()
    out = [{"bucket": bucket, "contract_days": int(count), "universe": "alive_with_reference_token"} for bucket, count in rows]
    out.append(
        {
            "bucket": "alive_without_reference_token",
            "contract_days": int(alive_all - alive_n),
            "universe": "alive_minus_token",
        }
    )
    out.append({"bucket": "alive_all_contracts", "contract_days": int(alive_all), "universe": "alive"})
    return out


def funnel(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    factor = str(FACTOR)
    row = con.execute(
        f"""
        SELECT
          count(*) AS with_close,
          count(*) FILTER (WHERE active) AS active_close,
          count(*) FILTER (WHERE active AND oi_shares IS NOT NULL) AS active_oi_obs,
          count(*) FILTER (WHERE active AND oi_shares > 0) AS active_oi_pos,
          count(*) FILTER (WHERE active AND oi_shares > 0 AND traded_prior_7d) AS prior_trade,
          count(*) FILTER (
            WHERE active AND oi_shares > 0 AND traded_prior_7d AND category <> ''
          ) AS with_category,
          count(*) FILTER (WHERE in_portfolio_sample) AS portfolio,
          count(*) FILTER (
            WHERE in_portfolio_sample
              AND formation_date NOT IN ({", ".join(f"DATE '{day}'" for day in MISSING_HOURLY)})
          ) AS portfolio_aligned,
          count(DISTINCT formation_date) FILTER (WHERE in_portfolio_sample) AS portfolio_dates
        FROM read_parquet('{factor}')
        """
    ).fetchone()
    labels = [
        ("hourly_close_any_contract_day", row[0]),
        ("alive_and_close_within_2h", row[1]),
        ("alive_close_with_oi_observation", row[2]),
        ("alive_close_positive_oi", row[3]),
        ("plus_trade_in_prior_7_calendar_days", row[4]),
        ("plus_nonempty_category", row[5]),
        ("plus_next_period_price_portfolio", row[6]),
        ("portfolio_on_dates_with_hourly_file", row[7]),
    ]
    table = []
    for name, count in labels:
        table.append(
            {
                "stage": name,
                "contract_days": int(count),
                "share_of_paper_raw": f"{count / PAPER_RAW:.6f}",
                "share_of_paper_portfolio": f"{count / PAPER_PORTFOLIO:.6f}",
            }
        )
    table.append(
        {
            "stage": "portfolio_dates",
            "contract_days": int(row[8]),
            "share_of_paper_raw": "",
            "share_of_paper_portfolio": "",
        }
    )
    return table


def oi_stats(con: duckdb.DuckDBPyConnection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    factor = str(FACTOR)
    summary = con.execute(
        f"""
        WITH book AS (
          SELECT condition_id, market_id, question, formation_date, oi_shares, yesmv
          FROM read_parquet('{factor}')
          WHERE in_portfolio_sample AND oi_shares > 0
        ),
        ranked AS (
          SELECT oi_shares,
                 sum(oi_shares) OVER () AS total_oi,
                 percent_rank() OVER (ORDER BY oi_shares) AS pct
          FROM book
        )
        SELECT
          count(*) AS n,
          quantile_cont(oi_shares, 0.50) AS median_oi,
          quantile_cont(oi_shares, 0.90) AS p90_oi,
          quantile_cont(oi_shares, 0.99) AS p99_oi,
          max(oi_shares) AS max_oi,
          sum(oi_shares) FILTER (WHERE pct >= 0.99) / max(total_oi) AS share_top_1pct_rows,
          sum(oi_shares) FILTER (WHERE pct >= 0.90) / max(total_oi) AS share_top_10pct_rows
        FROM ranked
        """
    ).fetchone()
    by_contract = con.execute(
        f"""
        WITH per AS (
          SELECT condition_id, avg(oi_shares) AS mean_oi
          FROM read_parquet('{factor}')
          WHERE in_portfolio_sample AND oi_shares > 0
          GROUP BY 1
        ),
        ranked AS (
          SELECT mean_oi,
                 sum(mean_oi) OVER () AS total_oi,
                 percent_rank() OVER (ORDER BY mean_oi) AS pct
          FROM per
        )
        SELECT
          count(*) AS contracts,
          sum(mean_oi) FILTER (WHERE pct >= 0.99) / max(total_oi) AS share_top_1pct_contracts,
          sum(mean_oi) FILTER (WHERE pct >= 0.90) / max(total_oi) AS share_top_10pct_contracts
        FROM ranked
        """
    ).fetchone()
    harris = con.execute(
        f"""
        SELECT formation_date, oi_shares, yesmv, p_form, category
        FROM read_parquet('{factor}')
        WHERE market_id = '253597' AND formation_date = DATE '2024-10-30'
        """
    ).fetchone()
    top = con.execute(
        f"""
        SELECT formation_date, market_id, question, oi_shares, yesmv, p_form
        FROM read_parquet('{factor}')
        WHERE in_portfolio_sample
        ORDER BY oi_shares DESC
        LIMIT 15
        """
    ).fetchall()
    stats = [
        {"stat": "portfolio_contract_days", "value": f"{int(summary[0])}"},
        {"stat": "median_oi", "value": f"{summary[1]:.4f}"},
        {"stat": "p90_oi", "value": f"{summary[2]:.4f}"},
        {"stat": "p99_oi", "value": f"{summary[3]:.4f}"},
        {"stat": "max_oi", "value": f"{summary[4]:.4f}"},
        {"stat": "share_of_summed_oi_top_1pct_contract_days", "value": f"{summary[5]:.6f}"},
        {"stat": "share_of_summed_oi_top_10pct_contract_days", "value": f"{summary[6]:.6f}"},
        {"stat": "unique_portfolio_contracts", "value": f"{int(by_contract[0])}"},
        {"stat": "share_of_mean_oi_top_1pct_contracts", "value": f"{by_contract[1]:.6f}"},
        {"stat": "share_of_mean_oi_top_10pct_contracts", "value": f"{by_contract[2]:.6f}"},
        {
            "stat": "harris_2024_10_30_oi",
            "value": "" if harris is None else f"{harris[1]:.4f}",
        },
        {
            "stat": "harris_2024_10_30_yesmv",
            "value": "" if harris is None or harris[2] is None else f"{harris[2]:.4f}",
        },
    ]
    extremes = [
        {
            "formation_date": str(item[0]),
            "market_id": item[1],
            "question": item[2],
            "oi_shares": f"{item[3]:.4f}",
            "yesmv": "" if item[4] is None else f"{item[4]:.4f}",
            "p_form": f"{item[5]:.6f}",
        }
        for item in top
    ]
    return stats, extremes


def categories(con: duckdb.DuckDBPyConnection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    factor = str(FACTOR)
    listed = con.execute(
        f"""
        SELECT coalesce(nullif(category, ''), '(blank)') AS category,
               count(*) AS priced_days,
               count(*) FILTER (WHERE active) AS active_priced_days,
               count(*) FILTER (WHERE in_portfolio_sample) AS portfolio_days,
               count(DISTINCT condition_id) FILTER (WHERE in_portfolio_sample) AS portfolio_contracts
        FROM read_parquet('{factor}')
        GROUP BY 1
        ORDER BY portfolio_days DESC, priced_days DESC
        """
    ).fetchall()
    daily = con.execute(
        f"""
        WITH per_day AS (
          SELECT formation_date,
                 count(DISTINCT category) AS n_categories,
                 count(*) AS n_contracts
          FROM read_parquet('{factor}')
          WHERE in_portfolio_sample AND category <> ''
          GROUP BY 1
        ),
        per_cell AS (
          SELECT formation_date, category, count(*) AS n_contracts
          FROM read_parquet('{factor}')
          WHERE in_portfolio_sample AND category <> ''
          GROUP BY 1, 2
        )
        SELECT
          (SELECT count(*) FROM per_day),
          (SELECT avg(n_categories) FROM per_day),
          (SELECT quantile_cont(n_categories, 0.50) FROM per_day),
          (SELECT min(n_categories) FROM per_day),
          (SELECT max(n_categories) FROM per_day),
          (SELECT avg(n_contracts) FROM per_day),
          (SELECT avg(n_contracts) FROM per_cell),
          (SELECT quantile_cont(n_contracts, 0.50) FROM per_cell),
          (SELECT count(*) FROM per_cell WHERE n_contracts < 3)
        """
    ).fetchone()
    blank = con.execute(
        f"""
        SELECT
          count(*) FILTER (WHERE category = '' OR category IS NULL) AS blank_priced,
          count(*) AS priced,
          count(*) FILTER (WHERE active AND (category = '' OR category IS NULL)) AS blank_active
        FROM read_parquet('{factor}')
        """
    ).fetchone()
    summary = [
        {"stat": "portfolio_dates", "value": f"{int(daily[0])}"},
        {"stat": "mean_categories_per_day", "value": f"{daily[1]:.4f}"},
        {"stat": "median_categories_per_day", "value": f"{daily[2]:.4f}"},
        {"stat": "min_categories_per_day", "value": f"{int(daily[3])}"},
        {"stat": "max_categories_per_day", "value": f"{int(daily[4])}"},
        {"stat": "mean_portfolio_contracts_per_day", "value": f"{daily[5]:.4f}"},
        {"stat": "mean_contracts_per_category_day", "value": f"{daily[6]:.4f}"},
        {"stat": "median_contracts_per_category_day", "value": f"{daily[7]:.4f}"},
        {"stat": "category_days_with_fewer_than_3_contracts", "value": f"{int(daily[8])}"},
        {"stat": "priced_days_blank_category", "value": f"{int(blank[0])}"},
        {"stat": "priced_days", "value": f"{int(blank[1])}"},
        {"stat": "blank_share_of_priced_days", "value": f"{blank[0] / blank[1]:.6f}"},
        {"stat": "active_priced_days_blank_category", "value": f"{int(blank[2])}"},
    ]
    detail = [
        {
            "category": row[0],
            "priced_days": int(row[1]),
            "active_priced_days": int(row[2]),
            "portfolio_days": int(row[3]),
            "portfolio_contracts": int(row[4]),
        }
        for row in listed
    ]
    return summary, detail


def load_portfolio(con: duckdb.DuckDBPyConnection) -> dict[date, list[dict[str, Any]]]:
    missing = ", ".join(f"DATE '{day}'" for day in MISSING_HOURLY)
    rows = con.execute(
        f"""
        SELECT formation_date, category, yesmv, lor_1, lor_2, lor_3, lor_4, lor_5, lor_6,
               oi_shares, r_pp
        FROM read_parquet('{FACTOR}')
        WHERE in_portfolio_sample
          AND formation_date NOT IN ({missing})
          AND category <> ''
          AND oi_shares > 0
          AND r_pp IS NOT NULL
        """
    ).fetchall()
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for formation_date, category, yesmv, l1, l2, l3, l4, l5, l6, oi, payoff in rows:
        grouped[formation_date].append(
            {
                "category": category,
                "yesmv": yesmv,
                "lor_1": l1,
                "lor_2": l2,
                "lor_3": l3,
                "lor_4": l4,
                "lor_5": l5,
                "lor_6": l6,
                "oi": float(oi),
                "r": float(payoff),
            }
        )
    print(f"aligned portfolio days {len(grouped)} rows {len(rows)}", flush=True)
    return grouped


def cap_oi(members: list[dict[str, Any]], probability: float) -> list[dict[str, Any]]:
    cap = percentile(sorted(member["oi"] for member in members), probability)
    capped = []
    for member in members:
        copied = dict(member)
        copied["oi"] = min(member["oi"], cap)
        capped.append(copied)
    return capped


def drop_above(members: list[dict[str, Any]], probability: float) -> list[dict[str, Any]]:
    cap = percentile(sorted(member["oi"] for member in members), probability)
    return [member for member in members if member["oi"] <= cap]


def equal_weight(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**member, "oi": 1.0} for member in members]


def summarize_scheme(
    grouped: dict[date, list[dict[str, Any]]],
    scheme: str,
    transform,
) -> list[dict[str, Any]]:
    daily: dict[str, list[dict[str, float]]] = {name: [] for name in CHARS}
    for members in grouped.values():
        adjusted = transform(members)
        for name in CHARS:
            usable = []
            for member in adjusted:
                value = member[name]
                if value is None:
                    continue
                usable.append(
                    {"category": member["category"], "x": float(value), "oi": float(member["oi"]), "r": member["r"]}
                )
            result = category_portfolios(usable)
            if result is None:
                continue
            daily[name].append(result)
    rows = []
    for name in CHARS:
        series = daily[name]
        if not series:
            continue
        count = len(series)
        hl = [item["high_minus_low"] * 100 for item in series]
        rows.append(
            {
                "scheme": scheme,
                "characteristic": name,
                "n_dates": count,
                "mean_low_cents": f"{sum(item['low'] for item in series) / count * 100:.6f}",
                "mean_middle_cents": f"{sum(item['middle'] for item in series) / count * 100:.6f}",
                "mean_high_cents": f"{sum(item['high'] for item in series) / count * 100:.6f}",
                "mean_high_minus_low_cents": f"{sum(hl) / count:.6f}",
                "newey_west_t_lag7": "" if (t := newey_west_t(hl, 7)) is None else f"{t:.4f}",
                "paper_ia15_high_minus_low_cents": f"{PAPER_HL[name]['hl']:.3f}",
                "paper_ia15_t": f"{PAPER_HL[name]['t']:.2f}",
            }
        )
    return rows


def main() -> int:
    con = connect()
    funnel_rows = funnel(con)
    age_rows = price_age(con)
    oi_rows, extreme_rows = oi_stats(con)
    category_rows, category_detail = categories(con)
    grouped = load_portfolio(con)
    spreads = []
    spreads.extend(summarize_scheme(grouped, "aligned_raw_oi", lambda members: members))
    spreads.extend(summarize_scheme(grouped, "aligned_oi_capped_at_date_p99", lambda members: cap_oi(members, 0.99)))
    spreads.extend(summarize_scheme(grouped, "aligned_drop_oi_above_date_p99", lambda members: drop_above(members, 0.99)))
    spreads.extend(summarize_scheme(grouped, "aligned_equal_weight", equal_weight))
    previous = list(csv.DictReader(PREVIOUS.open(encoding="utf-8")))
    write_csv(OUT / "diagnostic_funnel.csv", funnel_rows)
    write_csv(OUT / "diagnostic_price_age.csv", age_rows)
    write_csv(OUT / "diagnostic_oi.csv", oi_rows)
    write_csv(OUT / "diagnostic_oi_extremes.csv", extreme_rows)
    write_csv(OUT / "diagnostic_category_summary.csv", category_rows)
    write_csv(OUT / "diagnostic_categories.csv", category_detail)
    write_csv(OUT / "diagnostic_spreads.csv", spreads)
    (OUT / "diagnostic_numbers.json").write_text(
        json.dumps(
            {
                "funnel": funnel_rows,
                "price_age": age_rows,
                "oi": oi_rows,
                "category_summary": category_rows,
                "spreads": spreads,
                "previous_full_sample": previous,
                "paper_portfolio_contract_days": PAPER_PORTFOLIO,
                "paper_raw_contract_days": PAPER_RAW,
                "missing_hourly_dates": list(MISSING_HOURLY),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("diagnostics written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
