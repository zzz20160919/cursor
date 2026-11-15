# PM-HL Cross-Market Arbitrage

## Strategy Goal

This module monitors cross-market arbitrage between Polymarket and Hyperliquid for matching real-world event outcomes.

The strategy goal is to find buy-only mirror boxes:

`buy PM outcome + buy HL complementary outcome`

If the two legs resolve to complementary payoffs and total entry cost is below $1 per set, the box has a positive settlement floor. This project currently runs as research and monitoring infrastructure, not live trading.

## Core Box Logic

A box combines two outcome tokens that pay $1 in total at settlement regardless of the event result.

- Polymarket leg: buy one event outcome token.
- Hyperliquid leg: buy the complementary HIP-4 outcome token.
- No shorting is assumed on Hyperliquid; outcome markets are treated as spot-like tokens.
- Entry must use executable ask prices.
- Early exit valuation must use executable bid prices.

## Current Focus

Fed no-change is the current priority:

- PM event: no change in Fed interest rates after the June 2026 meeting.
- HL event: June Fed rate change, outcome `#1040` = change and `#1041` = no-change.
- PM no-change payoff matches HL no-change payoff, so the mirror box uses the complementary leg mapping from the handoff.

World Cup champion markets are kept as monitoring and research candidates. They are farther dated and have historically shown thinner or noisier edge.

## Core Formulas

Entry cost per set:

`box_cost = PM_leg_ask + HL_complement_ask`

Gross edge:

`gross_edge = 1 - box_cost`

Estimated cost:

`estimated_cost = PM_taker_fee + HL_taker_fee`

Net edge:

`net_edge = gross_edge - estimated_cost`

APR:

`apr = net_edge / days_to_settle * 365`

Executable size:

`executable_size = min(PM ask depth, HL ask depth, budget-limited size)`

## Bid / Ask Rules

- Entry uses ask: both legs are buys.
- Exit uses bid: liquidation sells both held legs.
- The monitor must not use mid price for opportunity edge.

Mid price is not executable. Using mid systematically overstates edge by roughly half the spread and turns thin false positives into apparent opportunities.

## S1-S6 Summary

- S1: held-to-settle taker box with positive settlement floor.
- S2: box that may exit early when spread convergence improves realized return.
- S3: alternate direction of the same convergence logic.
- S4: maker PM entry, then HL hedge after confirmed PM fill.
- S5: deprecated delayed directional scalp; not migrated.
- S6: z-score reversion box, double taker, only when the chosen box has `C < 1`.

## S6 Orphan Bug And Fix Principle

The old S6 implementation could leave an orphan HL leg when HL filled but PM returned zero fill without raising an exception.

The migrated execution design is conservative:

- Default gates block all real orders.
- Any real open flow must compare both leg fills.
- If fill sizes do not match within tolerance, the flow refuses to continue.
- If automatic unwind cannot be proven safe, the code logs a clear manual intervention warning.
- The recorded position size must never claim zero shares while a real leg remains open.

## API Clients

Polymarket client:

- Reads positions, position value, book data, and collateral cash.
- Can build an authenticated CLOB client only when local secrets are configured.
- Does not place orders unless strategy safety gates allow it.

Hyperliquid client:

- Reads spot balances, including HIP-4 outcome tokens.
- Reads perp state and open orders.
- Can build an authenticated Exchange client only when local secrets are configured.
- Injects HIP-4 `#N` aliases for outcome trading when available.

## Safety Switches

Defaults:

- `DRY_RUN=true`
- `TRADING_ENABLED=false`
- `REQUIRE_MANUAL_CONFIRMATION=true`
- `MAX_ORDER_NOTIONAL=100`
- `ALLOWED_MARKETS=` empty

The strategy also supports a `STOP` file in the project root. When present, trading helpers refuse new order actions.

Real trading requires explicitly disabling dry-run, enabling trading, passing market and notional checks, and satisfying manual confirmation. The default behavior is never to place a real order.

## Acceptance Criteria

- PM-HL modules import successfully.
- Missing secrets produce clear messages instead of crashes.
- Read positions runs in dry-run mode without placing orders.
- Monitor computes or mocks one PM-HL opportunity and writes it to SQLite.
- Opportunities use `opportunity_type = pm_hl_cross_market_arbitrage`.
- Opportunities use `status = dry_run_observed` by default.
- `raw_json` records key inputs and calculation results.
- `strategy_signals` and `opportunities` remain separate.
- No `orders`, `fills`, `positions`, `paper_orders`, or `risk_events` tables are created.
- Real order functions are blocked by default safety gates.
