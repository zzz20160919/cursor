# HLZ Step 3 portfolios

这是我们自己的分组结果，不是表 IA.15 的复述。价格仍是两小时内的小时收盘，类别仍是 vgregoire 的 7 个粗类。

The input is the Step 2 portfolio sample in `a3_factor_daily.parquet`. Prices, the volume screen, and open interest are not rebuilt. Within each formation date and `markets.category`, the characteristic is winsorized at the 1st and 99th percentiles of that cell. Low / Middle / High use the 30th and 70th percentiles of the winsorized values. Those breakpoints decide membership only. Contracts are weighted by formation-time raw open interest. A category enters the day only when Low, Middle, and High are all non-empty. Category portfolios are then weighted by that category's total open interest measured before the sort. The reported number is the mean next-period price change in cents per YES claim. t-statistics are Newey–West with 7 lags on the daily High−Low series.

Sample end remains 2026-03-29. Categories are Politics, Sports, Crypto, Culture, Finance, Tech, and Weather.

## Our table

| Characteristic | Dates | Low | Middle | High | High−Low | NW(7) t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YESMV | 884 | 0.074 | -0.164 | 0.283 | **0.209** | 1.21 |
| Open interest | 884 | 0.289 | -0.231 | 0.276 | **-0.013** | -0.07 |
| Formation price | 880 | -0.076 | 0.213 | 0.222 | **0.298** | 1.46 |
| LOR(1) | 755 | 0.250 | 0.133 | 0.164 | **-0.086** | -0.40 |
| LOR(2) | 729 | 0.193 | -0.077 | -0.036 | **-0.229** | -1.04 |
| LOR(3) | 730 | 0.094 | -0.090 | 0.089 | **-0.005** | -0.04 |
| LOR(4) | 722 | 0.026 | 0.000 | 0.117 | **0.090** | 0.51 |
| LOR(5) | 717 | -0.024 | -0.056 | -0.013 | **0.011** | 0.09 |
| LOR(6) | 710 | 0.040 | -0.075 | 0.029 | **-0.011** | -0.08 |

Stars use the normal two-sided cuts 1.645 / 1.96 / 2.576. None of the required YESMV or LOR spreads reach the 10% cut on this sample.

## Side by side

The diagnostic High−Low means are the earlier raw-open-interest sorts on this same panel. They match this table. The diagnostic t-statistics were computed on the daily series in storage order, not calendar order, so they are not repeated as the inference. The t-statistics in this table are Newey–West with 7 lags on the calendar-ordered High−Low. IA.15 is the paper's Polymarket sort. It can use a quote midpoint when no fresh close exists, and it uses an official category this file does not contain.

| Characteristic | Our High−Low | Our t | Diagnostic High−Low | IA.15 High−Low | IA.15 t |
| --- | ---: | ---: | ---: | ---: | ---: |
| YESMV | 0.209 | 1.21 | 0.208871 | -0.255 | -5.81 |
| Open interest | -0.013 | -0.07 |  | 0.069 | 1.18 |
| Formation price | 0.298 | 1.46 |  | -0.216 | -2.54 |
| LOR(1) | -0.086 | -0.40 | -0.086138 | -0.725 | -5.29 |
| LOR(2) | -0.229 | -1.04 | -0.228806 | -0.603 | -4.39 |
| LOR(3) | -0.005 | -0.04 | -0.005322 | -0.538 | -4.22 |
| LOR(4) | 0.090 | 0.51 | 0.090265 | -0.553 | -4.40 |
| LOR(5) | 0.011 | 0.09 | 0.010740 | -0.566 | -4.87 |
| LOR(6) | -0.011 | -0.08 | -0.011034 | -0.501 | -3.96 |

## What this is not

- Not a replication of Table IA.15. The paper's High−Low YESMV is −0.255 cents (t = −5.81). Ours is positive and insignificant.
- The paper can price a contract with a two-hour quote midpoint when the last trade is older than two hours. This panel cannot.
- The paper's official category is unnamed. These sorts use seven vgregoire categories.
- Open interest and formation price are included because they are already on the factor panel. Seven-day maximum price, maturity, volume, and liquidity sorts are not on the panel and are not filled in.
- Bid–ask and cost-of-arbitrage sorts are omitted in the paper's Polymarket table and are omitted here.
- Step 4 is not started.

Daily series: `outputs/strategy/hlz_cross_section/step3_spreads_daily.csv`.

中文：YESMV 的 High−Low 是 +0.209 分，按日历排序的 Newey–West t 是 1.21，和论文的 −0.255 分（t = −5.81）方向相反。LOR(1) 是 -0.086 分（t = -0.40），LOR(2) 到 LOR(6) 也都接近零且不显著。这些均值和诊断表里的原始持仓量加权结果一致。
