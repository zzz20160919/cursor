# PM-HL MVP2 Final Report

## 1. Executive Summary

MVP2 scanner research can close. Across four 1v1 Moneyline matches, the only opportunity family that should move into execution layer v1 is **op1: cross_venue_direct_no_complete_set**.

Strongest match evidence: **Argentina vs Austria**, op1 max net `0.069472`, estimated 20-share profit `1.389440`.

## 2. Four-match Evidence

| match | completed_iterations | warning_count | first_warning_time_utc8 | op1_max_net | op1_positive_rows | op1_positive_windows | op1_best_outcome | op1_best_side | op1_best_profit_20_shares | op1_portfolio_return_range | op3_max_net | op3_positive_rows | op3_positive_windows | op3_best_outcome | op3_best_side | op4_best_condition | final_conclusion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina vs Austria | 494 | 346 | 2026-06-23 04:20:53 UTC+8 | 0.069472 | 60 | 29 | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 1.389440 | 1.158% - 1.287% | 0.007741 | 25 | 17 | Argentina | buy_hl_Argentina_yes_buy_pm_Draw+Austria_yes | PM sum_bid_minus_1 > 0 | strong op1 evidence |
| Portugal vs Uzbekistan | 265 | 335 | 2026-06-24 03:09:03 UTC+8 | 0.007822 | 44 | 19 | Portugal | buy_hl_Portugal_yes_buy_pm_Portugal_no | 0.156449 | 0.130% - 0.145% | 0.005960 | 6 | 6 | Draw | buy_hl_Draw_yes_buy_pm_Portugal+Uzbekistan_yes | hyperliquid sum_bid_minus_1 > 0 | modest op1 validation |
| Switzerland vs Canada | 600 | 0 |  | 0.060091 | 39 | 13 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Switzerland_no | 1.201830 | 1.002% - 1.113% | 0.054841 | 21 | 9 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Draw+Canada_yes | hyperliquid sum_bid_minus_1 > 0 | strong op1 evidence |
| Bosnia and Herzegovina vs Qatar | 600 | 0 |  | 0.012696 | 24 | 17 | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 0.253926 | 0.212% - 0.235% | 0.020241 | 45 | 28 | Bosnia-Herzegovina | buy_hl_Bosnia-Herzegovina_yes_buy_pm_Draw+Qatar_yes | polymarket sum_ask_minus_1 < 0 | op3 stronger but future research |

## 3. Positive Window Analysis

Positive window rule: consecutive positive rows are grouped if gaps are <= 90 seconds.

| match | op_group | outcome_or_condition | side | window_start_utc8 | window_end_utc8 | duration_seconds | positive_rows_in_window | max_net_or_edge | mean_net_or_edge | best_timestamp_utc8 | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 00:13:48 UTC+8 | 2026-06-23 00:13:48 UTC+8 | 0.000000 | 1 | 0.002083 | 0.002083 | 2026-06-23 00:13:48 UTC+8 | 0.041660 | 0.038574 | 0.034717 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 00:28:57 UTC+8 | 2026-06-23 00:28:57 UTC+8 | 0.000000 | 1 | 0.000033 | 0.000033 | 2026-06-23 00:28:57 UTC+8 | 0.000660 | 0.000611 | 0.000550 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 01:54:08 UTC+8 | 2026-06-23 01:55:46 UTC+8 | 98.000000 | 4 | 0.003154 | 0.003154 | 2026-06-23 01:54:08 UTC+8 | 0.063070 | 0.058399 | 0.052559 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 02:10:31 UTC+8 | 2026-06-23 02:10:31 UTC+8 | 0.000000 | 1 | 0.001071 | 0.001071 | 2026-06-23 02:10:31 UTC+8 | 0.021414 | 0.019828 | 0.017845 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 02:19:16 UTC+8 | 2026-06-23 02:19:16 UTC+8 | 0.000000 | 1 | 0.000099 | 0.000099 | 2026-06-23 02:19:16 UTC+8 | 0.001977 | 0.001830 | 0.001647 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 2026-06-23 02:25:15 UTC+8 | 2026-06-23 02:25:15 UTC+8 | 0.000000 | 1 | 0.001071 | 0.001071 | 2026-06-23 02:25:15 UTC+8 | 0.021414 | 0.019828 | 0.017845 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:10:37 UTC+8 | 2026-06-23 01:12:47 UTC+8 | 130.000000 | 4 | 0.013087 | 0.004361 | 2026-06-23 01:10:37 UTC+8 | 0.261740 | 0.242352 | 0.218117 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:14:24 UTC+8 | 2026-06-23 01:14:24 UTC+8 | 0.000000 | 1 | 0.003175 | 0.003175 | 2026-06-23 01:14:24 UTC+8 | 0.063500 | 0.058796 | 0.052917 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:16:01 UTC+8 | 2026-06-23 01:16:01 UTC+8 | 0.000000 | 1 | 0.000587 | 0.000587 | 2026-06-23 01:16:01 UTC+8 | 0.011740 | 0.010870 | 0.009783 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:29:04 UTC+8 | 2026-06-23 01:29:04 UTC+8 | 0.000000 | 1 | 0.001803 | 0.001803 | 2026-06-23 01:29:04 UTC+8 | 0.036060 | 0.033389 | 0.030050 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:33:58 UTC+8 | 2026-06-23 01:36:42 UTC+8 | 164.000000 | 4 | 0.002863 | 0.001372 | 2026-06-23 01:33:58 UTC+8 | 0.057260 | 0.053019 | 0.047717 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:42:09 UTC+8 | 2026-06-23 01:42:42 UTC+8 | 33.000000 | 2 | 0.001018 | 0.001018 | 2026-06-23 01:42:09 UTC+8 | 0.020360 | 0.018852 | 0.016967 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 01:44:20 UTC+8 | 2026-06-23 01:48:08 UTC+8 | 228.000000 | 5 | 0.014352 | 0.004531 | 2026-06-23 01:48:08 UTC+8 | 0.287040 | 0.265778 | 0.239200 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 02:51:29 UTC+8 | 2026-06-23 02:51:29 UTC+8 | 0.000000 | 1 | 0.003063 | 0.003063 | 2026-06-23 02:51:29 UTC+8 | 0.061260 | 0.056722 | 0.051050 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 2026-06-23 02:56:59 UTC+8 | 2026-06-23 02:56:59 UTC+8 | 0.000000 | 1 | 0.006345 | 0.006345 | 2026-06-23 02:56:59 UTC+8 | 0.126900 | 0.117500 | 0.105750 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 2026-06-23 01:14:56 UTC+8 | 2026-06-23 01:15:29 UTC+8 | 33.000000 | 2 | 0.004528 | 0.004528 | 2026-06-23 01:14:56 UTC+8 | 0.090560 | 0.083852 | 0.075467 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 2026-06-23 01:38:53 UTC+8 | 2026-06-23 01:38:53 UTC+8 | 0.000000 | 1 | 0.069472 | 0.069472 | 2026-06-23 01:38:53 UTC+8 | 1.389440 | 1.286519 | 1.157867 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 2026-06-23 02:49:50 UTC+8 | 2026-06-23 02:49:50 UTC+8 | 0.000000 | 1 | 0.001322 | 0.001322 | 2026-06-23 02:49:50 UTC+8 | 0.026440 | 0.024481 | 0.022033 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 2026-06-23 02:52:03 UTC+8 | 2026-06-23 02:52:03 UTC+8 | 0.000000 | 1 | 0.000763 | 0.000763 | 2026-06-23 02:52:03 UTC+8 | 0.015260 | 0.014130 | 0.012717 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 2026-06-23 02:54:47 UTC+8 | 2026-06-23 02:55:52 UTC+8 | 65.000000 | 3 | 0.006015 | 0.004695 | 2026-06-23 02:55:52 UTC+8 | 0.120300 | 0.111389 | 0.100250 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 2026-06-23 03:07:22 UTC+8 | 2026-06-23 03:07:22 UTC+8 | 0.000000 | 1 | 0.000130 | 0.000130 | 2026-06-23 03:07:22 UTC+8 | 0.002601 | 0.002408 | 0.002167 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_pm_Austria_yes_buy_hl_Austria_no | 2026-06-23 02:16:31 UTC+8 | 2026-06-23 02:17:37 UTC+8 | 66.000000 | 3 | 0.003386 | 0.001329 | 2026-06-23 02:17:37 UTC+8 | 0.067717 | 0.062701 | 0.056431 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_pm_Austria_yes_buy_hl_Austria_no | 2026-06-23 02:30:43 UTC+8 | 2026-06-23 02:34:32 UTC+8 | 229.000000 | 7 | 0.001586 | 0.001283 | 2026-06-23 02:33:26 UTC+8 | 0.031717 | 0.029368 | 0.026431 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Austria | buy_pm_Austria_yes_buy_hl_Austria_no | 2026-06-23 02:54:47 UTC+8 | 2026-06-23 02:54:47 UTC+8 | 0.000000 | 1 | 0.000170 | 0.000170 | 2026-06-23 02:54:47 UTC+8 | 0.003401 | 0.003149 | 0.002834 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 2026-06-23 02:26:53 UTC+8 | 2026-06-23 02:26:53 UTC+8 | 0.000000 | 1 | 0.001915 | 0.001915 | 2026-06-23 02:26:53 UTC+8 | 0.038300 | 0.035463 | 0.031917 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 2026-06-23 02:29:04 UTC+8 | 2026-06-23 02:29:04 UTC+8 | 0.000000 | 1 | 0.001915 | 0.001915 | 2026-06-23 02:29:04 UTC+8 | 0.038300 | 0.035463 | 0.031917 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 2026-06-23 02:39:59 UTC+8 | 2026-06-23 02:40:32 UTC+8 | 33.000000 | 2 | 0.001915 | 0.001915 | 2026-06-23 02:39:59 UTC+8 | 0.038300 | 0.035463 | 0.031917 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 2026-06-23 02:46:33 UTC+8 | 2026-06-23 02:48:45 UTC+8 | 132.000000 | 4 | 0.002457 | 0.002457 | 2026-06-23 02:46:33 UTC+8 | 0.049140 | 0.045500 | 0.040950 |
| Argentina vs Austria | cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 2026-06-23 02:52:03 UTC+8 | 2026-06-23 02:53:41 UTC+8 | 98.000000 | 3 | 0.002400 | 0.001734 | 2026-06-23 02:52:03 UTC+8 | 0.048000 | 0.044444 | 0.040000 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 00:13:48 UTC+8 | 2026-06-23 00:13:48 UTC+8 | 0.000000 | 1 | 0.002083 | 0.002083 | 2026-06-23 00:13:48 UTC+8 | 0.041660 | 0.038574 | 0.034717 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 00:28:57 UTC+8 | 2026-06-23 00:28:57 UTC+8 | 0.000000 | 1 | 0.000033 | 0.000033 | 2026-06-23 00:28:57 UTC+8 | 0.000660 | 0.000611 | 0.000550 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 01:54:08 UTC+8 | 2026-06-23 01:55:46 UTC+8 | 98.000000 | 4 | 0.003154 | 0.003154 | 2026-06-23 01:54:08 UTC+8 | 0.063070 | 0.058399 | 0.052559 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 02:10:31 UTC+8 | 2026-06-23 02:10:31 UTC+8 | 0.000000 | 1 | 0.001071 | 0.001071 | 2026-06-23 02:10:31 UTC+8 | 0.021414 | 0.019828 | 0.017845 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 02:19:16 UTC+8 | 2026-06-23 02:19:16 UTC+8 | 0.000000 | 1 | 0.000099 | 0.000099 | 2026-06-23 02:19:16 UTC+8 | 0.001977 | 0.001830 | 0.001647 |
| Argentina vs Austria | cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 2026-06-23 02:25:15 UTC+8 | 2026-06-23 02:25:15 UTC+8 | 0.000000 | 1 | 0.001071 | 0.001071 | 2026-06-23 02:25:15 UTC+8 | 0.021414 | 0.019828 | 0.017845 |
| Argentina vs Austria | cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 2026-06-23 01:10:37 UTC+8 | 2026-06-23 01:12:47 UTC+8 | 130.000000 | 4 | 0.013087 | 0.004361 | 2026-06-23 01:10:37 UTC+8 | 0.261740 | 0.242352 | 0.218117 |
| Argentina vs Austria | cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 2026-06-23 01:14:24 UTC+8 | 2026-06-23 01:14:24 UTC+8 | 0.000000 | 1 | 0.003175 | 0.003175 | 2026-06-23 01:14:24 UTC+8 | 0.063500 | 0.058796 | 0.052917 |
| Argentina vs Austria | cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 2026-06-23 01:16:01 UTC+8 | 2026-06-23 01:16:01 UTC+8 | 0.000000 | 1 | 0.000587 | 0.000587 | 2026-06-23 01:16:01 UTC+8 | 0.011740 | 0.010870 | 0.009783 |
| Argentina vs Austria | cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 2026-06-23 01:29:04 UTC+8 | 2026-06-23 01:29:04 UTC+8 | 0.000000 | 1 | 0.001803 | 0.001803 | 2026-06-23 01:29:04 UTC+8 | 0.036060 | 0.033389 | 0.030050 |
| Argentina vs Austria | cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 2026-06-23 01:33:58 UTC+8 | 2026-06-23 01:36:42 UTC+8 | 164.000000 | 4 | 0.002863 | 0.001372 | 2026-06-23 01:33:58 UTC+8 | 0.057260 | 0.053019 | 0.047717 |

Full window detail is in `outputs/pm_hl_mvp2_scanner/mvp2_positive_windows_detail.csv`.

## 4. Opportunity Decision

| opportunity | buy_only_executable | independent_alpha | observed_strength | positive_window_evidence | implementation_complexity | execution_layer_decision | reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| op1 cross_venue_direct_no_complete_set | yes | yes | Strongest evidence across four matches; best 20-share profit about $1.39 | 78 windows; best=0.069472 in Argentina vs Austria | medium | include_v1_execution | Only scoped two-leg buy-only candidate; positive windows across all four matches. |
| op2 cross_venue_single_outcome | no | no | Overlaps op1 pricing evidence | 77 windows; best=0.060091 in Switzerland vs Canada | medium/high | monitor_only | Reference signal, not independent buy-only execution. |
| op3 cross_venue_complement_basket | yes but three-leg | yes | Independent positives exist, notably Switzerland and Bosnia/Qatar | 60 windows; best=0.054841 in Switzerland vs Canada | high | future_research | Three-leg execution is too complex for v1. |
| op4 single_venue_three_way_sum_diagnostic | no | no | Useful structure/quality signal only | 83 windows; best=0.060000 in Argentina vs Austria | n/a | diagnostic_only | Not a PM-HL cross-venue execution candidate. |

## 5. Expected MVP Return Rough Range

Returns are MVP rough estimates: `max_net_or_edge * 20 shares`, portfolio denominator `$108-$120`.

| match | op_group | total_rows | positive_rows | positive_pct | positive_windows | max_net_or_edge | mean_positive_net_or_edge | best_outcome_or_condition | best_side | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct | execution_decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina vs Austria | cross_venue_direct_no_complete_set | 1123 | 60 | 0.053428 | 29 | 0.069472 | 0.003504 | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 1.389440 | 1.286519 | 1.157867 | include_v1_execution |
| Argentina vs Austria | cross_venue_single_outcome | 1123 | 60 | 0.053428 | 29 | 0.049268 | 0.003167 | Argentina | buy_hl_yes_sell_pm_yes | 0.985360 | 0.912370 | 0.821133 | monitor_only |
| Argentina vs Austria | cross_venue_complement_basket | 2162 | 25 | 0.011563 | 17 | 0.007741 | 0.004085 | Argentina | buy_hl_Argentina_yes_buy_pm_Draw+Austria_yes | 0.154813 | 0.143345 | 0.129011 | future_research |
| Argentina vs Austria | single_venue_three_way_sum_diagnostic | 1648 | 37 | 0.022451 | 16 | 0.060000 | 0.006349 | PM sum_bid_minus_1 > 0 | polymarket | 1.200000 | 1.111111 | 1.000000 | diagnostic_only |
| Portugal vs Uzbekistan | cross_venue_direct_no_complete_set | 773 | 44 | 0.056921 | 19 | 0.007822 | 0.001079 | Portugal | buy_hl_Portugal_yes_buy_pm_Portugal_no | 0.156449 | 0.144860 | 0.130374 | include_v1_execution |
| Portugal vs Uzbekistan | cross_venue_single_outcome | 773 | 46 | 0.059508 | 18 | 0.007822 | 0.001124 | Portugal | buy_hl_yes_sell_pm_yes | 0.156449 | 0.144860 | 0.130374 | monitor_only |
| Portugal vs Uzbekistan | cross_venue_complement_basket | 1293 | 6 | 0.004640 | 6 | 0.005960 | 0.002931 | Draw | buy_hl_Draw_yes_buy_pm_Portugal+Uzbekistan_yes | 0.119209 | 0.110378 | 0.099341 | future_research |
| Portugal vs Uzbekistan | single_venue_three_way_sum_diagnostic | 792 | 108 | 0.136364 | 14 | 0.007050 | 0.001047 | hyperliquid sum_bid_minus_1 > 0 | hyperliquid | 0.141000 | 0.130556 | 0.117500 | diagnostic_only |
| Switzerland vs Canada | cross_venue_direct_no_complete_set | 1443 | 39 | 0.027027 | 13 | 0.060091 | 0.014079 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Switzerland_no | 1.201830 | 1.112805 | 1.001525 | include_v1_execution |
| Switzerland vs Canada | cross_venue_single_outcome | 1443 | 39 | 0.027027 | 13 | 0.060091 | 0.014079 | Switzerland | buy_pm_yes_sell_hl_yes | 1.201830 | 1.112805 | 1.001525 | monitor_only |
| Switzerland vs Canada | cross_venue_complement_basket | 2767 | 21 | 0.007589 | 9 | 0.054841 | 0.022502 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Draw+Canada_yes | 1.096830 | 1.015583 | 0.914025 | future_research |
| Switzerland vs Canada | single_venue_three_way_sum_diagnostic | 1980 | 258 | 0.130303 | 23 | 0.020150 | 0.003862 | hyperliquid sum_bid_minus_1 > 0 | hyperliquid | 0.403000 | 0.373148 | 0.335833 | diagnostic_only |
| Bosnia and Herzegovina vs Qatar | cross_venue_direct_no_complete_set | 1464 | 24 | 0.016393 | 17 | 0.012696 | 0.002730 | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 0.253926 | 0.235116 | 0.211605 | include_v1_execution |
| Bosnia and Herzegovina vs Qatar | cross_venue_single_outcome | 1464 | 24 | 0.016393 | 17 | 0.012341 | 0.002443 | Qatar | buy_hl_yes_sell_pm_yes | 0.246817 | 0.228534 | 0.205680 | monitor_only |
| Bosnia and Herzegovina vs Qatar | cross_venue_complement_basket | 2799 | 45 | 0.016077 | 28 | 0.020241 | 0.003784 | Bosnia-Herzegovina | buy_hl_Bosnia-Herzegovina_yes_buy_pm_Draw+Qatar_yes | 0.404810 | 0.374824 | 0.337342 | future_research |
| Bosnia and Herzegovina vs Qatar | single_venue_three_way_sum_diagnostic | 2055 | 149 | 0.072506 | 30 | 0.024000 | 0.002439 | polymarket sum_ask_minus_1 < 0 | polymarket | 0.480000 | 0.444444 | 0.400000 | diagnostic_only |

## 6. Main Risks

- Single-leg exposure if only one venue fills.
- Stale quote between signal and execution.
- Rule/revalidation mismatch between PM and HL.
- Top-of-book monitor rows are not VWAP/fill-verified.
- Fee/slippage can erase small gross edges.

## 7. Execution Layer Handoff

Execution layer v1 should take only op1 signals, paper first, then tiny live. It must revalidate both legs, require manual approval, record fills, compute PnL, and include kill switch plus no retry/chase.

## 8. MVP3 Backlog

- op3 complement basket execution research.
- op4 single-venue structural diagnostics.
- deeper book/VWAP simulation.
- multi-match portfolio allocator.
