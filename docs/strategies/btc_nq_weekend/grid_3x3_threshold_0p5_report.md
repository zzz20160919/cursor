# BTC-NQ Weekend 3x3 Threshold 0.5% Report

Scope: threshold 0.5% comparison only. Event is `monday_0930`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, daily strategy, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.

## Signal Modes

- `no_threshold`: old rule, sign(btc_ret).
- `threshold_0p5`: long if btc_ret > 0.005, short if btc_ret < -0.005, otherwise no trade.

## Threshold Summary

- btc_ret_1h__nq_fwd_1h: trades=34, no_trade=45, endpoint_missing=0, cum net=13.910121%, net win=76.470588%.
- btc_ret_1h__nq_fwd_4h: trades=34, no_trade=38, endpoint_missing=7, cum net=19.962906%, net win=64.705882%.
- btc_ret_1h__nq_fwd_to_1600_same_day: trades=34, no_trade=38, endpoint_missing=7, cum net=23.759531%, net win=64.705882%.
- btc_ret_4h__nq_fwd_1h: trades=41, no_trade=38, endpoint_missing=0, cum net=10.975160%, net win=68.292683%.
- btc_ret_4h__nq_fwd_4h: trades=39, no_trade=33, endpoint_missing=7, cum net=17.957338%, net win=64.102564%.
- btc_ret_4h__nq_fwd_to_1600_same_day: trades=39, no_trade=33, endpoint_missing=7, cum net=22.486071%, net win=66.666667%.
- btc_ret_12h__nq_fwd_1h: trades=60, no_trade=19, endpoint_missing=0, cum net=-1.556533%, net win=55.000000%.
- btc_ret_12h__nq_fwd_4h: trades=56, no_trade=16, endpoint_missing=7, cum net=-7.508569%, net win=48.214286%.
- btc_ret_12h__nq_fwd_to_1600_same_day: trades=56, no_trade=16, endpoint_missing=7, cum net=-3.318233%, net win=42.857143%.

## Threshold Subsample OOS

- btc_ret_1h__nq_fwd_1h: OOS trades=5, no_trade=8, cum net=1.329112%, net win=80.000000%.
- btc_ret_1h__nq_fwd_4h: OOS trades=5, no_trade=7, cum net=1.265705%, net win=60.000000%.
- btc_ret_1h__nq_fwd_to_1600_same_day: OOS trades=5, no_trade=7, cum net=1.916117%, net win=60.000000%.
- btc_ret_4h__nq_fwd_1h: OOS trades=5, no_trade=8, cum net=0.158791%, net win=60.000000%.
- btc_ret_4h__nq_fwd_4h: OOS trades=5, no_trade=7, cum net=-0.170500%, net win=60.000000%.
- btc_ret_4h__nq_fwd_to_1600_same_day: OOS trades=5, no_trade=7, cum net=0.556956%, net win=60.000000%.
- btc_ret_12h__nq_fwd_1h: OOS trades=12, no_trade=1, cum net=-1.012216%, net win=50.000000%.
- btc_ret_12h__nq_fwd_4h: OOS trades=11, no_trade=1, cum net=-2.822043%, net win=36.363636%.
- btc_ret_12h__nq_fwd_to_1600_same_day: OOS trades=11, no_trade=1, cum net=-2.506278%, net win=36.363636%.

## Skip Attribution

- btc_ret_1h__nq_fwd_1h: threshold no-trade=45, OOS no-trade=8, OOS endpoint missing=0.
- btc_ret_1h__nq_fwd_4h: threshold no-trade=38, OOS no-trade=7, OOS endpoint missing=1.
- btc_ret_1h__nq_fwd_to_1600_same_day: threshold no-trade=38, OOS no-trade=7, OOS endpoint missing=1.
- btc_ret_4h__nq_fwd_1h: threshold no-trade=38, OOS no-trade=8, OOS endpoint missing=0.
- btc_ret_4h__nq_fwd_4h: threshold no-trade=33, OOS no-trade=7, OOS endpoint missing=1.
- btc_ret_4h__nq_fwd_to_1600_same_day: threshold no-trade=33, OOS no-trade=7, OOS endpoint missing=1.
- btc_ret_12h__nq_fwd_1h: threshold no-trade=19, OOS no-trade=1, OOS endpoint missing=0.
- btc_ret_12h__nq_fwd_4h: threshold no-trade=16, OOS no-trade=1, OOS endpoint missing=1.
- btc_ret_12h__nq_fwd_to_1600_same_day: threshold no-trade=16, OOS no-trade=1, OOS endpoint missing=1.

## Conclusion

- Stability is judged by first_half, second_half, OOS, OOS trade count, OOS win rate, no-trade count, endpoint missing, and side attribution.
- This is a single threshold test, not a threshold grid search.
