# BTC-NQ Weekend 3x3 Grid Report

Scope: old weekly/weekend BTC-NQ strategy grid only. Event is `monday_0930`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC threshold optimization, daily strategy, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.

## Grid

- BTC lookbacks: btc_ret_1h, btc_ret_4h, btc_ret_12h
- NQ targets: nq_fwd_1h, nq_fwd_4h, nq_fwd_to_1600_same_day
- `btc_ret_12h` is computed in this report script from local BTC parquet with the same hourly bar-close convention as existing BTC returns.
- `nq_fwd_to_1600_same_day` uses exact Monday 16:00 America/New_York 1m bar on the same active raw NQ contract.

## Available-Sample Summary

- btc_ret_1h__nq_fwd_1h: first/second/OOS events=33/33/13, cumulative net=11.571133%, average net=0.140093%, net win rate=59.493671%.
- btc_ret_1h__nq_fwd_4h: first/second/OOS events=30/30/12, cumulative net=22.598208%, average net=0.286782%, net win rate=56.944444%.
- btc_ret_1h__nq_fwd_to_1600_same_day: first/second/OOS events=30/30/12, cumulative net=24.148159%, average net=0.304671%, net win rate=58.333333%.
- btc_ret_4h__nq_fwd_1h: first/second/OOS events=33/33/13, cumulative net=9.278174%, average net=0.113833%, net win rate=54.430380%.
- btc_ret_4h__nq_fwd_4h: first/second/OOS events=30/30/12, cumulative net=19.848692%, average net=0.255312%, net win rate=56.944444%.
- btc_ret_4h__nq_fwd_to_1600_same_day: first/second/OOS events=30/30/12, cumulative net=22.545347%, average net=0.286642%, net win rate=54.166667%.
- btc_ret_12h__nq_fwd_1h: first/second/OOS events=33/33/13, cumulative net=-1.746283%, average net=-0.020625%, net win rate=51.898734%.
- btc_ret_12h__nq_fwd_4h: first/second/OOS events=30/30/12, cumulative net=-5.899751%, average net=-0.080203%, net win rate=47.222222%.
- btc_ret_12h__nq_fwd_to_1600_same_day: first/second/OOS events=30/30/12, cumulative net=-2.353768%, average net=-0.028428%, net win rate=45.833333%.

## Common-Sample Summary

- btc_ret_1h__nq_fwd_1h: events=72, cumulative net=12.548907%, average net=0.165817%, net win rate=62.500000%.
- btc_ret_1h__nq_fwd_4h: events=72, cumulative net=22.598208%, average net=0.286782%, net win rate=56.944444%.
- btc_ret_1h__nq_fwd_to_1600_same_day: events=72, cumulative net=24.148159%, average net=0.304671%, net win rate=58.333333%.
- btc_ret_4h__nq_fwd_1h: events=72, cumulative net=9.815551%, average net=0.131704%, net win rate=55.555556%.
- btc_ret_4h__nq_fwd_4h: events=72, cumulative net=19.848692%, average net=0.255312%, net win rate=56.944444%.
- btc_ret_4h__nq_fwd_to_1600_same_day: events=72, cumulative net=22.545347%, average net=0.286642%, net win rate=54.166667%.
- btc_ret_12h__nq_fwd_1h: events=72, cumulative net=-0.844649%, average net=-0.009959%, net win rate=54.166667%.
- btc_ret_12h__nq_fwd_4h: events=72, cumulative net=-5.899751%, average net=-0.080203%, net win rate=47.222222%.
- btc_ret_12h__nq_fwd_to_1600_same_day: events=72, cumulative net=-2.353768%, average net=-0.028428%, net win rate=45.833333%.

## Stability Labels

- Three segments profitable: ['btc_ret_1h__nq_fwd_1h', 'btc_ret_1h__nq_fwd_4h', 'btc_ret_1h__nq_fwd_to_1600_same_day']
- IS good but OOS bad: ['btc_ret_4h__nq_fwd_1h', 'btc_ret_4h__nq_fwd_4h', 'btc_ret_4h__nq_fwd_to_1600_same_day']
- OOS good but IS unstable: none
- Long/short extreme imbalance: ['btc_ret_12h__nq_fwd_1h', 'btc_ret_12h__nq_fwd_4h', 'btc_ret_12h__nq_fwd_to_1600_same_day']

## Endpoint Missing Attribution

- btc_ret_1h__nq_fwd_4h: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- btc_ret_1h__nq_fwd_to_1600_same_day: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- btc_ret_4h__nq_fwd_4h: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- btc_ret_4h__nq_fwd_to_1600_same_day: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- btc_ret_12h__nq_fwd_4h: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- btc_ret_12h__nq_fwd_to_1600_same_day: skipped=7, OOS skipped=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.

## Conclusion

- Stability is judged by first_half, second_half, OOS, OOS win rate, low sample status, and side concentration, not by full-period return alone.
- This grid is exploratory within the old weekly strategy frame and should not be treated as threshold optimization or a new daily strategy.
