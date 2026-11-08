# HLZ Polymarket paper sample (Step 1)

Builds the Hou–Li–Zheng contract universe on Polymarket. This step stops at the screened pool. It does not compute factors, portfolios, curves, or a daily tradable set.

Public Gamma reads only. No API keys.

The Kalshi paper keeps a contract when three metadata facts hold: reported cumulative volume is at least 10,000 contracts, scheduled life is at least two days, and the opening date is on or before the archive end. In the paper that archive end is April 28, 2026. Here the sample end date is chosen at runtime. The default is today UTC. Pass `--end-date` to use another cutoff, including `2026-04-28` when you want the paper's own cutoff.

## Run

From the repo root:

```bash
python3 scripts/strategy/hlz_cross_section/build_universe.py --self-test
python3 scripts/strategy/hlz_cross_section/build_universe.py
python3 scripts/strategy/hlz_cross_section/build_universe.py --end-date 2026-11-07
```

A full run pages Gamma `/markets/keyset` for open markets (`closed=false`) and closed markets (`closed=true`), ordered by lifetime `volumeNum`. Repeat runs reuse `outputs/strategy/hlz_cross_section/cache/bands/`. Pass `--refresh` to fetch again.

## Output

| File | Contents |
| --- | --- |
| `outputs/strategy/hlz_cross_section/paper_sample_markets.csv` | One row per selected binary contract |
| `outputs/strategy/hlz_cross_section/paper_sample_meta.json` | Cutoff, funnel, paging, volume stats |
| `outputs/strategy/hlz_cross_section/SUMMARY.md` | Chinese and English counts, volume stats, and how to read the CSV |

The band cache under `outputs/` stays untracked. The CSV, meta JSON, and `SUMMARY.md` checked in with this change are the practical pull for sample end date 2026-11-07 UTC: 277,481 contracts, 128,063 events (5,862 open, 271,619 closed). Lifetime USD notional on that pool: min 10,000.00, median 37,856.59, mean 327,626.19, p90 408,387.80, max 1,531,479,284.50. The mean sits far above the median because a few contracts, led by the 2024 presidential market, are very large.

CSV columns: `market_id`, `question`, `event_id`, `event_title`, `cumulative_volume`, `volume_unit`, `scheduled_life_days`, `open_date`, `expiry`, `closed`, `open_date_source`, `expiry_source`, `slug`, `outcomes`, `yes_token`, `sample_end_date`.

`cumulative_volume` is Gamma `volumeNum` when that field is present, otherwise `volume`. `volume_unit` is `usd_notional`. The paper's 10,000 is a contract count. Polymarket's figure is lifetime size and is typically USD notional, not a contract count. The numeric floor is still 10,000.

Rows are sorted by lifetime volume, largest first. One binary market is one contract. Two markets in the same event are two rows.

## Rules

- Lifetime volume ≥ 10,000 (`--min-volume`).
- Scheduled life ≥ 2 days (`--min-life-days`). Life is the elapsed time from the opening timestamp to expiry, in days of 86400 seconds. A date-only field is UTC midnight.
- Opening date, as a UTC calendar date, is on or before the sample end date. A contract that opens on the cutoff date stays in.
- Opening timestamp, first field that parses: `startDate`, `startDateIso`, the parent event `startDate`, `createdAt`, the event `createdAt`, the event `creationDate`.
- Expiry, first field that parses: `endDate`, `endDateIso`, the event `endDate`, the event `endDateIso`.
- Exactly two outcomes. Labels do not have to be Yes/No. Over/Under, Up/Down, and team-name markets stay in. `yes_token` is filled only when an outcome is named Yes.
- Open markets and closed/settled markets both stay in when the three screens pass. `closed=false` is not also required to be `active=true`.

`closedTime` is the actual close, so it is not the scheduled expiry. `gameStartTime` is a sports fixture time, not the contract open.

Gamma notes from a live check on 2026-11-07:

- `GET /markets` with `offset=2001` returns 422 (`offset too large, use /markets/keyset`).
- Keyset `order=volume_num` is rejected. The field name that works is `volumeNum`.
- `volume_num_min` is inclusive.
- `closed=any` without an identifier filter is rejected, so open and closed are paged separately.
- The `archived=true` query parameter did not filter. Closed markets are whatever `closed=true` returns.
- Ordering by `volume1wk` and stopping when the trailing week is thin drops settled markets and markets that are quiet this week. That stop is not used.

The closed book above the floor is large, so the volume range is split into inclusive bands and paged in parallel. Bands share their boundary value. Market ids are deduped before the screens run. A closed band below $100,000 that comes back empty fails the run, as does a book that never reaches the volume floor or the head of the closed book.

## Not inclusion rules

The earlier Polymarket adaptation used the following as reasons to enter the daily universe. The paper sample does not.

- Trailing 7-day average volume (`volume1wk / 7`) ≥ $10,000
- Days to expiry ≥ 3 on the trade date
- YES price in [0.10, 0.90]
- One market per event
- A UTC day with fewer than 10 names treated as cash

Those can be built later as a separate tradable-day table. They are not this file.

## Step 2: YESMV and log odds ratio

`build_factors.py` reads `paper_sample_markets.csv` and builds the paper's formation panel. It does not re-apply the old 7-day average-volume, price-band, one-market-per-event, or cash-day rules.

```bash
python3 scripts/strategy/hlz_cross_section/build_factors.py --self-test
python3 scripts/strategy/hlz_cross_section/build_factors.py --start-date 2026-11-01 --end-date 2026-11-06
```

Formation is 4:00 p.m. America/New_York, including daylight saving time. The formation price is the latest CLOB `prices-history` point (`fidelity=60`) at or before that time. Lookbacks do not use a later print. The holding-period endpoint is the recorded YES settlement if Gamma `closedTime` falls at or before the next 4:00 p.m. Eastern, and otherwise that next 4:00 p.m. price.

Portfolio rows also require the price point to be at most two hours old and at least one history point on one of the preceding seven Eastern calendar dates. `YESMV = P^form × oi_shares`. `LOR(h) = logit(P^form_t) − logit(P^form_{t−h})` for h = 1..6. Inside each date–category cell the characteristic is winsorized at the 1st and 99th percentiles and split at the 30th and 70th. Contract price changes are weighted by the open-interest share proxy. Category legs are aggregated with presort category open interest on the matched set of categories that can form Low, Middle, and High.

Open interest is the blocker. Gamma and CLOB have no 4:00 p.m. open-interest history. The paper's Polymarket appendix rebuilds that path from chain events. Data API `GET /v2/oi` is a current priced-gross USDC snapshot. The script attaches it only to the latest formation date whose next 4:00 p.m. price is already observable, and it does not copy the snapshot onto earlier dates. `oi_shares` divides that USDC figure by `P^form + (1 − P^form)`. The numbers for the checked-in window are in `outputs/strategy/hlz_cross_section/STEP2_SUMMARY.md`.

| File | Contents |
| --- | --- |
| `factor_daily.csv` | One row per contract-formation day |
| `portfolio_spreads.csv` | Mean Low, Middle, High, and High−Low in cents |
| `portfolio_spreads_daily.csv` | The same spreads on each formation date that clears the OI rule |
| `step2_meta.json` | Window, lag, and the spread table |
| `STEP2_SUMMARY.md` | Paper quotes, the Polymarket mapping, and this run |

The default `--closed-mode open` keeps the CLOB pull to Step 1 contracts that were open at the universe snapshot and have a YES token. `--closed-mode all` also reads closed contracts. Price history is cached under `outputs/strategy/hlz_cross_section/cache/step2/`.

The checked-in window is 2026-11-01 through 2026-11-06 for 5,364 open YES contracts (30,686 factor rows). Open interest is attached only on 2026-11-06, 30.31 hours after that 4:00 p.m. Eastern mark. On that one date the High−Low spread is −0.2415 cents for YESMV and −0.3936 cents for LOR(1). There is no Newey–West t-statistic, because the OI snapshot does not support a second date.
