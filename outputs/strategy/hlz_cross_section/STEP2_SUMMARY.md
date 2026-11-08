# HLZ Step 2 / YESMV and log odds ratio

Window / 窗口: **2026-11-01** through **2026-11-06** (formation dates, 4:00 p.m. Eastern).
OI anchor date / 使用公开 OI 快照的形成日: **2026-11-06**.
OI snapshot taken / 快照时间: 2026-11-08T03:18:32Z.
Hours from that formation to the snapshot / 形成时点到快照的小时数: 30.31.

## Paper definitions / 论文定义

Formation, from the paper:

> We set a common formation time of 4:00 p.m. Eastern Time and account for daylight saving time. The formation price is the most recent valid hourly observation at or before that time. We use its closing transaction price when available and the midpoint of a valid two-sided quote otherwise. All lookbacks end at the formation time, so no post-formation observation enters a characteristic.

Portfolio sample, from the paper:

> The portfolio sample imposes two further requirements. The price source must be no more than two hours old, and the contract must have traded on at least one day during the preceding seven calendar days. These restrictions limit measurement error from stale prices and prolonged nontrading. Open interest is the latest observation available at or before formation and is never filled backward from future data. The two-hour limit applies only to execution prices, not to this stock variable.

Equations:

> (1) YESMV_{i,t} = P^form_{i,t} × OI_{i,t}

> (2) R^{pp}_{i,t+1} = P^end_{i,t+1} − P^form_{i,t}

> For each contract-day, the holding period ends at settlement or at 4:00 p.m. on the following Eastern calendar day, whichever occurs first.

> (5) LOR_{i,t}(h) = logit(P^form_{i,t}) − logit(P^form_{i,t−h}), logit(p) = log[p/(1−p)], h = 1,...,6

> We winsorize each continuous characteristic at the first and 99th percentiles of its formation-date–category cross-section and assign contracts to Low, Middle, and High portfolios using the 30th and 70th percentiles.

Within a category, contract price changes are weighted by formation-time raw open interest (Eq. 3). Category portfolios are aggregated with the matched category set and presort category open interest (Eq. 4). High−Low is reported in cents per YES claim. Newey–West uses seven lags when at least two dates exist.

## Polymarket mapping / 映射

Universe: Step 1 `paper_sample_markets.csv` (cumulative volume ≥ 10,000 USD notional, scheduled life ≥ 2 days, opening date on or before the Step 1 sample end). This run keeps YES-token contracts with `closed_mode=open`. Markets in the run: 5364. The paper's Polymarket appendix uses cumulative volume above 2,000 and a chain-reconstructed open-interest path. This Step 2 file does not replace the Step 1 screen with that 2,000 cutoff.

Formation price: CLOB `GET /prices-history` for the YES token, `fidelity=60` (about one point per hour). P^form is the latest point at or before 4:00 p.m. America/New_York. The feed has a single price, not a separate closing trade and a two-sided quote, so there is no trade-then-midpoint fallback. The portfolio sample keeps a price only when that point is at most two hours old.

Traded in the preceding seven Eastern calendar dates: at least one `prices-history` point falls on one of those dates. The feed does not flag a print as a trade, so a carried hourly price can satisfy the screen. That is wider than the paper's transaction test.

Endpoint: recorded YES settlement if Gamma `closedTime` is at or before the next 4:00 p.m. Eastern and the YES outcome price is 0 or 1. Otherwise the next calendar day's 4:00 p.m. price, under the same two-hour rule.

Category: one Gamma tag per contract. A slug in a fixed broad list (sports, politics, crypto, business, and the rest in the script) wins when several tags are present. Otherwise the first tag is the category. This is not Kalshi's official category field.

### Open interest / 未平仓量

The paper's Polymarket appendix says open interest at 4:00 p.m. Eastern is reconstructed from Polygon CTF and negative-risk lifecycle events. Gamma and CLOB do not publish that history. Data API `GET /v2/oi` returns the current priced gross open interest in USDC:

> Σ ((shares − fee_receiver_shares) / 1e6 · outcome_price) across outcomes, with no netting.

It is one snapshot for the whole life of the request, not a value as of 4:00 p.m. on each formation date. Copying it backward would put later position changes into earlier characteristics, which the paper rules out. This run attaches the snapshot only on the latest formation date whose next 4:00 p.m. mark is already in the price history. The snapshot is still after that 4:00 p.m. The lag in hours is above. Share proxy: oi_shares = oi_usdc / (P^form + (1 − P^form)) = oi_usdc, using the complementary NO price because the NO print is not in the YES history. YESMV = P^form × oi_shares. The price is not used by itself as the size measure.

How this can differ from the paper: ranks and weights move if open interest changed between 4:00 p.m. and the snapshot; priced-gross USDC equals the raw contract count only when YES and NO prices sum to one; the High−Low mean is a one-date cross-section when only one formation date receives OI, so it is not the paper's multi-year Newey–West mean.

未平仓量只有当前快照，没有每个形成日 16:00 的历史。快照只挂在最近一个已经能观察到下一交易日 16:00 价格的形成日上，不回填到更早的日期。YESMV 仍是形成价乘以份额代理，而不是单独用价格。

## This run / 本次结果

- Factor rows / 因子行数: 30686
- Portfolio-sample rows / 进入组合的行数: 4648
- Formation dates in the panel / 面板中的形成日数: 6
- Dates with a High−Low portfolio / 能算出多空组合的日期数: 1
- Mean High−Low YESMV: -0.2415 cents over 1 date(s), Newey-West t = n/a (fewer than two dates)
- Mean High−Low LOR(1): -0.3936 cents over 1 date(s), Newey-West t = n/a (fewer than two dates)

Cents are R^{pp} times 100. A negative High−Low means the high characteristic has the lower subsequent price change.

### Spreads / 价差（美分）

| Characteristic | Dates | Low | Middle | High | High−Low | NW t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| yesmv | 1 | -0.0258 | 0.0006 | -0.2673 | -0.2415 |  |
| lor_1 | 1 | -0.0235 | 0.0325 | -0.4172 | -0.3936 |  |
| lor_2 | 1 | -0.0209 | -0.0199 | -0.5157 | -0.4949 |  |
| lor_3 | 1 | 0.1156 | -0.2101 | -0.5484 | -0.6640 |  |
| lor_4 | 1 | 0.0844 | -0.1473 | -0.6811 | -0.7655 |  |
| lor_5 | 1 | 0.0894 | -0.3330 | -0.4307 | -0.5200 |  |
| lor_6 | 1 | -0.0276 | -0.0900 | -0.6241 | -0.5965 |  |

Category counts in the portfolio sample:

- Politics: 1445
- Sports: 862
- Crypto: 641
- Culture: 365
- Finance: 289
- Tech: 279
- Business: 217
- Geopolitics: 129
- Science: 69
- Weather: 60
- World: 53
- Fed: 30

Rebuild / 重跑:

```bash
python3 scripts/strategy/hlz_cross_section/build_factors.py --self-test
python3 scripts/strategy/hlz_cross_section/build_factors.py --start-date 2026-11-01 --end-date 2026-11-06
```
