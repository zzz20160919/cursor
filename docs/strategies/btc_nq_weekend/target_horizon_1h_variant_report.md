# BTC-NQ Target Horizon 1h Variant Report

Scope: BTC-NQ Weekend NQ target horizon test only. Event, BTC feature, signal rule, cost, OOS definition, and NQ mode remain unchanged. No PM-HL, Futu, live/paper trading, QQQ proxy, BTC lookback optimization, BTC threshold optimization, data download, external API call, continuous NQ, or baseline/smoke-test modification was used.

## Endpoint Convention

- `nq_fwd_1h`, `nq_fwd_4h`, `nq_fwd_1d`, and `nq_fwd_2d` use existing old-grid event dataset endpoints.
- `nq_fwd_to_1600_same_day` uses exact Monday 16:00 America/New_York 1m bar on the same active raw NQ contract.
- No nearest / previous / next fill is used; missing endpoint means skipped trade for that target.

## Available-Sample Summary

- nq_fwd_1h: total=79, IS=66, OOS=13, cumulative net=9.278174%, OOS available shown in subsample table.
- nq_fwd_4h: total=72, IS=60, OOS=12, cumulative net=19.848692%, OOS available shown in subsample table.
- nq_fwd_to_1600_same_day: total=72, IS=60, OOS=12, cumulative net=22.545347%, OOS available shown in subsample table.
- nq_fwd_1d: total=79, IS=66, OOS=13, cumulative net=30.286430%, OOS available shown in subsample table.
- nq_fwd_2d: total=77, IS=64, OOS=13, cumulative net=9.468332%, OOS available shown in subsample table.

## Common-Sample Summary

- nq_fwd_1h: total=70, IS=58, OOS=12, cumulative net=8.836746%, average net=0.122648%, net win rate=54.285714%.
- nq_fwd_4h: total=70, IS=58, OOS=12, cumulative net=21.189800%, average net=0.278457%, net win rate=58.571429%.
- nq_fwd_to_1600_same_day: total=70, IS=58, OOS=12, cumulative net=23.372186%, average net=0.304411%, net win rate=55.714286%.
- nq_fwd_1d: total=70, IS=58, OOS=12, cumulative net=29.460096%, average net=0.377078%, net win rate=65.714286%.
- nq_fwd_2d: total=70, IS=58, OOS=12, cumulative net=12.881039%, average net=0.185524%, net win rate=55.714286%.

## Available-Sample Subsample Stability

### nq_fwd_1h
- first_half: events=33, cumulative net=10.692049%, average net=0.310026%, net win rate=69.696970%, long/short=15/18, low_sample_warning=false.
- second_half: events=33, cumulative net=1.272960%, average net=0.039467%, net win rate=48.484848%, long/short=18/15, low_sample_warning=false.
- oos: events=13, cumulative net=-2.518209%, average net=-0.195420%, net win rate=30.769231%, long/short=8/5, low_sample_warning=true.

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

## Common-Sample Subsample Stability

### nq_fwd_1h
- first_half: events=29, cumulative net=10.285270%, average net=0.340064%, net win rate=68.965517%, long/short=15/14, low_sample_warning=false.
- second_half: events=29, cumulative net=1.147338%, average net=0.040569%, net win rate=48.275862%, long/short=17/12, low_sample_warning=false.
- oos: events=12, cumulative net=-2.432859%, average net=-0.204415%, net win rate=33.333333%, long/short=8/4, low_sample_warning=true.

### nq_fwd_4h
- first_half: events=29, cumulative net=17.036632%, average net=0.548774%, net win rate=68.965517%, long/short=15/14, low_sample_warning=false.
- second_half: events=29, cumulative net=6.855130%, average net=0.230721%, net win rate=51.724138%, long/short=17/12, low_sample_warning=false.
- oos: events=12, cumulative net=-3.094400%, average net=-0.259445%, net win rate=50.000000%, long/short=8/4, low_sample_warning=true.

### nq_fwd_to_1600_same_day
- first_half: events=29, cumulative net=17.800658%, average net=0.571648%, net win rate=65.517241%, long/short=15/14, low_sample_warning=false.
- second_half: events=29, cumulative net=8.156587%, average net=0.272997%, net win rate=55.172414%, long/short=17/12, low_sample_warning=false.
- oos: events=12, cumulative net=-3.168520%, average net=-0.265494%, net win rate=33.333333%, long/short=8/4, low_sample_warning=true.

### nq_fwd_1d
- first_half: events=29, cumulative net=23.402025%, average net=0.739628%, net win rate=82.758621%, long/short=15/14, low_sample_warning=false.
- second_half: events=29, cumulative net=6.515644%, average net=0.221382%, net win rate=58.620690%, long/short=17/12, low_sample_warning=false.
- oos: events=12, cumulative net=-1.508163%, average net=-0.122819%, net win rate=41.666667%, long/short=8/4, low_sample_warning=true.

### nq_fwd_2d
- first_half: events=29, cumulative net=12.696321%, average net=0.427498%, net win rate=65.517241%, long/short=15/14, low_sample_warning=false.
- second_half: events=29, cumulative net=5.742445%, average net=0.199980%, net win rate=55.172414%, long/short=17/12, low_sample_warning=false.
- oos: events=12, cumulative net=-5.275590%, average net=-0.434181%, net win rate=33.333333%, long/short=8/4, low_sample_warning=true.

## Available-Sample Side Attribution

### nq_fwd_1h
- long_only: trades=41, cumulative net=7.615148%, average net=0.180935%, net win rate=60.975610%.
- short_only: trades=38, cumulative net=1.545345%, average net=0.041434%, net win rate=47.368421%.
- symmetric: trades=79, cumulative net=9.278174%, average net=0.113833%, net win rate=54.430380%.

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

## Endpoint Missing Attribution

- nq_fwd_1d: IS available=66, OOS available=13, skipped=0, OOS skipped dates=none, reason={}.
- nq_fwd_1h: IS available=66, OOS available=13, skipped=0, OOS skipped dates=none, reason={}.
- nq_fwd_2d: IS available=64, OOS available=13, skipped=2, OOS skipped dates=none, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 2}.
- nq_fwd_4h: IS available=60, OOS available=12, skipped=7, OOS skipped dates=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.
- nq_fwd_to_1600_same_day: IS available=60, OOS available=12, skipped=7, OOS skipped dates=2026-05-25, reason={'target_endpoint_missing_within_active_contract_coverage_likely_holiday_or_session_gap': 7}.

## Conclusion

- A target is only interesting if first_half, second_half, and OOS are all acceptable.
- `nq_fwd_1h` should be compared against `nq_fwd_1d` using both available-sample and common-sample outputs before any BTC lookback test.
