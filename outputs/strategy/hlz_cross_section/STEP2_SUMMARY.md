# HLZ Step 2 strict pilot

The Data API `/v2/oi` snapshot used in the earlier Step 2 run is **invalid for inference**. It was observed after 4:00 p.m. Eastern formation, so those YESMV ranks and open-interest weights are not the paper's.

This file is a **pilot**, not the full Polymarket sample in Appendix A.3.

Formation window: 2024-10-30 through 2024-11-05, 4:00 p.m. America/New_York.
Step 1 contracts in this pilot: 25. Of those, 25 have at least one usable hourly close at a 4:00 p.m. slot.

价格来源是论文备用的 vgregoire 小时 OHLCV 的 `close`（该小时最后一笔成交）。没有买卖报价中点，LOR 只用这个收盘价的 logit。
Factor rows: 160. Portfolio-sample rows: 150.
Mean High−Low YESMV: 1.0645 cents over 7 verified date(s).
Mean High−Low LOR(1): 3.3782 cents over 6 verified date(s).

## What the paper says

Section 3.2 (PDF page 7): formation is 4:00 p.m. Eastern, daylight-saving aware. The price is the most recent valid hourly observation at or before that time: the closing trade when one exists, otherwise the midpoint of a valid two-sided quote. Lookbacks end at formation. The portfolio sample also requires the price source to be no more than two hours old and a trade on at least one of the preceding seven calendar days. Open interest is the latest observation at or before formation and is never filled from the future. The two-hour limit does not apply to that stock variable.

Section 3.3 equations (1) and (2), PDF page 8: `YESMV = P^form × OI` and `R^pp = P^end − P^form`. The holding period ends at settlement or at 4:00 p.m. the next Eastern day, whichever is first.

Section 3.4 equations (3) and (4), PDF page 9: within a category, weight by formation-time raw open interest; across categories, use the matched set and presort category open interest.

Section 4.1 equation (5), PDF page 10: `LOR(h) = logit(P^form_t) − logit(P^form_{t−h})` for h = 1..6, with characteristics winsorized at the 1st and 99th percentiles of the date–category cell and split at the 30th and 70th.

Appendix A.3, PDF page 70: Polymarket definitions and settlements come from official metadata; transactions come from `TimeSeventeen/Polymarket-v1`; Dome hourly prices are primary and `vgregoire/polymarket-users` hourly OHLCV is the fallback; 4:00 p.m. open interest is reconstructed from Polygon CTF and negative-risk lifecycle events via Dune and TimeSeventeen. The appendix sample uses cumulative volume above 2,000, life of at least two days, and a start date no later than April 28, 2026, keeps one outcome per condition (typically YES), and includes standard and negative-risk binaries. It then requires a fresh price, an active contract, positive raw open interest, a trade in the prior seven calendar days, and a next price change.

Table IA.15 notes, PDF page 66: sort within formation date and official category at the 30th and 70th percentiles, weight by raw open interest, then aggregate with presort category open interest.

## Interfaces actually used

- Price: `vgregoire/polymarket-users` `ohlcv_1h` (the appendix A.3 fallback; Dome returned HTTP 503 and is not used). `timestamp` is the UTC start of the hour. `close` is the last trade in that hour. There is no bid, ask, or midpoint, so LOR uses logit of that close only. The bar counts only if it ends at or before 4:00 p.m. Eastern and the bar start is no more than two hours earlier, because the close can be as old as the start of the hour. The token is the Yes outcome when `predictions.outcome` is Yes, otherwise outcome index 0. The No token is not a second contract.
- Open interest: `CTF/splits.parquet`, `merges.parquet`, and `redemptions.parquet`. `usdc_amount` is the dataset's USDC.e collateral notional. On Polymarket, one unit of that collateral mints one complete set, so the net is the raw complete-set count. Only root positions (`parent_collection_id` all zeros), collateral USDC.e, native USDC, or the neg-risk wrapper `0x3a3b…002e2`, and partition `{1,2}` enter the sum. Split adds, merge and redemption subtract. The block number is parsed from `chainId_blockNumber_logIndex` because these tables have no timestamp column. Block time and hash come from Polygon `eth_getBlockByNumber` on `polygon-bor-rpc.publicnode.com`. A changed hash aborts the run.
- Settlement: `CTF/resolutions.parquet` `payout_numerators`. `['1','0']` pays 1 on the reference outcome and `['0','1']` pays 0. The resolution counts only when its block time is at or before the next 4:00 p.m. `resolved_at` on the trade file is not used; it is frozen metadata and can post-date the fill.
- Universe: every Step 1 contract, open or settled, whose slug matches `market_slug` in the loaded days. Step 1's 10,000 volume screen is stricter than the appendix's 2,000 cutoff. This pilot does not rebuild the appendix's 3,507,194 contract-days.
- Category: `category_refined` (Politics, Sports, Crypto, and the other cleaned buckets). The raw `category` field is a fine label such as Trump or Mentions. The paper says official category and does not name this column. Sorts use the refined field and keep the raw label beside it.

## Not used

Current `/v2/oi`, Gamma `openInterest`, cumulative volume, liquidity, CLOB `prices-history`, and Dome. A formation with no hourly bar inside the two-hour window is missing. It is not filled with a quote midpoint, because this OHLCV file does not have one.

## Hourly coverage / 小时线覆盖

All 25 pilot contracts have at least one usable 4:00 p.m. close. Six contract-days have no bar inside the two-hour window: Tim Walz on 2024-10-30, 2024-11-01, and 2024-11-02; Dinamo Zagreb and Red Star Belgrade on 2024-11-01; Lille on 2024-11-03. Those slots stay missing. They are not filled with a midpoint.

25 个合约都至少有一个可用的下午 4 点收盘价。上面 6 个合约日没有落在两小时窗口内的小时线，保持缺失。

## Coverage

```
{
  "alive_contract_days": 160,
  "portfolio_sample": 150,
  "no_trade_at_or_before_formation": 6,
  "already_expired": 15,
  "block_time_max_abs_error_seconds": 38
}
```

Rebuild:

```bash
bash scripts/strategy/hlz_cross_section/download_pit.sh
python3 scripts/strategy/hlz_cross_section/hlz_paper.py
python3 scripts/strategy/hlz_cross_section/build_factors.py
```
