# PM-HL MVP2 Arg/Aus Core Profit Review

## Conclusions First

- Best observed positive net across op1/op2/op3 was **0.069472** from `cross_venue_direct_no_complete_set` / `Argentina` / `buy_hl_Argentina_yes_buy_pm_Argentina_no` at **2026-06-23 01:38:53 UTC+8**.
- For op1 specifically, Argentina had the largest max net. This supports continuing MVP execution research, but only with strict fill/leg-risk controls because this is top-of-book monitoring, not execution-verified VWAP.
- A single 20-share Argentina slot at max observed op1 net would have made roughly **$1.39** before operational slippage; S1+S2 together would be roughly **$2.78**.
- Main downside is not rule-complete-set payout if both legs fill and rules match; the practical MVP risk is one-leg-only exposure, roughly **$18-$20** for one 20-share slot or **$36-$40** for S1+S2.

## 1. op1 / op2 / op3 Positive Net Statistics

### op1: direct No-token complete-set

| op_group | outcome | side | total_rows | positive_net_rows | positive_net_pct | mean_positive_net | max_positive_net | best_timestamp_utc8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_direct_no_complete_set | Argentina | buy_hl_Argentina_yes_buy_pm_Argentina_no | 96 | 7 | 0.072917 | 0.012253 | 0.069472 | 2026-06-23 01:38:53 UTC+8 |
| cross_venue_direct_no_complete_set | Argentina | buy_pm_Argentina_yes_buy_hl_Argentina_no | 292 | 20 | 0.068493 | 0.003130 | 0.014352 | 2026-06-23 01:48:08 UTC+8 |
| cross_venue_direct_no_complete_set | Austria | buy_hl_Austria_yes_buy_pm_Austria_no | 267 | 9 | 0.033708 | 0.001886 | 0.003154 | 2026-06-23 01:54:08 UTC+8 |
| cross_venue_direct_no_complete_set | Austria | buy_pm_Austria_yes_buy_hl_Austria_no | 109 | 11 | 0.100917 | 0.001195 | 0.003386 | 2026-06-23 02:17:37 UTC+8 |
| cross_venue_direct_no_complete_set | Draw | buy_hl_Draw_yes_buy_pm_Draw_no | 268 | 2 | 0.007463 | 0.004528 | 0.004528 | 2026-06-23 01:14:56 UTC+8 |
| cross_venue_direct_no_complete_set | Draw | buy_pm_Draw_yes_buy_hl_Draw_no | 91 | 11 | 0.120879 | 0.002063 | 0.002457 | 2026-06-23 02:46:33 UTC+8 |

### op2: single outcome cross-venue

| op_group | outcome | side | total_rows | positive_net_rows | positive_net_pct | mean_positive_net | max_positive_net | best_timestamp_utc8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_single_outcome | Argentina | buy_hl_yes_sell_pm_yes | 96 | 7 | 0.072917 | 0.009367 | 0.049268 | 2026-06-23 01:38:53 UTC+8 |
| cross_venue_single_outcome | Argentina | buy_pm_yes_sell_hl_yes | 292 | 20 | 0.068493 | 0.003130 | 0.014352 | 2026-06-23 01:48:08 UTC+8 |
| cross_venue_single_outcome | Austria | buy_hl_yes_sell_pm_yes | 267 | 9 | 0.033708 | 0.001886 | 0.003154 | 2026-06-23 01:54:08 UTC+8 |
| cross_venue_single_outcome | Austria | buy_pm_yes_sell_hl_yes | 109 | 11 | 0.100917 | 0.001195 | 0.003386 | 2026-06-23 02:17:37 UTC+8 |
| cross_venue_single_outcome | Draw | buy_hl_yes_sell_pm_yes | 268 | 2 | 0.007463 | 0.004528 | 0.004528 | 2026-06-23 01:14:56 UTC+8 |
| cross_venue_single_outcome | Draw | buy_pm_yes_sell_hl_yes | 91 | 11 | 0.120879 | 0.002063 | 0.002457 | 2026-06-23 02:46:33 UTC+8 |

### op3: complement basket

| op_group | outcome | side | total_rows | positive_net_rows | positive_net_pct | mean_positive_net | max_positive_net | best_timestamp_utc8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cross_venue_complement_basket | Argentina | buy_hl_Argentina_yes_buy_pm_Draw+Austria_yes | 376 | 6 | 0.015957 | 0.005706 | 0.007741 | 2026-06-23 02:47:06 UTC+8 |
| cross_venue_complement_basket | Argentina | buy_pm_Argentina_yes_buy_hl_Draw+Austria_yes | 344 | 12 | 0.034884 | 0.004096 | 0.007338 | 2026-06-23 01:15:29 UTC+8 |
| cross_venue_complement_basket | Austria | buy_hl_Austria_yes_buy_pm_Argentina+Draw_yes | 344 | 0 | 0.000000 |  |  |  |
| cross_venue_complement_basket | Austria | buy_pm_Austria_yes_buy_hl_Argentina+Draw_yes | 376 | 2 | 0.005319 | 0.001933 | 0.002078 | 2026-06-23 01:39:58 UTC+8 |
| cross_venue_complement_basket | Draw | buy_hl_Draw_yes_buy_pm_Argentina+Austria_yes | 344 | 2 | 0.005814 | 0.003057 | 0.005055 | 2026-06-23 01:40:31 UTC+8 |
| cross_venue_complement_basket | Draw | buy_pm_Draw_yes_buy_hl_Argentina+Austria_yes | 378 | 3 | 0.007937 | 0.002916 | 0.004815 | 2026-06-23 02:55:52 UTC+8 |

## 2. op4 Diagnostic Opportunity Statistics

| venue | condition | total_rows | true_rows | true_pct | mean_edge_when_true | max_edge_when_true | min_edge_when_true |
| --- | --- | --- | --- | --- | --- | --- | --- |
| polymarket | PM sum_ask_minus_1 < 0 | 344 | 1 | 0.002907 | 0.001000 | 0.001000 | 0.001000 |
| polymarket | PM sum_bid_minus_1 > 0 | 337 | 7 | 0.020772 | 0.020571 | 0.060000 | 0.002000 |
| hyperliquid | HL sum_ask_minus_1 < 0 | 494 | 4 | 0.008097 | 0.005453 | 0.012720 | 0.000930 |
| hyperliquid | HL sum_bid_minus_1 > 0 | 473 | 25 | 0.052854 | 0.002724 | 0.016750 | 0.000010 |

## 3. op1 Rough Return Math

| scenario | max_net_per_share | gross_profit_usd | capital_used_low_usd | capital_used_high_usd | trade_return_low_capital | trade_return_high_capital | portfolio_capital_low_usd | portfolio_capital_high_usd | portfolio_return_low_capital | portfolio_return_high_capital | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Argentina one 20-share slot caught at max net | 0.069472 | 1.389440 | 18.000000 | 20.000000 | 0.077191 | 0.069472 | 108.000000 | 120.000000 | 0.012865 | 0.011579 | Uses top-of-book max monitor net; not VWAP/execution verified. |
| Argentina S1+S2 both 20-share slots caught at max net | 0.069472 | 2.778880 | 36.000000 | 40.000000 | 0.077191 | 0.069472 | 108.000000 | 120.000000 | 0.025730 | 0.023157 | Assumes both slots fill at same best observed net; optimistic MVP rough calculation. |
| single-leg naked exposure estimate: one 20-share slot |  |  | 18.000000 | 20.000000 |  |  | 108.000000 | 120.000000 |  |  | If only one leg fills, rough naked downside can approach the 20-share leg notional, about $18-$20. |
| single-leg naked exposure estimate: S1+S2 40 shares |  |  | 36.000000 | 40.000000 |  |  | 108.000000 | 120.000000 |  |  | If S1+S2 both suffer one-leg-only fill, rough naked downside can approach $36-$40. |

## 4. Max Loss Rough Estimate

- If both legs fill and PM/HL rule matching holds, the position is intended as a complete set. The main residual risks are fee/slippage, rule mismatch, venue settlement/funding issues, and operational mistakes.
- If only one leg fills for a 20-share slot, rough naked downside can approach the funded leg notional, about **$18-$20** under the simple capital assumption.
- If S1+S2 both get one-leg-only exposure, rough naked downside can approach **$36-$40**.

## MVP Decision

This match supports continuing op1 MVP execution-layer work, but not because every signal was tradable. The reason is that the data produced real positive top-of-book net windows, especially Argentina. However, the edge is episodic and execution-sensitive, so the next layer should focus narrowly on atomic/controlled two-leg execution, fill confirmation, kill switch, and one-leg exposure handling. Do not broaden to op2/op3/op4 execution yet.

## Source Files

- CSV: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv`
- JSON: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json`
- LOG: `D:\cursor\2026_strategy_lab\outputs\pm_hl_mvp2_scanner\pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log`
- JSON completed iterations: `494`
- JSON warnings: `346`
