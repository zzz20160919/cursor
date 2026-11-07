# BTC-NQ Weekly Relative Signal Report

Scope: weekly MVP only. Event is `monday_0930`, BTC lookback is `btc_ret_1h`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, daily strategy, data download, external API call, continuous NQ, beta scaling, z-score, vol adjustment, or extra thresholds were used.

## Summary

- btc_threshold_0p5__nq_fwd_1h: trades=34, no_trade=45, cum net=13.910121%, net win=76.470588%.
- btc_threshold_0p5__nq_fwd_4h: trades=34, no_trade=45, cum net=19.962906%, net win=64.705882%.
- btc_threshold_0p5__nq_fwd_to_1600_same_day: trades=34, no_trade=45, cum net=23.759531%, net win=64.705882%.
- relative_underreaction__nq_fwd_1h: trades=25, no_trade=54, cum net=11.844064%, net win=80.000000%.
- relative_underreaction__nq_fwd_4h: trades=25, no_trade=54, cum net=16.302885%, net win=64.000000%.
- relative_underreaction__nq_fwd_to_1600_same_day: trades=25, no_trade=54, cum net=14.238149%, net win=64.000000%.
- btc_minus_nq_spread_0p5__nq_fwd_1h: trades=37, no_trade=42, cum net=11.545067%, net win=72.972973%.
- btc_minus_nq_spread_0p5__nq_fwd_4h: trades=35, no_trade=42, cum net=16.813470%, net win=62.857143%.
- btc_minus_nq_spread_0p5__nq_fwd_to_1600_same_day: trades=35, no_trade=42, cum net=21.064649%, net win=65.714286%.

## OOS

- btc_threshold_0p5__nq_fwd_1h: OOS trades=5, no_trade=8, cum net=1.329112%, net win=80.000000%.
- btc_threshold_0p5__nq_fwd_4h: OOS trades=5, no_trade=8, cum net=1.265705%, net win=60.000000%.
- btc_threshold_0p5__nq_fwd_to_1600_same_day: OOS trades=5, no_trade=8, cum net=1.916117%, net win=60.000000%.
- relative_underreaction__nq_fwd_1h: OOS trades=2, no_trade=11, cum net=1.073811%, net win=100.000000%.
- relative_underreaction__nq_fwd_4h: OOS trades=2, no_trade=11, cum net=0.498850%, net win=50.000000%.
- relative_underreaction__nq_fwd_to_1600_same_day: OOS trades=2, no_trade=11, cum net=0.249962%, net win=50.000000%.
- btc_minus_nq_spread_0p5__nq_fwd_1h: OOS trades=3, no_trade=10, cum net=1.088965%, net win=100.000000%.
- btc_minus_nq_spread_0p5__nq_fwd_4h: OOS trades=3, no_trade=10, cum net=0.218203%, net win=33.333333%.
- btc_minus_nq_spread_0p5__nq_fwd_to_1600_same_day: OOS trades=3, no_trade=10, cum net=0.577776%, net win=66.666667%.

## Filtered Counterfactual

- relative_underreaction nq_fwd_1h filtered_threshold_trades: events=9, avg net=0.204522%, cum net=1.847266%.
- relative_underreaction nq_fwd_1h kept_threshold_trades: events=25, avg net=0.450639%, cum net=11.844064%.
- relative_underreaction nq_fwd_4h filtered_threshold_trades: events=9, avg net=0.348209%, cum net=3.146974%.
- relative_underreaction nq_fwd_4h kept_threshold_trades: events=25, avg net=0.610738%, cum net=16.302885%.
- relative_underreaction nq_fwd_to_1600_same_day filtered_threshold_trades: events=9, avg net=0.898994%, cum net=8.334678%.
- relative_underreaction nq_fwd_to_1600_same_day kept_threshold_trades: events=25, avg net=0.538560%, cum net=14.238149%.
- btc_minus_nq_spread_0p5 nq_fwd_1h filtered_threshold_trades: events=5, avg net=0.150964%, cum net=0.754004%.
- btc_minus_nq_spread_0p5 nq_fwd_1h kept_threshold_trades: events=29, avg net=0.425926%, cum net=13.057662%.
- btc_minus_nq_spread_0p5 nq_fwd_4h filtered_threshold_trades: events=5, avg net=0.336115%, cum net=1.672514%.
- btc_minus_nq_spread_0p5 nq_fwd_4h kept_threshold_trades: events=29, avg net=0.576613%, cum net=17.989516%.
- btc_minus_nq_spread_0p5 nq_fwd_to_1600_same_day filtered_threshold_trades: events=5, avg net=0.466798%, cum net=2.333687%.
- btc_minus_nq_spread_0p5 nq_fwd_to_1600_same_day kept_threshold_trades: events=29, avg net=0.662792%, cum net=20.937234%.