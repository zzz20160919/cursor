# 202604_stra BTC-NQ Data Inventory

Agent: `data_btc_nq1`

Current migration scope: pure market data source layer only. This phase migrates BTCUSDT and NQ downloaders plus basic clean parquet validation. It explicitly does not implement BTC-NQ timestamp/session alignment, `btc_nq_1m_clean.parquet`, weekend feature datasets, macro-event reaction datasets, `event_reactions`, ZT/rates proxy, strategy signals, PnL/backtests, Futu API, live trading, order placement, secrets, or any modification to the old project.

## Executive Summary

The old project has a usable BTC-NQ data pipeline centered on:

- Binance USD-M `BTCUSDT` perpetual 1-minute klines from Binance Vision.
- Databento CME `NQ` 1-minute OHLCV, mainly as continuous volume front contract `NQ.v.0`.
- UTC-based macro-event alignment tables that compute BTC/NQ returns around CPI/FOMC/NFP events.

No Binance BTC spot historical downloader was found in the BTC-NQ 1-minute pipeline. There are unrelated BTC spot/current-index references, including Deribit current BTC index price and BTC regime research files, but the BTC-NQ event pipeline uses `BTCUSDT` USD-M perpetual.

For speed, the current migration should stop at raw market data download and validation. BTC-NQ alignment and weekend feature definitions depend on the specific strategy and should be handled later by `btc_nq_strategy1`.

## Current Phase Narrowing

This migration phase is narrowed to the pure market data source layer only:

- Migrate Binance BTCUSDT USD-M perpetual 1m downloader and validator.
- Migrate Databento NQ continuous 1m downloader and validator.
- Keep BTCUSDT and NQ as separate clean market data sources.
- Defer BTC-NQ timestamp/session alignment to `btc_nq_strategy1`.
- Defer weekend feature definitions and datasets to `btc_nq_strategy1`.
- Do not migrate macro-event datasets, `event_reactions`, event paths, ZT/rates proxy, Futu execution, strategy signals, PnL, or backtests in this phase.

## 1. Binance BTC Data Download Files

Primary migration candidate:

- `D:\cursor\202604_stra\scripts\market_data\download_binance_btcusdt_um_1m.py`
  - Downloads Binance Vision monthly USD-M futures klines.
  - Hard-coded instrument: `BTCUSDT`.
  - Market: Binance USD-M futures / perpetual.
  - Interval: `1m`.
  - Requested range: `2020-01` through `2026-04`.
  - Actual downloaded range in validation: `2020-01` through `2026-03`; `2026-04` returned HTTP 404.
  - Output parquet: `data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_2020_2026.parquet`.
  - Raw ZIP directory: `data/raw/market_data/binance/futures/um/monthly/klines/BTCUSDT/1m/`.

Secondary/reference only:

- `D:\cursor\202604_stra\stra\data\download_binance_vision_klines.py`
  - Generic Binance Vision USD-M futures downloader.
  - Supports `BTCUSDT` by default and intervals `15m`, `1h`, `4h`, `1d`.
  - Can optionally export simplified bars CSV: `timestamp,open,high,low,close,volume`.
  - Does not cover spot; it is still USD-M futures.

Not a migration candidate for BTC-NQ 1m:

- `D:\cursor\202604_stra\scripts\calc_btc_hit_fair_prob.py`
  - Fetches current Deribit BTC index/spot-like price for Polymarket-style probability work.
  - Not a historical Binance spot downloader.

## 2. Databento NQ Download Files

Primary migration candidate:

- `D:\cursor\202604_stra\scripts\market_data\download_databento_nq_1m.py`
  - Uses `databento.Historical`.
  - Dataset: `GLBX.MDP3`.
  - Schema: `ohlcv-1m`.
  - Symbol: `NQ.v.0`.
  - `stype_in`: `continuous`.
  - Range: `2020-01-01` to `2026-05-01`.
  - Output parquet: `data/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.parquet`.
  - Raw DBN: `data/raw/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.dbn`.
  - Requires `DATABENTO_API_KEY`; do not copy any secrets.

Secondary/reference only:

- `D:\cursor\202604_stra\stra\data\download_databento_nq_1m.py`
  - Parameterized raw-symbol contract downloader.
  - Dataset: `GLBX.MDP3`.
  - Schema: `ohlcv-1m`.
  - `stype_in`: `raw_symbol`.
  - Example symbols/windows documented: `NQH6`, `NQM6`, `NQU6`, `NQZ6`, `NQH7`.
  - Produces raw per-contract CSV under `data/raw/databento/nq/`.

- `D:\cursor\202604_stra\stra\data\download_databento_nqh6_1m.py`
  - Older/specific NQH6 helper, superseded by the parameterized raw-symbol downloader.

- `D:\cursor\202604_stra\stra\data\clean_check_databento_nq_1m.py`
  - Cleans one raw-symbol NQ CSV and writes a Chicago-time clean CSV plus summary.
  - Useful as QA reference, but the newer continuous `NQ.v.0` path is the main migration target.

## 3. Existing Data Files, Formats, Fields

BTCUSDT perpetual 1m:

- `D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet`
- Format: parquet.
- Rows: `3,286,080`.
- Timestamp range: `2020-01-01 00:00:00+00:00` to `2026-03-31 23:59:00+00:00`.
- Columns: `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `quote_asset_volume`, `number_of_trades`, `taker_buy_base_asset_volume`, `taker_buy_quote_asset_volume`, `ignore`, `source_month`, `open_time_utc`, `close_time_utc`.

NQ continuous 1m:

- `D:\cursor\202604_stra\data\market_data\databento\GLBX.MDP3\NQ\1m\nq_continuous_volume_front_1m_2020_2026.parquet`
- Format: parquet.
- Rows: `2,233,693`.
- Timestamp range: `2020-01-01 23:00:00+00:00` to `2026-04-30 23:59:00+00:00`.
- Columns: `ts_event`, `rtype`, `publisher_id`, `instrument_id`, `open`, `high`, `low`, `close`, `volume`, `symbol`, `ts_event_utc`.

NQ raw-symbol clean CSV spot-check files:

- Directory: `D:\cursor\202604_stra\data\processed\databento\nq\`.
- Files found: `NQH5`, `NQM5`, `NQU5`, `NQZ5`, `NQH6` clean CSVs and summaries.
- Clean CSV columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `symbol`.
- Timezone: `America/Chicago` ISO string in the cleaned raw-symbol CSVs.
- Example `NQH6` summary: `86,101` rows, `2025-12-18 18:00:00-06:00` to `2026-03-19 18:57:00-05:00`, no duplicate timestamps, no missing values, no non-positive OHLC.

BTC-NQ event reaction outputs:

- `D:\cursor\202604_stra\data\event_reactions\btcusdt_um_1m_macro_event_reactions_2020_2026.csv`
  - Rows: `360`, columns: `61`.
  - Event range: `2015-01-09 13:30:00+00:00` to `2026-04-29 18:00:00+00:00`.
  - `btc_data_available=True`: `197`; `False`: `163`.

- `D:\cursor\202604_stra\data\event_reactions\nq_zt_macro_event_reactions_2020_2026.csv`
  - Rows: `360`, columns: `70`.
  - `nq_data_available=True`: `196`; `False`: `164`.
  - Includes ZT/rate proxy columns; useful as alignment reference, but ZT is outside this migration scope unless later requested.

- `D:\cursor\202604_stra\data\event_reactions\btc_nq_zt_macro_event_reactions_2020_2026.csv`
  - Rows: `360`, columns: `127`.
  - `all_assets_available=True`: `194`; clean all-assets-available: `188`.
  - Includes derived BTC/NQ alignment/regime fields. Treat as reference dataset, not strategy logic.

- `D:\cursor\202604_stra\data\event_reactions\event_return_paths_btc_nq_zt_2020_2026.csv`
  - Rows: `105,342`, columns: `12`.
  - Assets: `BTC`, `NQ`, `ZT`, each `35,114` rows.
  - Event range: `2020-01-10 13:30:00+00:00` to `2026-03-18 18:00:00+00:00`.
  - Useful for event-path alignment reference; contains ZT and diagnostic/hypothesis context.

Older BTC bars:

- `D:\cursor\202604_stra\data\bars_BTCUSDT_1h_202301_202603.csv`
  - Rows: `28,464`.
  - Columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`.
  - Range: `2023-01-01 00:00:00+00:00` to `2026-03-31 23:00:00+00:00`.

- `D:\cursor\202604_stra\data\bars_BTCUSDT_1d_202301_202603.csv`
  - Rows: `1,186`.
  - Columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`.
  - Range: `2023-01-01 00:00:00+00:00` to `2026-03-31 00:00:00+00:00`.

These older BTC bar CSVs are not the main BTC-NQ 1m migration source.

## 4. BTC Symbols, Intervals, Time Ranges

BTCUSDT perpetual:

- Symbol: `BTCUSDT`.
- Market: Binance USD-M futures / perpetual.
- Primary interval: `1m`.
- Requested download range: `2020-01` to `2026-04`.
- Actual clean range: `2020-01-01 00:00:00 UTC` to `2026-03-31 23:59:00 UTC`.
- Validation: no duplicates, no 1-minute gaps, no OHLC sanity violations.

Generic/older BTCUSDT futures bars:

- Symbol: `BTCUSDT`.
- Intervals supported by generic downloader: `15m`, `1h`, `4h`, `1d`.
- Existing CSVs: `1h` and `1d`, `2023-01` through `2026-03`.

BTC spot:

- No Binance spot historical downloader was found for the BTC-NQ 1m pipeline.
- Deribit current BTC index fetch exists but is unrelated to clean BTC-NQ historical data migration.

## 5. NQ Databento Dataset, Schema, Symbol, Time Range

Primary NQ:

- Dataset: `GLBX.MDP3`.
- Schema: `ohlcv-1m`.
- Symbol: `NQ.v.0`.
- `stype_in`: `continuous`.
- Range: `2020-01-01` to `2026-05-01`.
- Actual output range: `2020-01-01 23:00:00 UTC` to `2026-04-30 23:59:00 UTC`.
- Instrument roll diagnostics: `26` unique `instrument_id` values in validation.

Raw-symbol NQ reference:

- Dataset: `GLBX.MDP3`.
- Schema: `ohlcv-1m`.
- `stype_in`: `raw_symbol`.
- Found clean files: `NQH5`, `NQM5`, `NQU5`, `NQZ5`, `NQH6`.
- Intended for contract-level spot checks and roll validation, not the primary continuous dataset.

## 6. Timezone and Session Handling

BTC:

- Binance kline timestamps are converted from epoch milliseconds to UTC.
- `open_time_utc` and `close_time_utc` are timezone-aware UTC timestamps.
- BTC is treated as 24/7 1-minute data; validation expected every minute and found no gaps across the loaded range.

NQ continuous:

- Databento `store.to_df(..., tz="UTC")` is used.
- `ts_event` is converted to UTC and duplicated as `ts_event_utc`.
- CME futures gaps are expected due to maintenance breaks, weekends, holidays, and bars only printing when trades occur.
- Validation explicitly says not to auto-fill all `>1m` gaps.

NQ raw-symbol clean CSVs:

- Raw Databento timestamps are parsed as UTC, then converted to `America/Chicago`.
- The output `timestamp` is a Chicago-time ISO string.
- This is useful for session QA, but it differs from the primary UTC continuous dataset.

Macro event calendar:

- Events have ET fields and `event_time_utc`.
- Final calendar rows: `360`, spanning `2015-01-09` to `2026-04-29`.
- Event types in the BTC-NQ research spine are CPI, FOMC, and NFP.
- Compound/near-event rows are preserved and tagged with `clean_event_flag` and `event_context_type`.

## 7. Data Cleaning Logic

BTCUSDT perpetual downloader:

- Reads monthly Binance ZIP CSVs.
- Handles files with or without a header row.
- Enforces standard Binance kline columns.
- Converts numeric columns with `pd.to_numeric`.
- Converts `open_time` and `close_time` from milliseconds to UTC.
- Drops rows missing required timestamps.
- Sorts by `open_time`.
- Deduplicates by `open_time`, keep first.
- Validates monthly expected row counts, 1-minute gaps, duplicate counts, and OHLC sanity.
- Saves parquet first, CSV fallback if parquet is unavailable.

NQ continuous downloader:

- Queries Databento historical range.
- Saves raw DBN when possible.
- Converts Databento store to DataFrame using float prices, pretty timestamps, mapped symbols, UTC timezone.
- Ensures `ts_event` exists and is UTC.
- Converts OHLCV numeric fields.
- Sorts and deduplicates by `ts_event`.
- Validates missing values, duplicate counts, OHLC sanity, gaps, and instrument rolls.
- Saves parquet first, CSV fallback if parquet is unavailable.

NQ raw-symbol cleaner:

- Requires columns `timestamp`, `open`, `high`, `low`, `close`, `volume`, `symbol`.
- Converts OHLCV to numeric.
- Strips symbol strings.
- Converts timestamp from UTC to `America/Chicago`.
- Sorts by Chicago timestamp.
- Writes clean CSV and summary.
- Does not auto-fill holiday/session gaps.

## 8. BTC and NQ Alignment Inventory Only

The old project mainly aligns BTC and NQ at macro-event timestamps, not as a continuous joined 1-minute panel. This section is inventory context only. Do not migrate or implement this alignment in the current `data_btc_nq1` phase.

BTC event alignment:

- Source: `scripts/event_study/build_btc_event_reaction_table.py`.
- Event time source: `event_time_utc`.
- Base time: `event_time - 1 minute`.
- Requires exact BTC bars for the full window from `event_time - 60m` through `event_time + 120m`.
- Returns include `btc_ret_1m`, `btc_ret_5m`, `btc_ret_15m`, `btc_ret_30m`, `btc_ret_60m`, `btc_ret_120m`.
- Also computes post-event max up/down, volume ratios, and realized volatility.

NQ event alignment:

- Source: `scripts/event_study/build_nq_zt_event_reaction_table.py`.
- Event time source: `event_time_utc`.
- Base target: `event_time - 1 minute`.
- Uses at-or-before lookup on NQ bars with `2` minute tolerance.
- Computes `nq_ret_5m`, `nq_ret_15m`, `nq_ret_30m`, `nq_ret_60m`, `nq_ret_120m`.
- Records `nq_base_instrument_id`, `nq_t_plus_120m_instrument_id`, and `nq_roll_window_flag`.

Deferred cross-asset merge:

- Source: `scripts/event_study/build_btc_nq_zt_cross_asset_diagnostics.py`.
- BTC and NQ/ZT reaction tables are merged by `event_id`, `validate="one_to_one"`.
- `all_assets_available = btc_data_available & nq_data_available & zt_data_available`.
- For BTC-NQ-only migration, a narrower `btc_nq_available = btc_data_available & nq_data_available` should be created instead of retaining ZT dependency.

Deferred event return paths:

- Source: `scripts/event_study/build_three_asset_first5m_and_event_paths.py`.
- Builds paths from `minute_offset = -60` to `120`.
- BTC uses exact minute lookup.
- NQ uses as-of lookup with `2` minute tolerance.
- Output includes `timestamp_used_utc` and `alignment_delta_minutes`.
- This file includes hypothesis/signal diagnostics and ZT, so migrate only the data alignment pattern, not the signal/backtest-like diagnostics.

## 9. Files That Can Be Migrated Now

Recommended direct migration or adaptation in the current pure data-source phase:

- `scripts/market_data/download_binance_btcusdt_um_1m.py`
- `scripts/market_data/download_databento_nq_1m.py`
- Basic BTCUSDT 1m clean parquet validator.
- Basic NQ continuous 1m clean parquet validator.

Data artifacts worth validating, but not copying unless explicitly approved:

- BTCUSDT 1m parquet.
- NQ continuous 1m parquet.

## 10. Files Not To Migrate

Do not migrate:

- BTC-NQ strategy/backtest files under `research/weekend_btc_nq/`.
- `stra/strategies/` strategy logic.
- `stra/cli/run_backtest.py` and backtest engine code unless separately requested.
- `pm_fade/` Polymarket research/data/results.
- `outputs/macro_event_mvp/*` plots/reports except validation summaries as documentation references.
- `scripts/event_study/build_btc_event_reaction_table.py`.
- `scripts/event_study/build_nq_zt_event_reaction_table.py`.
- `scripts/event_study/build_btc_nq_zt_cross_asset_diagnostics.py`.
- `scripts/event_study/build_three_asset_first5m_and_event_paths.py`.
- ZT-specific download/alignment code unless a later task explicitly includes rates/ZT.
- BTC-NQ timestamp/session alignment.
- `btc_nq_1m_clean.parquet`.
- Weekend feature datasets.
- Macro-event reaction datasets and `event_reactions`.
- Futu API/live/order code.
- Any `.env`, local API keys, credentials, or secrets.
- Old logs as runnable code; use them only as audit trail.

## 11. Suggested Target Structure In 2026 Strategy Lab

Recommended structure:

```text
D:\cursor\2026_strategy_lab\
  docs\
    migrations\
      202604_stra_data_inventory.md
    data_sources\
      binance_btc.md
      databento_nq.md
  scripts\
    data\
      binance\
        download_btcusdt_um_1m.py
        validate_btcusdt_um_1m.py
      databento\
        download_nq_continuous_1m.py
        validate_nq_continuous_1m.py
  data\
    raw\
      binance\
      databento\
    market_data\
      binance\
      databento\
  outputs\
    data_validation\
      market_data\
```

Current data-source contract:

- BTCUSDT clean market data remains a standalone parquet with Binance kline fields and UTC timestamp columns.
- NQ continuous clean market data remains a standalone parquet with Databento OHLCV fields and UTC timestamp columns.
- No BTC-NQ merged dataset is produced in this phase.
- No event-window dataset is produced in this phase.

## Next Minimal Migration Plan

1. Keep the migrated BTCUSDT downloader configurable for symbol, interval, month range, raw directory, and output path.
2. Keep the migrated Databento NQ downloader configurable for dataset, schema, symbol, time range, raw DBN path, and output path.
3. Require explicit user confirmation before any Databento API-credit usage.
4. Validate existing local BTCUSDT and NQ parquet files before copying or regenerating data.
5. Add data-source docs and rerun instructions; do not copy secrets or old strategy/backtest code.

Deferred to `btc_nq_strategy1`:

- BTC-NQ timestamp/session alignment.
- `btc_nq_1m_clean.parquet`.
- Weekend feature definitions and datasets.
- Macro-event reaction datasets and `event_reactions`.
- Any strategy signal, PnL, or backtest work.
