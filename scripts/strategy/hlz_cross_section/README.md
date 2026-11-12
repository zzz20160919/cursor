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

An earlier run attached Data API `/v2/oi` after 4:00 p.m. formation. Those ranks and weights are not valid. Nothing in this step reads that snapshot.

Appendix A.3 names Dome hourly prices first. Dome is not available, so the formation price is the documented fallback and is the only price used here: `vgregoire/polymarket-users` hourly OHLCV `close` (last trade in that hour). There is no quote midpoint. LOR is the change in the logit of that close. A bar is used only when the hour ends at or before 4:00 p.m. Eastern and the bar opened no more than two hours earlier. A bar that opened three hours before formation is rejected. Open interest is the TimeSeventeen CTF split/merge/redemption replay. Settlement is the CTF resolution.

The universe for this step is the Polymarket appendix, not the ≥10,000 file above. Lifetime Gamma volume must be **above 2,000** USD notional (`volumeNum`, else `volume`). Observed life is at least 2 days. The opening date is on or before 2026-03-29, which is the last day of the hourly files (the 2026-03-30 file is HTTP 404). One reference outcome per condition: the Yes token, or outcome index 0 when the market has no Yes label.

```bash
bash scripts/strategy/hlz_cross_section/download_pit.sh
python3 scripts/strategy/hlz_cross_section/hlz_paper.py
python3 scripts/strategy/hlz_cross_section/build_universe.py \
  --min-volume 2000 --volume-above --life-mode observed --end-date 2026-03-29 \
  --fill-identifiers \
  --output outputs/strategy/hlz_cross_section/paper_sample_markets_a3.csv \
  --meta outputs/strategy/hlz_cross_section/paper_sample_meta_a3.json \
  --summary outputs/strategy/hlz_cross_section/SUMMARY_A3.md
python3 scripts/strategy/hlz_cross_section/build_a3_panel.py
```

`download_pit.sh` still pulls the short 2024-10-23..2024-11-06 trade tapes used by the earlier pilot, and it also pulls hourly bars from 2022-11-21 through 2026-03-29. `build_factors.py` remains the 25-contract pilot. `build_a3_panel.py` is the full sample.

Checked-in A.3 universe, sample end 2026-03-29: **178,408** contracts, **72,497** events (2,482 open, 175,926 closed). The earlier ≥10,000 scheduled-life file (sample end 2026-11-07) is unchanged at 277,481 contracts and 128,063 events. Volume on the A.3 file: min 2,000.13, median 21,722.85, mean 353,685.22.

Formation dates run 2022-11-21 through 2026-03-29. Alive contract-days: 3,882,837. With a close at most 2 hours old: 737,834. Portfolio sample: 379,371. Mean High−Low is about **+0.21 cents** for YESMV (884 dates) and **−0.09 cents** for LOR(1) (755 dates). These are this sample's estimates, not a restatement of Table IA.15. Coverage, the other LOR horizons, and the remaining gaps are in `outputs/strategy/hlz_cross_section/STEP2_SUMMARY.md`.

中文：成交额严格大于 2,000 美元名义；价格是小时收盘且不超过 2 小时；样本停在 2026-03-29，因为小时数据在这一天结束。

Why these High−Low numbers differ from Table IA.15 is written up in `outputs/strategy/hlz_cross_section/DIAGNOSTIC_STEP2.md`. That note does not change the price rule or the universe.

## Step 3: category portfolios

`build_step3.py` reads the factor panel above. It does not rebuild prices or the universe. Within each formation date and `vgregoire` category it winsorizes the characteristic at the 1st and 99th percentiles, assigns Low / Middle / High at the 30th and 70th, weights contracts by raw formation open interest, and aggregates categories by presort category open interest. The outcome is the mean next-period price change in cents. Newey–West t-statistics use 7 calendar lags.

```bash
python3 scripts/strategy/hlz_cross_section/build_step3.py
```

The result is this pipeline’s table, not a claim that Table IA.15 has been replicated. The side-by-side is in `outputs/strategy/hlz_cross_section/STEP3_SUMMARY.md`.

中文：这一步只对已有因子表做分组，价格仍是两小时内的小时收盘，类别仍是那 7 个粗类。

Why the YESMV High leg is positive is in `outputs/strategy/hlz_cross_section/DIAGNOSTIC_YESMV_HIGH.md`. The price check of those twenty contract-days is in `DIAGNOSTIC_YESMV_HIGH_PRICES.md`. A minimum High/Low bucket-size comparison, which does not replace the official table, is in `STEP3_MIN_N_SENSITIVITY.md`. A weight-cap comparison on that N=5 book is in `STEP3_WEIGHT_CAP_SENSITIVITY.md`. Neither replaces the official Step 3 numbers.
