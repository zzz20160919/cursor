# HLZ Step 3 portfolios

官方口径是 7 个 vgregoire 类别、N=5、没有权重上限。同一形成日、同一类别里，Low 和 High 各至少 5 个不同市场；任一不足则该类别日剔除，两腿只用共同留下的类别。
其余仍按论文：类别内 1% / 99% winsorize，30% / 70% 分位只决定成员身份，raw open interest 两阶段加权，结果是下一期 YES 价格变动（美分/张），Newey–West 滞后 7 期。
价格仍是两小时内的小时收盘，没有重跑价格或持仓，也没有换成 12 类。12 类对照仍在 `STEP3_CATEGORY12_SENSITIVITY.md`。

The input is the Step 2 portfolio sample in `a3_factor_daily.parquet`. Sample end remains 2026-03-29. Categories are Politics, Sports, Crypto, Culture, Finance, Tech, and Weather.

## Official table

| Characteristic | Dates | Low | Middle | High | High−Low | NW(7) t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YESMV | 671 | 0.057 | 0.005 | -0.043 | **-0.100** | -3.59*** |
| Open interest | 671 | 0.118 | -0.010 | -0.026 | **-0.144** | -2.36** |
| Formation price | 671 | -0.001 | -0.039 | -0.009 | **-0.008** | -0.12 |
| LOR(1) | 653 | 0.031 | -0.007 | -0.057 | **-0.088** | -0.79 |
| LOR(2) | 648 | 0.074 | -0.066 | -0.070 | **-0.145** | -1.56 |
| LOR(3) | 652 | 0.032 | -0.055 | 0.050 | **0.019** | 0.16 |
| LOR(4) | 649 | 0.087 | -0.075 | 0.018 | **-0.069** | -0.59 |
| LOR(5) | 647 | 0.058 | -0.026 | 0.052 | **-0.006** | -0.05 |
| LOR(6) | 646 | 0.028 | -0.013 | -0.009 | **-0.037** | -0.34 |

Stars use the normal two-sided cuts 1.645 / 1.96 / 2.576.

## 与旧官方、与论文

旧官方不设最少合约数：YESMV 884 天，High−Low +0.208871，t 1.2140。论文 IA.15 没有披露天数。

| Characteristic | Dates | High−Low | t | 旧官方天数 | 旧官方 High−Low | 旧官方 t | IA.15 Low | IA.15 High | IA.15 High−Low | IA.15 t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| YESMV | 671 | -0.100 | -3.59 | 884 | +0.209 | 1.21 | +0.084 | -0.171 | -0.255 | -5.81 |
| Open interest | 671 | -0.144 | -2.36 | 884 | -0.013 | -0.07 | -0.191 | -0.122 | +0.069 | 1.18 |
| Formation price | 671 | -0.008 | -0.12 | 880 | +0.298 | 1.46 | -0.024 | -0.240 | -0.216 | -2.54 |
| LOR(1) | 653 | -0.088 | -0.79 | 755 | -0.086 | -0.40 | +0.121 | -0.604 | -0.725 | -5.29 |
| LOR(2) | 648 | -0.145 | -1.56 | 729 | -0.229 | -1.04 | +0.151 | -0.452 | -0.603 | -4.39 |
| LOR(3) | 652 | 0.019 | 0.16 | 730 | -0.005 | -0.04 | +0.046 | -0.492 | -0.538 | -4.22 |
| LOR(4) | 649 | -0.069 | -0.59 | 722 | +0.090 | 0.51 | +0.133 | -0.420 | -0.553 | -4.40 |
| LOR(5) | 647 | -0.006 | -0.05 | 717 | +0.011 | 0.09 | +0.180 | -0.387 | -0.566 | -4.87 |
| LOR(6) | 646 | -0.037 | -0.34 | 710 | -0.011 | -0.08 | +0.125 | -0.376 | -0.501 | -3.96 |

YESMV：671 天，Low +0.056947，High -0.043212，High−Low -0.100159，t -3.5895。相对旧官方，天数从 884 减到 671，High−Low 从 +0.208871 变成 −0.100159。论文 IA.15 是 Low +0.084，High −0.171，High−Low −0.255，t −5.81。新的价差方向与论文相同，幅度大约是论文的四成，High 仍远没有到 −0.171。
LOR：LOR(1) 653 天，Low +0.031，High -0.057，High−Low -0.088，t -0.79；LOR(2) 648 天，Low +0.074，High -0.070，High−Low -0.145，t -1.56；LOR(3) 652 天，Low +0.032，High +0.050，High−Low +0.019，t 0.16；LOR(4) 649 天，Low +0.087，High +0.018，High−Low -0.069，t -0.59；LOR(5) 647 天，Low +0.058，High +0.052，High−Low -0.006，t -0.05；LOR(6) 646 天，Low +0.028，High -0.009，High−Low -0.037，t -0.34。论文对应的 High−Low 是 −0.725、−0.603、−0.538、−0.553、−0.566、−0.501。

## What this is not

- Not a replication of Table IA.15. The paper's YESMV High−Low is −0.255 cents (t = −5.81). This table is −0.100 cents (t = −3.59) over 671 dates.
- The paper can price a contract with a two-hour quote midpoint when the last trade is older than two hours. This panel cannot.
- These sorts use seven vgregoire categories, not the 12-class map.
- There is no single-name weight cap.
- Open interest and formation price are included because they are already on the factor panel. Seven-day maximum price, maturity, volume, and liquidity sorts are not on the panel.
- Bid–ask and cost-of-arbitrage sorts are omitted in the paper's Polymarket table and are omitted here.
- Step 4 is not started. The 12-class comparison is unchanged.

Daily series: `outputs/strategy/hlz_cross_section/step3_spreads_daily.csv`.
