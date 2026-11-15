# PM-HL Full Migration Handoff

> Source project: `C:\Users\Admin\claude code` (a.k.a. "PM-HL arb2")
> Target project: `D:\cursor\2026_strategy_lab`
> This document is self-contained: a fresh Cursor session should be able to migrate the whole
> Polymarket × Hyperliquid arbitrage system from it without reading the old chat history.
> **No secrets are included. Sensitive values appear as `REDACTED`.**

---

## 1. 项目目标

在 **Polymarket (PM)** 与 **Hyperliquid (HL)** 两个市场之间,对**同一个现实事件**做跨平台套利:
两边各持有一条"互补"的 outcome 腿,合起来在结算时**无论结果如何都付 $1/份**,而**买入总成本 < $1**,
赚取确定性的价差(held-to-settle box),并在价差收敛时可提前平仓提高资金周转率(APR)。

- 资金:PM 账户 ~$1000 抵押(collateral),HL sub1 ~$1000 现货 USDC。
- 模式:**半自动 / 监控为主**。下单能力已接通,但默认 **DRY-RUN**,实盘需人工显式开启 + 监督。
- 现状:监控/数据/套利计算成熟;实盘执行引擎有已知 bug(见 §5),迁移时需修复后再启用。

---

## 2. 当前策略核心逻辑

**Box = 在两个平台各买一条互补 outcome,只用 USDC 买(不做空)。**

- **Polymarket leg**:买某个 outcome token(YES 或 NO),`amount` 以 USDC 计(市价)或 shares 计(限价)。
- **Hyperliquid leg**:买 HIP-4 outcome 代币(现货 `#oid0`=YES / `#oid1`=NO),用 USDC 买。
  - HL 是**现货式 outcome 市场**:不能卖空你没持有的代币。对冲必须**买互补代币**,不能 SELL 另一腿。
- 一个 box = `buy PM(event) + buy HL(NOT event)`(或反向),结算必付 $1/份。

**已测试市场:**
- ✅ **Fed "No Change in June"**(PM)× **"June Fed rate change"**(HL #104)—— 当前重点,settle 2026-06-17。
- ⚠️ **World Cup Champion**(PM)× HL HIP-4 各队 outcome(team_map.json,如 Portugal #205、Spain #212…)—— 已测,边际/噪声为主。

**当前重点机会:** Fed no-change box,NET ~+0.3%,APR ~57%(2 天到期),HL 可执行深度 ~265 sets(~$264)。

**假机会(不要追):**
- 用 **mid** 价算出来的 edge(实际只能吃 ask/bid,mid 高估)。
- 把对冲腿建模成"卖 #oid0"而非"买 #oid1"(现货不能做空 → 0 成交;且名义额不对)。
- **World Cup z 反转信号**:σ 太小(Portugal σ≈0.06¢),回归幅度 < 交易成本 → 净亏。
- 价差时间序列里的**瞬时尖刺**(bid 侧被扫、几秒、很薄)—— 测的是 bid,买的是 ask,抓不到。
- 远期、低 APR、或 HL 腿名义额 < $10 最低下单额的 box。

**可能的真机会:**
- Fed no-change 稳态 box(近到期、正地板、深度够、APR 高)。
- 任意"两边 payoff/resolution 一致、净 edge ≥ 阈值、HL 腿 ≥ $10、APR 够高"的 box。

---

## 3. 已研究市场与 payoff 映射

> 市场定义在 `arb_bot.py: load_markets()` + `team_map.json`。HL 用整数 `hl` id;outcome 代币别名为
> `#N`,`N = 10*outcome_id + side`(side 0 = YES, 1 = NO)。

### Fed "No Change in June"  (重点)
- **PM question**: "Will there be no change in Fed interest rates after the June 2026 meeting?"
  - `pm_yes` = "no change", `pm_no` = "change". `same=False`。
- **HL market**: "June Fed rate change", `hl=104` → `#1040`=change(YES), `#1041`=no-change(NO)。
- **payoff 一致**: 是。PM "no change" ≡ HL `#1041`。互补腿 = `buy PM No(change 0.005) + buy HL #1041(no-change 0.99)`。
- **resolution 一致**: 是(同一次 6 月 FOMC 结果)。settle 2026-06-17。
- **适合套利**: ✅ 是。当前 box cost ≈ 0.995,floor ≈ +0.5%,NET ~+0.3%。
- **已知问题**: PM-No 极便宜(~0.5¢)→ 市价买单名义额 < $1 被拒(用 share-sized FAK 限价解决);HL no-change ~0.99 → 市价买价 +slip 会 >$1 被拒(买价 clamp 到 ≤0.999 解决)。

### World Cup Champion  (边际)
- **PM**: "Will <team> win the 2026 World Cup?" 每队一个 YES/NO 市场。`same=True`(PM-YES ≡ HL-YES)。
- **HL**: HIP-4 各队 outcome(`team_map.json` 里每队的 `hl` id)。
- **payoff 一致**: 名义一致(同冠军事件),但 **resolution 时间很远**(决赛 ~2026-07-19)。
- **适合套利**: ⚠️ 勉强。边际薄、APR 低(远期)、z 反转幅度 < 成本。当监控/研究,不当主力。
- **已知问题**: σ 极小(0.06¢);早期 z 有预热假象(−10σ 是方差未校准的伪信号,非真 10σ)。

### 其他已研究/扫描过的
- 通过 `twin_finder.py` / `wc_scanner2.py` / `zscore_rank.py` 扫过 PM-vs-HL 的"孪生"市场对(48 队等);
  多数无可执行 edge。数据见 `scan2_*.csv`、`wc_arb_log.csv`(历史,可不迁移)。

---

## 4. 核心套利公式

> 实现:`arb_bot.py: scan_market(), walk(), pm_fee()` + `arb_live_v3.py: maker_edge_now(), open_box()`。
> **规范方向**: `spread = HL(event) − PM(event)`(polarity 归一化;HL 更贵 = 正)。处处一致。

**Box(mirror)成本与 edge:**
```
C (box cost / set)   = PM_leg_ask + HL_complement_ask         # 进场都是 BUY,用 ASK
gross_edge           = 1 - C
PM taker fee / share = 0.03 * p * (1 - p)                      # 仅 PM taker BUY;maker = 0;p=PM腿价
HL fee / share       = 0.0                                     # "zero-fee period" —— 未独立核实,留参数 HL_TAKER_FEE
estimated_cost       = PM_taker_fee + HL_fee (+ 进出价差,若提前平)
net_edge             = gross_edge - estimated_cost
```

**bid/ask 用哪边、为什么不能用 mid:**
- **进场(买两条腿)→ 用 ASK**(你付卖一价)。
- **退场 / 估清算价值 V → 用 BID**(你卖给买一)。`V = PM_bid + HL_bid`(per set)。
- **不能用 mid**:mid 是买卖中点,实盘**永远吃不到** mid;用 mid 算 edge 会系统性高估 ~半个价差,把假机会当真机会(这是本项目踩过的核心坑)。

**真机会 vs 假机会:**
- **真机会**: `net_edge ≥ MIN_NET_EDGE(0.002 = 0.2%)` 且 `C < 1`(有结算地板)且 HL 腿 ≥ $10 且 APR 够高。
- **假机会**: 用 mid 算的;对冲腿方向/notional 算错的;sub-tick 噪声;远期低 APR;HL 腿 < $10。

**executable size(可执行规模)估算:** 沿两边盘口逐档 `walk()`,取 `min(PM_ask 深度, HL_ask 深度)`,
受 `MAX_USDC_PER_TRADE` 与账户资金上限约束;**HL 腿名义额必须 ≥ HL_MIN_NOTIONAL($10)**,否则跳过。
Fed 看板显示 "HL executable depth N sets"。

**APR 估算:** `APR = net_edge / days_to_settle * 365`。maker 进场门槛额外加 `APR ≥ APR_FLOOR(1%)`。
`days_to_settle` 来自每个市场的 `settle` 日期(Fed 2026-06-17;WC 2026-07-19)。

---

## 5. S1–S6 逻辑

| 策略 | 含义 | 实现状态 | 跑通? | bug? | 迁移? |
|---|---|---|---|---|---|
| **S1** | held-to-settle taker box(正地板,持有到期) | `scan_market` + `open_box(kind=box)` | HL/PM 下单 bug 修复后可成交 | 见下 | ✅ 迁移 |
| **S2** | box + dir1 收敛提前退出 | v3 `manage_position`(box 分支,spread≈0 退出) | 未实盘验证 | — | ✅ 迁移 |
| **S3** | box + dir2 收敛提前退出 | 同 S2 | 未实盘验证 | — | ✅ 迁移 |
| **S4** | maker box(PM 挂被动单,成交后买 HL 对冲) | v2/v3 `post_maker`/`poll_maker`/`settle_maker` | 部分(能挂/驻留/撤;HL 对冲腿曾有 bug,已修) | 见下 | ✅ 迁移 |
| **S5** | 延迟方向 scalp | **已弃(flawed)** | ❌ | n/a | ❌ DO_NOT migrate |
| **S6** | z 均值回归(双 taker,C<1 闸,exit z→0,无 stop) | v3 `open_box(kind=s6)` + `manage_position(s6)` | ❌ 有严重 bug | **是(orphan)** | ✅ 迁移**但必须先修** |

**进场/退场口径(已敲定):** S6 **双 taker**(确定性优先);S1-S3 box 进场 taker、提前退出按 **spread≈0**(不按 z);
S4 maker 进场。所有 box `C<1` 才进(正地板)。退出都要 `V − C > 退出费` 才提前平,否则**持有到期吃地板**。

### 重点:S6

- **S6 要解决什么**: 当价差被拉到极值(`|z| ≥ 2`)时,那一侧的 box 临时变得**更便宜(地板更厚)**;
  进场后若价差回归(`z → 0`),box 清算价值 `V` 上升 → 提前 taker 平仓赚更高 APR;若不回归,**持有到期吃地板**。
  关键洞察:因为只能买**镜像 box**,两侧 box 成本 `C(dir1)=1−spread`、`C(dir2)=1+spread`,二者和恒=2 →
  **任一时刻必有一侧 C<1(正地板)**。所以 S6 **不需要 stop-loss**,最差就是持有到期收 `1−C>0`。
  **闸:只在 C<1 时进。**
- **orphan box 是什么**: `open_box` 先买 HL 腿,再买 PM 腿。它**只在 PM 抛异常时回滚 HL**;
  当 PM 那条单**没成交又不报错(返回 0 成交)**时,它既**不回滚 HL**,又把仓位记成 `shares=min(got=0,filled)=0`。
  → 真实持有的 HL 成了"孤儿"(记录 0、实际 N 股),且记录股数与真实持仓脱节,导致后续累积。
- **1000 股 HL no-change box 是什么**: 上述 orphan 跨多次重启累积的结果 —— HL 实际买进了 **1000 股 `#1041`
  (no-change,花 ~$990,均价 0.99032),PM 一股没成**。这是一个**裸的、未对冲的**方向性仓位(赌 Fed 不变)。
  注意:`position_report` 当时显示 "HL −$990" 是**误导**(它没把 outcome 代币算进资产);代币值 ~$984,
  实际总回撤只有 ~$7(churn 价差)。
- **为什么可能是真机会**: 这 1000 股其实是 Fed box 的**一条腿**;补 1000 股 PM-No(~$5)即锁成正经 box
  (到期 $1000,floor ~+0.47%)。即"把烂摊子救成本来想要的 box"。
- **之前 bug**(待修,**本次未改任何交易逻辑**):
  1. `open_box`:HL 买入后若 PM 未配平(成交量不足,**不论是否抛异常**),必须**立即回滚 HL**(卖回);
     记录股数要与**真实持仓对账**,绝不记 `shares=0` 却留着真实 HL。
  2. entry / manage 调度要全包 `try/except`(HL/PM 偶发 502 不应崩引擎)。
  3. `position_report` 要把 HL **outcome 代币现货持仓**计入资产(当前只算 spot USDC + perp)。
- **如何修复**(给 Cursor 的方向,迁移时实现):开仓改为**原子化**:先读 baseline,买 HL,**确认 HL 成交量 F**,
  再买 PM **share-sized = F**,**确认 PM 成交量 G**;若 `|F−G| > tol` → 立刻把多出的那条腿 taker 平掉;
  仓位 `shares = min(F,G)`,并以**真实链上/交易所持仓**为准做对账(reconcile),不要只信内存记录。

---

## 6. API 与交易能力

> 依赖库(无 requirements.txt,需在新项目固化):
> - `py_clob_client_v2`（**注意:不是已废弃的 `py-clob-client`**;旧库会报 "invalid order version"）
> - `hyperliquid`（`hyperliquid-python-sdk` **>= 0.24.0**;0.21 在 spot_meta 上崩 IndexError）
> - `eth_account`
> - 标准库:`urllib`, `json`, `csv`, `os`, `time`, `datetime`

### Polymarket
- **client 文件**: `pm_connect.py`
- **读取市场/盘口/价格**:
  - `arb_bot.py: pm_book(token_id)` → GET `https://clob.polymarket.com/book?token_id=…` → `(bids, asks)`
  - `arb_live_v3.py: pm_top(token)` → `(best_bid, best_ask, tick_size, neg_risk)`
  - `pm_connect.http_json(url)` → 通用 GET JSON
- **读取持仓/余额/资产**:
  - `pm_connect.get_positions(funder)` → `https://data-api.polymarket.com/positions?user=<funder>`
  - `pm_connect.get_value(funder)` → `…/value?user=`
  - `pm_connect.get_usdc_balance(addr)` → 公链 RPC `eth_call balanceOf`(USDC.e / USDC on Polygon)
  - `pm_connect.get_cash(client)` → **权威抵押金**(authed client `get_balance_allowance(COLLATERAL)`);
    注意:链上 funder 余额常显示 $0,真实现金在 CLOB collateral,**必须用 `get_cash`**。
  - `arb_live_v3.py: pm_positions_size(funder, token)` → 某 token 的持仓股数
- **下单**(都在 `pm_connect.build_client()` 返回的 authed client 上):
  - 市价: `client.create_and_post_market_order(MarketOrderArgs(token_id, amount, side, order_type=OrderType.FOK), options=PartialCreateOrderOptions(tick_size, neg_risk), order_type=OrderType.FOK)` — `amount`=USDC(BUY)/shares(SELL)。**注意 BUY 有 ~$1 最低名义额**。
  - 限价/可成交限价: `client.create_and_post_order(OrderArgs(token_id, price, size, side), options, order_type=OrderType.GTC|FAK|FOK|GTD)` — `size`=shares,**最低 5 shares**。`FAK`=IOC。
  - 参考实现: `pm_trade_test.py`(限价 place/confirm/cancel)、`pm_fill_test.py`(市价 fill)、`arb_live_v3.py: pm_marketable_buy/pm_marketable_sell/pm_limit_buy`。
- **取消订单**: `client.cancel_order(OrderPayload(orderID=…))`(见 `pm_trade_test.py` / `arb_live_v3.py: pm_cancel`)。
- **查询订单状态**: `client.get_open_orders(OpenOrderParams(asset_id=token), only_first_page=True)`(见 `pm_trade_test.py`)。
- **环境变量**: `PM_FUNDER`, `PM_SIGNER`, `PM_PRIVATE_KEY`(secret), `PM_RELAYER_API_KEY`(secret,当前代码未强制用), `PM_SIGNATURE_TYPE`(=2)。
- **认证**: `build_client()` 用 `PM_PRIVATE_KEY` L1 签名 → `create_or_derive_api_key()` 派生 L2 creds(nonce 0 确定性;首次 create 返回 400 是正常的,会 fallback 到 derive)。

### Hyperliquid
- **client 文件**: `hl_connect.py`
- **读取市场/盘口/价格**:
  - `hl_connect.info(payload)` → POST `https://api.hyperliquid.xyz/info`(通用)
  - `arb_bot.py: hl_yes_book(oid)` → `{"type":"l2Book","coin":"#<oid*10>"}` → YES 腿盘口
  - `arb_live_v3.py: hl_coin_book("#N")` → 任意 outcome 代币盘口 `(bids, asks)`
- **读取持仓/余额/资产**:
  - `hl_connect.spot_balances(addr)` → `spotClearinghouseState` → `[(coin, total)]`(**outcome 代币持仓在这里,如 `+1041`**)
  - `hl_connect.perp_state(addr)` → `clearinghouseState` → `(accountValue, assetPositions)`
  - `hl_connect.open_orders(addr)` → `{"type":"openOrders"}`
- **下单**(在 `hl_connect.build_exchange()` 返回的 `Exchange` 上):
  - `ex.order(coin, is_buy, size, px, {"limit": {"tif": "Ioc"|"Alo"|"Gtc"}})`
  - 解析 `resp["response"]["data"]["statuses"][0]` → `resting.oid` 或 `filled.totalSz/avgPx`
  - 参考: `hl_trade_test.py`、`arb_live.py: hl_take`(marketable IOC,买价 clamp ≤0.999、卖价 ≥0.001)
- **取消订单**: `ex.cancel(coin, oid)`(见 `hl_trade_test.py`)。
- **查询订单状态**: `hl_connect.open_orders(addr)`。
- **sub-account 路由(关键)**: `Exchange(agent, MAINNET_API_URL, vault_address=sub1, account_address=sub1)`。
  **必须传 `vault_address`** 才会下到 sub1;只传 `account_address` 只影响读、订单会落到 master。
- **HIP-4 `#` 别名注入**: SDK 不认 `#N`,`build_exchange()` 手动注入 `coin_to_asset["#N"]=100_000_000+N`、`name_to_coin["#N"]="#N"`(N=10*outcome+side,两侧都注)。
- **环境变量**: `HL_MASTER`, `HL_ACCOUNT`(=sub1), `HL_AGENT_KEY`(secret;agent 可交易**不可提现**)。

---

## 7. 公开账户信息(非敏感,可输出)

| 字段 | 值 |
|---|---|
| Polymarket account (proxy / funder) | `0x9d335b39104631B7d5D495c04c3dFB1fB789ebd5` |
| Polymarket signer (MetaMask EOA, public) | `0xBF59AFAAbe7F723f62b8586f9BcDe1d8642f06b5` |
| Polymarket signature_type | `2` (POLY_GNOSIS_SAFE，浏览器/代理钱包) |
| Polymarket chain | Polygon (chain_id 137) |
| Polymarket CLOB host | `https://clob.polymarket.com` |
| Hyperliquid master (public) | `0xf318b7c7f3dd6bbf3b651efd3DCb161BB9f47674` |
| Hyperliquid sub1 — traded account (public) | `0x10c444c580db629bcffab84b73c77ba3b7323074` |
| Hyperliquid agent/API wallet (public addr) | `0x5289bB07B9Bc7ffB43EBa17D603aC3F24D712268` |
| Hyperliquid network | mainnet (`https://api.hyperliquid.xyz`) |

**绝不输出(本文件中均为 `REDACTED`)**: `PM_PRIVATE_KEY`, `PM_RELAYER_API_KEY`, `HL_AGENT_KEY`,
seed phrase / mnemonic, API secret/password, signing key, bearer token, session cookie。

> ⚠️ 安全提示:`PM_PRIVATE_KEY` 历史上曾被截图进聊天 → **视为已泄露**。新项目实盘前**强烈建议轮换**到
> 一个只放交易资金的专用钱包(本项目尚未轮换)。

---

## 8. Secret 迁移方案

- **是否迁移 secret**: **否**。不要复制 `secrets.env` 到新项目。
- **不应迁移的 secret**: `PM_PRIVATE_KEY`, `PM_RELAYER_API_KEY`, `HL_AGENT_KEY`(以及任何派生 creds)。
- **新项目如何复用本地环境变量**:
  - 用 `.env.local`(gitignored)在新项目机器本地填真实值,代码用 `os.environ` 读取(可用 `python-dotenv` 或现有 `load_env()` 思路)。
  - 变量名保持一致:`PM_FUNDER, PM_SIGNER, PM_PRIVATE_KEY, PM_RELAYER_API_KEY, PM_SIGNATURE_TYPE, HL_MASTER, HL_ACCOUNT, HL_AGENT_KEY`。
  - 公开地址(FUNDER/SIGNER/MASTER/ACCOUNT)可写进 `.env.example` 作为默认;**私钥/secret 留空**。
- **`.env.example`**: 需要。只含**变量名 + 公开默认值**,secret 留空,带注释。
- **`.env.local`**: 需要(真实 secret,本地,gitignored)。
- **`.gitignore` 应忽略**: `.env`, `.env.local`, `secrets.env`, `*.key`, `*.pem`, `data/*.sqlite`, `*.log`, `__pycache__/`, `*.csv`(数据)。
- **默认不意外下单**: 见 §13。代码入口默认 `DRY_RUN=true` / `TRADING_ENABLED=false`,任何下单函数在入口处检查这两个开关,未显式开启则只打印不下单。

---

## 9. 关键代码文件地图

> 标签:**MUST_COPY**(核心,基本可直接用)、**REWRITE**(逻辑要重构进新结构/修 bug)、
> **REFERENCE_ONLY**(读懂用,别直接跑)、**DO_NOT_COPY**(弃用/陈旧/本地/数据)。

| 文件 | 用途 | 标签 | 依赖 |
|---|---|---|---|
| `pm_connect.py` | Polymarket 连接器:读盘口/持仓/现金 + authed 下单 client | **MUST_COPY**(改 import 路径) | py_clob_client_v2, eth_account |
| `hl_connect.py` | Hyperliquid 连接器:读现货/perp/订单 + Exchange 下单 + `#` 别名注入 | **MUST_COPY** | hyperliquid, eth_account |
| `zcalc.py` | 共享 z-score(time-decay EWMA,4h halflife) | **MUST_COPY** | 标准库 |
| `arb_bot.py` | 市场定义 `load_markets()` + `scan_market()`(spread/edge/z)+ book/walk/fee | **MUST_COPY**(scan 逻辑是核心) | zcalc, team_map.json |
| `team_map.json` | WC 各队 → PM token / HL id 映射 | **MUST_COPY** | — |
| `arb_live_v3.py` | 最新执行引擎:box/S4 maker/S6/S2-3 退出/seed/position manager | **REWRITE**(有 orphan bug,拆进 strategy.py + clients) | arb_bot, arb_live, pm_connect, hl_connect |
| `arb_live.py` | v1 执行 + 共享 helper(`hl_take`, `pm_market_buy`, `ledger`, `pm_book_meta`, `pm_positions_size`) | **REWRITE**(helper 抽出来,丢弃 v1 main) | pm_connect, hl_connect |
| `arb_live_v2.py` | v2(+S4 maker),已被 v3 取代 | **REFERENCE_ONLY** | 同上 |
| `spread_collector.py` | 常驻采集器:每 10s 落 spread → 现写 CSV | **REWRITE**(改成写 SQLite) | arb_bot |
| `position_report.py` | 只读持仓报告(按策略分组) | **REWRITE**(修 §5 资产漏算 + 读 SQLite) | pm_connect, hl_connect, arb_live |
| `pm_trade_test.py` | PM 限价 place/confirm/cancel 验证 | **REFERENCE_ONLY**(下单 API 范例) | pm_connect |
| `pm_fill_test.py` | PM 市价 fill 验证 | **REFERENCE_ONLY** | pm_connect |
| `hl_trade_test.py` | HL 限价 place/confirm/cancel 验证(sub1) | **REFERENCE_ONLY** | hl_connect |
| `s4_spec_v2.1.md` | S4 maker box 设计文档 | **REFERENCE_ONLY** | — |
| `STATUS.md` | 项目状态/账户/坑/TODO 手册 | **REFERENCE_ONLY** | — |
| `dashboard_server.py` / `fed_dashboard.py` / `gateway.py` | 本地只读看板(WC/Fed/反代) | **REFERENCE_ONLY**(可选迁移可视化) | arb_bot, zcalc |
| `master_dashboard.py` / `start_all.py` | 旧看板/启动器(陈旧,start_all 用错文件) | **DO_NOT_COPY** | — |
| `twin_finder.py` / `wc_scanner2.py` / `wc_arb_scanner.py` / `zscore_rank.py` / `match_watch.py` / `fed_arb_calc.py` | 早期一次性扫描/研究脚本 | **DO_NOT_COPY**(研究产物) | — |
| `secrets.env` | 真实 secret | **DO_NOT_COPY**(绝不) | — |
| `secrets.example.env` | secret 模板(仅变量名) | **REFERENCE_ONLY** → 转成 `.env.example` | — |
| `*.csv`(live_ledger, spread_history, arb_bot_log, match_watch_*, scan2_*, wc_arb_log) | 运行数据/日志 | **DO_NOT_COPY**(重新生成 / 落 SQLite) | — |
| `*.json`(pm_wc_raw, hl_outcome_meta) | 一次性数据 dump | **DO_NOT_COPY**(可重抓) | — |

---

## 10. 当前运行命令

| 命令 | 作用 | 真实下单? |
|---|---|---|
| `python pm_connect.py` | PM 只读摘要(现金/持仓) | ❌ 只读 |
| `python pm_connect.py --check` | 同上 + 验证 authed creds(不下单) | ❌ |
| `python hl_connect.py` | HL sub1 只读摘要 | ❌ |
| `python hl_connect.py --check` | 同上 + 验证 agent 授权(不下单) | ❌ |
| `python position_report.py [--loop]` | 按策略分组的持仓/现金/总额报告 | ❌ 只读 |
| `python spread_collector.py` | 常驻采集 spread → spread_history.csv | ❌ 只读 |
| `python arb_bot.py [--once]` | DRY-RUN 监控 + paper(打印 WOULD-*) | ❌ DRY |
| `python pm_trade_test.py` | **会下 PM 限价单**(远离盘口、可撤),需手动确认 | ⚠️ **是** |
| `python pm_fill_test.py` | **会市价成交 ~$5**,需手动确认 | ⚠️ **是** |
| `python hl_trade_test.py` | **会下 HL post-only 限价(不成交)** + 撤单,需手动确认 | ⚠️ **是(挂单)** |
| `python arb_live.py` / `arb_live_v2.py` / `arb_live_v3.py` | 实盘引擎。**默认 `LIVE=False` = DRY**;`LIVE=True` **且** env `ARM_LIVE=1` 才真下单 | ⚠️ **武装后是** |

**急停**: 在项目目录建文件 `STOP`(`ni STOP`)或对引擎窗口 Ctrl+C。

---

## 11. 输出文件与数据文件

| 文件 | 类型 | 迁移价值 |
|---|---|---|
| `spread_history.csv` | 采集器价差时序(给 z seed) | 数据,**重新生成**(迁移后落 SQLite `spread_history` 表) |
| `live_ledger.csv` | 实盘成交流水(ts,strategy,market,venue,side,shares,price,asset) | 结构值得保留(→ SQLite `fills` 表);旧数据可丢 |
| `arb_bot_log.csv` | DRY 监控信号日志(WOULD-POST/WOULD-TRADE) | 临时,可丢 |
| `match_watch_edge.csv` / `match_watch_wake.csv` / `scan2_*.csv` / `wc_arb_log.csv` | 早期扫描产物 | 临时,**不迁移** |
| `team_map.json` | WC 市场映射 | **迁移**(MUST_COPY) |
| `pm_wc_raw.json` / `hl_outcome_meta.json` | 一次性 dump | 不迁移(可重抓) |
| `*_console*.log` / `*.err.log` | 进程 stdout/stderr | 临时,不迁移 |

**值得迁移的"输出结构"**: ledger 表(成交)、opportunity 表(机会快照)、spread 时序 —— 全部落到新项目的 SQLite。

---

## 12. 迁移到 `2026_strategy_lab` 的目标结构

```
D:\cursor\2026_strategy_lab\
├─ docs/
│  ├─ pm_hl_cross_market_arbitrage.md      # 策略说明(从本文 §1-5 提炼)
│  └─ pm_hl_full_migration_handoff.md      # 本文件
├─ src/
│  ├─ db.py                                # SQLite 连接 + schema(opportunities / fills / spread_history)
│  └─ strategies/
│     └─ pm_hl/
│        ├─ __init__.py
│        ├─ clients/
│        │  ├─ __init__.py
│        │  ├─ polymarket.py               # ← pm_connect.py(改 import,封装成类/模块)
│        │  └─ hyperliquid.py              # ← hl_connect.py
│        ├─ models.py                      # Market / Leg / Opportunity / Position 数据类 + team_map 加载
│        ├─ opportunity_model.py           # ← arb_bot.scan_market + zcalc(edge/spread/z/APR 计算)
│        └─ strategy.py                    # ← arb_live_v3 执行逻辑(S1-S4/S6,修 orphan,带安全开关)
├─ scripts/
│  ├─ run_pm_hl_monitor.py                 # 扫描 + 把 opportunity 写入 SQLite(只读,默认 DRY)
│  └─ run_pm_hl_read_positions.py          # ← position_report.py(修资产漏算,读 PM+HL)
├─ data/
│  └─ lab.sqlite                           # opportunities / fills / spread_history 表
├─ .env.example                            # 变量名 + 公开默认,secret 留空
├─ .env.local                             # 真实 secret(gitignored,本地填)
└─ .gitignore
```

建议 SQLite `opportunities` 表(最小):
```
id INTEGER PK, ts TEXT, market TEXT, direction TEXT,
pm_token TEXT, hl_coin TEXT,
pm_ask REAL, hl_ask REAL, box_cost REAL,
gross_edge REAL, est_cost REAL, net_edge REAL,
days_to_settle REAL, apr REAL,
exec_depth_sets REAL, z REAL, is_real INTEGER, note TEXT
```

---

## 13. 迁移后必须保留的安全开关

所有开关从 env 读取,**入口处校验**,默认安全:

| 开关 | 含义 | 默认值 |
|---|---|---|
| `DRY_RUN` | true = 只计算/打印,绝不下单 | **`true`** |
| `TRADING_ENABLED` | false = 任何下单函数直接 return(即使 DRY_RUN=false) | **`false`** |
| `MAX_ORDER_NOTIONAL` | 单笔名义额上限(美元),超出拒单 | 例如 `100` |
| `REQUIRE_MANUAL_CONFIRMATION` | true = 每笔下单前需人工确认 | **`true`** |
| `ALLOWED_MARKETS` | 白名单(逗号分隔,如 `Fed-NoChange`);不在表内不下单 | 默认空 = 无 |

**下单门禁逻辑(伪码)**:
```
def place_order(...):
    if DRY_RUN or not TRADING_ENABLED: log("DRY/disabled, no order"); return
    if market not in ALLOWED_MARKETS: refuse
    if notional > MAX_ORDER_NOTIONAL: refuse
    if REQUIRE_MANUAL_CONFIRMATION and not confirmed: refuse
    ... real order ...
```
> 同时保留旧项目的双闸思路:`TRADING_ENABLED=true` 之外,引擎进程级再要一个显式 ARM(env/flag),
> 并保留 `STOP` 文件急停。

---

## 14. 迁移后的验收标准

- [ ] 能 `import` 所有模块(`src.strategies.pm_hl.*`、`src.db`),无循环依赖。
- [ ] 能从 `.env.local` 读本地环境变量;缺失 secret 时**降级为只读**而非崩溃。
- [ ] 能连接 PM/HL **read-only** 数据(盘口、价格)。
- [ ] 能读取 PM 现金(`get_cash`)+ HL 现货/持仓(含 outcome 代币)。
- [ ] 能计算**一条** opportunity(box_cost / gross / net / APR / is_real),用 **ask 进、bid 退**,不用 mid。
- [ ] 能把该 opportunity 写入 `D:\cursor\2026_strategy_lab\data\lab.sqlite` 的 `opportunities` 表。
- [ ] **默认不会真实下单**(`DRY_RUN=true` / `TRADING_ENABLED=false`)。
- [ ] 仅当显式 `TRADING_ENABLED=true`(+ 其余安全门禁)才允许下单。
- [ ] orphan bug 已修:开仓原子化、两腿成交量对账、不留裸腿;entry/manage 全 try/except。
- [ ] `position_report` 把 HL outcome 代币计入资产(不再出现"−$990"假亏)。

---

## 15. 给 Cursor 的迁移说明(可直接用)

> 复制以下指令给 Cursor 执行迁移。**不要运行任何交易、不要下单、不要删除旧项目任何文件。**

**A. 从旧项目复制(改 import 路径)**
- `C:\Users\Admin\claude code\pm_connect.py` → `src/strategies/pm_hl/clients/polymarket.py`
- `C:\Users\Admin\claude code\hl_connect.py` → `src/strategies/pm_hl/clients/hyperliquid.py`
- `C:\Users\Admin\claude code\zcalc.py`      → `src/strategies/pm_hl/opportunity_model.py`(z 部分)或单独 `zscore.py`
- `C:\Users\Admin\claude code\arb_bot.py`(`load_markets`+`scan_market`+`pm_book`/`hl_yes_book`/`walk`/`pm_fee`) → `src/strategies/pm_hl/opportunity_model.py`
- `C:\Users\Admin\claude code\team_map.json` → `src/strategies/pm_hl/team_map.json`

**B. 重构(REWRITE)进新结构**
- `arb_live_v3.py` + `arb_live.py` 的执行 helper(`hl_take`、`pm_marketable_buy/sell`、`pm_limit_buy`、`pm_cancel`、
  `hl_coin_book`、`pm_top`、`hedge_leg`、`open_box`、`post_maker/poll_maker/settle_maker`、`manage_position`、`close_position`)
  → `src/strategies/pm_hl/strategy.py`,**并修 §5 的 orphan bug + 加 §13 安全门禁**。
- `position_report.py` → `scripts/run_pm_hl_read_positions.py`,**修 HL outcome 代币资产漏算**。
- `spread_collector.py` → 写入 SQLite `spread_history` 表(替代 CSV)。
- 新建 `scripts/run_pm_hl_monitor.py`:循环 `scan_market` → 组装 Opportunity → 写 `opportunities` 表(只读,默认 DRY)。

**C. 不要复制**
- `secrets.env`(任何 secret)、`master_dashboard.py`、`start_all.py`、所有 `*.csv`/早期扫描脚本/`*.json` dump、
  `arb_live.py`/`arb_live_v2.py` 的 `main()`(只取 helper)。

**D. import 路径要改的地方**
- 旧代码用 `import pm_connect as PM` / `import hl_connect as HL` / `import arb_bot as B` / `from arb_live import …`。
  迁移后改为相对/绝对包路径,例如 `from src.strategies.pm_hl.clients import polymarket as PM` 等。
- `load_markets()` 里的 `team_map.json` 路径要相对新模块定位(`os.path.dirname(__file__)`)。
- `secrets.env` 路径 → 改为读 `.env.local`(或保留 `load_env` 思路但指向新文件)。

**E. 接入 `src/db.py`**
- `db.py` 提供 `get_conn()`(连 `data/lab.sqlite`)+ `init_schema()`(建 `opportunities`/`fills`/`spread_history` 表)+
  `insert_opportunity(row)` / `insert_fill(row)` / `insert_spread(ts, market, spread)`。
- `run_pm_hl_monitor.py` 每次扫描后调用 `insert_opportunity(...)`;采集器调用 `insert_spread(...)`;
  实盘成交(若启用)调用 `insert_fill(...)`(替代旧 `live_ledger.csv` 的 `ledger()`)。

**F. 把机会写入 SQLite(伪码)**
```python
from src.db import get_conn, init_schema, insert_opportunity
init_schema()
for m in markets:
    r = scan_market(m)                       # opportunity_model
    opp = build_opportunity(m, r)            # ask 进/bid 退,算 net_edge/apr/is_real
    insert_opportunity(opp)                  # 落 data/lab.sqlite
```

**G. 安全(再次强调)**
- 默认 `DRY_RUN=true`、`TRADING_ENABLED=false`、`REQUIRE_MANUAL_CONFIRMATION=true`。
- 不输出任何真实 secret;`.env.example` 只放变量名 + 公开地址。
- 迁移过程**只生成代码与文档,不运行交易、不下单、不删旧文件**。

---

### 附:已知坑清单(迁移时务必带上)
1. **用 ask 进、bid 退,绝不用 mid**(假机会的头号来源)。
2. **HL 是现货式 outcome**:对冲=**买互补代币**,不能卖空;outcome 持仓在 `spotClearinghouseState`。
3. **HL 买价 clamp ≤ 0.999**(近 1 的腿乘 slip 会 >$1 被拒);卖价 ≥ 0.001。
4. **PM 便宜腿用 share-sized 限价(FAK)**,不用市价(市价 BUY 有 ~$1 最低名义额)。
5. **HL 腿 ≥ $10 最低下单额**,否则跳过(防裸腿)。
6. **HL sub-account 必须传 `vault_address`**,否则订单落 master。
7. **HL `#N` 别名要手动注入** coin_to_asset / name_to_coin。
8. **PM `get_cash` 才是权威现金**(链上 funder 余额常显 $0)。
9. **z 必须用持续更新的新数据 seed,拒绝陈旧数据**(预热假 z:序列起点 var 小 → 假 −10σ)。
10. **geoblock**: PM CLOB 偶发 403 "restricted in your region";**不做任何绕过**,遇到就停。
11. **PM 私钥视为已泄露**,实盘前轮换到专用钱包。
12. **HL "zero-fee" 未核实**,`HL_TAKER_FEE` 留参数,实盘前确认真实费率。
