# PM-HL MVP2 Portugal vs Uzbekistan Core Profit Review

## Conclusions First

- Scan is reviewable: `265` successful iterations, `335` warnings.
- Best op1 row: `Portugal` / `buy_hl_Portugal_yes_buy_pm_Portugal_no` with max net `0.007822` and 20-share profit `0.156449`.
- Best op3 row: `Draw` / `buy_hl_Draw_yes_buy_pm_Portugal+Uzbekistan_yes` with max net `0.005960`; keep as paper alpha only.
- Compared with Argentina vs Austria, this match is weaker: no Argentina-style large op1 spike; current max op1 profit is only about `$0.156449` per 20-share slot.

## 1. Scan Completeness

| planned_iterations | completed_iterations | warnings | first_warning_time_utc8 | data_reviewable |
| --- | --- | --- | --- | --- |
| 600 | 265 | 335 | 2026-06-24 03:09:03 UTC+8 | True |

## 2. op1: direct No-token complete-set

| op_group | outcome_or_condition | side | total_rows | positive_rows | positive_pct | max_net | mean_positive_net | best_timestamp_utc8 | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct | mvp_decision | comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_direct_no_complete_set | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 69 | 4 | 0.057971 | 0.002265 | 0.000750 | 2026-06-24 01:29:42 UTC+8 | 0.045290 | 0.041936 | 0.037742 | continue_op1_execution_mvp_research | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |
| cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 191 | 0 | 0.000000 |  |  |  |  |  |  | monitor_only | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |
| cross_venue_direct_no_complete_set | Portugal | buy_hl_Portugal_yes_buy_pm_Portugal_no | 131 | 12 | 0.091603 | 0.007822 | 0.001688 | 2026-06-24 01:30:47 UTC+8 | 0.156449 | 0.144860 | 0.130374 | continue_op1_execution_mvp_research | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |
| cross_venue_direct_no_complete_set | Portugal | buy_pm_Portugal_yes_buy_hl_Portugal_no | 117 | 12 | 0.102564 | 0.003089 | 0.001073 | 2026-06-24 01:10:44 UTC+8 | 0.061777 | 0.057201 | 0.051481 | continue_op1_execution_mvp_research | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |
| cross_venue_direct_no_complete_set | Uzbekistan | buy_hl_Uzbekistan_yes_buy_pm_Uzbekistan_no | 54 | 1 | 0.018519 | 0.000162 | 0.000162 | 2026-06-24 01:30:15 UTC+8 | 0.003249 | 0.003008 | 0.002707 | continue_op1_execution_mvp_research | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |
| cross_venue_direct_no_complete_set | Uzbekistan | buy_pm_Uzbekistan_yes_buy_hl_Uzbekistan_no | 211 | 15 | 0.071090 | 0.001570 | 0.000746 | 2026-06-24 01:17:16 UTC+8 | 0.031401 | 0.029075 | 0.026167 | continue_op1_execution_mvp_research | op1 is the only MVP2 execution candidate family; requires execution/VWAP validation. |

## 3. op3: complement basket

| op_group | outcome_or_condition | side | total_rows | positive_rows | positive_pct | max_net | mean_positive_net | best_timestamp_utc8 | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct | mvp_decision | comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_complement_basket | Draw | buy_hl_Draw_yes_buy_pm_Portugal+Uzbekistan_yes | 183 | 2 | 0.010929 | 0.005960 | 0.004321 | 2026-06-24 01:06:54 UTC+8 | 0.119209 | 0.110378 | 0.099341 | paper_alpha_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |
| cross_venue_complement_basket | Draw | buy_pm_Draw_yes_buy_hl_Portugal+Uzbekistan_yes | 248 | 0 | 0.000000 |  |  |  |  |  |  | monitor_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |
| cross_venue_complement_basket | Portugal | buy_hl_Portugal_yes_buy_pm_Draw+Uzbekistan_yes | 248 | 1 | 0.004032 | 0.000732 | 0.000732 | 2026-06-24 01:17:16 UTC+8 | 0.014639 | 0.013555 | 0.012199 | paper_alpha_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |
| cross_venue_complement_basket | Portugal | buy_pm_Portugal_yes_buy_hl_Draw+Uzbekistan_yes | 183 | 0 | 0.000000 |  |  |  |  |  |  | monitor_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |
| cross_venue_complement_basket | Uzbekistan | buy_hl_Uzbekistan_yes_buy_pm_Portugal+Draw_yes | 183 | 0 | 0.000000 |  |  |  |  |  |  | monitor_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |
| cross_venue_complement_basket | Uzbekistan | buy_pm_Uzbekistan_yes_buy_hl_Portugal+Draw_yes | 248 | 3 | 0.012097 | 0.005562 | 0.002738 | 2026-06-24 01:06:54 UTC+8 | 0.111249 | 0.103008 | 0.092707 | paper_alpha_only | op3 can be independent supplemental alpha, but not in MVP2 execution scope. |

## 4. op2 Reference

Best op2 row: `Portugal` / `buy_hl_yes_sell_pm_yes` with max net `0.007822`. op2 remains reference-only and is not counted as independent buy-only execution alpha.

| op_group | outcome_or_condition | side | total_rows | positive_rows | positive_pct | max_net | mean_positive_net | best_timestamp_utc8 | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct | mvp_decision | comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_single_outcome | Draw | buy_hl_yes_sell_pm_yes | 69 | 4 | 0.057971 | 0.004857 | 0.001892 | 2026-06-24 01:29:10 UTC+8 | 0.097140 | 0.089944 | 0.080950 | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |
| cross_venue_single_outcome | Draw | buy_pm_yes_sell_hl_yes | 191 | 0 | 0.000000 |  |  |  |  |  |  | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |
| cross_venue_single_outcome | Portugal | buy_hl_yes_sell_pm_yes | 131 | 14 | 0.106870 | 0.007822 | 0.001422 | 2026-06-24 01:30:47 UTC+8 | 0.156449 | 0.144860 | 0.130374 | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |
| cross_venue_single_outcome | Portugal | buy_pm_yes_sell_hl_yes | 117 | 12 | 0.102564 | 0.003089 | 0.001073 | 2026-06-24 01:10:44 UTC+8 | 0.061777 | 0.057201 | 0.051481 | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |
| cross_venue_single_outcome | Uzbekistan | buy_hl_yes_sell_pm_yes | 54 | 1 | 0.018519 | 0.000162 | 0.000162 | 2026-06-24 01:30:15 UTC+8 | 0.003249 | 0.003008 | 0.002707 | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |
| cross_venue_single_outcome | Uzbekistan | buy_pm_yes_sell_hl_yes | 211 | 15 | 0.071090 | 0.001570 | 0.000746 | 2026-06-24 01:17:16 UTC+8 | 0.031401 | 0.029075 | 0.026167 | reference_only | op2 is a same-outcome cross-venue mirror/reference, not independent buy-only execution scope. |

## 5. op4 Diagnostics

| op_group | outcome_or_condition | side | total_rows | positive_rows | positive_pct | max_net | mean_positive_net | best_timestamp_utc8 | est_profit_20_shares | portfolio_return_low_pct | portfolio_return_high_pct | mvp_decision | comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single_venue_three_way_sum_diagnostic | PM sum_ask_minus_1 < 0 | PM | 183 | 1 | 0.005464 | 0.001000 | 0.001000 | 2026-06-24 01:06:54 UTC+8 | 0.020000 | 0.018519 | 0.016667 | diagnostic_only | op4 is single-venue structure diagnostic only, not a trade trigger. |
| single_venue_three_way_sum_diagnostic | PM sum_bid_minus_1 > 0 | PM | 101 | 11 | 0.108911 | 0.003000 | 0.001182 | 2026-06-24 01:14:01 UTC+8 | 0.060000 | 0.055556 | 0.050000 | diagnostic_only | op4 is single-venue structure diagnostic only, not a trade trigger. |
| single_venue_three_way_sum_diagnostic | HL sum_ask_minus_1 < 0 | HL | 248 | 0 | 0.000000 |  |  |  |  |  |  | diagnostic_only | op4 is single-venue structure diagnostic only, not a trade trigger. |
| single_venue_three_way_sum_diagnostic | HL sum_bid_minus_1 > 0 | HL | 260 | 96 | 0.369231 | 0.007050 | 0.001033 | 2026-06-24 00:51:13 UTC+8 | 0.141000 | 0.130556 | 0.117500 | diagnostic_only | op4 is single-venue structure diagnostic only, not a trade trigger. |

## Decision

This match supports continuing to monitor op1, but it is weaker than Argentina vs Austria for execution MVP evidence. It does not add a strong new case for immediate execution beyond the prior Argentina result. If execution work continues, use Argentina-style stronger op1 windows as the motivating case and keep Portugal vs Uzbekistan as a lower-edge validation sample.

## Source Files

- CSV: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv`
- JSON: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.json`
- LOG: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_mvp2_overnight_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.log`
