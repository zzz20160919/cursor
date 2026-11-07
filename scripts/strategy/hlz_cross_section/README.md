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
