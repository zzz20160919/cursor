# HLZ Step 2 full sample

价格只用 vgregoire 小时 K 线的 `close`（该小时最后一笔成交），且这根 K 线的开端距美东 16:00 不超过 2 小时。没有 Dome，没有报价中点。
样本是附录 A.3：Gamma 累计成交额严格大于 2,000 美元名义，观察存续至少 2 天，开始日不晚于 2026-03-29。每个 condition 只保留一个 YES（没有 YES 标签时用 outcome 0）。

Price sample: 2022-11-21 through 2026-03-29. Hourly files run 2022-11-21 through 2026-03-29. vgregoire has no file for 2026-03-30, so formation dates stop at 2026-03-29. The next-day close for 2026-03-29 does not exist; that date enters the portfolio only when settlement supplies the endpoint.

## Universe versus the earlier ≥10,000 screen

Earlier Step 1 file (volume ≥ 10,000, scheduled life, sample end 2026-11-07): 277481 contracts, 128063 events (5862 open, 271619 closed).
This A.3 file (volume > 2,000, observed life, sample end 2026-03-29): 178408 contracts, 72497 events (2482 open, 175926 closed). Volume stats: min 2000.128, median 21722.848375, mean 353685.2227819832.
旧的 ≥10,000 文件保留作对照，不是这一次的样本。

## Coverage

Universe conditions with a condition id: 178408. With a YES or outcome-0 token in vgregoire predictions: 178025.
Alive contract-days (open, not yet closed, expiry still ahead): 3882837.
Contract-days with a ≤2h hourly close: 737834 across 124433 conditions.
Those closes that are also active at formation: 679124.
Active closes with a CTF open-interest observation: 679124. With positive raw OI: 678884.
Portfolio sample (active, positive OI, a trade on one of the prior 7 Eastern days, a category, and a next-period price): 379371.
Harris 2024-10-30 replay check: OI 118579214.28 (relative gap 0.000000 versus the earlier 25-contract run).

## High minus Low

Sorts are inside a date and a vgregoire category, 1st/99th winsorize, 30th/70th legs, raw-OI weights, then category-OI weights. Units are cents of price change.
YESMV: 0.2089 cents over 884 dates.
LOR(1): -0.0861 cents over 755 dates.
LOR(2): -0.2288 cents over 729 dates.
LOR(3): -0.0053 cents over 730 dates.
LOR(4): 0.0903 cents over 722 dates.
LOR(5): 0.0107 cents over 717 dates.
LOR(6): -0.0110 cents over 710 dates.
这些是本仓库按上述数据截止日算出的价差，不是论文表 IA.15 的复述。

## Remaining Appendix A.3 gaps

- Dome hourly prices are not available. There is no bid, ask, or quote midpoint. LOR uses the hourly close only.
- The trade's exact second inside the hour is not in the file. Age is measured from the bar open, which is the older bound.
- Hourly bars end 2026-03-29. The paper's TimeSeventeen archive continues to 2026-04-28. Seven days in late 2022 have no hourly file (2022-11-24, 2022-11-25, 2022-11-26, 2022-11-27, 2022-12-04, 2022-12-05, 2022-12-10).
- Category is `vgregoire/polymarket-users` `markets.category`. The paper says official category and does not name the column. TimeSeventeen `category_refined` is downloaded only for the 15-day pilot window, so it is not the full-sample category.
- Open interest counts root complete-set splits, merges, and redemptions whose collateral is USDC.e, native USDC, or the neg-risk wrapper `0x3a3bd7bb9528e159577f7c2e685cc81a765002e2`. One unit of collateral is one complete set. Lifecycle rows that never appear in those CTF tables are absent, not filled in.
- Block time is linear between anchors 500 blocks apart. Blocks within 15 minutes of a 4:00 p.m. cutoff are read exactly. The largest interpolation error on those exact blocks in this run is 245 seconds. The run aborts if that error can reach the cutoff (half of the 15-minute window).
- Cached Gamma bands at volume ≥ 10,000 did not store `closedTime`. Those rows were backfilled. A market that still has no `closedTime` uses expiry, capped at the sample-end day, as the observed end.
- Newey–West standard errors are not computed. Bid–ask and cost-of-arbitrage sorts are not in the Polymarket tables and are not computed here.
- Step 3 is not started. The withdrawn `/v2/oi` snapshot is not an input.

Factor table: `outputs/strategy/hlz_cross_section/a3_factor_daily.parquet`. Daily spreads: `outputs/strategy/hlz_cross_section/a3_spreads_daily.csv`.
