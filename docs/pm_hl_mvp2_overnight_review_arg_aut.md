# PM-HL MVP2 Overnight Review: Argentina vs Austria

## Conclusions First

- Warnings began at **2026-06-23 04:20:53 UTC+8**, iteration **495**, about **58.9 minutes** after the referenced final time of **2026-06-23 03:22:00 UTC+8**.
- The warnings are continuous after they start, supporting the explanation that post-final HL lifecycle/question discovery stopped returning the expected sample structure.
- For op1, **Argentina** came closest to zero by max net and had the strongest positive spike; **Austria** was the most frequent top1, but only by a small margin over Argentina.
- op1 had positive net rows before final: `{'Argentina': 27, 'Draw': 13, 'Austria': 20}`. These are monitoring rows, not execution records.
- PM ask stayed above 1 and was relatively steady before final, but PM post-final `sum_ask` became unavailable in the flat CSV. HL ask was somewhat farther above 1 before final, then moved closer to 1 post-final.

## Table 1: Warning Summary

| total_iterations | completed_iterations | total_warnings | first_warning_iteration | first_warning_timestamp_utc8 | last_good_iteration | warning_ratio | match_final_time_utc8 | warning_vs_final_time_delta_minutes | preliminary_interpretation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 840 | 494 | 346 | 495 | 2026-06-23 04:20:53 UTC+8 | 494 | 0.411905 | 2026-06-23 03:22:00 UTC+8 | 58.883333 | Warnings start after the reported final time and then continue, which supports a post-final HL lifecycle/question discovery failure explanation. |

## Table 2: op1 by Outcome Summary

Near-miss threshold: `net > -0.002`.

| outcome | max_net | max_net_timestamp_utc8 | min_net | mean_net | median_net | max_gross | mean_fee | max_depth | near_miss_count | positive_net_count | top1_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina | 0.069472 | 2026-06-23 01:38:53 UTC+8 | -0.031468 | -0.007674 | -0.006488 | 0.076000 | 0.004936 | 197189.000000 | 90 | 27 | 162 |
| Draw | 0.004528 | 2026-06-23 01:14:56 UTC+8 | -0.039105 | -0.010194 | -0.009648 | 0.010000 | 0.004381 | 1000000.000000 | 33 | 13 | 58 |
| Austria | 0.003386 | 2026-06-23 02:17:37 UTC+8 | -0.024393 | -0.005699 | -0.003737 | 0.005020 | 0.001754 | 400000.000000 | 124 | 20 | 168 |

## Table 3: Top1 Ranking Explanation

| outcome | top1_count | avg_rank | avg_gross | avg_fee | avg_net | avg_depth | main_reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina | 162 | 1.840206 | -0.002738 | 0.004936 | -0.007674 | 4281.971727 | worse net after gross/fee combination |
| Draw | 58 | 2.317549 | -0.005813 | 0.004381 | -0.010194 | 22929.319861 | worse net after gross/fee combination |
| Austria | 168 | 1.779255 | -0.003945 | 0.001754 | -0.005699 | 31847.983059 | best average net, lowest average fee, most frequent top1 |

## Table 4: op4 Venue Structure Summary

| venue | mean_sum_ask | mean_sum_bid | mean_sum_ask_minus_1 | mean_sum_bid_minus_1 | pre_final_mean_sum_ask_minus_1 | post_final_mean_sum_ask_minus_1 | min_sum_ask_minus_1 | max_sum_ask_minus_1 | stability_comment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| polymarket | 1.014834 | 0.988285 | 0.014834 | -0.011715 | 0.014834 |  | -0.001000 | 0.100000 | noticeable movement, inspect time series around final |
| hyperliquid | 1.016600 | 0.986311 | 0.016600 | -0.013689 | 0.019866 | 0.004789 | -0.012720 | 0.116940 | noticeable movement, inspect time series around final |

## Charts

![Warning timeline](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_warning_timeline.png)

![op1 net time series](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_op1_net_timeseries.png)

![Top1 distribution](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_top1_distribution.png)

![op4 structure](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_op4_structure.png)

![Gross vs fee](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_gross_fee.png)

![Depth time series](D:/cursor/2026_strategy_lab/outputs/pm_hl_mvp2_scanner/review_arg_aut_depth_timeseries.png)

## Interpretation

### 1. Warning timing

The monitor has two phases: a normal phase with usable op1/op4 rows, then a warning phase. The first warning starts after the reported final time, and warnings continue afterward. That supports the post-final lifecycle hypothesis: the market outcome metadata or question discovery path no longer matched the pre-final structure.

### 2. op1 near-miss behavior

The closest-to-action periods are where op1 net is highest. Argentina had the strongest positive net spike around its max timestamp; Austria had the most near-miss rows and the best average net. These are top-of-book monitor rows only, not proof that a complete live execution would have filled.

### 3. Why Austria was often top1

Austria's advantage is mostly fee plus steadier net: its relevant PM leg often carried a lower PM quadratic fee, and its average net was less negative. It was top1 most often, but the count was close to Argentina, so this is a plurality rather than overwhelming dominance. Depth was not the main source of the ranking; it mainly affected capacity.

### 4. op4 structure

PM ask-side three-way sum was stable around a positive spread before final, but PM post-final ask diagnostics are blank in the flat CSV. HL ask-side sum was farther above 1 before final and closer to 1 after final. Bid-side sums stayed below or near 1, consistent with spread rather than an executable single-venue strategy in this MVP2 scope.

## Source Files

- JSON: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json`
- CSV: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv`
- TEXT_LOG: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log`
