# Price check for the 20 largest YESMV High contributions

Each row is one contract-day from `diagnostic_yesmv_high_top.csv`. The check compares the factor panel with the raw `vgregoire` hourly file for that token, the CTF resolution clock when settlement is the endpoint, and a CLOB `prices-history` sample (fidelity 60) near the same bar. No portfolio rule was changed.

`data_check` is pass when all of these hold: the panel close equals the raw hourly close, the bar is the latest hour that ends by 4:00 p.m. Eastern and opened no more than two hours earlier, the token is Yes or outcome index 0, the endpoint matches the next eligible close or a resolution inside the holding window, and the cent change equals `P_{t+1} - P_t`.

All 20 rows pass. The jumps are in the hourly file or in the resolution timestamp. They are not a wrong token, a wrong hour, a timezone shift, a Yes/No swap, or a settlement assigned outside the window.

Fourteen of the twenty days have one name in the High leg, so that contract's weight that day is 1. The other six share the day (`day_high_weight` below 1 in the CSV).

## What was compared

| Check | Result |
| --- | --- |
| Raw hourly close equals panel `P_t` | 20/20 |
| Bar is inside the two-hour window and is the later eligible hour | 20/20 |
| Token is Yes, or outcome 0 when the market has no Yes label | 20/20 |
| Endpoint matches the next close, or settlement payout and time | 20/20 |
| Cent change matches the table | 20/20 |
| Single name in that day's High leg | 14/20 |

CLOB `prices-history` is a sampled series, not the last trade. It sits within 5 cents of the hourly close on 14 rows and 5–15 cents away on 6 rows. The largest gap is the Nov 20 ceasefire bar: the raw bar opened at 0.39 and closed at 0.56, and the CLOB sample is 0.415. The panel used the close, which is the high of that bar. On the five rows where the Yes and No hourly closes do not sum to 1, the panel price is still the Yes print, not the No print. Those two closes are different trades inside the hour.

TimeSeventeen trade files on disk cover only 2024-10-23 through 2024-11-06, so none of these twenty dates can be checked against that local tape.

## Rows that look large but still match the file

- **2024-05-20, Ethereum ETF approved by May 31?** Formation close is 0.20 at 19:00 UTC (three trades, bar range 0.20–0.33). The next hour, which ends after 4:00 p.m., traded from 0.21 to 0.77 on 114 trades. The next day's eligible close is 0.67. The +47 cent change is the gap between a pre-4:00 p.m. print and the next day's print. The file shows the move; the two-hour rule does not let the post-4:00 p.m. hour into `P_t`.
- **2023-10-12, Israeli troops on the ground in Gaza.** `P_t` is 0.28. The next day's close is 0.90. During the next morning the same token already printed a bar from 0.18 to 0.99. Resolution to 1.00 is at 20:32 UTC on Oct 13, thirty-two minutes after the next 4:00 p.m., so the endpoint stays the 0.90 close. That timing is correct.
- **2024-03-09, US government shutdown by Mar 23.** The formation bar is a two-trade print at 0.68 after an hour that traded down to 0.50. The following hour closed at 0.96. The next day's close is 0.936. The +25.6 cents is that rebound in the hourly file. The CLOB sample near the bar is 0.805.
- **2023-11-20, ceasefire by Nov 30.** The formation bar opened at 0.39 and closed at 0.56 (five trades). The No token's close in that same hour is 0.58, so the two hourly closes cross. The panel still uses the Yes close. The next day's close is 0.83.
- **Settlements.** Four endpoints are resolutions, all payout 1 for the reference outcome, all inside the holding window, and none of those four has an eligible next-day close: FIDE Candidates on 2024-04-21 (0.44 to 1 at 03:38 UTC), Succession on 2023-05-28 (0.83 to 1 at 04:32 UTC), Trump mugshot on 2023-08-24 (0.83 to 1 at 03:31 UTC), and the Taiwan Hou-vs-Ko market on 2024-01-12. That last market has no Yes label. Outcome index 0 is Hou Yu-ih, and the predictions file marks that outcome as the winner, which matches payout 1.

Eight formation bars contain a single trade, including the +37 cent ceasefire print (0.40 to 0.77, one trade on each side). A one-trade close can be a thin print. It is still the close stored in the hourly file.

## 结论

这 20 个合约日的形成价都能在 vgregoire 原始小时文件里对上，用的是 4pm 前两小时内最后一根合格 K 线，代币是 Yes 或 outcome 0，下一期价格和美分变动也一致。没有发现错代币、错小时、时区错位、把 No 当成 Yes，或把窗口外的结算拿来当收盘价。

跳跃在源数据里。有的是一根只有一笔成交的收盘，有的是 4pm 之后那一小时已经大涨、但规则正确地没用那根 K 线。CLOB 的抽样价有时和小时收盘差 5 到 15 分，最大的一档收盘落在当根 K 线的最高价上，不是另一套价格被拼进来。

明细表：`outputs/strategy/hlz_cross_section/diagnostic_yesmv_high_price_check.csv`。
