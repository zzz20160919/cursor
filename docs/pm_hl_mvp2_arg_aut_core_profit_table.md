# PM-HL MVP2 Arg/Aus Core Profit Table

## Conclusions First

- Best observed edge: `cross_venue_direct_no_complete_set` / `Argentina` / `buy_hl_Argentina_yes_buy_pm_Argentina_no` with max edge `0.069472` at `2026-06-23 01:38:53 UTC+8`.
- Best MVP2 execution candidate remains op1: `Argentina` / `buy_hl_Argentina_yes_buy_pm_Argentina_no` with max net `0.069472`.
- A 20-share slot at that best op1 net is roughly `$1.389440` profit, or `1.286519% - 1.157867%` on a $108-$120 six-slot portfolio.
- op2/op3 stay paper monitor only; op4 stays diagnostic only.

## Core Profit Table

| op_group | outcome_or_condition | side | total_rows | positive_rows | positive_pct | max_positive_net_or_edge | mean_positive_net_or_edge | best_timestamp_utc8 | est_profit_20_shares | est_portfolio_return_low_pct | est_portfolio_return_high_pct | mvp_decision | comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 96 | 7 | 0.072917 | 0.069472 | 0.012253 | 2026-06-23 01:38:53 UTC+8 | 1.389440 | 1.286519 | 1.157867 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 292 | 20 | 0.068493 | 0.014352 | 0.003130 | 2026-06-23 01:48:08 UTC+8 | 0.287040 | 0.265778 | 0.239200 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 267 | 9 | 0.033708 | 0.003154 | 0.001886 | 2026-06-23 01:54:08 UTC+8 | 0.063070 | 0.058399 | 0.052559 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_direct_no_complete_set | Austria | buy_pm_Austria_yes_buy_hl_Austria_no | 109 | 11 | 0.100917 | 0.003386 | 0.001195 | 2026-06-23 02:17:37 UTC+8 | 0.067717 | 0.062701 | 0.056431 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_direct_no_complete_set | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 268 | 2 | 0.007463 | 0.004528 | 0.004528 | 2026-06-23 01:14:56 UTC+8 | 0.090560 | 0.083852 | 0.075467 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 91 | 11 | 0.120879 | 0.002457 | 0.002063 | 2026-06-23 02:46:33 UTC+8 | 0.049140 | 0.045500 | 0.040950 | continue_op1_execution_mvp_research | Best fit for MVP2 execution research, but needs two-leg execution controls and VWAP validation. |
| cross_venue_single_outcome | Argentina | buy_hl_yes_sell_pm_yes | 96 | 7 | 0.072917 | 0.049268 | 0.009367 | 2026-06-23 01:38:53 UTC+8 | 0.985360 | 0.912370 | 0.821133 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 292 | 20 | 0.068493 | 0.014352 | 0.003130 | 2026-06-23 01:48:08 UTC+8 | 0.287040 | 0.265778 | 0.239200 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 267 | 9 | 0.033708 | 0.003154 | 0.001886 | 2026-06-23 01:54:08 UTC+8 | 0.063070 | 0.058399 | 0.052559 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_single_outcome | Austria | buy_pm_yes_sell_hl_yes | 109 | 11 | 0.100917 | 0.003386 | 0.001195 | 2026-06-23 02:17:37 UTC+8 | 0.067717 | 0.062701 | 0.056431 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_single_outcome | Draw | buy_hl_yes_sell_pm_yes | 268 | 2 | 0.007463 | 0.004528 | 0.004528 | 2026-06-23 01:14:56 UTC+8 | 0.090560 | 0.083852 | 0.075467 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_single_outcome | Draw | buy_pm_yes_sell_hl_yes | 91 | 11 | 0.120879 | 0.002457 | 0.002063 | 2026-06-23 02:46:33 UTC+8 | 0.049140 | 0.045500 | 0.040950 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Argentina | buy_hl_Argentina_yes_buy_pm_Draw+Austria_yes | 376 | 6 | 0.015957 | 0.007741 | 0.005706 | 2026-06-23 02:47:06 UTC+8 | 0.154813 | 0.143345 | 0.129011 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Argentina | buy_pm_Argentina_yes_buy_hl_Draw+Austria_yes | 344 | 12 | 0.034884 | 0.007338 | 0.004096 | 2026-06-23 01:15:29 UTC+8 | 0.146760 | 0.135889 | 0.122300 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Austria | buy_hl_Austria_yes_buy_pm_Argentina+Draw_yes | 344 | 0 | 0.000000 |  |  |  |  |  |  | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Austria | buy_pm_Austria_yes_buy_hl_Argentina+Draw_yes | 376 | 2 | 0.005319 | 0.002078 | 0.001933 | 2026-06-23 01:39:58 UTC+8 | 0.041560 | 0.038481 | 0.034633 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Draw | buy_hl_Draw_yes_buy_pm_Argentina+Austria_yes | 344 | 2 | 0.005814 | 0.005055 | 0.003057 | 2026-06-23 01:40:31 UTC+8 | 0.101100 | 0.093611 | 0.084250 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| cross_venue_complement_basket | Draw | buy_pm_Draw_yes_buy_hl_Argentina+Austria_yes | 378 | 3 | 0.007937 | 0.004815 | 0.002916 | 2026-06-23 02:55:52 UTC+8 | 0.096300 | 0.089167 | 0.080250 | paper_monitor_only | Keep monitoring/research; do not enter MVP2 execution scope. |
| single_venue_three_way_sum_diagnostic | HL sum_ask_minus_1 < 0 | hyperliquid | 494 | 4 | 0.008097 | 0.012720 | 0.005453 | 2026-06-23 01:39:58 UTC+8 | 0.254400 | 0.235556 | 0.212000 | diagnostic_only | Single-venue structural signal only; do not use as MVP2 execution trigger. |
| single_venue_three_way_sum_diagnostic | HL sum_bid_minus_1 > 0 | hyperliquid | 473 | 25 | 0.052854 | 0.016750 | 0.002724 | 2026-06-23 01:07:55 UTC+8 | 0.335000 | 0.310185 | 0.279167 | diagnostic_only | Single-venue structural signal only; do not use as MVP2 execution trigger. |
| single_venue_three_way_sum_diagnostic | PM sum_ask_minus_1 < 0 | polymarket | 344 | 1 | 0.002907 | 0.001000 | 0.001000 | 2026-06-23 01:47:03 UTC+8 | 0.020000 | 0.018519 | 0.016667 | diagnostic_only | Single-venue structural signal only; do not use as MVP2 execution trigger. |
| single_venue_three_way_sum_diagnostic | PM sum_bid_minus_1 > 0 | polymarket | 337 | 7 | 0.020772 | 0.060000 | 0.020571 | 2026-06-23 01:38:53 UTC+8 | 1.200000 | 1.111111 | 1.000000 | diagnostic_only | Single-venue structural signal only; do not use as MVP2 execution trigger. |

## Notes

- Uses existing overnight monitor data only; no new scan was started.
- Return math is MVP rough math: `max_positive_net_or_edge * 20 shares`.
- Portfolio denominator uses `$108-$120` for six 20-share slots.
- Positive diagnostic op4 rows are not execution recommendations.

## Source Files

- CSV: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv`
- JSON: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json`
- LOG: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log`
- JSON completed iterations: `494`
- JSON warnings: `346`
