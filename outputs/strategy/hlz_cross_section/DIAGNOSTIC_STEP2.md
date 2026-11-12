# Step 2 diagnostic: why High−Low differs from Table IA.15

This note does not change the locked price or universe rules and does not start Step 3. Formation price remains the vgregoire hourly close, and only a bar that opened no more than two hours before 4:00 p.m. Eastern is used. The universe remains lifetime volume strictly above 2,000 USD notional, observed life at least 2 days, and one YES (or outcome 0) token per condition.

Table IA.15 (PDF page 66) reports mean next-period price changes in cents. Parentheses in the paper are Newey–West t-statistics with 7 lags. The two rows this note focuses on:

| Characteristic | Paper Low | Paper Middle | Paper High | Paper High−Low | Paper t |
| --- | ---: | ---: | ---: | ---: | ---: |
| YES market value | 0.084 | −0.020 | −0.171 | **−0.255** | −5.81 |
| LOR(1) | 0.121 | −0.086 | −0.604 | **−0.725** | −5.29 |
| LOR(2) | 0.151 | −0.147 | −0.452 | **−0.603** | −4.39 |
| LOR(3) | 0.046 | −0.106 | −0.492 | **−0.538** | −4.22 |
| LOR(4) | 0.133 | −0.112 | −0.420 | **−0.553** | −4.40 |
| LOR(5) | 0.180 | −0.171 | −0.387 | **−0.566** | −4.87 |
| LOR(6) | 0.125 | −0.099 | −0.376 | **−0.501** | −3.96 |

Paper LOR High−Low spreads are between −0.725 and −0.501, all significant at 1%. Ours are an order of magnitude smaller and, with 7 Newey–West lags, not distinguishable from zero.

## 1. Date alignment and the coverage funnel

The hourly files run from 2022-11-21 through 2026-03-29. Seven dates in that span have no hourly file: 2022-11-24, 2022-11-25, 2022-11-26, 2022-11-27, 2022-12-04, 2022-12-05, and 2022-12-10. The paper’s archive continues through 2026-04-28, thirty calendar days past our last price file. Those thirty days are about 2.4% of our 1,225-day span.

The aligned sample drops those seven missing-file dates and does not go past 2026-03-29. That is already the sample the factor table was built on. Recomputing High−Low on it reproduces the previous full-sample means to the reported digit (YESMV +0.208871 cents over 884 dates). The seven missing dates contain 732 alive contract-days with a reference token and zero portfolio rows.

Paper Appendix A.3: raw panel 3,507,194 contract-days, portfolio sample 898,019 (25.6% kept). Our alive count uses the same open / not-yet-closed / expiry-still-ahead rule as the factor panel.

| Stage | Contract-days | Share of paper raw | Share of paper portfolio |
| --- | ---: | ---: | ---: |
| Alive (open, not closed, expiry ahead) | 3,882,837 | 1.107 | 4.324 |
| Alive, no reference token in predictions | 49,846 |  |  |
| Alive with a token, close within 2 hours | 679,124 | 0.194 | 0.756 |
| Of those, positive raw open interest | 678,884 | 0.194 | 0.756 |
| Plus a trade on one of the prior 7 Eastern days | 633,856 | 0.181 | 0.706 |
| Plus a non-empty vgregoire category | 633,856 | 0.181 | 0.706 |
| Plus a next-period price (portfolio sample) | 379,371 | 0.108 | 0.422 |

The portfolio count is identical if the seven missing-file dates are dropped. Detail is in `diagnostic_funnel.csv` and `diagnostic_price_age.csv`.

Where the 3,832,991 alive days that have a reference token go:

| Last hourly close that had already ended by 4:00 p.m. | Contract-days | Share |
| --- | ---: | ---: |
| Within 2 hours (the only days we can price) | 679,124 | 17.7% |
| Stale, 2 to 6 hours | 459,625 | 12.0% |
| Stale, 6 to 24 hours | 612,777 | 16.0% |
| Stale, 1 to 7 days | 863,172 | 22.5% |
| Older than 7 days | 428,424 | 11.2% |
| No hourly close before formation | 789,137 | 20.6% |
| Formation date has no hourly file | 732 | 0.0% |

The paper’s price is the closing trade when one exists, otherwise the midpoint of a valid two-sided quote, and either source must be no more than two hours old. We have no quotes. Every alive day without a ≤2h close is a day the paper could still price with a midpoint. That set is 3,153,867 contract-days (82.3% of alive days with a token). It is an upper bound, not a count of valid quotes.

Two comparisons make the size of that hole concrete.

- Conditional on a ≤2h close, positive OI barely binds (240 days fail), the prior-7-day trade drops about 45,000 days, and category drops none. The next-period price then drops 254,485 days, from 633,856 to 379,371. Of the portfolio days that remain, 340,140 end at the next day’s ≤2h close and 39,231 end at settlement. The 254,485 that fail have neither. The two-hour close rule therefore binds twice: once at formation and once at the endpoint.
- The paper’s portfolio is 518,648 contract-days larger than ours (898,019 − 379,371). Thirty extra calendar days at our average of 339 portfolio names a day are on the order of 10,000 contract-days. The seven missing files are 732 alive days and no portfolio rows. The calendar window is a few percent of the count gap, not the gap itself. The formation-price screen alone leaves us with 679,124 days, already short of the paper’s final 898,019, before the endpoint screen removes another 254,485.

## 2. Open interest

On the 379,371 portfolio contract-days, raw open interest is heavily skewed. Harris on 2024-10-30 is 118,579,214 shares, YESMV 40,198,354. That row is large, and it is not the maximum. Trump on 2024-11-04 is 226,234,526 shares. The top of the book is the 2024 presidential complete-set, including many names priced near 0 or 1 with YESMV near 150,000 because the price, not the share count, is tiny.

| Stat | Value |
| --- | ---: |
| Median OI | 52,907 |
| p90 | 951,501 |
| p99 | 5,414,243 |
| Max | 226,234,526 |
| Share of summed OI in the top 1% of contract-days | 42.0% |
| Share of summed OI in the top 10% of contract-days | 75.4% |
| Share of mean OI in the top 1% of contracts | 44.1% |
| Share of mean OI in the top 10% of contracts | 78.6% |

Capping each date’s open-interest weights at that date’s 99th percentile does not move YESMV (still about +0.21 cents). Dropping contract-days above the date’s 99th percentile cuts the YESMV spread to +0.103 and pulls LOR(1) from −0.086 to −0.234 and LOR(2) from −0.229 to −0.509. Equal weights leave YESMV at +0.164 and make LOR(1) −0.383 and LOR(2) −0.501. None of these sign-matches Table IA.15 for YESMV. The less extreme weighting moves short-horizon LOR toward the paper and still leaves the spreads one to three times too small, with Newey–West t-statistics mostly below 2. The full grid is in `diagnostic_spreads.csv`. The largest rows are in `diagnostic_oi_extremes.csv`.

## 3. Category

Every priced contract-day has a non-empty `vgregoire` `markets.category`. There is no uncategorized mass in this panel. The distinct values are only seven:

| Category | Priced days | Portfolio days | Portfolio contracts |
| --- | ---: | ---: | ---: |
| Politics | 242,048 | 124,620 | 13,396 |
| Sports | 214,600 | 112,088 | 25,107 |
| Crypto | 94,122 | 52,475 | 14,994 |
| Culture | 73,703 | 39,027 | 7,074 |
| Finance | 54,404 | 24,642 | 4,358 |
| Tech | 36,761 | 17,752 | 2,667 |
| Weather | 22,196 | 8,767 | 5,566 |

On portfolio dates the median number of categories present is 7 and the maximum is 7. A category-day has a median of 25 contracts (mean 67). 1,014 category-days have fewer than three contracts, so they cannot form Low, Middle, and High. The paper sorts inside the official category and does not name the column. These seven labels are coarser than the fine labels seen on the 15-day TimeSeventeen pilot (Trump, USA Election, and similar). We cannot observe that official field, so we cannot rerun the sort on it.

## 4. Price source, restated

Of alive contract-days with a reference token, 17.7% have a close in the two-hour window and 82.3% do not. The paper would use a midpoint on a day whose last trade is stale or missing, but only when that quote itself is no more than two hours old. We cannot see those quotes. The 82.3% is the maximum set a midpoint could add. Inside the days we do price, the same rule removes another 254,485 names at the next endpoint.

## 5. High−Low on the aligned dates

Aligned dates are the dates with an hourly file, 2022-11-21 through 2026-03-29 excluding the seven missing files. Means match the previous full-sample table. t-statistics are Newey–West with 7 lags on the daily High−Low series. The paper’s t-statistics are from its own sample, not from ours.

| Characteristic | Dates | Low | Middle | High | High−Low | NW t | Paper High−Low | Paper t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| YESMV | 884 | 0.074 | −0.164 | 0.283 | **+0.209** | 1.03 | −0.255 | −5.81 |
| LOR(1) | 755 | 0.250 | 0.133 | 0.164 | **−0.086** | −0.42 | −0.725 | −5.29 |
| LOR(2) | 729 | 0.193 | −0.077 | −0.036 | **−0.229** | −0.96 | −0.603 | −4.39 |
| LOR(3) | 730 | 0.094 | −0.090 | 0.089 | **−0.005** | −0.04 | −0.538 | −4.22 |
| LOR(4) | 722 | 0.026 | 0.000 | 0.117 | **+0.090** | 0.55 | −0.553 | −4.40 |
| LOR(5) | 717 | −0.024 | −0.056 | −0.013 | **+0.011** | 0.07 | −0.566 | −4.87 |
| LOR(6) | 710 | 0.040 | −0.075 | 0.029 | **−0.011** | −0.08 | −0.501 | −3.96 |

The YESMV disagreement is not a parallel shift. Our Low leg (+0.074) is close to the paper’s Low leg (+0.084). Our High leg is +0.283 where the paper’s is −0.171. For LOR(1) the paper’s High leg is −0.604; ours is +0.164. Our own YESMV mean is about one standard error above zero. Treating the paper’s −0.255 as a fixed benchmark, the gap of 0.46 cents is a bit more than two of our standard errors (standard error ≈ 0.209 / 1.03 ≈ 0.20). The LOR(1) gap of 0.64 cents is about three of our standard errors. The estimates disagree. They are not estimated precisely enough, on this price sample, to look like the paper’s 1% results.

Weighting sensitivities on the same aligned dates:

| Scheme | YESMV High−Low | t | LOR(1) | t | LOR(2) | t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw open interest | +0.209 | 1.03 | −0.086 | −0.42 | −0.229 | −0.96 |
| Cap weights at the date’s p99 | +0.212 | 1.05 | −0.091 | −0.45 | −0.230 | −0.97 |
| Drop names above the date’s p99 | +0.103 | 0.53 | −0.234 | −1.41 | −0.509 | −2.49 |
| Equal weight | +0.164 | 0.78 | −0.383 | −1.73 | −0.501 | −2.23 |
| Table IA.15 | −0.255 | −5.81 | −0.725 | −5.29 | −0.603 | −4.39 |

## 结论

样本窗口不是主因。缺小时文件的 7 天只有 732 个存续日，对齐之后的 High−Low 与原先全样本完全一样。论文多出来的大约 30 天，按我们每天约 340 个组合合约估算，只占合约日缺口的很小一部分。

持仓量极不均匀，前 1% 的合约日占了权重合计的大约 42%，Harris 在 2024-10-30 的 1.19 亿份就是其中的极端值。把权重截到当日 99 分位、丢掉这些极端值，或者改成等权，YESMV 的 High−Low 仍然为正。所以持仓量加权解释不了 YESMV 的符号。等权会把短期 LOR 的价差放大，但仍然明显小于论文，而且大多不显著。

类别没有空白，但 `vgregoire` 只有 Politics、Sports、Crypto、Culture、Finance、Tech、Weather 这 7 个粗类。论文用的 official category 我们看不到，粗分类有可能把价差稀释掉，这一点无法单独证实。

能定量看清的是价格。大约 82% 的存续日在美东 16:00 前两小时内没有成交收盘价，论文在这些日子上还可以用两小时内的报价中点，我们没有报价。即便在已经有收盘价的日子里，下一期价格再去掉约 25 万个合约日。合约日数量上的缺口主要来自这条价格规则，而不是日期窗口。

符号和幅度则还不能收成单一原因。去掉超大持仓量之后 YESMV 依然为正，和论文的 −0.255 相反；LOR 的方向有时接近，幅度仍然偏弱。价格样本变薄是最大的可测差异，类别口径无法核对，因此 High−Low 为什么变号，目前仍不能下定论。
