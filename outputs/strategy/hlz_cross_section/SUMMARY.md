# HLZ Polymarket paper sample / Hou–Li–Zheng 论文样本

Sample end / 样本截止: **2026-11-07 UTC**.

The sample end date is the UTC date of this run unless `--end-date` set it. The Hou–Li–Zheng Kalshi archive cutoff is April 28, 2026. This file uses that date only when the command line passes it.

样本截止日是本次运行的 UTC 日期；若命令行传入 `--end-date`，则以该日期为准。Hou–Li–Zheng 论文的 Kalshi 档案截止日是 2026-04-28。只有命令行传入该日期时，这里才会使用它。

## Counts / 数量

| | |
| --- | ---: |
| Contracts / 合约 | 277,481 |
| Events / 事件 | 128,063 |
| Open contracts / 未结束合约 | 5,862 |
| Closed or settled contracts / 已结束或已结算合约 | 271,619 |
| Contracts with no parent event id / 没有父事件 id 的合约 | 2 |

## Cumulative volume / 累计成交量

Unit / 单位: USD notional (`volumeNum`, else `volume`) / 美元名义金额，不是论文里的合约张数。

| | USD notional |
| --- | ---: |
| min | 10,000.00 |
| median | 37,856.59 |
| mean | 327,626.19 |
| p90 | 408,387.80 |
| max | 1,531,479,284.50 |

p90 is a linear percentile (NumPy's default).

p90 为线性分位数（与 NumPy 默认百分位相同）。

## Screens / 筛选规则

A row is one binary Polymarket market, which is the contract. Markets that share an event each stay in the file.

每一行是一个二元 Polymarket 市场，也就是一张合约。同一事件下的多个市场都保留。

1. Lifetime volume ≥ 10,000.00. Paper threshold: 10,000 contracts. Polymarket's figure is USD notional.
2. Scheduled life ≥ 2 days, elapsed time from the opening timestamp to expiry.
3. Opening date (UTC calendar date) is on or before 2026-11-07.

1. 累计成交量 ≥ 10,000.00。论文门槛是 10,000 张合约；Polymarket 这里用的是美元名义金额。
2. 预定存续期 ≥ 2 天，即到期时刻减去开盘时刻的实际时长。
3. 开盘日（UTC 日历日）不晚于 2026-11-07。

Opening timestamp, in order: `startDate`, `startDateIso`, the parent event `startDate`, `createdAt`, the event `createdAt`, the event `creationDate`. Expiry, in order: `endDate`, `endDateIso`, the event `endDate`, the event `endDateIso`. `closedTime` and `gameStartTime` are not used.

开盘时刻按以下顺序取第一个能解析的字段：`startDate`、`startDateIso`、父事件 `startDate`、`createdAt`、事件 `createdAt`、事件 `creationDate`。到期时刻按 `endDate`、`endDateIso`、事件 `endDate`、事件 `endDateIso`。不用 `closedTime`（实际结束时间），也不用 `gameStartTime`（比赛开始时间）。

These are not inclusion rules / 以下不是纳入条件:

- Trailing 7-day average volume / 近 7 日平均成交量
- Days to expiry on a trade date / 某个交易日的剩余到期天数
- YES price inside [0.10, 0.90] / YES 价格落在 [0.10, 0.90]
- One market per event / 每个事件只留一个市场
- Drop the day when fewer than 10 markets pass / 当天不足 10 个市场则整日剔除

## How to read the CSV / 如何读 CSV

`paper_sample_markets.csv` is UTF-8, one contract per row, largest lifetime volume first.

`paper_sample_markets.csv` 为 UTF-8，一行一张合约，按累计成交量从高到低排列。

| Column | Meaning / 含义 |
| --- | --- |
| `market_id` | Gamma market id / Gamma 市场 id |
| `question` | Contract question / 合约问题 |
| `event_id`, `event_title` | Parent event. `market:<id>` means Gamma did not attach an event / 父事件。`market:<id>` 表示 Gamma 没有挂上事件 |
| `cumulative_volume`, `volume_unit` | Lifetime size. `usd_notional` means USD notional, not a contract count / 累计规模。`usd_notional` 表示美元名义金额，不是张数 |
| `scheduled_life_days` | Expiry minus open, in days / 到期减去开盘，单位为天 |
| `open_date`, `expiry` | UTC timestamps used for the two rules above / 上面两条规则使用的 UTC 时间 |
| `open_date_source`, `expiry_source` | Which Gamma field supplied that timestamp / 该时间来自哪个 Gamma 字段 |
| `closed` | `true` if Gamma reports the market closed / Gamma 标记为已结束时为 `true` |
| `outcomes` | The two outcome labels / 两个结果标签 |
| `yes_token` | CLOB YES token when an outcome is labeled Yes. Empty is still in the sample / 结果名为 Yes 时的 CLOB token。为空仍然留在样本里 |
| `sample_end_date` | Opening-date cutoff for every row / 每一行使用的开盘日截止 |

Companion file / 配套文件: `paper_sample_meta.json` (funnel, paging, volume stats).

## Funnel / 过滤过程

Each fetched market is counted once, at the first rule it fails. Boundary duplicates created by overlapping volume bands are removed before this count.

每个抓取到的市场只计一次，记在它第一次失败的规则上。重叠成交量区间造成的边界重复已在计数前去掉。

| Reason / 原因 | Markets / 市场数 |
| --- | ---: |
| Fetched unique / 去重后抓取 | 493,855 |
| Below volume / 成交量不足 | 0 |
| Not binary (not exactly two outcomes) / 不是二元（结果不是恰好两个） | 30 |
| Missing opening timestamp / 缺少开盘时间 | 0 |
| Missing expiry / 缺少到期时间 | 608 |
| Scheduled life under the minimum / 预定存续期不足 | 215,736 |
| Opened after the sample end / 开盘晚于样本截止 | 0 |
| Selected / 入选 | 277,481 |

## Paging / 翻页

Gamma `/markets/keyset` ordered by `volumeNum`, with `volume_num_min` at the paper floor. Open (`closed=false`) and closed (`closed=true`) markets are both paged. The volume range is split into inclusive bands so the closed book finishes in parallel. Band edges overlap and are deduped by `market_id`. `volume1wk` is not a stop rule.

使用 Gamma `/markets/keyset`，按 `volumeNum` 排序，并用 `volume_num_min` 设在论文门槛上。未结束（`closed=false`）和已结束（`closed=true`）都会翻页。成交量区间被切成闭区间分段并行抓取已结束市场。区间边界会重叠，按 `market_id` 去重。`volume1wk` 不作为停止条件。

Rebuild / 重跑:

```bash
python3 scripts/strategy/hlz_cross_section/build_universe.py --self-test
python3 scripts/strategy/hlz_cross_section/build_universe.py --end-date 2026-11-07
```
