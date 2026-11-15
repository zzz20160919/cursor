# PM-HL MVP2 Four 1v1 Opportunity Comparison

## Conclusions First

- Best execution-layer candidate: **op1 / cross_venue_direct_no_complete_set**.
- Strongest evidence still comes from **Argentina vs Austria**, with op1 max net `0.069472` and 20-share profit `1.389440`.
- op3 has independent supplemental alpha, but it is weaker and more complex because it needs three legs.
- op2 is useful as a reference/mirror but should not be double-counted as independent buy-only execution alpha.
- op4 remains diagnostic only.

## Table 1: Match-level Summary

| match | completed_iterations | warning_count | first_warning_time_utc8 | op1_max_net | op1_positive_rows | op1_positive_pct | op1_best_outcome | op1_best_side | op1_est_profit_20 | op1_portfolio_return_range | op3_max_net | op3_positive_rows | op3_positive_pct | op4_best_condition | short_conclusion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina vs Austria | 494 | 346 | 2026-06-23 04:20:53 UTC+8 | 0.069472 | 60 | 0.053428 | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 1.389440 | 1.158% - 1.287% | 0.007741 | 25 | 0.011563 | PM sum_bid_minus_1 > 0 | strong op1 spike; best execution-layer evidence |
| Portugal vs Uzbekistan | 265 | 335 | 2026-06-24 03:09:03 UTC+8 | 0.007822 | 44 | 0.056921 | Portugal | buy_hl_Portugal_yes_buy_pm_Portugal_no | 0.156449 | 0.130% - 0.145% | 0.005960 | 6 | 0.004640 | hyperliquid sum_bid_minus_1 > 0 | positive but modest op1; useful validation sample |
| Switzerland vs Canada | 600 | 0 |  | 0.060091 | 39 | 0.027027 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Switzerland_no | 1.201830 | 1.002% - 1.113% | 0.054841 | 21 | 0.007589 | hyperliquid sum_bid_minus_1 > 0 | strong op1 spike; best execution-layer evidence |
| Bosnia and Herzegovina vs Qatar | 600 | 0 |  | 0.012696 | 24 | 0.016393 | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 0.253926 | 0.212% - 0.235% | 0.020241 | 45 | 0.016077 | polymarket sum_ask_minus_1 < 0 | positive but modest op1; useful validation sample |

## Table 2: op-group Comparison

| match | op_group | total_rows | positive_rows | positive_pct | max_net_or_edge | mean_positive_net_or_edge | best_outcome_or_condition | best_side | est_profit_20 | portfolio_return_low_pct | portfolio_return_high_pct | execution_suitability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina vs Austria | cross_venue_direct_no_complete_set | 1123 | 60 | 0.053428 | 0.069472 | 0.003504 | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 1.389440 | 1.286519 | 1.157867 | include_v1_execution |
| Argentina vs Austria | cross_venue_single_outcome | 1123 | 60 | 0.053428 | 0.049268 | 0.003167 | Argentina | buy_hl_yes_sell_pm_yes | 0.985360 | 0.912370 | 0.821133 | monitor_only_reference |
| Argentina vs Austria | cross_venue_complement_basket | 2162 | 25 | 0.011563 | 0.007741 | 0.004085 | Argentina | buy_hl_Argentina_yes_buy_pm_Draw+Austria_yes | 0.154813 | 0.143345 | 0.129011 | future_research |
| Argentina vs Austria | single_venue_three_way_sum_diagnostic | 1648 | 37 | 0.022451 | 0.060000 | 0.006349 | PM sum_bid_minus_1 > 0 | polymarket | 1.200000 | 1.111111 | 1.000000 | diagnostic_only |
| Portugal vs Uzbekistan | cross_venue_direct_no_complete_set | 773 | 44 | 0.056921 | 0.007822 | 0.001079 | Portugal | buy_hl_Portugal_yes_buy_pm_Portugal_no | 0.156449 | 0.144860 | 0.130374 | include_v1_execution |
| Portugal vs Uzbekistan | cross_venue_single_outcome | 773 | 46 | 0.059508 | 0.007822 | 0.001124 | Portugal | buy_hl_yes_sell_pm_yes | 0.156449 | 0.144860 | 0.130374 | monitor_only_reference |
| Portugal vs Uzbekistan | cross_venue_complement_basket | 1293 | 6 | 0.004640 | 0.005960 | 0.002931 | Draw | buy_hl_Draw_yes_buy_pm_Portugal+Uzbekistan_yes | 0.119209 | 0.110378 | 0.099341 | future_research |
| Portugal vs Uzbekistan | single_venue_three_way_sum_diagnostic | 792 | 108 | 0.136364 | 0.007050 | 0.001047 | hyperliquid sum_bid_minus_1 > 0 | hyperliquid | 0.141000 | 0.130556 | 0.117500 | diagnostic_only |
| Switzerland vs Canada | cross_venue_direct_no_complete_set | 1443 | 39 | 0.027027 | 0.060091 | 0.014079 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Switzerland_no | 1.201830 | 1.112805 | 1.001525 | include_v1_execution |
| Switzerland vs Canada | cross_venue_single_outcome | 1443 | 39 | 0.027027 | 0.060091 | 0.014079 | Switzerland | buy_pm_yes_sell_hl_yes | 1.201830 | 1.112805 | 1.001525 | monitor_only_reference |
| Switzerland vs Canada | cross_venue_complement_basket | 2767 | 21 | 0.007589 | 0.054841 | 0.022502 | Switzerland | buy_pm_Switzerland_yes_buy_hl_Draw+Canada_yes | 1.096830 | 1.015583 | 0.914025 | future_research |
| Switzerland vs Canada | single_venue_three_way_sum_diagnostic | 1980 | 258 | 0.130303 | 0.020150 | 0.003862 | hyperliquid sum_bid_minus_1 > 0 | hyperliquid | 0.403000 | 0.373148 | 0.335833 | diagnostic_only |
| Bosnia and Herzegovina vs Qatar | cross_venue_direct_no_complete_set | 1464 | 24 | 0.016393 | 0.012696 | 0.002730 | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 0.253926 | 0.235116 | 0.211605 | include_v1_execution |
| Bosnia and Herzegovina vs Qatar | cross_venue_single_outcome | 1464 | 24 | 0.016393 | 0.012341 | 0.002443 | Qatar | buy_hl_yes_sell_pm_yes | 0.246817 | 0.228534 | 0.205680 | monitor_only_reference |
| Bosnia and Herzegovina vs Qatar | cross_venue_complement_basket | 2799 | 45 | 0.016077 | 0.020241 | 0.003784 | Bosnia-Herzegovina | buy_hl_Bosnia-Herzegovina_yes_buy_pm_Draw+Qatar_yes | 0.404810 | 0.374824 | 0.337342 | future_research |
| Bosnia and Herzegovina vs Qatar | single_venue_three_way_sum_diagnostic | 2055 | 149 | 0.072506 | 0.024000 | 0.002439 | polymarket sum_ask_minus_1 < 0 | polymarket | 0.480000 | 0.444444 | 0.400000 | diagnostic_only |

## Table 3: Execution Decision Table

| opportunity | buy_only_executable | independent_alpha | observed_strength | frequency | complexity | execution_layer_decision | reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_direct_no_complete_set | yes | yes | moderate: strong Argentina spike plus modest positives in other matches; max=0.069472 | seen in all 4 matches, but concentrated in spikes; positive_rows=167/4803 | medium | include_v1_execution | Only buy-only candidate family; strongest risk/reward evidence. |
| cross_venue_single_outcome | no | no | mirrors op1 price discrepancies; max=0.060091 | frequent but not independent; positive_rows=169/4803 | medium/high due to sell/inventory assumptions | monitor_only | Do not double count op1-like edge. |
| cross_venue_complement_basket | yes but 3-leg | yes | small positives, weaker than op1; max=0.054841 | sporadic; positive_rows=97/9021 | high, three-leg execution | future_research | Independent alpha exists but not v1 execution. |
| single_venue_three_way_sum_diagnostic | no | no | diagnostic signals present; max=0.060000 | varies by venue; positive_rows=552/6475 | not an execution strategy | diagnostic_only | Useful sanity/future research only. |

## Table 4: Final Ranking

| rank | opportunity | evidence_from_4_matches | estimated_value | implementation_cost | decision |
| --- | --- | --- | --- | --- | --- |
| 1 | cross_venue_direct_no_complete_set | Best max edge and only scoped buy-only candidate; Argentina spike plus smaller positives elsewhere. | highest MVP value; best observed 20-share profit about $1.39 | medium | include_v1_execution |
| 2 | cross_venue_complement_basket | Independent positives exist, but max and frequency weaker; three-leg execution. | supplemental alpha | high | future_research |
| 3 | cross_venue_single_outcome | Useful reference but overlaps op1 economics and requires sell/inventory assumptions. | monitoring signal | medium/high | monitor_only |
| 4 | single_venue_three_way_sum_diagnostic | Shows structure changes and diagnostic opportunities, not MVP2 execution scope. | diagnostic/future MVP3 | n/a | diagnostic_only |

## Notes

- Returns are MVP rough calculations: `max_net_or_edge * 20 shares`.
- Portfolio denominator is `$108-$120` for six 20-share slots.
- Positive rows are monitoring observations, not independent executable trades.
- No monitor was started by this review.
