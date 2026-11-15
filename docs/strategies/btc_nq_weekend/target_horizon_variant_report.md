# BTC-NQ Target Horizon Variant Report

Scope: BTC-NQ Weekend target horizon test only. Event, BTC feature, signal rule, cost, OOS definition, and NQ mode remain unchanged. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC lookback optimization, BTC threshold optimization, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.

## Tested Targets

- `nq_fwd_4h`: existing old grid, 4h after Monday 09:30 NY.
- `nq_fwd_to_1600_same_day`: exact 1m bar at Monday 16:00 America/New_York on the same active raw NQ contract.
- `nq_fwd_1d`: old locked baseline target.
- `nq_fwd_2d`: optional old-grid reference only.

## Full IS + OOS Summary

- nq_fwd_4h: total=72, IS=60, OOS=12, cumulative net=19.848692%, average net=0.255312%, net win rate=56.944444%, max DD=-3.783945%, sharpe=2.168.
- nq_fwd_to_1600_same_day: total=72, IS=60, OOS=12, cumulative net=22.545347%, average net=0.286642%, net win rate=54.166667%, max DD=-3.765887%, sharpe=2.323.
- nq_fwd_1d: total=79, IS=66, OOS=13, cumulative net=30.286430%, average net=0.342410%, net win rate=63.291139%, max DD=-3.479262%, sharpe=2.056.
- nq_fwd_2d: total=77, IS=64, OOS=13, cumulative net=9.468332%, average net=0.128990%, net win rate=53.246753%, max DD=-9.711682%, sharpe=0.612.

## Subsample Stability

### nq_fwd_4h
- first_half: events=30, cumulative net=14.939594%, average net=0.470240%, net win rate=63.333333%, long/short=14/16, low_sample_warning=false.
- second_half: events=30, cumulative net=7.600617%, average net=0.246286%, net win rate=53.333333%, long/short=18/12, low_sample_warning=false.
- oos: events=12, cumulative net=-3.094400%, average net=-0.259445%, net win rate=50.000000%, long/short=8/4, low_sample_warning=true.

### nq_fwd_to_1600_same_day
- first_half: events=30, cumulative net=16.135564%, average net=0.505110%, net win rate=60.000000%, long/short=14/16, low_sample_warning=false.
- second_half: events=30, cumulative net=8.972026%, average net=0.289029%, net win rate=56.666667%, long/short=18/12, low_sample_warning=false.
- oos: events=12, cumulative net=-3.168520%, average net=-0.265494%, net win rate=33.333333%, long/short=8/4, low_sample_warning=true.

### nq_fwd_1d
- first_half: events=33, cumulative net=20.726470%, average net=0.583589%, net win rate=72.727273%, long/short=15/18, low_sample_warning=false.
- second_half: events=33, cumulative net=9.451319%, average net=0.277462%, net win rate=60.606061%, long/short=18/15, low_sample_warning=false.
- oos: events=13, cumulative net=-1.400280%, average net=-0.104945%, net win rate=46.153846%, long/short=8/5, low_sample_warning=true.

### nq_fwd_2d
- first_half: events=32, cumulative net=9.982225%, average net=0.311626%, net win rate=59.375000%, long/short=16/16, low_sample_warning=false.
- second_half: events=32, cumulative net=5.866040%, average net=0.184892%, net win rate=56.250000%, long/short=17/15, low_sample_warning=false.
- oos: events=13, cumulative net=-5.982363%, average net=-0.458177%, net win rate=30.769231%, long/short=8/5, low_sample_warning=true.

## Side Attribution

### nq_fwd_4h
- long_only: trades=40, cumulative net=16.240738%, average net=0.380436%, net win rate=72.500000%.
- short_only: trades=32, cumulative net=3.103864%, average net=0.098907%, net win rate=37.500000%.
- symmetric: trades=72, cumulative net=19.848692%, average net=0.255312%, net win rate=56.944444%.

### nq_fwd_to_1600_same_day
- long_only: trades=40, cumulative net=18.248073%, average net=0.423882%, net win rate=65.000000%.
- short_only: trades=32, cumulative net=3.634118%, average net=0.115093%, net win rate=40.625000%.
- symmetric: trades=72, cumulative net=22.545347%, average net=0.286642%, net win rate=54.166667%.

### nq_fwd_1d
- long_only: trades=41, cumulative net=20.865716%, average net=0.472482%, net win rate=70.731707%.
- short_only: trades=38, cumulative net=7.794364%, average net=0.202069%, net win rate=55.263158%.
- symmetric: trades=79, cumulative net=30.286430%, average net=0.342410%, net win rate=63.291139%.

### nq_fwd_2d
- long_only: trades=41, cumulative net=18.608942%, average net=0.426555%, net win rate=63.414634%.
- short_only: trades=36, cumulative net=-7.706510%, average net=-0.209902%, net win rate=41.666667%.
- symmetric: trades=77, cumulative net=9.468332%, average net=0.128990%, net win rate=53.246753%.

## Skips and Timestamp Convention

- Skipped events by target: `{'nq_fwd_4h': {'missing_nq_fwd_4h': 7}, 'nq_fwd_to_1600_same_day': {'missing_nq_fwd_to_1600_same_day': 7}, 'nq_fwd_1d': {}, 'nq_fwd_2d': {'missing_nq_fwd_2d': 2}}`
- `nq_fwd_to_1600_same_day` uses the exact 1m bar timestamp for Monday 16:00 America/New_York, converted to UTC, and does not cross-fill across contracts.

## Conclusion

- A target is considered more interesting only if first_half, second_half, and OOS are all acceptable; OOS-only strength is not enough.
- Based on this run, review the stability table before promoting any horizon to the next BTC lookback test.
