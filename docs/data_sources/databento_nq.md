# Databento NQ Data Source

Current owner: `data_btc_nq1`

Current scope: pure market data download and basic clean parquet validation.

## Dataset

- Source: Databento Historical.
- Dataset: `GLBX.MDP3`.
- Schema: `ohlcv-1m`.
- Symbol: `NQ.v.0`.
- `stype_in`: `continuous`.
- Primary output target: `data/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.parquet`.
- Raw DBN target: `data/raw/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.dbn`.

The old project validation showed usable data from `2020-01-01 23:00:00 UTC` through `2026-04-30 23:59:00 UTC`.

## Scripts

- Continuous downloader: `scripts/data/databento/download_nq_continuous_1m.py`
- Continuous validator: `scripts/data/databento/validate_nq_continuous_1m.py`
- **Raw-symbol downloader:** `scripts/data/databento/download_nq_raw_contract_1m.py` (dry-run by default)
- **Raw-symbol clean:** `scripts/data/databento/clean_nq_raw_contract_1m.py`
- **Raw-symbol validator:** `scripts/data/databento/validate_nq_raw_contract_1m.py`

Downloader parameters:

- `--dataset`, default `GLBX.MDP3`
- `--schema`, default `ohlcv-1m`
- `--symbol`, default `NQ.v.0`
- `--stype-in`, default `continuous`
- `--start`, default `2020-01-01`
- `--end`, default `2026-05-01`
- `--output`, clean parquet output path
- `--raw-dbn`, optional raw DBN output path
- `--execute`, required to call Databento
- `--confirm-use-api-credits`, required with `--execute`

Default local output path:

- `data/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.parquet`

Example validation against an existing old-project parquet:

```powershell
python scripts/data/databento/validate_nq_continuous_1m.py --input "D:\cursor\202604_stra\data\market_data\databento\GLBX.MDP3\NQ\1m\nq_continuous_volume_front_1m_2020_2026.parquet"
```

## API Credit Safety

Do not run the Databento downloader unless a human explicitly confirms API-credit usage.

The downloader defaults to safe dry-run/config validation and makes no API call. It only calls Databento when both `--execute` and `--confirm-use-api-credits` are passed. For the current migration phase, prefer validating existing local parquet files or copying data only after explicit approval.

Current task status:

- NQM6 raw-symbol downloaded / cleaned / validated: **yes** (88,063 rows; PASS).
- NQU6 raw-symbol downloaded / cleaned / validated: **partial** (1,380 rows; 2026-06-18 UTC only; PASS).
- Databento API called: **yes**.
- Databento credits used: **yes** (NQM6 + NQU6 only).

OOS update plan: see `docs/data_sources/btc_nq_oos_data_update_plan.md`.

**Important:** OOS baseline uses **raw-symbol single contracts** (`old_raw_contract`). Clean paths for new contracts:

- `data/processed/databento/nq/NQM6_1m_20260320_20260620_clean.csv`
- `data/processed/databento/nq/NQU6_1m_20260620_latest_clean.csv` (partial; re-download when license extends)

## Validation Contract

Required fields:

- `ts_event` or `ts_event_utc`
- `open`
- `high`
- `low`
- `close`
- `volume`

Optional but useful fields:

- `instrument_id`
- `symbol`
- `rtype`
- `publisher_id`

Basic checks:

- Timestamp source detection from common timestamp columns or datetime index.
- Timestamp parse and normalization assumption: UTC.
- Sorted ascending timestamp check.
- No duplicate timestamp.
- OHLC sanity: `high` must contain open/low/close, `low` must contain open/high/close.
- OHLC values must be positive.
- Volume must be numeric and non-negative.
- Report `>1m` gaps, but do not fail solely because of gaps. CME futures have daily maintenance breaks, weekends, holidays, and sparse trade intervals.
- Report unique `instrument_id` count when available.

## Out Of Scope

- BTC-NQ timestamp/session alignment.
- BTC-NQ clean panel generation.
- Macro-event reaction datasets.
- Weekend feature datasets.
- ZT / rates proxy.
- Strategy signals.
- PnL or backtests.
- Futu API or live trading.
