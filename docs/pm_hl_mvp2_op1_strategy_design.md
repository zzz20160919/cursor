# PM-HL MVP2 op1 Strategy Design

Status: live-gate design plus dry-run monitor. `execution_enabled = false` by default.

Scope:

- Match: Argentina vs Austria
- Market: Moneyline only
- Strategy family: `op1_direct_no_complete_set`
- Tradable candidate type: `cross_venue_direct_no_complete_set` only
- Monitor-only types: `cross_venue_single_outcome`, `cross_venue_complement_basket`
- Diagnostic-only type: `single_venue_three_way_sum_diagnostic`

Do not use this document as an execution runbook. It does not enable live orders, trade intents, S1/S2 executor changes, or MVP1 state writes. Current code reports whether a future live gate would pass; live order submission is not implemented.

## 1. Strategy Family

`op1_direct_no_complete_set` evaluates three outcome instances:

- `Argentina`
- `Draw`
- `Austria`

For each outcome `X`, op1 has two possible direct No-token complete-set sides:

```text
PM X yes + HL X no
HL X yes + PM X no
```

The payoff intent is a complete-set relation: exactly one of `X yes` or `X no` should pay out 1, assuming PM and HL rule matching remains valid.

Each outcome instance has two position slots:

- `S1_HOLD_TO_MATURITY`: base slot, hold to settlement by default.
- `S2_EARLY_EXIT`: enhanced slot, may exit early if all-in exit thresholds are met.

S1 and S2 are allowed to coexist for the same outcome. There is no re-entry, repeated open/close cycle, dynamic add, chase, or retry in this MVP2 design.

## 2. Configuration

```text
target_match = Argentina vs Austria
pm_event_slug = fifwc-arg-aut-2026-06-22
hl_question_name = World Cup: Argentina vs Austria
target_strategy_type = op1_direct_no_complete_set
execution_enabled = false
live_order_submission_implemented = false

s1_shares = 20
s2_shares = 20
max_active_outcomes = 1

rule_match_threshold = 0.90
entry_min_best_book_depth_shares = 40
s2_exit_min_best_bid_depth_shares = 20
entry_net_edge_bps_threshold = 10
entry_expected_profit_threshold_usd = 0.03

s2_exit_realized_net_pnl_all_in_threshold_usd = 0.03
s2_exit_net_edge_bps_all_in_threshold = 10
s2_exit_exit_vs_hold_usd_threshold = 0

pre_match_cutoff_minutes = 10
consecutive_signal_count = 1
```

Threshold source:

- Entry and S2 exit thresholds use MVP1 `normal` profile:
  - `entry_min_net_edge_bps = 10`
  - `entry_min_profit_usd = 0.03`
  - `exit_min_profit_bps = 10`
  - `exit_min_profit_usd = 0.03`

Config notes:

- `entry_min_best_book_depth_shares = 40` means both entry legs must each have at least 40 shares at best ask. This is a hard gate because pricing is still top-of-book, not 40-share VWAP.
- `s2_exit_min_best_bid_depth_shares = 20` means both S2 exit legs must each have at least 20 shares at best bid before early exit can be considered.
- `rule_match_threshold = 0.90` matches the current evaluator score for PM/HL Moneyline: both resolve on regular 90 minutes plus stoppage time, but fallback/cancellation text is not identical.
- `pre_match_cutoff_minutes = 10` blocks new entries in the last 10 minutes before scheduled start.
- `consecutive_signal_count = 1` means no extra signal smoothing in the design dry-run. Raising this is a later monitoring/strategy decision.

## 3. Entry Logic

Entry is evaluated for all three outcomes on every monitor tick.

For outcome `X`, evaluate both direct No-token sides.

### Side A: PM yes + HL no

```text
entry_cost = pm_X_yes_ask + hl_X_no_ask
entry_gross_edge = 1 - entry_cost
entry_fee = pm_fee(pm_X_yes_ask) + hl_taker_fee
entry_net_edge = entry_gross_edge - entry_fee
expected_profit = entry_net_edge * shares
net_edge_bps = entry_net_edge / entry_cost * 10000
entry_depth = min(pm_X_yes_ask_size, hl_X_no_ask_size)
capacity_usd = entry_depth * entry_cost
```

Hard entry liquidity gate:

```text
pm_X_yes_ask_size >= 40
hl_X_no_ask_size >= 40
```

### Side B: HL yes + PM no

```text
entry_cost = hl_X_yes_ask + pm_X_no_ask
entry_gross_edge = 1 - entry_cost
entry_fee = hl_taker_fee + pm_fee(pm_X_no_ask)
entry_net_edge = entry_gross_edge - entry_fee
expected_profit = entry_net_edge * shares
net_edge_bps = entry_net_edge / entry_cost * 10000
entry_depth = min(hl_X_yes_ask_size, pm_X_no_ask_size)
capacity_usd = entry_depth * entry_cost
```

Hard entry liquidity gate:

```text
hl_X_yes_ask_size >= 40
pm_X_no_ask_size >= 40
```

Fee note:

- PM fee uses existing MVP2 estimate `0.03 * p * (1 - p)`.
- HL fee uses `HL_TAKER_FEE`, default 0.
- All fees are estimated.

Entry eligibility for each S1/S2 slot:

```text
entry_net_edge_bps >= 10
expected_profit >= 0.03
both entry legs best ask depth >= 40 shares
rule_match_score >= 0.90
outside pre-match cutoff window
```

Full outcome activation eligibility:

```text
both entry legs best ask depth >= 40 shares
S1 eligible
S2 eligible
outcome rank is top 1
no active outcome already selected
execution_enabled = false means dry-run only
live_order_submission_implemented = false means no orders are sent by current code
```

## 4. S1 Hold To Maturity

S1 role:

- Open 20 shares of the selected direct complete-set side.
- Hold to settlement by default.
- No active exit logic.
- Only abandon in future live design for extreme data/rule mismatch, manual halt, or operational risk.

S1 entry condition:

```text
outcome is ranked top 1
entry thresholds pass
both entry legs best ask depth >= 40
rule match passes
execution gate would allow dry-run plan only
```

S1 and S2 can both be active on the same selected outcome.

## 5. S2 Early Exit

S2 role:

- Open another 20 shares of the same selected direct complete-set side.
- Monitor exit value using bid-side liquidation value of the two held legs.
- Exit only if MVP1 normal profile S2 exit thresholds pass.

For a held side `PM X yes + HL X no`:

```text
exit_value_gross = pm_X_yes_bid + hl_X_no_bid
exit_fee = pm_fee(pm_X_yes_bid) + hl_taker_fee
exit_value_net = exit_value_gross - exit_fee
realized_net_pnl_all_in = exit_value_net - entry_cost - entry_fee
net_edge_bps_all_in = realized_net_pnl_all_in / entry_cost * 10000
exit_vs_hold_usd = exit_value_net - 1
```

S2 exit best-bid depth gate:

```text
pm_X_yes_bid_size >= 20
hl_X_no_bid_size >= 20
```

For a held side `HL X yes + PM X no`:

```text
exit_value_gross = hl_X_yes_bid + pm_X_no_bid
exit_fee = hl_taker_fee + pm_fee(pm_X_no_bid)
exit_value_net = exit_value_gross - exit_fee
realized_net_pnl_all_in = exit_value_net - entry_cost - entry_fee
net_edge_bps_all_in = realized_net_pnl_all_in / entry_cost * 10000
exit_vs_hold_usd = exit_value_net - 1
```

S2 exit best-bid depth gate:

```text
hl_X_yes_bid_size >= 20
pm_X_no_bid_size >= 20
```

S2 exit trigger:

```text
realized_net_pnl_all_in >= 0.03
net_edge_bps_all_in >= 10
exit_vs_hold_usd >= 0
both exit legs best bid depth >= 20 shares
```

`realized_net_pnl_all_in` is full lifecycle net PnL after entry fee and exit fee. `exit_vs_hold_usd >= 0` ensures early exit is not worse than holding a complete-set payoff to maturity.

If any S2 exit condition fails, S2 remains open and continues monitoring. No re-entry is allowed after exit in this design.

## 6. State Fields

Per outcome candidate state:

```text
outcome
strategy_type
s1_status
s2_status
entry_depth_ok
s2_exit_depth_ok
entry_signal
entry_cost
expected_profit
net_edge_bps
active_side
rank_score
activation_reason
exit_signal
realized_net_pnl_all_in
net_edge_bps_all_in
exit_vs_hold_usd
notes
```

Suggested status values:

```text
s1_status: idle | candidate | blocked | dry_run_planned | active | settled | halted
s2_status: idle | candidate | blocked | dry_run_planned | active | exit_candidate | exited | halted
entry_signal: pass | fail
exit_signal: pass | fail | not_applicable
```

No MVP1 live state file is used.

## 7. Ranking Logic

All three outcomes are monitored and scored every tick:

```text
monitor all 3
score all 3
generate S1/S2 candidates for all 3
activate top 1 only by default
```

Candidate rank inputs:

```text
rank_score = expected_profit_for_full_outcome
expected_profit_for_full_outcome = entry_net_edge * (s1_shares + s2_shares)
```

Tie-breakers:

1. Higher `entry_net_edge_bps`
2. Higher `entry_depth`
3. Higher `rule_match_score`

The first version activates only the top ranked eligible outcome because:

- It limits correlated match-level exposure.
- It avoids opening multiple mutually exclusive complete-set positions in one match.
- It keeps execution design separate from opportunity monitoring.
- It makes dry-run review easier before any live system exists.

The other two outcomes remain monitored, ranked, and reported, but are not built as positions by default.

## 8. Current Dry-Run Example

Snapshot time: 2026-06-22T15:25:52Z.

Latest op1 direct No-token complete-set candidates:

| outcome | best side | net | net bps | entry leg depths | S2 exit bid depths | expected profit S1 20 | expected profit S1+S2 40 | rank |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| Austria | `buy_hl_Austria_yes_buy_pm_Austria_no` | -0.0036 | -35.95 | 10000 / 26543.98 | pass | -0.0719 | -0.1439 | 1 |
| Draw | `buy_hl_Draw_yes_buy_pm_Draw_no` | -0.0093 | -92.98 | 10000 / 131269.07 | pass | -0.1868 | -0.3736 | 2 |
| Argentina | `buy_hl_Argentina_yes_buy_pm_Argentina_no` | -0.0135 | -134.34 | 614 / 651776.06 | pass | -0.2706 | -0.5411 | 3 |

Dry-run decision:

```text
top outcome = Austria
S1 entry = blocked
S2 entry = blocked
execution_enabled = false
live_order_submission_implemented = false
orders = none
```

Why blocked:

- `expected_profit` is negative for all three outcomes.
- `net_edge_bps` is negative for all three outcomes.
- MVP1 normal entry thresholds require `net_edge_bps >= 10` and `expected_profit >= 0.03`.
- Entry depth is sufficient for the top outcome because both best ask legs are above 40 shares.
- S2 exit bid depth would be sufficient for the top outcome because both best bid legs are above 20 shares.
- Edge/profit thresholds fail, so no S1/S2 entry is allowed.

If the dry-run gate flag `execution_enabled` were true, this snapshot would still not place orders. Current code also has no live order submission path.

## 9. Tonight Live-Gate Boundary

The intended minimal live version is constrained as follows:

```text
strategy_type = op1_direct_no_complete_set only
active outcome = top1 only
S1 and S2 enter together
S1 shares = 20
S2 shares = 20
entry liquidity = both best ask legs >= 40
S2 exit liquidity = both best bid legs >= 20
pre-match cutoff = 10 minutes
no re-entry
no retry
no chase
no op2/op3/op4 trading
no other matches
no child markets
no MVP1 state writes
```

Current code reports whether this future live gate would pass. It does not submit orders.

