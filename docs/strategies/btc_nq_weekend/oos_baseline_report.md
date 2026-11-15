# BTC-NQ Weekend OOS Baseline Report

Scope: BTC-NQ Weekend only. Baseline NQ mode is `old_raw_contract`. No PM-HL, Futu, live trading, paper trading, parameter optimization, QQQ proxy, 4pm target variant, data download, or external API calls were used.

## Smoke Test

- smoke_test_old_output_reproduction: PASS

## Inputs

- BTC inputs:
  - `D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet`
  - `D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet`
  - `D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260601_20260618_daily.parquet`
- NQ raw contract inputs:
  - `NQH5`: `D:\cursor\202604_stra\data\processed\databento\nq\NQH5_1m_20241211_20250322_clean.csv`
  - `NQM5`: `D:\cursor\202604_stra\data\processed\databento\nq\NQM5_1m_20250312_20250621_clean.csv`
  - `NQU5`: `D:\cursor\202604_stra\data\processed\databento\nq\NQU5_1m_20250611_20250920_clean.csv`
  - `NQZ5`: `D:\cursor\202604_stra\data\processed\databento\nq\NQZ5_1m_20250910_20251220_clean.csv`
  - `NQH6`: `D:\cursor\202604_stra\data\processed\databento\nq\NQH6_1m_20251219_20260320_clean.csv`
  - `NQM6`: `D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQM6_1m_20260320_20260620_clean.csv`
  - `NQU6`: `D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQU6_1m_20260620_latest_clean.csv`
- Roll chain: NQH5 -> NQM5 -> NQU5 -> NQZ5 -> NQH6 -> NQM6 -> NQU6

## OOS Event Dataset

- OOS valid event range: 2026-03-23T09:30:00-04:00 to 2026-06-15T09:30:00-04:00
- Latest valid event: 2026-06-15T09:30:00-04:00
- OOS valid event count: 13
- Candidate Monday events scanned: 13
- Skipped events: 0
- Skipped reasons: {}

## Baseline Strategy

- Event: `monday_0930`
- Feature: `btc_ret_4h`
- Target: `nq_fwd_1d`
- Signal: long NQ if BTC 4h return > 0; short NQ if BTC 4h return < 0
- Cost: 0.001

## OOS Results

- Long / short count: 8 / 5
- Gross return sum: -0.064289%
- Net return sum after cost: -1.364289%
- Cumulative gross return: -0.109312%
- Cumulative net return: -1.400280%
- Gross win rate: 46.153846%
- Net win rate: 46.153846%
- Average gross return: -0.004945%
- Average net return: -0.104945%
- Benchmark NQ gross return sum: -0.844281%
- Benchmark NQ net return sum: -2.144281%
- Benchmark NQ cumulative gross return: -0.885472%
- Benchmark NQ cumulative net return: -2.167173%

## IS Baseline Comparison

- IS events: 66
- OOS events: 13
- IS average net return: 0.430525%
- OOS average net return: -0.104945%
- IS cumulative net return: 32.136714%
- OOS cumulative net return: -1.400280%
- IS net win rate: 66.666667%
- OOS net win rate: 46.153846%

## Conclusion

- OOS is not profitable on this local data window.
- The OOS sample is small, so stability should be treated as provisional.
- This is worth reviewing before any QQQ proxy or 4pm target variant work; those were not run in this task.

<!-- btc-nq-oos-visual-report-sections -->

## IS vs OOS NAV

- Unified NAV chart: `D:\cursor\2026_strategy_lab\reports\btc_nq_weekend\oos_baseline\monday_0930_is_oos_nav.png`
- OOS vertical separator: 2026-03-23
- NAV basis: net strategy returns and net benchmark returns; OOS NAV starts from the IS terminal NAV for visual continuity.

## Subsample Attribution: first_half / second_half / oos

- first_half: events=33, average net=0.583589%, cumulative net=20.726470%, net win rate=72.727273%, long/short=15/18.
- second_half: events=33, average net=0.277462%, cumulative net=9.451319%, net win rate=60.606061%, long/short=18/15.
- oos: events=13, average net=-0.104945%, cumulative net=-1.400280%, net win rate=46.153846%, long/short=8/5, low_sample_warning=true.

## Side Attribution: long_only / short_only / symmetric

- long_only: trades=8, average net=-0.156786%, cumulative net=-1.282192%, net win rate=37.500000%, max drawdown net=-2.422143%.
- short_only: trades=5, average net=-0.022001%, cumulative net=-0.119621%, net win rate=60.000000%, max drawdown net=-1.280088%.
- symmetric: trades=13, average net=-0.104945%, cumulative net=-1.400280%, net win rate=46.153846%, max drawdown net=-3.479262%.

