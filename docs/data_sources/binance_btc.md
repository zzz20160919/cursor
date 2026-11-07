# Binance BTCUSDT Data Source

Current owner: `data_btc_nq1`

Current scope: pure market data download and basic clean parquet validation.

## Dataset

- Source: Binance Vision public data.
- Market: USD-M futures.
- Instrument: `BTCUSDT` perpetual.
- Interval: `1m`.
- Primary output target: `data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_2020_2026.parquet`.
- Raw ZIP target: `data/raw/market_data/binance/futures/um/monthly/klines/BTCUSDT/1m/`.

The old project validation showed usable data from `2020-01-01 00:00:00 UTC` through `2026-03-31 23:59:00 UTC`. The requested `2026-04` monthly ZIP was unavailable at that time.

## Scripts

- Downloader: `scripts/data/binance/download_btcusdt_um_1m.py`
- Validator: `scripts/data/binance/validate_btcusdt_um_1m.py`

Downloader parameters:

- `--mode`, `monthly` (default) or `daily`
- `--symbol`, default `BTCUSDT`
- `--interval`, default `1m`
- `--start`, inclusive UTC start date/timestamp, default `2020-01-01`
- `--end`, exclusive UTC end date/timestamp, default `2026-04-01`
- `--start-month` and `--end-month`, retained for month-level Binance Vision cache selection
- `--raw-dir`, optional local ZIP cache path (defaults to `monthly/` or `daily/` subdir by mode)
- `--output`, clean parquet output path

Daily mode example (June 2026 incremental):

```powershell
python scripts/data/binance/download_btcusdt_um_1m.py `
  --mode daily `
  --start 2026-06-01 `
  --end 2026-06-20 `
  --output "data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_20260601_20260618_daily.parquet"
```

Trailing day in range (`--end` exclusive) may be unavailable on Binance Vision; script reports `unavailable_days` without failing.

Default local output path:

- `data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_2020_2026.parquet`

Example validation against an existing old-project parquet:

```powershell
python scripts/data/binance/validate_btcusdt_um_1m.py --input "D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet"
```

Current task status:

- Old data copied: no.
- BTC Apr–May staging: **yes** (`btcusdt_um_1m_20260401_20260601.parquet`, 87,840 rows, PASS).
- BTC June daily staging: **yes** (`btcusdt_um_1m_20260601_20260618_daily.parquet`, 25,920 rows, PASS).
- Databento API called: not applicable.

OOS update plan: see `docs/data_sources/btc_nq_oos_data_update_plan.md`.

Do not overwrite the old-project baseline parquet at `202604_stra`.

## Validation Contract

Required fields:

- `open_time`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `close_time`
- `open_time_utc`
- `close_time_utc`

Basic checks:

- Timestamp source detection from common timestamp columns or datetime index.
- Timestamp parse and normalization assumption: UTC.
- Sorted ascending timestamp check.
- No duplicate timestamp.
- No `>1m` gaps for the 24/7 BTCUSDT 1m series.
- OHLC sanity: `high` must contain open/low/close, `low` must contain open/high/close.
- OHLC values must be positive.
- Volume must be numeric and non-negative.

## Out Of Scope

- BTC-NQ timestamp/session alignment.
- BTC-NQ clean panel generation.
- Macro-event reaction datasets.
- Weekend feature datasets.
- Strategy signals.
- PnL or backtests.
- Futu API or live trading.
