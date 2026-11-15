# PM-HL Execution Layer v1 Handoff

## Scope

- Strategy: op1 `cross_venue_direct_no_complete_set` only
- Market: 1v1 Moneyline first
- Mode: paper first, then tiny live
- Size: 20 shares per slot

## Flow

1. Scanner signal
2. Manual approve
3. Revalidate both legs
4. Paper or tiny execution
5. Record fills
6. Compute PnL

## Must-have Risk Controls

- Kill switch
- No auto retry/chase
- Single-leg exposure handling
- Max one active trade per match/outcome
- Fresh quote revalidation immediately before action

## Not in v1

- op2
- op3
- op4
- WC Winner
- Portfolio allocator
- Automatic re-entry
- S1/S2 live state machine reuse from MVP1

## Evidence

Four-match MVP2 scanner research supports op1-only execution v1. See `D:\cursor\2026_strategy_lab\docs\pm_hl_mvp2_final_report.md`.
