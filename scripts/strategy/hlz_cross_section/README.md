# HLZ Polymarket universe (Step 1)

Builds the daily binary-market universe for the Hou–Li–Zheng cross-section. This step stops at the universe table. It does not compute factors, portfolios, or curves.

Public Gamma and CLOB reads only. No API keys.

## Run

From the repo root:

```bash
python3 scripts/strategy/hlz_cross_section/build_universe.py
```

The default window is 183 UTC days ending today. A full run pages Gamma, then requests one CLOB `prices-history` series (`interval=max`, `fidelity=1440`) per event representative. Repeat runs reuse `outputs/strategy/hlz_cross_section/cache/`. Pass `--refresh` to fetch prices again.

Check the filter logic without the network:

```bash
python3 scripts/strategy/hlz_cross_section/build_universe.py --self-test
```

## Output

`outputs/` is gitignored.

| File | Contents |
| --- | --- |
| `outputs/strategy/hlz_cross_section/universe_daily.csv` | One row per market on days that clear the filters and have at least 10 names |
| `outputs/strategy/hlz_cross_section/universe_daily_coverage.csv` | Every date in the window: `n_markets` and `included` or `cash` |
| `outputs/strategy/hlz_cross_section/universe_daily_meta.json` | Window, counts, and the volume definition |

Universe columns: `date`, `market_id`, `event_id`, `event_title`, `question`, `slug`, `yes_token`, `yes_price`, `volume_7d_avg`, `volume_7d`, `volume_asof`, `expiry`, `days_to_expiry`.

Days with fewer than 10 markets are left out of `universe_daily.csv` (cash). They remain in the coverage file with `status=cash`. The script writes CSV only (no parquet dependency).

A run on 2026-11-07, using the default 183-day window, wrote 8,641 market rows across all 183 days (134 events, 20–69 names on a day, no cash days).

## Rules

- Open binary Yes/No markets with a CLOB YES token. Resolved markets are left out: after close, Gamma freezes `volume1wk` and stops publishing `volume24hr`, so that number is not a trailing week.
- Trailing 7-day average volume = Gamma `volume1wk / 7`, kept when that average is at least $10,000. `volume_asof` is the snapshot date (`updatedAt`). Gamma does not provide a daily volume history, so this one live snapshot is the liquidity screen for every date in the lookback.
- Days to expiry at least 3, using `endDate`.
- YES price in [0.10, 0.90], using the last CLOB print on that UTC date. A single missing day can reuse the previous close (`--max-stale-days`, default 1).
- One market per event: the binary with the largest trailing 7-day average volume.
- Fewer than 10 markets after those screens: that day is cash.

Daily membership changes with the YES price and time to expiry. It does not change because of a historical volume path. Names that were liquid earlier and are quiet now are missing, and names that are liquid now can appear on earlier dates when their price was already in band.
