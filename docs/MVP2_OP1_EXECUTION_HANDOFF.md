# MVP2 op1 Execution Handoff

Read-only handoff from the MVP2 scanner agent to a new Execution Agent.

**Scope:** `cross_venue_direct_no_complete_set` (op1) only.  
**Boundary:** This document extracts scanner inputs, fields, helpers, and caveats. It does **not** implement execution, modify scanner core logic, or touch MVP1 live executor / state machine.

---

## 1. How MVP2 op1 Scanner Runs

### Entry scripts

| Role | Path |
|------|------|
| Wrapper (recommended) | `scripts/run_pm_hl_mvp2_scanner.py` |
| CLI implementation | `src/strategies/pm_hl/mvp2_scanner/scanner_main.py` |
| op1 dry-run monitor | `src/strategies/pm_hl/mvp2_scanner/op1_strategy_dry_run.py` |
| op1 pricing / alignment core | `src/strategies/pm_hl/mvp2_scanner/match_opportunity_evaluator.py` |
| PM Moneyline discovery | `src/strategies/pm_hl/mvp2_scanner/pm_sports_match_discovery.py` |

### Two scan modes relevant to op1

| Mode | Purpose |
|------|---------|
| `pm-hl-1v1-monitor` | Continuous read-only monitor; exports op1/op2/op3/op4 each iteration |
| `pm-hl-op1-dry-run` | op1 strategy gate monitor; ranks outcomes, applies MVP1-normal entry thresholds |

Both modes call `evaluate_match()` internally. Neither submits live orders (`live_order_submission_implemented = false`).

### Recommended commands

**Single-shot evaluation (debug):**

```powershell
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-hl-1v1-sample --event-slug fifwc-arg-aut-2026-06-22 --hl-question-name "World Cup: Argentina vs Austria"
```

**Overnight-style op1 signal monitor (primary signal source):**

```powershell
python scripts/run_pm_hl_mvp2_scanner.py `
  --scan pm-hl-1v1-monitor `
  --event-slug fifwc-arg-aut-2026-06-22 `
  --hl-question-name "World Cup: Argentina vs Austria" `
  --output-label fifwc-arg-aut-2026-06-22 `
  --duration-minutes 420 `
  --interval-seconds 30
```

**op1 dry-run gate monitor (strategy eligibility):**

```powershell
python scripts/run_pm_hl_mvp2_scanner.py `
  --scan pm-hl-op1-dry-run `
  --event-slug fifwc-arg-aut-2026-06-22 `
  --hl-question-name "World Cup: Argentina vs Austria" `
  --duration-minutes 420 `
  --interval-seconds 30 `
  --s1-shares 20 `
  --s2-shares 20
```

`--execution-enabled` is a dry-run flag only. It sets `would_place_orders=true` when all gates pass, but **no order API is called**.

### Output directory

All outputs go to:

```text
outputs/pm_hl_mvp2_scanner/
```

Override with `--output-dir`.

### Output file naming

**1v1 monitor** (`pm-hl-1v1-monitor`):

| Artifact | Pattern |
|----------|---------|
| JSON snapshots | `pm_hl_1v1_moneyline_monitor_{output_label}_{YYYYMMDD_HHMMSS}.json` |
| Flat CSV | `pm_hl_1v1_moneyline_monitor_{output_label}_{YYYYMMDD_HHMMSS}.csv` |
| Text log | `pm_hl_mvp2_overnight_monitor_{output_label}_{YYYYMMDD_HHMMSS}.log` |

`output_label` defaults to `--event-slug` if `--output-label` is omitted.

**op1 dry-run** (`pm-hl-op1-dry-run`):

| Artifact | Pattern |
|----------|---------|
| JSON snapshots | `pm_hl_op1_strategy_dry_run_{event_slug}_{YYYYMMDD_HHMMSS}.json` |
| Flat CSV | `pm_hl_op1_strategy_dry_run_{event_slug}_{YYYYMMDD_HHMMSS}.csv` |

### Where to find op1 positive rows

There is **no** `latest_op1` symlink or rolling file. Positive rows live inside timestamped CSV exports.

**Primary filter (monitor CSV):**

```text
op_group == "cross_venue_direct_no_complete_set"
AND positive_flag == True          # new format; or net > 0 for older CSVs
```

**Pre-aggregated positive windows (review artifact):**

```text
outputs/pm_hl_mvp2_scanner/mvp2_positive_windows_detail.csv
```

Filter `op_group == cross_venue_direct_no_complete_set`.

**Strategy-eligible rows (dry-run CSV):**

```text
s1_entry_eligible == True
AND top1_flag == True
AND block_reason == "pass_dry_run_only"   # when execution_enabled=false
```

**Known monitor CSVs with review-ready fields** (include `positive_flag`, `edge`, `timestamp_utc8`):

- `pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv`
- `pm_hl_1v1_moneyline_monitor_bih-qat_20260624_165144.csv`
- `pm_hl_1v1_moneyline_monitor_sui-can_20260624_165140.csv`

Older Argentina CSV (`...155136.csv`) uses legacy columns (`key` instead of `outcome_or_condition`; no `positive_flag`). Use `net > 0` instead.

---

## 2. Output CSV / JSON Field Reference

### A. Monitor CSV (`pm-hl-1v1-monitor`)

Actual field names from `MONITOR_CSV_FIELDS` in `match_opportunity_evaluator.py`:

| Field | Meaning | PM leg | HL leg | signal_net / fee / depth | candidate_id |
|-------|---------|--------|--------|--------------------------|--------------|
| `timestamp` | Scan time (UTC ISO) | | | | ✓ |
| `timestamp_utc8` | Same time in UTC+8 | | | | ✓ |
| `iteration` | Monitor loop index | | | | ✓ |
| `op_group` | Opportunity family; op1 = `cross_venue_direct_no_complete_set` | | | | ✓ |
| `outcome_or_condition` | Moneyline outcome label (`Argentina`, `Draw`, …) | | | | ✓ |
| `side` | Best side string; encodes both legs (see §3) | ✓ | ✓ | | ✓ |
| `gross` | Gross edge per 1 complete set: `1 - sum_ask` | derived | derived | signal_net input | |
| `fee` | Estimated total taker fee for both legs | PM fee part | HL fee part | signal_net input | |
| `net` | Net edge per 1 set: `gross - fee` (= signal_net) | | | **signal_net** | |
| `edge` | Same as `net` (review alias) | | | **signal_net** | |
| `positive_flag` | `edge > 0` | | | derived from signal_net | filter |
| `depth` | `min(best_ask_size_leg1, best_ask_size_leg2)` | ask size | ask size | **entry depth (min)** | |
| `capacity_usd` | `depth * sum_ask` | | | derived | |
| `sum_ask` | Sum of best asks on entry legs | PM ask | HL ask | pricing input | |
| `sum_bid` | Usually empty for op1 | | | | |
| `rec` | Scanner recommendation (`ignore` / `observe` / `paper` / `manual_review`) | | | | |
| `est_profit_20_shares` | `edge * 20` | | | derived | |
| `est_portfolio_return_low_pct` | profit / 108 * 100 | | | derived | |
| `est_portfolio_return_high_pct` | profit / 120 * 100 | | | derived | |
| `note` | Fixed disclaimer string | | | | |

**Leg mapping from `side`:**

| `side` pattern | Leg 1 (buy) | Leg 2 (buy) |
|----------------|-------------|-------------|
| `buy_pm_{X}_yes_buy_hl_{X}_no` | PM `{X}` YES @ ask | HL `{X}` NO @ ask |
| `buy_hl_{X}_yes_buy_pm_{X}_no` | HL `{X}` YES @ ask | PM `{X}` NO @ ask |

Token/coin IDs are **not** in the monitor CSV. Resolve them from JSON `aligned_outcomes` (see §4).

### B. op1 dry-run CSV (`pm-hl-op1-dry-run`)

Fields from `DRY_RUN_CSV_FIELDS` in `op1_strategy_dry_run.py`:

| Field | Meaning | Notes |
|-------|---------|-------|
| `timestamp`, `iteration` | Scan metadata | candidate_id |
| `outcome` | Moneyline outcome | candidate_id |
| `best_side` | Same encoding as monitor `side` | PM+HL legs | candidate_id |
| `entry_cost` | `sum_ask` of best op1 side | pricing |
| `entry_gross_edge` | `1 - entry_cost` | = monitor `gross` |
| `entry_fee` | Estimated fee | = monitor `fee` |
| `entry_net` | Net edge per set | = monitor `net` / **signal_net** |
| `entry_net_bps` | `entry_net / entry_cost * 10000` | gate input |
| `expected_profit_s1_20` | `entry_net * s1_shares` | gate input |
| `expected_profit_s1s2_40` | `entry_net * (s1+s2)` | rank_score |
| `depth` | Min ask depth (same as monitor) | coarse gate |
| `entry_leg1_depth`, `entry_leg2_depth` | Per-leg best ask sizes | **hard depth gate (≥40)** |
| `s2_exit_leg1_bid_depth`, `s2_exit_leg2_bid_depth` | Per-leg best bid sizes | S2 exit gate (≥20) |
| `rule_match_score` | PM/HL rule match (0.90 for Moneyline) | gate input |
| `rank`, `top1_flag`, `rank_score` | Outcome ranking | only top1 can activate |
| `s1_entry_eligible`, `s2_entry_eligible` | All entry gates passed | **executable dry-run flag** |
| `depth_ok`, `net_bps_ok`, `expected_profit_ok`, `rule_match_ok`, `pre_match_cutoff_ok`, `activation_allowed` | Individual gates | debugging |
| `s2_exit_depth_ok` | S2 bid depth gate | exit planning |
| `block_reason` | Comma-separated failure codes or `pass_dry_run_only` | |
| `would_place_orders` | `eligible AND execution_enabled` | always false in practice today |

### C. JSON snapshots

**Monitor JSON** (`pm_hl_1v1_moneyline_monitor_*.json`):

- Top-level: `pm_event_slug`, `hl_question_name`, `snapshots[]`
- Each snapshot contains `op1_direct_no_complete_set[]` with full op1 rows plus `raw_opportunity_snapshot` on dry-run only

**Dry-run JSON** (`pm_hl_op1_strategy_dry_run_*.json`):

- `config`: all threshold parameters
- `snapshots[]`: `ranking_rows`, `gate_rows`, `top1_decision`, `raw_opportunity_snapshot`
- `raw_opportunity_snapshot.aligned_outcomes[]`: **execution-critical IDs**

`aligned_outcomes` fields per outcome:

| Field | Venue | Use |
|-------|-------|-----|
| `pm_yes_token`, `pm_no_token` | PM CLOB token IDs | order routing |
| `pm_market_id`, `pm_market_slug` | PM metadata | candidate_id |
| `pm_yes_book`, `pm_no_book` | bid/ask/size/tick_size | revalidation |
| `hl_outcome_id` | HL outcome integer | candidate_id |
| `hl_yes_coin`, `hl_no_coin` | e.g. `#1040`, `#1041` | HL order routing |
| `hl_yes_book`, `hl_no_book` | bid/ask/size | revalidation |

**Single-evaluation JSON** (`pm-hl-1v1-sample`):

- `write_evaluation_json()` → `pm_hl_1v1_moneyline_{slug}_{stamp}.json`
- Same `aligned_outcomes` + `opportunity_groups.cross_venue_direct_no_complete_set`

---

## 3. Identifying Executable op1 Positive Rows

### op1 definition (1v1 Moneyline YES+NO complete set)

For each outcome `X` in a 3-way Moneyline (Team A, Draw, Team B), op1 evaluates two **buy-only** two-leg complete sets:

```text
Side A: PM X YES  +  HL X NO
Side B: HL X YES  +  PM X NO
```

Payoff intent: exactly one leg pays $1 at settlement (complete-set relation), assuming PM and HL resolve the same outcome under matched rules.

Per outcome, the scanner picks the side with higher `net`. Monitor CSV exports one row per outcome (best side only).

### signal_net formula

From `_direct_no_candidates()` in `match_opportunity_evaluator.py`:

**Side `buy_pm_{X}_yes_buy_hl_{X}_no`:**

```text
sum_ask   = pm_X_yes_ask + hl_X_no_ask
gross     = 1 - sum_ask
fee       = pm_fee(pm_X_yes_ask) + HL_TAKER_FEE
net       = gross - fee                    ← this is signal_net
```

**Side `buy_hl_{X}_yes_buy_pm_{X}_no`:**

```text
sum_ask   = hl_X_yes_ask + pm_X_no_ask
gross     = 1 - sum_ask
fee       = HL_TAKER_FEE + pm_fee(pm_X_no_ask)
net       = gross - fee
```

**PM fee function** (`src/strategies/pm_hl/opportunity_model.py`):

```text
pm_fee(price) = 0.03 * price * (1 - price)
```

**HL fee:** `float(os.environ.get("HL_TAKER_FEE", "0"))`, default `0`.

Pricing is **top-of-book best ask only**, not VWAP over depth.

### depth formula

**Monitor `depth` (coarse):**

```text
depth = min(best_ask_size_leg1, best_ask_size_leg2)
```

**Dry-run entry depth (hard gate, per leg):**

| `best_side` | `entry_leg1_depth` | `entry_leg2_depth` |
|-------------|--------------------|--------------------|
| `buy_pm_*_yes_buy_hl_*_no` | PM YES ask size | HL NO ask size |
| `buy_hl_*_yes_buy_pm_*_no` | HL YES ask size | PM NO ask size |

Gate: **both legs ≥ 40 shares** (`entry_min_best_book_depth_shares`).

S2 exit gate (dry-run only): both exit legs' best **bid** sizes ≥ 20 shares.

### Must-satisfy conditions

**Layer 1 — Scanner positive signal (monitor CSV):**

| Condition | Rule |
|-----------|------|
| op group | `op_group == "cross_venue_direct_no_complete_set"` |
| positive edge | `positive_flag == True` or `net > 0` |
| valid side | `side` starts with `buy_pm_` or `buy_hl_` |
| non-empty outcome | `outcome_or_condition` not empty |

This layer does **not** enforce 40-share per-leg depth or MVP1 profit thresholds.

**Layer 2 — Strategy eligible (dry-run CSV / gates):**

| Gate | Threshold |
|------|-----------|
| `depth_ok` | both `entry_leg*_depth` ≥ 40 |
| `net_bps_ok` | `entry_net_bps` ≥ 10 |
| `expected_profit_ok` | `expected_profit_s1_20` ≥ $0.03 |
| `rule_match_ok` | `rule_match_score` ≥ 0.90 |
| `pre_match_cutoff_ok` | > 10 minutes before match start |
| `activation_allowed` | `top1_flag == True` (max 1 active outcome) |
| `s1_entry_eligible` | all above true |

For execution v1, require **Layer 1 + fresh revalidation of Layer 2** immediately before any order.

### candidate_id suggestion

No canonical `candidate_id` exists today. Recommended composite key:

```text
{pm_event_slug}|{hl_question_name}|{outcome}|{best_side}|{timestamp}
```

For stable leg routing, join to JSON `aligned_outcomes` and include `{pm_yes_token or pm_no_token, hl_yes_coin or hl_no_coin}` depending on `best_side`.

---

## 4. Existing Helper Functions

### PM — `src/strategies/pm_hl/clients/polymarket.py`

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `load_env(path?)` | optional `.env.local` path | `bool` | loads PM env vars |
| `gamma_event_by_slug(slug)` | event slug | `dict \| None` | PM sports event metadata |
| `gamma_event_by_id(id)` | event id | `dict \| None` | |
| `gamma_market_by_slug(slug)` | market slug | `dict \| None` | |
| `gamma_market_by_id(id)` | market id | `dict \| None` | |
| `book(token_id)` | CLOB token id | `(bids, asks, raw)` | full order book |
| `top(token_id)` | CLOB token id | `(best_bid, best_ask, tick_size, neg_risk)` | top-of-book |
| `build_client()` | env keys | ClobClient | **order client — do not use from scanner handoff** |
| `get_cash(client?)` | client | `(balance, client)` | account read |

Scanner uses `book`/`top` via `pm_sports_match_discovery._top_for_token()`.

### HL — `src/strategies/pm_hl/clients/hyperliquid.py`

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `load_env(path?)` | optional path | `bool` | |
| `info(payload)` | e.g. `{"type":"outcomeMeta"}` | JSON dict | metadata + questions |
| `coin_book(coin)` | e.g. `"#1040"` | `(bids, asks)` | L2 book |
| `yes_book(outcome_id)` | int outcome id | `(bids, asks)` | shorthand for YES coin |
| `build_exchange(account?)` | env keys | `(Exchange, agent, account)` | **order client — do not use from scanner handoff** |
| `spot_balances(addr?)` | address | `[(coin, total), ...]` | read-only |
| `outcome_balances(addr?)` | address | `{coin: total}` | read-only |

Scanner uses `info({"type":"outcomeMeta"})` and `coin_book()` via `match_opportunity_evaluator._hl_top()`.

### PM Moneyline discovery — `pm_sports_match_discovery.py`

| Function | Input | Output |
|----------|-------|--------|
| `discover_moneyline(event_slug)` | PM event slug | `SportsMoneylineDiscovery` with 3 Moneyline markets, token IDs, top-of-book |

### Evaluator — `match_opportunity_evaluator.py`

| Function | Input | Output |
|----------|-------|--------|
| `evaluate_match(pm_event_slug, hl_question_name)` | slugs / question name | `MatchEvaluation` with `aligned_outcomes`, `opportunity_groups` |
| `monitor_match(...)` | duration, interval | JSON + CSV + log paths |
| `write_evaluation_json(output_dir, evaluation)` | evaluation | one-shot JSON path |

### op1 dry-run — `op1_strategy_dry_run.py`

| Function | Input | Output |
|----------|-------|--------|
| `build_strategy_snapshot(evaluation, config, ...)` | match eval + config | ranking/gate/top1 dict |
| `monitor_op1_strategy_dry_run(output_dir, config)` | config | dry-run JSON path |

### Fee helper — `src/strategies/pm_hl/opportunity_model.py`

| Function | Input | Output |
|----------|-------|--------|
| `pm_fee(price)` | float price | estimated PM taker fee |

### Legacy order helpers — **list only, do not use or modify for MVP2 v1**

Located in `src/strategies/pm_hl/strategy.py` (MVP1-era, hardcoded market maps, different semantics):

| Function | Purpose |
|----------|---------|
| `hl_take(exchange, coin, is_buy, size, ref_px, ...)` | HL IOC order |
| `pm_marketable_buy(client, token, shares, ref_ask, ...)` | PM FAK buy |
| `pm_limit_buy(...)` | PM GTC limit buy |
| `pm_marketable_sell(...)` | PM FAK sell |
| `pm_cancel(...)` | cancel |
| `open_box_atomic(...)` | two-leg box open |
| `close_position(...)` | position close |
| `hedge_leg(market, direction)` | **WC champion map only — wrong for 1v1 Moneyline** |

These are tied to MVP1 `team_map.json` markets, not PM sports Moneyline discovery. Execution v1 should build new routing from `aligned_outcomes`, not reuse `hedge_leg` / `open_box_atomic`.

---

## 5. Sample op1 Positive Rows

From existing monitor output (no secrets). Values are per 1 complete set unless noted.

### Sample 1 — Bosnia vs Qatar monitor

Source: `pm_hl_1v1_moneyline_monitor_bih-qat_20260624_165144.csv`, iteration 241

| Field | Value |
|-------|-------|
| `timestamp_utc8` | 2026-06-25T03:01:35+08:00 |
| `op_group` | cross_venue_direct_no_complete_set |
| `outcome_or_condition` | Bosnia-Herzegovina |
| `side` | buy_pm_Bosnia-Herzegovina_yes_buy_hl_Bosnia-Herzegovina_no |
| `gross` | 0.0100 |
| `fee` | 0.006528 |
| `net` (signal_net) | 0.003472 |
| `positive_flag` | True |
| `depth` | 63.0 |
| `rec` | paper |
| `est_profit_20_shares` | 0.06944 |

### Sample 2 — Portugal vs Uzbekistan monitor

Source: `pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv`, iteration 50

| Field | Value |
|-------|-------|
| `timestamp_utc8` | 2026-06-24T01:10:44+08:00 |
| `op_group` | cross_venue_direct_no_complete_set |
| `outcome_or_condition` | Portugal |
| `side` | buy_pm_Portugal_yes_buy_hl_Portugal_no |
| `gross` | 0.00399 |
| `fee` | 0.000901 |
| `net` (signal_net) | 0.003089 |
| `positive_flag` | True |
| `depth` | 12.0 |
| `rec` | paper |
| `est_profit_20_shares` | 0.06178 |

Note: Sample 2 has `depth=12` (< 40), so it is a **positive signal** but would fail dry-run `depth_ok`. This illustrates the difference between Layer 1 and Layer 2.

---

## 6. Known Issues and Caveats

### Empty or missing fields

- `sum_ask`, `sum_bid` are often blank in monitor CSV (not exported in flat CSV mapping); reconstruct from JSON or re-fetch books.
- If a book fetch fails, `pm_yes_book.error` / `hl_yes_book.error` is set; op1 row may have `net=None` and be excluded from positives.
- Legacy monitor CSVs use column `key` instead of `outcome_or_condition` and lack `positive_flag`, `edge`, `timestamp_utc8`.

### Token / outcome mapping

- PM outcomes come from `discover_moneyline()` (`groupItemTitle` / event `teams`).
- HL outcomes matched by exact label or normalized label (`_norm_label()`); alias example: `Bosnia-Herzegovina` (PM) ↔ `Bosnia and Herzegovina` (HL).
- HL YES coin = `#{outcome_id * 10}`; HL NO coin = `#{outcome_id * 10 + 1}`.
- Wrong mapping → wrong leg. Always verify `aligned_outcomes` for the specific `pm_event_slug` + `hl_question_name` pair before execution.

### Fee assumptions

- PM fee is a taker approximation, not exact CLOB fee schedule.
- HL fee defaults to 0; set `HL_TAKER_FEE` env if needed.
- Fees apply only to the PM leg in each op1 side (one PM price per side).

### Depth assumptions

- `depth` is min top-of-book ask size, **not** 40-share VWAP.
- Dry-run `entry_leg1_depth` / `entry_leg2_depth` are per-leg best ask sizes; stricter than monitor `depth` when one leg is thin.
- Large depth on one leg can mask thin liquidity on the other (Sample 2).

### Quote age / timestamps

- CSV `timestamp` is scan loop time, **not** exchange book timestamp.
- PM CLOB `book` response may include server fields in `raw`, but scanner does not record book age.
- HL `l2Book` has no quote-age field in current code.
- **Execution must re-fetch both legs immediately before ordering**; do not trust stale scanner rows.

### Execution risk points

| Risk | Detail |
|------|--------|
| Top-of-book only | Edge can disappear at realistic fill size |
| No sequencing | Scanner does not plan leg1-then-leg2 or handle partial fills |
| Single-leg exposure | One leg filling without the other is the primary operational risk |
| Rule match score | Fixed 0.90 heuristic; not a legal equivalence proof |
| `sell_*` in op2 | op2 side labels are **not** execution instructions |
| `--execution-enabled` | Does not submit orders; `would_place_orders` is informational only |
| Pre-match cutoff | Dry-run blocks entry within 10 minutes of `start_time`; monitor positives ignore this |
| Match start time | From PM `startTime` / `startDate`; may be missing → cutoff gate passes by default |

---

## 7. Recommendations for Execution Agent

### Files safe to read

| File | Why |
|------|-----|
| `docs/pm_hl_mvp2_op1_strategy_design.md` | Thresholds, S1/S2 design intent |
| `docs/pm_hl_execution_layer_v1_handoff.md` | v1 scope and risk controls |
| `docs/pm_hl_mvp2_final_report.md` | Four-match evidence summary |
| `src/strategies/pm_hl/mvp2_scanner/match_opportunity_evaluator.py` | op1 formulas, alignment |
| `src/strategies/pm_hl/mvp2_scanner/op1_strategy_dry_run.py` | Gate logic |
| `src/strategies/pm_hl/mvp2_scanner/pm_sports_match_discovery.py` | PM Moneyline structure |
| `src/strategies/pm_hl/clients/polymarket.py` | PM book/metadata |
| `src/strategies/pm_hl/clients/hyperliquid.py` | HL book/metadata |
| `outputs/pm_hl_mvp2_scanner/mvp2_positive_windows_detail.csv` | Aggregated positive windows |
| `outputs/pm_hl_mvp2_scanner/mvp2_execution_handoff_decision.csv` | op1 vs op2/op3/op4 decision |

### Files do not modify

| File / area | Reason |
|-------------|--------|
| `src/strategies/pm_hl/mvp2_scanner/*` core evaluator | Scanner agent owns this; execution should consume outputs |
| MVP1 live executor / state machine | Explicit boundary |
| `logs/pm_hl/`, `data/lab.sqlite` | MVP1 runtime state |
| `src/strategies/pm_hl/strategy.py` | Legacy; do not extend for MVP2 op1 |

### Old code not to reuse

- `hedge_leg()` / `open_box_atomic()` — built for WC champion `team_map.json`, not 1v1 Moneyline
- Champion scanner paths (`opportunity_builder.py`, `market_mapper.py` champion modes)
- op2 / op3 / op4 rows as execution inputs
- MVP1 S1/S2 state machine as-is (per execution layer v1 handoff)

### Minimum execution v1 starting CSV

Start from a **review-ready monitor CSV** with op1 positives:

```text
outputs/pm_hl_mvp2_scanner/pm_hl_1v1_moneyline_monitor_fifwc-prt-uzb-2026-06-23_20260623_164411.csv
```

Filter:

```python
op_group == "cross_venue_direct_no_complete_set" and positive_flag == True
```

Join each row to the corresponding monitor JSON snapshot's `aligned_outcomes` (same `timestamp` + `iteration`) for token/coin IDs.

For gate-aligned backtesting, use dry-run CSV instead and filter `s1_entry_eligible == True`.

Evidence baseline: `mvp2_execution_handoff_decision.csv` confirms op1 as the only `include_v1_execution` candidate (78 positive windows across four matches; strongest observed net ≈ 0.069 per set on Argentina vs Austria).

---

## Quick Reference — op1 Side → Order Legs

```text
buy_pm_{X}_yes_buy_hl_{X}_no:
  LEG1: BUY  PM token = aligned_outcomes[X].pm_yes_token  @ pm_yes_book.ask
  LEG2: BUY  HL coin   = aligned_outcomes[X].hl_no_coin    @ hl_no_book.ask

buy_hl_{X}_yes_buy_pm_{X}_no:
  LEG1: BUY  HL coin   = aligned_outcomes[X].hl_yes_coin   @ hl_yes_book.ask
  LEG2: BUY  PM token  = aligned_outcomes[X].pm_no_token   @ pm_no_book.ask
```

---

*Generated by MVP2 scanner agent. Read-only handoff; no execution code included.*
