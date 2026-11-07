# BTC-NQ Weekend Strategy Inventory

Agent: `btc_nq_strategy1`

Scope: old-logic extraction only. No Futu, live trading, paper trading, new production backtest, new signals, new PnL, data download, or external API calls were performed for this inventory.

## 1. Executive Summary

The old BTC-NQ weekend research lives in `D:\cursor\202604_stra\research\weekend_btc_nq\`. It is an event-study research module, not a production backtest and not part of the old `stra` backtest engine.

The old project tested whether BTC returns lead NQ forward returns around weekly event times. Two event definitions were implemented:

- `sunday_1700`: `t0 = Sunday 17:00 America/Chicago`.
- `monday_0930`: `t0 = Monday 09:30 America/New_York`, intentionally the New York cash open, not Chicago 09:30.

The main branch selected for follow-up validation was:

- Event: `monday_0930`
- BTC signal: `btc_ret_4h`
- NQ target: `nq_fwd_1d`
- Signal rule: symmetric sign strategy, long NQ when `btc_ret_4h > 0`, short NQ when `btc_ret_4h < 0`
- Holding window: one event-level NQ forward window from `t0` to `t0 + 1d`
- Return basis: NQ log return converted to simple return with `exp(nq_fwd_1d) - 1`
- Cost model in v2: fixed `0.001` per event trade, representing transaction cost plus slippage

The old result is small-sample research evidence only. The Monday focused validation used 66 weekly events and a chronological 33/33 first-half/second-half stability check. No true train/test or out-of-sample protocol was found.

## 2. Old Strategy File Map

Main old strategy and event-study modules:

- `D:\cursor\202604_stra\research\weekend_btc_nq\run.py`
  - Main CLI for building event datasets and writing pairwise stats.
  - Supports `--event-name sunday_1700|monday_0930`.
  - Accepts configurable `--btc-csv`, `--btc-bar-freq`, `--nq-dir`, repeated `--nq-csv`, `--roll-chain`, `--btc-lookbacks`, and `--nq-forwards`.
- `D:\cursor\202604_stra\research\weekend_btc_nq\events.py`
  - Defines event timestamps, BTC feature computation, NQ forward target computation, and event-level BTC/NQ alignment.
- `D:\cursor\202604_stra\research\weekend_btc_nq\focused_validation.py`
  - Hard-coded focused validation for `monday_0930`, `btc_ret_4h`, `nq_fwd_1d`.
  - Writes subsample stability, event-trade, gross/net performance, and NAV outputs.
- `D:\cursor\202604_stra\research\weekend_btc_nq\run_focused_validation.py`
  - CLI wrapper around focused validation.
- `D:\cursor\202604_stra\research\weekend_btc_nq\event_trade.py`
  - Earlier/minimal Sunday event-trade validation using `btc_ret_1h` and `nq_fwd_1h`.
- `D:\cursor\202604_stra\research\weekend_btc_nq\stats_outputs.py`
  - Pairwise correlations, conditional means, sign-hit ratio, Welch t-tests, ranked summary, and summary text outputs.
- `D:\cursor\202604_stra\research\weekend_btc_nq\nq_contracts.py`
  - Multi-contract NQ event assignment.
- `D:\cursor\202604_stra\research\weekend_btc_nq\loaders.py`
  - Strict BTC and NQ CSV loaders.
- `D:\cursor\202604_stra\research\weekend_btc_nq\time_utils.py`
  - Timezone parsing, relative window parsing, and BTC bar-frequency mapping.
- `D:\cursor\202604_stra\research\weekend_btc_nq\input_formats.py`
  - Text contract for old BTC/NQ CSV input formats.

Main old documentation:

- `D:\cursor\202604_stra\PROJECT_STATUS.md`
- `D:\cursor\202604_stra\research\CONCLUSIONS.md`

No relevant `.ipynb` notebooks were found in the old project.

## 3. Old Data Input Map

Old BTC input:

- `D:\cursor\202604_stra\data\bars_BTCUSDT_1h_202301_202603.csv`
  - Required columns: `timestamp`, `close`.
  - Optional OHLCV columns ignored by this research.
  - Timestamp is treated as Binance-style bar open time in UTC.
  - The BTC bar frequency is supplied separately by CLI, typically `--btc-bar-freq 1h`.

Other BTC file present but not the old weekend strategy's main input:

- `D:\cursor\202604_stra\data\bars_BTCUSDT_1d_202301_202603.csv`

Old NQ inputs:

- `D:\cursor\202604_stra\data\processed\databento\nq\NQH5_1m_20241211_20250322_clean.csv`
- `D:\cursor\202604_stra\data\processed\databento\nq\NQM5_1m_20250312_20250621_clean.csv`
- `D:\cursor\202604_stra\data\processed\databento\nq\NQU5_1m_20250611_20250920_clean.csv`
- `D:\cursor\202604_stra\data\processed\databento\nq\NQZ5_1m_20250910_20251220_clean.csv`
- `D:\cursor\202604_stra\data\processed\databento\nq\NQH6_1m_20251219_20260320_clean.csv`

NQ requirements:

- Required columns: `timestamp`, `close`, `symbol`.
- Each file contains exactly one NQ deliverable symbol.
- Timestamps are timezone-aware ISO strings, parsed to UTC and converted to `America/Chicago`.
- Each row is a 1-minute bar open timestamp; the `close` field is used for all return endpoints.

Important migration note:

- The old strategy did not use the new validated parquet inputs directly.
- The new migration should support configurable BTC and NQ input paths and adapt the old logic to the new validated sources:
  - BTC: `D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet`
  - NQ: `D:\cursor\202604_stra\data\market_data\databento\GLBX.MDP3\NQ\1m\nq_continuous_volume_front_1m_2020_2026.parquet`

## 4. Old Output Reports and Result Files

Primary old output directories:

- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_sunday_fullstats_v1\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_sunday_trade_v1\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_v1\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_trade_v1\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_trade_v2\`

Important Monday full-stat files:

- `monday_0930_event_dataset.csv`
- `pairwise_stats.csv`
- `conditional_means.csv`
- `sign_hit_ratio.csv`
- `ttest_summary.csv`
- `result_summary_ranked.csv`
- `correlation_matrix.csv`
- `overlap_assignment_summary.txt`
- `summary.txt`

Important Monday focused-validation v2 files:

- `monday_0930_subsample_stats.csv`
- `monday_0930_subsample_summary.txt`
- `monday_0930_event_trade_trades.csv`
- `monday_0930_event_trade_summary.csv`
- `monday_0930_event_trade_summary.txt`
- `monday_0930_performance_fullsample.csv`
- `monday_0930_performance_first_half.csv`
- `monday_0930_performance_second_half.csv`
- `monday_0930_performance_summary.txt`
- `monday_0930_event_trade_nav.html`
- `monday_0930_nav_fullsample_net.html`
- `monday_0930_nav_first_half_net.html`
- `monday_0930_nav_second_half_net.html`

Older/preliminary output directories also exist:

- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_run1\`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_mc_test\`

## 5. Reconstructed Old Strategy Logic

The old workflow had three layers:

1. Build an event-level dataset.
   - Generate weekly `t0` event timestamps between the combined BTC/NQ data coverage bounds.
   - Assign one active NQ contract per event.
   - Compute BTC lookback log returns ending at `t0`.
   - Compute NQ forward log returns from `t0` to `t0 + forward_window`.

2. Rank BTC/NQ feature-target pairs.
   - Compute Pearson and Spearman correlations.
   - Compute conditional NQ means when BTC return is negative vs non-negative.
   - Compute sign-hit ratio when BTC return is negative.
   - Compute Welch t-test p-values.
   - Rank by absolute Spearman correlation, then absolute Pearson correlation, then p-value, then sample count.

3. Focused validation on the selected pair.
   - Hard-coded event: `monday_0930`.
   - Hard-coded signal: `btc_ret_4h`.
   - Hard-coded target: `nq_fwd_1d`.
   - Build short-only, long-only, and symmetric event-trade variants.
   - Compare the symmetric strategy to event-aligned NQ full-long benchmark.
   - Report gross and net metrics with a fixed per-trade cost in v2.

## 6. Exact BTC Feature Definitions

BTC feature name format:

- `btc_ret_<lookback>`

Supported window parser:

- `m`: minutes
- `h`: hours
- `d`: calendar days of 24 hours each

Old broad Monday run used:

- `btc_ret_1h`
- `btc_ret_4h`
- `btc_ret_1d`
- `btc_ret_2d`

Exact computation:

- For each event `t0`, convert `t0` to `America/Chicago`, then to UTC for BTC lookup.
- Snap both endpoints to UTC BTC bar-open keys using `floor(btc_bar_rule)`.
- Start key: `floor_utc(t0 - lookback)`.
- End key: `floor_utc(t0)`.
- Price: BTC `close` at the bar-open key.
- Feature value: `log(close_end / close_start)`.

For the main focused strategy:

- `btc_ret_4h = log(BTC close at floor_utc(t0) / BTC close at floor_utc(t0 - 4h))`.
- With old 1h BTC bars and `monday_0930`, `t0` is 09:30 New York, which maps to 13:30 or 14:30 UTC depending on DST. The old hourly lookup floors this to the UTC hour.

If any required BTC bar is missing or has a non-positive close, the entire event row is skipped.

## 7. Exact NQ Feature and Target Definitions

NQ target name format:

- `nq_fwd_<forward>`

Old broad Monday run used:

- `nq_fwd_5m`
- `nq_fwd_10m`
- `nq_fwd_30m`
- `nq_fwd_1h`
- `nq_fwd_4h`
- `nq_fwd_1d`
- `nq_fwd_2d`

Exact computation:

- Convert event `t0` to `America/Chicago`.
- Assign exactly one active NQ contract for the event.
- Snap NQ endpoints to 1-minute Chicago bar-open keys using floor to `1min`.
- Start key: `floor_chicago(t0)`.
- End key: `floor_chicago(t0 + forward_window)`.
- Price: NQ `close` at those 1-minute bar-open keys on the active contract.
- Target value: `log(close_end / close_start)`.

For the main focused strategy:

- `nq_fwd_1d = log(NQ active-contract close at t0 + 1d / NQ active-contract close at t0)`.
- `monday_0930` maps to `08:30 America/Chicago` at the old event dates, so the focused holding window is Monday 08:30 Chicago to Tuesday 08:30 Chicago on the selected active contract.

If the active contract does not contain either endpoint, or either endpoint has a missing/non-positive close, that `(event, forward)` is set to NaN and marked skipped. The event row may still remain usable for other forward windows.

## 8. BTC/NQ Alignment Logic

The old alignment is event-level, not continuous bar-by-bar alignment.

Timestamp rules:

- BTC source timestamps are parsed as UTC bar opens.
- NQ source timestamps are parsed as timezone-aware instants, normalized to UTC, then converted to `America/Chicago`.
- Event timestamps are generated in the event's own local timezone.
- BTC returns are looked up on UTC bar-open keys.
- NQ returns are looked up on Chicago 1-minute bar-open keys.

NQ active-contract rule:

- Each NQ contract coverage interval is `[first_open_chicago, last_open_chicago]`, inclusive.
- Candidate contracts are all contracts whose coverage contains `t0`.
- Fixed roll chain: `NQH5 -> NQM5 -> NQU5 -> NQZ5 -> NQH6`.
- If multiple contracts cover `t0`, the later symbol in the fixed roll chain wins.
- No volume or open-interest selection is used.
- No back-adjustment is used.
- No intra-event contract switching is allowed.
- If no active contract covers `t0`, the entire event is omitted.
- If a forward endpoint cannot be computed on the active contract, the old code does not substitute another contract.

The old Monday full-stat output reported:

- `event_rows: 66`
- `overlap_t0_multi_contract_events: 3`
- `forward_skipped_5m: 0`
- `forward_skipped_10m: 0`
- `forward_skipped_30m: 0`
- `forward_skipped_1h: 0`
- `forward_skipped_4h: 6`
- `forward_skipped_1d: 0`
- `forward_skipped_2d: 2`
- `no_active_contract_for_t0: 104`

## 9. Weekend and Session Definition

Implemented old event definitions:

- `sunday_1700`
  - `t0 = Sunday 17:00 America/Chicago`
  - This corresponds to CME Sunday evening session open.
  - The earlier event-trade validation used `btc_ret_1h -> nq_fwd_1h`.

- `monday_0930`
  - `t0 = Monday 09:30 America/New_York`
  - Explicitly intended as the New York cash equity open, not Chicago 09:30.
  - This became the main branch for follow-up validation.
  - The focused validation used `btc_ret_4h -> nq_fwd_1d`.

NQ session/break handling in the old project was implicit through bar existence in the selected 1-minute contract CSV. There was no explicit CME session calendar object. Missing forward endpoints were skipped instead of filled.

## 10. Prediction Target

The exact main prediction target is:

- `target = nq_fwd_1d`
- Type: log return.
- Computation: `log(NQ_close(t0 + 1d) / NQ_close(t0))` on the active NQ contract.
- The trade layer converts it to simple return with `exp(nq_fwd_1d) - 1`.

For exploratory ranking, the old project also evaluated `nq_fwd_5m`, `nq_fwd_10m`, `nq_fwd_30m`, `nq_fwd_1h`, `nq_fwd_4h`, and `nq_fwd_2d`.

## 11. Trading Signal and Position Logic

Focused validation signal:

- `signal = btc_ret_4h`

Focused validation strategy variants:

- `short_only`
  - Trade only when `btc_ret_4h < 0`.
  - Position: short NQ for the event window.
- `long_only`
  - Trade only when `btc_ret_4h > 0`.
  - Position: long NQ for the event window.
- `symmetric`
  - If `btc_ret_4h < 0`, short NQ.
  - If `btc_ret_4h > 0`, long NQ.
  - If `btc_ret_4h == 0`, the trade builder emits no trade. In the performance-frame helper, `np.sign(0)` would produce zero gross return while still subtracting cost, but no zero-signal case was identified in the old output.

Position sizing:

- Event-level one-unit notional exposure.
- No leverage model.
- No capital allocation model.
- No volatility targeting.
- No stop loss or take profit.
- No overlapping position management was implemented beyond weekly event cadence.

Benchmark:

- Event-aligned NQ full-long benchmark.
- Return: `exp(nq_fwd_1d) - 1`.
- Net benchmark in v2 subtracts the same `cost_rate`.

## 12. Holding Period and Execution Price Assumption

Focused Monday holding period:

- Enter at `t0 = Monday 09:30 America/New_York`.
- Exit at `t0 + 1d`.
- For old event dates this maps to Chicago 08:30 to next-day Chicago 08:30.
- The holding window is exactly 24 hours, not necessarily an RTH close-to-close window.

Execution price assumption:

- The old code does not model actual order placement, bid/ask, partial fills, market impact, or exchange-specific order timing.
- It uses NQ `close` at the 1-minute bar whose open timestamp equals `t0` as the entry price proxy.
- It uses NQ `close` at the 1-minute bar whose open timestamp equals `t0 + forward_window` as the exit price proxy.
- Long gross return: `exp(nq_fwd_1d) - 1`.
- Short gross return: `-(exp(nq_fwd_1d) - 1)`.

This is a research proxy and should be revisited before production backtesting.

## 13. Transaction Cost and Slippage Assumption

Old Sunday trade validation:

- Gross only.
- `fee = 0`.
- `slippage = 0`.

Old Monday focused validation v1:

- Gross only.
- `fee = 0`.
- `slippage = 0`.

Old Monday focused validation v2:

- `cost_rate = 0.001` per event trade by default.
- Text label: `transaction_cost_plus_slippage = 0.0010 per trade`.
- Net strategy return: `trade_return_gross - cost_rate`.
- Net NQ benchmark return: `(exp(nq_fwd_1d) - 1) - cost_rate`.

The old code treats the cost as a flat simple-return deduction per event trade, not ticks, bps per side, commissions, spread, or contract multiplier dollars.

## 14. Train/Test or OOS Methodology

No true train/test or out-of-sample methodology was found.

What exists:

- Ranking was performed on the available event sample.
- The focused pair `monday_0930 + btc_ret_4h -> nq_fwd_1d` was selected from the same research universe.
- Focused validation split the 66 events chronologically:
  - `fullsample`: 66 events
  - `first_half`: first 33 events
  - `second_half`: last 33 events
- Stability check compared first-half and second-half direction/strength.

Old v2 subsample summary:

- `direction_consistent: true`
- `obvious_instability: false`
- `second_half_materially_weaker_than_first_half: false`
- first-half Pearson/Spearman: `0.602236` / `0.545455`
- second-half Pearson/Spearman: `0.414921` / `0.369318`
- strength ratio second over first: `0.689`

This is supportive stability evidence, not OOS validation.

## 15. Metrics Used in Old Reports

Pairwise/research metrics:

- Pearson correlation and p-value.
- Spearman correlation and p-value.
- Conditional mean of NQ forward return when BTC return is negative.
- Conditional mean of NQ forward return when BTC return is non-negative.
- Sign-hit ratio: when BTC return is negative, fraction of events where NQ forward return is negative.
- Welch t-test statistic and p-value.
- Low sample warning threshold: `20`.
- Ranked summary sorted by absolute Spearman, absolute Pearson, p-value, and sample count.

Trade/performance metrics:

- Trade count.
- Mean return.
- Median return.
- Hit ratio.
- Cumulative simple return: `sum(r)`.
- Cumulative geometric return: `prod(1 + r) - 1`.
- Annualized return: `(prod(1 + r))^(52 / N) - 1`.
- Annualized volatility/risk: `std(r, ddof=1) * sqrt(52)`.
- Sharpe: `mean(r) / std(r, ddof=1) * sqrt(52)`, risk-free rate `0`.
- Max drawdown from cumulative geometric equity `cumprod(1 + r)`.
- Calmar ratio: `annualized_return / abs(max_drawdown)`.
- Success ratio: positive-return events divided by total events.

Old Monday v2 fullsample net snapshot:

- Strategy net annual return: `0.245523`
- Benchmark net annual return: `0.045629`
- Strategy net Sharpe: `2.499109`
- Benchmark net Sharpe: `0.509288`
- Strategy net max drawdown: `-0.029250`
- Benchmark net max drawdown: `-0.078318`

## 16. Hard-Coded Paths, Dates, Parameters, and Assumptions

Hard-coded or default paths:

- Default NQ directory in old `run.py`: `PROJECT_ROOT / data / processed / databento / nq`.
- Default output directory in old `run.py`: `PROJECT_ROOT / research / outputs / weekend_btc_leads_nq`.
- Old documentation identifies BTC input as `data/bars_BTCUSDT_1h_202301_202603.csv`.
- Old documentation identifies the five NQ clean contract CSVs listed above.

Hard-coded focused validation constants:

- `EVENT_NAME = "monday_0930"`
- `SIGNAL_COL = "btc_ret_4h"`
- `TARGET_COL = "nq_fwd_1d"`
- `TRADES_PER_YEAR = 52.0`
- `LOW_SAMPLE_WARN_THRESHOLD = 20`
- `DEFAULT_COST_RATE = 0.001`

Hard-coded NQ roll chain:

- `("NQH5", "NQM5", "NQU5", "NQZ5", "NQH6")`

Default broad-run parameters in source:

- `DEFAULT_BTC_LOOKBACKS = ["1h"]`
- `DEFAULT_NQ_FORWARDS = ["5m", "10m", "30m", "1h"]`

Actual old Monday output indicates a broader run:

- BTC lookbacks: `1h`, `4h`, `1d`, `2d`.
- NQ forwards: `5m`, `10m`, `30m`, `1h`, `4h`, `1d`, `2d`.

Assumptions:

- Inputs are already cleaned CSVs.
- BTC is available continuously enough for event endpoints.
- NQ session availability is handled by missing/present 1-minute bars, not an explicit calendar.
- One active NQ contract per event.
- Later-quarter contract wins on overlap.
- No cross-contract fill for forward windows.
- No macro-event filters.
- No bid/ask or exchange execution model.

## 17. Macro-Event Dependencies

No CPI, FOMC, NFP, macro-event, `ZT`, or `event_reactions` dependency was found inside `research\weekend_btc_nq\` or in `research\CONCLUSIONS.md`.

There are unrelated macro-event and BTC/NQ/zt reaction datasets elsewhere in the old project, but they are not directly required by the old BTC-NQ weekend strategy logic identified here.

## 18. Known Issues and Ambiguities

- The old strategy uses old CSV inputs, not the newly validated parquet data layer. Migration must adapt input loaders without changing old event math.
- The old NQ input is five raw-symbol contract CSVs with event-level contract assignment. The new validated NQ file is a continuous volume-front parquet. Using the continuous file will not exactly reproduce old active-contract assignment unless the new data contains equivalent symbol/roll information or the migration explicitly chooses continuous-NQ semantics.
- Old BTC data is 1h. The new validated BTC source is 1m. To reproduce old features exactly from 1m data, resampling or endpoint selection must match old hourly UTC bar-open behavior.
- The old execution assumption uses `close` at the 1-minute bar-open timestamp as a proxy price. This is not a realistic fill model.
- The focused validation pair appears selected after looking at same-sample rankings. Treat reported performance as in-sample research.
- There is no explicit CME session calendar. Missing NQ bars drive skip behavior.
- The old `sunday_fullstats_v1\summary.txt` text still contains an outdated note about small N around 12 Sunday events even though the output shows 66 rows.
- In `focused_validation.py`, zero signal handling differs slightly between trade-output construction and performance-frame construction; no zero-signal events were observed in the inspected output.
- Old result output contains preliminary directories (`weekend_btc_leads_nq`, `weekend_btc_leads_nq_run1`, `weekend_btc_leads_nq_mc_test`) that appear superseded by the named v1/v2 directories.

## 19. Proposed Clean Migration Plan for Next Step

Next step should be a faithful research migration, not a production trading implementation.

Recommended plan:

1. Create a small `strategies/btc_nq_weekend/` or `research/btc_nq_weekend/` module in the new repo.
2. Port only the event-grid, feature, target, and focused-validation logic needed to reproduce old outputs.
3. Add configurable input paths for BTC and NQ.
4. Implement BTC 1m-to-feature handling so `btc_ret_4h` and other lookbacks use the same UTC bar-open endpoint semantics as old code.
5. Decide explicitly whether the NQ migration target is:
   - exact old raw-symbol active-contract semantics, requiring per-contract NQ inputs; or
   - new continuous volume-front semantics, which is cleaner for the new data layer but not exact old reproduction.
6. Add a small validation script that builds the event dataset only and compares row counts, timestamps, feature columns, skip counts, and a few hand-picked return values against old CSV outputs.
7. Only after event-dataset parity is documented, add focused validation output reproduction.
8. Defer production backtesting, Futu, paper/live trading, and order execution assumptions until after old-logic parity.

## 20. Exact Files That Should Be Migrated or Rewritten Next

Rewrite or port next:

- `D:\cursor\202604_stra\research\weekend_btc_nq\events.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\time_utils.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\loaders.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\nq_contracts.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\stats_outputs.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\focused_validation.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\run.py`
- `D:\cursor\202604_stra\research\weekend_btc_nq\run_focused_validation.py`

Use as reference outputs for parity:

- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_v1\monday_0930_event_dataset.csv`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_v1\result_summary_ranked.csv`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_v1\summary.txt`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_trade_v2\monday_0930_performance_summary.txt`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_trade_v2\monday_0930_performance_fullsample.csv`
- `D:\cursor\202604_stra\research\outputs\weekend_btc_leads_nq_monday_0930_trade_v2\monday_0930_event_trade_trades.csv`

Do not migrate next unless a later task explicitly asks for it:

- Futu integration.
- Live trading.
- Paper trading.
- Macro-event, CPI, FOMC, NFP, or ZT/rates logic.
- Unrelated `pm_fade`, BTC regime, or old `stra` toy strategy modules.

## 21. Step 2 Status: Event-Dataset Parity Migration

Step 2 implemented a minimal event-study dataset builder and parity validator in the new repo:

- `src/strategies/btc_nq_weekend/event_dataset.py`
- `scripts/strategy/btc_nq_weekend/build_event_dataset.py`
- `scripts/strategy/btc_nq_weekend/validate_event_dataset_parity.py`
- `docs/strategies/btc_nq_weekend/event_dataset_parity.md`
- `docs/strategies/btc_nq_weekend/event_dataset_parity_report.md`

Current parity result using new BTC 1m parquet and continuous NQ 1m parquet:

- `monday_0930` row count matches old output: `66 / 66`.
- `sunday_1700` row count matches old output: `66 / 66`.
- Focused Monday split matches old validation: `33 / 33`.
- BTC returns match old output exactly after resampling 1m BTC to old-style left-labeled 1h bar-close values.
- NQ continuous returns do not exactly match old raw-symbol active-contract output, so continuous NQ should not be treated as exact old-output parity.

No production backtest, Futu integration, live trading, paper trading, macro-event migration, data download, or external API call was performed in Step 2.
