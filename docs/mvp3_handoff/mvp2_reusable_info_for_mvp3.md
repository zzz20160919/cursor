# MVP2 Reusable Info for MVP3

This is a read-only handoff from the old MVP2 PM-HL agent to a future MVP3 agent.

MVP2:

```text
Polymarket vs Hyperliquid
```

MVP3:

```text
Polymarket vs Predict.fun
```

The reusable part is the cross-venue complete-set arbitrage scanner design:

```text
Buy Venue A YES + Buy Venue B NO
or
Buy Venue B YES + Buy Venue A NO
```

This document extracts reusable information only. It does not implement MVP3, Predict.fun, execution, live orders, or any change to old PM-HL code.

---

## 1. MVP3 Background

MVP3 = Polymarket vs Predict.fun arbitrage scanner.

### MVP3-A: data probe only

First phase should only prove data access and semantics:

- Find a Polymarket market.
- Find the corresponding Predict.fun market.
- Pull Polymarket orderbook.
- Pull Predict.fun orderbook.
- Save raw JSON from both venues.
- Confirm YES / NO price representation.
- Confirm token / outcome identifiers.
- Do not place orders.
- Do not run live.
- Do not implement execution.

MVP3-A should answer: "Can we reliably identify the same market on PM and Predict.fun, and can we read comparable YES/NO top-of-book prices?"

### MVP3-B: scanner

Only after MVP3-A proves the data layer, build a scanner:

- Normalize PM / Predict.fun orderbooks into one internal schema.
- Calculate PM YES + Predict.fun NO.
- Calculate Predict.fun YES + PM NO.
- Output `candidate`, `near_miss`, `monitor`, and `summary`.
- Save raw JSON alongside normalized rows.
- Stay read-only.
- Do not call execution functions.

---

## 2. What MVP2 and MVP3 Have in Common

MVP3 can reuse the following PM-HL ideas, with the second venue replaced by Predict.fun.

1. Cross-venue complete-set arbitrage logic:
   - One leg buys YES on one venue.
   - The other leg buys NO on the other venue.
   - If settlement rules match, exactly one side should pay 1.

2. YES + NO buy-only combinations:
   - Direction A: buy PM YES + buy other venue NO.
   - Direction B: buy other venue YES + buy PM NO.
   - MVP3 should avoid short/sell logic in initial scanner.

3. Gross edge:

```text
gross_edge = 1 - yes_ask - no_ask
```

4. Net edge after cost:

```text
net_edge = gross_edge - venue_fees - cost_buffer
```

5. Fee / cost buffer:
   - MVP2 used PM taker fee approximation `0.03 * price * (1 - price)`.
   - MVP2 used `HL_TAKER_FEE` env default `0`.
   - MVP3 must replace HL fee with Predict.fun fee, and add an explicit `cost_buffer`.

6. Depth check:
   - MVP2 used top-of-book size, not VWAP.
   - Complete-set depth = minimum size available across the two entry legs.
   - MVP3 should output both per-leg depth and `min_depth`.

7. Minimum profit:
   - MVP2 used per-share edge multiplied by target size.
   - Example: `estimated_profit_usd = net_edge * target_size_shares`.

8. Market rule mapping:
   - MVP2 tracked `rule_match_score`, rule text, mapping status, failure reasons.
   - MVP3 should require PM and Predict.fun settlement rule equivalence before candidate status.

9. Quote freshness:
   - MVP2 learned that scan timestamp is not enough for live action.
   - MVP3 should record orderbook timestamps if Predict.fun provides them.
   - If not provided, mark `UNKNOWN / NEEDS_RECHECK` and use local fetch time as fallback metadata only.

10. Output shape:
   - Monitor rows for every scanned mapping.
   - Candidate rows for rows above threshold.
   - Near-miss rows for rows close to threshold or blocked by one clear reason.
   - Summary markdown for quick review.

11. No fake candidate:
   - If no true candidate exists, output zero candidates.
   - Do not fabricate a row just to test downstream execution.

12. Paper first:
   - Scanner should be read-only.
   - Any future execution should start with paper / payload preview.

13. Fresh revalidation before live:
   - Never place from stale scanner rows.
   - Re-fetch both books and recalculate edge and depth immediately before any future order.

14. No chase / no retry / no deeper book:
   - Future execution should not chase price after movement.
   - Do not auto retry.
   - Do not consume deeper book unless explicitly designed and tested.

15. Taker-limit price protection:
   - Future execution reference only.
   - Limit price should equal the revalidated best ask, or a separately approved max acceptable price.
   - Do not use market orders.

---

## 3. What MVP2 and MVP3 Do Not Share

Do not directly reuse the following PM-HL pieces for MVP3:

| PM-HL component | Do not reuse because |
| --- | --- |
| Hyperliquid API | MVP3 second venue is Predict.fun, not HL. |
| HL `outcomeMeta` | Predict.fun market metadata must be discovered independently. |
| HL `l2Book` format | Predict.fun orderbook schema may be different. |
| HL coin IDs like `#2120` / `#2121` | Predict.fun instruments and IDs must be verified from Predict.fun API. |
| HL question names | Predict.fun likely uses market IDs/slugs, not HL `question_name`. |
| HL YES/NO mapping rule `outcome_id * 10` | Predict.fun YES/NO representation must be checked from raw data. |
| `HL_TAKER_FEE` | Replace with Predict.fun fee; do not assume zero. |
| HL execution adapter | Not relevant to Predict.fun. |
| PM-HL S1/S2 portfolio state | MVP3-A/B is scanner only; do not inherit live portfolio state. |
| PM-HL reentry / exit state machine | MVP3 scope is data probe then scanner, not portfolio lifecycle. |
| PM-HL live execution loop | Do not connect MVP3 to old live loop. |
| Old live executor | It contains HL assumptions and old PM-HL state. |
| PM-HL positions / fills / risk events | Historical PM-HL runtime state is not MVP3 state. |
| PM-HL market list | MVP3 must build its own PM vs Predict.fun mapping list. |
| PM-HL thresholds | May be useful as starting scanner knobs only; not live thresholds until revalidated. |

Reason:

```text
MVP3's second venue is Predict.fun. The MVP3 agent must re-verify Predict.fun API, orderbook, YES/NO representation, fee, tick size, min size, depth, settlement rules, cancellation rules, and void rules from raw responses and official docs.
```

---

## 4. Reusable Code Path Inventory

Default rule: old PM-HL files are reference-only. Safe to modify = NO unless the file is the new MVP3 handoff document.

| file path | what it does | reusable for MVP3? | how MVP3 should use it | safe to modify? |
| --- | --- | --- | --- | --- |
| `docs/mvp3_handoff/mvp2_reusable_info_for_mvp3.md` | This handoff document | YES | Copy to MVP3 agent as context | YES |
| `src/strategies/pm_hl/clients/polymarket.py` | PM Gamma, CLOB, positions, PM client helpers | YES, PM data layer | Reference `gamma_*`, `book`, `top`, `http_json`; do not call order client in MVP3-A/B | NO |
| `src/strategies/pm_hl/mvp2_scanner/pm_sports_match_discovery.py` | PM sports parent event -> Moneyline binary markets, YES/NO tokens, top books | YES for PM sports market discovery pattern | Reference event slug, child markets, `clobTokenIds`, `outcomes`, top-of-book parsing | NO |
| `src/strategies/pm_hl/mvp2_scanner/market_mapper.py` | PM Gamma market scanning, name normalization, champion and match mapping | YES as mapping pattern | Reference `normalize_name`, alias handling, PM champion discovery | NO |
| `src/strategies/pm_hl/mvp2_scanner/match_opportunity_evaluator.py` | PM-HL 1v1 alignment and op1/op2/op3/op4 calculations | YES for formulas and output grouping | Reuse concepts only; replace HL types/books with Predict.fun normalized book | NO |
| `src/strategies/pm_hl/mvp2_scanner/op1_strategy_dry_run.py` | op1 gate logic, top1 selection, depth/profit/rule gates | YES for scanner gate pattern | Reference only; do not copy S1/S2 execution semantics into MVP3-A/B | NO |
| `src/strategies/pm_hl/mvp2_scanner/sinks.py` | CSV/JSON/table output helpers | YES | Reference flat CSV + JSON output style | NO |
| `src/strategies/pm_hl/mvp2_scanner/schemas.py` | Dataclass shapes for books, mappings, rows, summaries | YES conceptually | Use as inspiration for MVP3 dataclasses | NO |
| `src/strategies/pm_hl/mvp2_scanner/risk_scoring.py` | Simple risk/recommendation scoring | YES as initial scanner heuristic | Reference recommendation categories and depth/missing-price penalties | NO |
| `src/strategies/pm_hl/opportunity_model.py` | Older PM-HL math, `pm_fee`, deeper-book `walk` | PARTIAL | Reuse PM fee idea; do not reuse HL-specific derived NO logic | NO |
| `scripts/run_pm_hl_mvp2_scanner.py` | Wrapper to run MVP2 scanner CLI | YES as CLI structure | Reference wrapper pattern only | NO |
| `src/strategies/pm_hl/mvp2_scanner/scanner_main.py` | argparse modes and output-dir pattern | YES | Reference CLI shape and `--no-export` / `--output-dir` pattern | NO |
| `scripts/run_pm_hl_op1_batch_watcher.py` | Batch op1 watcher, candidates, near-miss, coverage, summary | YES for scanner output categories | Reference `candidate`, `near_miss`, `coverage`, `summary` output pattern | NO |
| `outputs/pm_hl_mvp2_scanner/op1_live_candidates_latest.csv` | Latest candidate CSV shape | YES as field pattern | Reference headers only; not input to MVP3 | NO |
| `outputs/pm_hl_mvp2_scanner/op1_near_miss_latest.csv` | Latest near-miss CSV shape | YES as field pattern | Reference headers only; not input to MVP3 | NO |
| `docs/pm_hl_mvp2_scanner_v0.md` | MVP2 scanner design doc | YES | Reference non-goals, read-only scanner posture, formulas | NO |
| `docs/MVP2_OP1_EXECUTION_HANDOFF.md` | op1 execution handoff from MVP2 | PARTIAL | Reference caveats and helper inventory; avoid HL-specific routing | NO |
| `docs/pm_hl_execution_layer_v1_handoff.md` | Future execution controls | PARTIAL | Reference risk controls only | NO |
| `scripts/run_pm_hl_execution_v1.py` | Revalidation, order intents, paper/live safety outputs | FUTURE ONLY | Execution v3 reference; MVP3-A/B must not call it | NO |
| `src/strategies/pm_hl/strategy.py` | Old MVP1-era PM/HL live helper functions | FUTURE ONLY / mostly do not reuse | Reference safety concepts only; do not copy `hedge_leg` or `open_box_atomic` | NO |
| `src/strategies/pm_hl/clients/hyperliquid.py` | HL info/book/exchange helpers | NO for MVP3 | Do not use; replace with Predict.fun client after MVP3-A probe | NO |
| `logs/pm_hl/*` | PM-HL runtime logs/state | NO | Historical audit only, not MVP3 input | NO |
| `data/execution_v1/*` | PM-HL execution v1 output artifacts | FUTURE ONLY | Reference CSV names / safety fields only | NO |

---

## 5. Polymarket Data Layer Reuse

### 5.1 PM market search / discovery

Reusable helper:

```text
src/strategies/pm_hl/clients/polymarket.py
```

PM Gamma endpoints used:

- `gamma_event_by_slug(slug)` -> calls `/events?slug=...`.
- `gamma_event_by_id(event_id)` -> calls `/events?id=...`.
- `gamma_market_by_slug(slug)` -> calls `/markets?slug=...`.
- `gamma_market_by_id(market_id)` -> calls `/markets?id=...`.
- `_gamma_list(path, params)` -> generic list helper.

For broader market discovery, `market_mapper.py` uses:

```text
GET https://gamma-api.polymarket.com/markets?limit=100&offset=...&active=true&closed=false&enableOrderBook=true
```

MVP3 can reuse the discovery pattern, but should build a new PM vs Predict.fun universe rather than use PM-HL market lists.

### 5.2 PM market slug source

Known sources:

- User-provided slug via CLI (`--event-slug`) for sports parent event samples.
- Gamma event response field `slug`.
- Gamma market response field `slug`.
- PM champion discovery stores `slug` in `market_mapper.discover_pm_champion_markets()`.

MVP3 should record both PM market slug and PM market ID in normalized rows.

### 5.3 PM token_id source

PM token IDs come from Gamma market field:

```text
clobTokenIds
```

In the old code, `clobTokenIds` may be a JSON string or list. Helpers parse it with `_parse_json_list()`.

For binary markets:

- `clobTokenIds[0]` usually maps to YES if `outcomes[0] == "Yes"`.
- `clobTokenIds[1]` usually maps to NO if `outcomes[1] == "No"`.

Safer champion logic:

```text
yes_index = outcomes.index("yes") if "yes" in outcomes else 0
no_index = outcomes.index("no") if "no" in outcomes else 1
```

MVP3 should use explicit `outcomes` index mapping, not assume `[0] = YES` unless verified for that market.

### 5.4 YES and NO token identification

Sports Moneyline discovery currently assumes:

```text
pm_yes_token = clob_token_ids[0]
pm_no_token  = clob_token_ids[1]
```

Champion discovery checks the lowercased `outcomes` list to find YES and NO indices.

MVP3 recommendation:

- Read `outcomes` and `clobTokenIds` together.
- Persist `pm_yes_token_source = "outcomes_index"` or similar.
- If `outcomes` missing or not `["Yes", "No"]`, mark mapping `UNKNOWN / NEEDS_RECHECK`.

### 5.5 PM CLOB orderbook

Reusable helper:

```text
pm.book(token_id)
```

It calls:

```text
GET https://clob.polymarket.com/book?token_id={token_id}
```

It returns:

```python
(bids, asks, raw)
```

Where:

```python
bids = [(price_float, size_float), ...]  # sorted descending
asks = [(price_float, size_float), ...]  # sorted ascending
raw  = original response dict
```

The raw response is available to callers, but not always persisted in flat monitor CSV. MVP3-A should save raw JSON explicitly.

### 5.6 Best bid / best ask parsing

Reusable helper:

```text
pm.top(token_id)
```

Returns:

```python
(
  best_bid or (0.0, 0.0),
  best_ask or (1.0, 0.0),
  tick_size,
  neg_risk,
)
```

In `pm_sports_match_discovery._top_for_token()`, empty bids/asks become `None` fields inside `TokenBookTop`, and exceptions are captured as `error`.

MVP3 should prefer `None` for missing quotes in scanner outputs, because `0.0` / `1.0` fallback can hide missing-book conditions.

### 5.7 Tick size / min order size

Known:

- `pm.book()` raw response includes `tick_size`; `pm.top()` returns `tick_size`.
- `pm_sports_match_discovery.TokenBookTop` stores `tick_size`.
- `neg_risk` is returned by `pm.top()` from raw.

UNKNOWN / NEEDS_RECHECK:

- PM min order size is not consistently modeled in MVP2 scanner.
- PM CLOB exact fee/min-size/tick behavior should be rechecked before any execution.

### 5.8 PM fee

Reusable helper:

```text
src/strategies/pm_hl/opportunity_model.py
pm_fee(price) = 0.03 * price * (1 - price)
```

This is an estimated taker fee approximation used for scanner math. MVP3 should label it as estimate and verify exact PM fee rules before any live execution.

### 5.9 Raw response storage

Existing behavior:

- `pm_sports_match_discovery.write_discovery_json()` writes normalized discovery, not full raw event/book JSON.
- `match_opportunity_evaluator.write_evaluation_json()` writes dataclass snapshots and normalized books.
- `opportunity_builder.build_champion_row()` stores PM raw book fields partially in row `raw`.

MVP3-A should save full raw PM and Predict.fun responses to disk before normalization.

### 5.10 API error / timeout handling

PM helper `http_json()` uses `urllib.request.urlopen(..., timeout=8)` with `User-Agent` and JSON headers.

Handling patterns:

- Low-level `http_json()` raises exceptions.
- `pm_sports_match_discovery._top_for_token()` catches exceptions and stores a truncated `error`.
- `opportunity_builder._safe_pm_book()` returns empty `BookTop` plus error string.
- Monitors catch iteration errors and continue to next interval.

MVP3 should use safe wrapper functions for both venues and include `fail_reason` in output rows.

### 5.11 Empty orderbook handling

Existing patterns:

- `pm.book()` returns empty lists if raw has no bids/asks.
- `pm.top()` returns bid `(0,0)` and ask `(1,0)` for missing book.
- `TokenBookTop` pattern stores `None` for missing price/size.
- Opportunity rows are not candidates if price is missing.

MVP3 should:

- Treat empty book as `quote_ok = false`.
- Do not create a candidate.
- Emit near-miss or monitor row with `missing_reason = "empty_pm_book"` or venue-specific equivalent.

---

## 6. Arbitrage Calculation Logic

### MVP2 original op1 logic

Reference files:

- `src/strategies/pm_hl/mvp2_scanner/match_opportunity_evaluator.py`
- `_direct_no_candidates()`
- `_formula_reference()`

MVP2 Direction A:

```text
Buy PM YES + Buy HL NO
sum_ask = pm_yes_ask + hl_no_ask
gross = 1 - sum_ask
fee = pm_fee(pm_yes_ask) + hl_fee
net = gross - fee
depth = min(pm_yes_ask_size, hl_no_ask_size)
```

MVP2 Direction B:

```text
Buy HL YES + Buy PM NO
sum_ask = hl_yes_ask + pm_no_ask
gross = 1 - sum_ask
fee = hl_fee + pm_fee(pm_no_ask)
net = gross - fee
depth = min(hl_yes_ask_size, pm_no_ask_size)
```

### MVP3 corresponding logic

MVP3 Direction A:

```text
Buy PM YES + Buy Predict.fun NO
sum_ask = pm_yes_ask + pd_no_ask
gross = 1 - sum_ask
fee = pm_fee(pm_yes_ask) + pd_fee(pd_no_ask)
net = gross - fee - cost_buffer
depth = min(pm_yes_ask_size, pd_no_ask_size)
```

MVP3 Direction B:

```text
Buy Predict.fun YES + Buy PM NO
sum_ask = pd_yes_ask + pm_no_ask
gross = 1 - sum_ask
fee = pd_fee(pd_yes_ask) + pm_fee(pm_no_ask)
net = gross - fee - cost_buffer
depth = min(pd_yes_ask_size, pm_no_ask_size)
```

MVP3 should output both directions, even if neither is a candidate.

Recommended normalized result fields:

```text
direction_a_gross_edge
direction_a_net_edge
direction_a_depth
direction_b_gross_edge
direction_b_net_edge
direction_b_depth
best_direction
best_net_edge
```

Do not reuse HL-specific functions such as `_hl_taker_fee()`, `_hl_top()`, `_hl_question()`, or `hl.coin_book()`.

---

## 7. YES / NO Representation and Gotchas

### Polymarket

PM binary markets have separate CLOB token IDs for YES and NO. The old code gets them from `clobTokenIds`, paired with `outcomes`.

PM top book for each token:

```text
YES token -> YES bid/ask
NO token  -> NO bid/ask
```

MVP3 can reuse this PM representation, subject to verifying `outcomes` index order.

### Hyperliquid in MVP2

HL used:

```text
YES coin = #{outcome_id * 10}
NO coin  = #{outcome_id * 10 + 1}
```

This is HL-specific and must not be copied to Predict.fun.

Older MVP1 code sometimes derived HL NO asks from YES bids:

```text
hl_no_asks = [(1 - yes_bid, size), ...]
```

That is not a general rule. Do not apply it to Predict.fun without API proof.

### Predict.fun warning for MVP3

MVP3 new agent must verify:

- Does Predict.fun expose separate YES and NO books?
- Does Predict.fun expose only YES book?
- If only YES book, is NO price derivable as `1 - YES bid` or `1 - YES ask`?
- Are sizes reusable under derived NO, or do they require separate liquidity semantics?
- Does Predict.fun include fees in displayed prices?
- Does Predict.fun have AMM/liquidity-pool semantics rather than CLOB semantics?

If any NO value is derived, output:

```text
pd_no_ask_source = "direct_book" | "derived_from_yes_bid" | "UNKNOWN"
pd_no_ask_size_source = ...
```

Do not guess.

---

## 8. Mapping / Rule Check Reuse

MVP2 mapping experience to reuse:

| MVP2 concept | Where | MVP3 equivalent |
| --- | --- | --- |
| `event_slug` | PM sports parent event | PM market slug or event slug |
| `market_title` | Gamma `question` / event title | PM title + Predict.fun title |
| `outcome name` | Moneyline label / champion team | PM outcome + PD outcome |
| team name normalization | `normalize_name()` and `_norm_label()` | shared normalization helper |
| `question_name` | HL question name | Predict.fun market ID / slug / title |
| `rule_match_score` | fixed 0.90 for matched Moneyline; 0.95 for champion | explicit PM vs PD rule score |
| `manual_verified` | conceptually needed; not consistently represented in MVP2 rows | required for MVP3 candidate |
| `notes` | output row notes and summary notes | carry mapping/rule notes |
| `failure_reason` / `fail_reason` | scanner stats and gate rows | required output field |
| rule mismatch blocker | `rule_match_ok` gate | `rule_match_score_min` and `manual_verified_required` |

Useful mapping functions:

- `market_mapper.normalize_name(value)`
- `match_opportunity_evaluator._norm_label(value)`
- `pm_sports_match_discovery._expected_moneyline_outcomes(raw_event)`
- `pm_sports_match_discovery._moneyline_label(market)`

MVP3 mapping row should include:

```text
pm_market_slug
pm_market_id
pm_yes_token
pm_no_token
pd_market_id
pd_market_slug
pd_yes_instrument
pd_no_instrument
pm_outcome_name
pd_outcome_name
normalized_outcome
rule_match_score
manual_verified
settlement_rule_note
cancellation_rule_note
void_rule_note
mapping_ok
fail_reason
```

MVP3 candidate rule:

```text
mapping_ok == true
AND rule_match_score >= 0.90
AND manual_verified == true
```

MVP3-A may produce `manual_verified=false` rows for probing, but MVP3-B should not mark them as live-style candidates.

---

## 9. Depth / Threshold / Candidate Classification

MVP2 reusable scanner ideas:

- `depth = min(best_ask_size_leg1, best_ask_size_leg2)`.
- Per-leg depth is more useful than a single min depth.
- `target_size_shares` converts edge into dollars.
- `estimated_profit_usd = net_edge * target_size_shares`.
- `net_edge_bps = net_edge / entry_cost * 10000` in dry-run gate logic.
- `fail_reason` should explain why no candidate.
- `near_miss` should preserve the best non-candidate rows.
- `quote_ok` and missing price count matter.
- Only one active candidate can be selected in future execution context, but MVP3 scanner may list all candidates.
- No fake candidate.

Existing MVP2 thresholds to treat as scanner inspiration only:

- Batch watcher threshold default: `0.0005`.
- Batch watcher min S1/S2 profit: `$0.01`.
- op1 dry-run depth: both legs >= 40 shares.
- op1 dry-run rule score min: `0.90`.
- op1 dry-run pre-match cutoff: 10 minutes.

MVP3 initial scanner parameters:

```text
target_size_shares = 20
candidate_net_edge_threshold = 0.0005
near_miss_lower_bound = -0.0010
min_profit_usd = 0.01
max_quote_age_seconds = 10
rule_match_score_min = 0.90
manual_verified_required = true
```

These are initial scanner parameters, not live trading parameters.

Candidate status suggestion:

| status | condition |
| --- | --- |
| `candidate` | mapping ok, quote ok, rule ok, manual verified, depth ok, edge/profit pass |
| `near_miss` | best net edge >= `near_miss_lower_bound` but one or more gates fail |
| `monitor_only` | mapped but rule/manual verification incomplete |
| `blocked` | clear fail reason such as `rule_mismatch`, `empty_book`, `quote_stale` |
| `error` | API or parsing failure |

Fail reason examples:

```text
edge_below_threshold
profit_below_min
depth_below_target
mapping_not_verified
rule_match_score_below_min
quote_stale
empty_pm_book
empty_pd_book
pd_no_price_unknown
fee_unknown
```

---

## 10. Output File Format

MVP2 output habits to reuse:

- Write flat CSV for review.
- Write JSON snapshots with raw/normalized details.
- Write markdown summary.
- Keep output directory separate from live logs.
- Preserve failures and near-misses, not only candidates.
- Continue scanning if one iteration fails; record warning/error.

MVP3 suggested output directory:

```text
outputs/mvp3_pm_predictfun/
```

MVP3 suggested files:

```text
outputs/mvp3_pm_predictfun/winner_top20_monitor.csv
outputs/mvp3_pm_predictfun/winner_top20_candidates.csv
outputs/mvp3_pm_predictfun/winner_top20_near_miss.csv
outputs/mvp3_pm_predictfun/winner_top20_summary.md
```

Also recommended for MVP3-A:

```text
outputs/mvp3_pm_predictfun/raw/pm_<slug_or_id>_<timestamp>.json
outputs/mvp3_pm_predictfun/raw/predictfun_<market_id>_<timestamp>.json
```

### Monitor fields

```text
timestamp
team
pm_market_slug
pd_market_id
pm_yes_ask
pm_yes_ask_size
pm_no_ask
pm_no_ask_size
pd_yes_ask
pd_yes_ask_size
pd_no_ask
pd_no_ask_size
direction_a_gross_edge
direction_a_net_edge
direction_b_gross_edge
direction_b_net_edge
best_direction
best_net_edge
depth_ok
rule_match_score
recommendation
fail_reason
```

Additional recommended monitor fields:

```text
pm_quote_ok
pd_quote_ok
mapping_ok
manual_verified
pm_orderbook_timestamp
pd_orderbook_timestamp
pm_raw_path
pd_raw_path
pd_no_ask_source
fee_status
cost_buffer_bps
```

### Candidates fields

```text
candidate_id
timestamp
team
direction
pm_leg
pd_leg
pm_price
pd_price
pm_size
pd_size
gross_edge
fee_bps
cost_buffer_bps
net_edge
target_size
estimated_profit_usd
pm_orderbook_timestamp
pd_orderbook_timestamp
status
```

Candidate ID suggestion:

```text
{pm_market_slug}|{pd_market_id}|{team}|{direction}|{timestamp}
```

### Near-miss fields

```text
timestamp
team
direction
best_net_edge
missing_reason
depth_ok
mapping_ok
quote_ok
notes
```

Additional useful near-miss fields:

```text
candidate_net_edge_threshold
near_miss_lower_bound
estimated_profit_usd
rule_match_score
manual_verified
```

### Summary fields / sections

```text
scan duration
teams scanned
valid mappings
quote success rate
candidate count
near_miss count
best opportunity
best net edge
best estimated profit
main fail reasons
recommendation
```

MVP3 summary should also include:

```text
no_fake_candidate: true
live_allowed: false
execution_called: false
predictfun_no_price_verified: true/false
manual_verified_required: true
```

---

## 11. Future Execution v3 Reference Only

MVP3-A must not call execution functions.

MVP3-B scanner must not call execution functions.

These are future Execution v3 references only.

Reusable safety principles from PM-HL:

1. Fresh revalidation:
   - Re-fetch both legs immediately before order.
   - Recompute edge, fee, depth, and rule gates.
   - Use revalidated prices for order intent, not scanner prices.

2. Order intent:
   - Write intent rows before any submission.
   - Include venue, leg, instrument, side, order type, time-in-force, size, revalidated best ask, limit price, max acceptable price, and depth pass.

3. Marketable limit order:
   - Use limit orders, not market orders.
   - MVP2 Execution v1 summary says `execution_style: taker_limit`.

4. Price protection:
   - `limit_price = revalidated best ask`.
   - `max_acceptable_price = revalidated best ask`.
   - Any mismatch is a `limit_price_violation`.

5. FOK preferred / IOC fallback:
   - PM-HL v1 references FOK, then IOC.
   - MVP3 must verify which time-in-force Predict.fun supports.

6. No market order:
   - Market order should be blocked.

7. No chase:
   - If price moves, do not adjust and try again automatically.

8. No retry:
   - Failed or partial execution should not trigger automatic retry.

9. No deeper book:
   - MVP2 scanner used top-of-book only.
   - Future execution should not consume deeper levels unless separately designed.

10. Partial fill detection:
    - Detect partial fills per leg.
    - Log critical risk event.

11. Single-leg exposure:
    - Detect one-leg-filled / other-leg-not-filled.
    - Log critical risk event.
    - Do not chase/retry automatically.

12. `confirmed_exact`:
    - Future execution should reconcile intended shares vs actual position/fill deltas.
    - Only mark exact if both legs match intended size.

13. STOP / kill switch:
    - PM-HL had STOP file checks before live actions.
    - MVP3 future execution should have a similar kill switch.

14. Logs:
    - Store order intents, revalidations, paper fills, live orders, live fills, risk events, and summary.

Reference files only:

- `scripts/run_pm_hl_execution_v1.py`
- `data/execution_v1/summary.md`
- `docs/pm_hl_execution_layer_v1_handoff.md`
- `src/strategies/pm_hl/strategy.py`

Do not wire these into MVP3-A or MVP3-B.

---

## 12. Copy This Section to MVP3 New Agent

MVP3 goal:

```text
Build a Polymarket vs Predict.fun arbitrage scanner.
```

MVP3-A scope:

- Data probe only.
- Find one PM market and one Predict.fun market.
- Pull both raw orderbooks.
- Save raw JSON.
- Confirm YES/NO price representation.
- Confirm fees, tick size, min size, depth, market IDs, settlement rules.
- No live, no execution, no fake candidate.

MVP3-B future scope:

- Normalize PM and Predict.fun books.
- Compute:

```text
PM YES + Predict.fun NO
Predict.fun YES + PM NO
```

- Output monitor / candidates / near_miss / summary.
- Stay read-only.

Old files to reference:

- `src/strategies/pm_hl/clients/polymarket.py`
- `src/strategies/pm_hl/mvp2_scanner/pm_sports_match_discovery.py`
- `src/strategies/pm_hl/mvp2_scanner/market_mapper.py`
- `src/strategies/pm_hl/mvp2_scanner/match_opportunity_evaluator.py`
- `src/strategies/pm_hl/mvp2_scanner/op1_strategy_dry_run.py`
- `src/strategies/pm_hl/mvp2_scanner/sinks.py`
- `src/strategies/pm_hl/mvp2_scanner/risk_scoring.py`
- `scripts/run_pm_hl_op1_batch_watcher.py`
- `docs/pm_hl_mvp2_scanner_v0.md`
- `docs/MVP2_OP1_EXECUTION_HANDOFF.md`

Old files not to reuse directly:

- `src/strategies/pm_hl/clients/hyperliquid.py`
- `scripts/run_pm_hl_execution_v1.py`
- `src/strategies/pm_hl/strategy.py`
- `logs/pm_hl/*`
- `data/execution_v1/*`
- Any PM-HL S1/S2 portfolio state or live loop.

PM data access method:

- Use Gamma for market/event metadata.
- Use `clobTokenIds` + `outcomes` to map YES/NO tokens.
- Use PM CLOB `/book?token_id=...` for orderbook.
- Parse bids/asks as `(price, size)` lists.
- Save raw JSON in MVP3-A.

Arbitrage formulas:

```text
Direction A:
gross = 1 - pm_yes_ask - pd_no_ask
net = gross - pm_fee - pd_fee - cost_buffer

Direction B:
gross = 1 - pd_yes_ask - pm_no_ask
net = gross - pd_fee - pm_fee - cost_buffer
```

Mapping rules:

- Normalize team/outcome names.
- Store PM slug/market ID/token IDs.
- Store Predict.fun market ID/outcome IDs.
- Require settlement rule check.
- Require cancellation/void rule check.
- Use `rule_match_score`.
- Require `manual_verified = true` for candidate status.

Candidate / near-miss output:

- Write `winner_top20_monitor.csv`.
- Write `winner_top20_candidates.csv`.
- Write `winner_top20_near_miss.csv`.
- Write `winner_top20_summary.md`.
- No fake candidate; zero candidates is valid.

Future Execution v3 safety principles:

- Fresh revalidation.
- Order intent before submission.
- Taker-limit only.
- `limit_price = revalidated best ask`.
- FOK preferred / IOC fallback only if supported.
- No market order.
- No chase.
- No retry.
- No deeper book.
- Partial fill detection.
- Single-leg exposure flag.
- STOP / kill switch.
- Full order/fill/risk logs.

Forbidden:

- Do not modify PM-HL MVP2 scanner.
- Do not modify PM-HL Execution v1.
- Do not modify old live executor/state machine.
- Do not start live.
- Do not place orders.
- Do not write Predict.fun code during handoff.
- Do not connect Predict.fun to PM-HL Execution v1.
- Do not use HL-specific token/coin mapping.
- Do not assume Predict.fun NO price semantics.

---

## UNKNOWN / NEEDS_RECHECK Items for MVP3

- Predict.fun API base URL and authentication model.
- Predict.fun market discovery endpoint.
- Predict.fun raw market ID / slug format.
- Predict.fun orderbook endpoint and response schema.
- Whether Predict.fun exposes separate YES and NO books.
- Whether Predict.fun NO prices can be derived from YES book.
- If derived NO is possible, which side (`YES bid` or `YES ask`) and size semantics apply.
- Predict.fun fee schedule.
- Predict.fun tick size.
- Predict.fun min order size / min notional.
- Predict.fun time-in-force support.
- Predict.fun quote timestamps / quote age fields.
- Predict.fun settlement, cancellation, void, and dispute rules.
- Whether PM `0.03 * price * (1 - price)` remains sufficiently accurate for MVP3 scanner assumptions.
- PM exact min order size handling in this repo.
- PM raw Gamma/CLOB fields needed for MVP3 chosen market universe.

---

Generated as read-only MVP2 reusable information extraction for MVP3. No code changes, live process, order submission, or Predict.fun integration included.
