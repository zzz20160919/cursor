# Why the YESMV High leg is +0.28¢

This note uses the same membership as Step 3. Within each formation date and vgregoire category, YESMV is winsorized at the 1st and 99th percentiles and split at the 30th and 70th. A category is kept only when Low, Middle, and High are all non-empty. The High-leg return that day weights contracts by raw open interest inside the High bucket, then weights categories by total open interest measured before the sort. The reported mean is the equal-weighted average of those daily High returns, over the 884 dates on which the sort forms. Rebuilding that mean from the contract-day weights below returns +0.282845 cents for High and +0.073974 cents for Low, the Step 3 figures. Locked price and universe settings are unchanged. Step 4 is not started.

The paper's Table IA.15 High leg is −0.171 cents. Our Low leg (+0.074) is already close to the paper's Low leg (+0.084). The sign gap is in High.

A contract-day's contribution is its share of that day's High (or Low) portfolio, divided by 884, times its next-period price change in cents. Contributions add up to the leg mean.

## What the average day looks like

| | High | Low |
| --- | ---: | ---: |
| Dates | 884 | 884 |
| Contract-days | 114,504 | 114,504 |
| Mean, cents | +0.283 | +0.074 |
| Median daily return, cents | −0.000 | +0.013 |
| Share of dates with a positive leg | 49.0% | 57.9% |
| Dates with a leg return of at least +5¢ | 28 | 25 |
| Contribution of those dates to the mean | +0.451 | +0.520 |
| Dates with a leg return of at least +10¢ | 12 | 15 |
| Contribution of those dates to the mean | +0.313 | +0.438 |
| Top 20 contract-days, contribution | +0.418 | +0.487 |
| All other contract-days, contribution | −0.136 | −0.413 |

The High median is zero. About half of High days are positive. Twelve days of +10 cents or more contribute +0.313 cents, more than the whole +0.283 mean. The other 114,484 High contract-days contribute −0.136 cents together. Several of the largest High names have a weight of exactly 1/884, which means that one contract was the entire High portfolio on that date.

The same pattern is in the Low leg, and it is stronger there: the top 20 Low contract-days contribute +0.487 cents and the rest contribute −0.413. The Low mean stays near +0.07 because those two pieces nearly cancel. They do not cancel in High. The body of the High leg is mildly negative (−0.136 once the twenty largest up-moves are set aside). That remainder is near the paper's −0.171, but dropping the largest positive days after seeing them is not a replication.

## Settlement, extreme prices, and extreme open interest

Weights are the portfolio weights above, not raw contract counts. "Contribution" is the slice's piece of the 884-date mean, in cents. The slice mean is that contribution divided by the slice's weight.

| Slice | High days | High weight | High contribution | High slice mean | Low weight | Low contribution | Low slice mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Next-day close | 90.2% | 96.8% | +0.236 | +0.244 | 93.8% | +0.101 | +0.108 |
| Settlement | 9.8% | 3.2% | +0.046 | +1.434 | 6.2% | −0.027 | −0.446 |
| Price ≤ 0.05 | 19.9% | 30.9% | −0.011 | −0.037 | 78.7% | +0.088 | +0.105 |
| Price ≥ 0.95 | 6.1% | 5.5% | +0.016 | +0.291 | 0.1% | +0.003 | +0.803 |
| Price ≤ 0.05 or ≥ 0.95 | 26.0% | 36.4% | +0.005 | +0.012 | 78.7% | +0.091 | +0.108 |
| Price strictly inside (0.05, 0.95) | 74.0% | 63.6% | +0.278 | +0.437 | 21.3% | −0.017 | −0.114 |
| OI at or above that leg's p99 | 1.0% | 12.1% | +0.010 | +0.080 | 1.0% | +0.004 | +0.027 |
| Trump 253591 | 174 days | 4.4% | +0.008 | +0.192 | 0 | 0 | |
| Harris 253597 | 136 days | 1.8% | +0.003 | +0.175 | 2 days | −0.000 | −0.218 |
| Trump or Harris | 310 days | 6.2% | +0.011 | +0.187 | 0.1% | −0.000 | −0.218 |

High-leg open-interest p99 is 16,633,280 shares. Low-leg p99 is lower and is stored in `diagnostic_yesmv_high_meta.csv`. Settlement is 3.2% of High weight and adds +0.046 cents. Prices at the 0.05 / 0.95 edges are 36% of High weight and add +0.005 cents. The top 1% of High open interest is 12% of the weight and adds +0.010 cents. Trump and Harris together add +0.011 cents. None of those slices is the +0.283.

The interior-price High names, the ones between 0.05 and 0.95, contribute +0.278 of the +0.283. Their own weighted mean is +0.437 cents. That is where the positive sign sits, and the top rows show it is a few large overnight moves rather than a small positive drift on every name.

## Largest High contributions

Each line is one contract-day. Contribution is in cents of the 884-date High mean. A weight of 0.001131 is 1/884, so that contract was the whole High portfolio that day.

| Date | Market | Price | Endpoint | Return | Contribution |
| --- | --- | ---: | --- | ---: | ---: |
| 2023-11-18 | Israel and Hamas ceasefire in 2023? | 0.40 | next close | +37.0¢ | +0.042 |
| 2023-03-12 | Uninsured SVB depositors repaid by June 30? | 0.67 | next close | +31.0¢ | +0.035 |
| 2023-11-21 | Sam back as CEO of OpenAI? | 0.68 | next close | +29.0¢ | +0.033 |
| 2023-07-21 | Barbie gross over $150m on opening weekend? | 0.66 | next close | +28.0¢ | +0.032 |
| 2023-11-20 | Israel and Hamas ceasefire by Nov 30? | 0.56 | next close | +27.0¢ | +0.031 |
| 2024-04-21 | Will another player win FIDE Candidates 2024? | 0.44 | settlement | +56.0¢ | +0.030 |
| 2024-03-09 | US government shutdown by Mar 23? | 0.68 | next close | +25.6¢ | +0.029 |
| 2023-10-27 | Israel major ground offensive in Gaza by Oct 31? | 0.65 | next close | +22.5¢ | +0.025 |

The full top 20 for both legs is `diagnostic_yesmv_high_top.csv`. The Low control's largest names are the same kind of event: a thin book and a one-day jump of tens of cents, not the 2024 presidential markets.

## 结论

High 腿的中位数是 0，不是 −0.17 分。均值被少数大涨日拉到 +0.28 分：12 个日收益至少 +10 分的日子就贡献了 +0.31 分；贡献最大的 20 个合约日合计 +0.42 分，其余大约 11.4 万个合约日合计 −0.14 分。这 20 个里有不少当天独占了整个 High 组合，权重正好是 1/884。

结算日只占 High 权重的 3%，贡献 +0.05 分。价格在 0.05 以下或 0.95 以上占了 36% 的权重，贡献几乎为 0。持仓量处于本腿 99 分位以上的名字占 12% 的权重，贡献 +0.01 分。Trump 和 Harris 合计也只有 +0.01 分。这些都不是 +0.28 的来源。

Low 腿有同样的大涨日，但其余合约日更负（−0.41 分），所以 Low 的均值停在 +0.07，和论文的 +0.08 接近。High 的其余部分只有 −0.14 分，盖不住那些大涨。因此 High 的符号差，最可能来自少数单日大幅上涨在“每天等权”里的杠杆，而不是结算、极端价格或超大持仓量。把最大的上涨事后拿掉以后，剩下的 −0.14 分接近论文的 −0.17，但这不是论文的算法，不能当成已经对上。
