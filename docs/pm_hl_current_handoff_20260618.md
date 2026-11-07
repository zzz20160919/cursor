# PM-HL Current Handoff - 2026-06-18

## 1. Project

Project path:

`D:\cursor\2026_strategy_lab`

Current P0:

PM-HL cross-market arbitrage live validation.

Current active market:

`WC-Portugal-Champion`.

Scope constraints for the next Agent:

- Do not migrate other projects in this Agent.
- Do not work on PM high fade/trend.
- Do not work on BTC-NQ.
- Do not implement S3-S6 now.
- Do not output secrets.
- Do not run live unless the user explicitly chooses to do so.

## 2. Market Mapping

Polymarket:

World Cup Winner / Portugal

Hyperliquid:

2026 World Cup Champion / Portugal

Payoff:

- PM YES = Portugal wins 2026 World Cup
- PM NO = Portugal does not win 2026 World Cup
- HL YES = Portugal wins 2026 World Cup
- HL NO = Portugal does not win 2026 World Cup

Box directions:

- `dir1` = Buy PM Portugal YES + Buy HL Portugal NO
- `dir2` = Buy PM Portugal NO + Buy HL Portugal YES

Rules:

- Use direct ask for entry.
- Use direct bid for exit.
- No mid.
- No `1 - opposite bid/ask`.
- No short.
- No auto-chase.
- No auto-repair.

Current watchlist identifiers:

- Market key: `WC-Portugal-Champion`
- PM YES token: `45415751658241142530386585138386640503488308219341470020075667342738719018629`
- PM NO token: `31940783580344558651011323787577288681658737625185216525249046282994042503801`
- HL outcome id: `205`
- HL YES coin: `#2050`
- HL NO coin: `#2051`
- Mapping status: `verified`

## 3. Strategies

`S1_HOLD_TO_MATURITY`:

- 20 box shares
- Entry only
- Hold to resolution
- Exit policy: `hold_to_resolution`

`S2_EARLY_EXIT`:

- 20 box shares
- Same entry as S1
- After entry, monitor exit
- Exit policy: `exit_if_profit_available`
- Exit threshold:
  - `min_early_exit_profit_bps = 20`
  - `min_early_exit_profit_usd = 0.03`

S2 exit formula:

```text
exit_value = PM held leg direct bid + HL held leg direct bid
realized_profit_if_exit = exit_value * matched_box_shares - original_entry_cost - estimated_exit_fees
```

Only one active S2 slot is allowed.

## 4. Sizing

Current sizing is shares-based, not notional-based.

Command uses:

```text
--box-shares-per-strategy 20
--max-total-notional-per-strategy 25
```

Definition:

1 box share = 1 PM selected leg share + 1 HL complement leg share

For S1:

20 PM shares + 20 HL shares

For S2:

20 PM shares + 20 HL shares

Combined:

```text
combined_required_shares = 40
```

Precheck must verify:

- `net_edge > 0`
- `expected_profit > 0`
- `combined_depth_ok = true`
- `combined_executable_size >= 40`
- PM min notional OK
- HL min notional OK
- `total_notional <= max_total_notional_per_strategy`
- `active_s2 = false`
- STOP file absent
- `ALLOWED_MARKETS` contains `WC-Portugal-Champion`

Important recent fix:

- PM FAK buy must use direct ask1 as limit price.
- Do not add a price buffer such as `ask + 0.005`.
- PM returned fields are Polymarket/CLOB fields:
  - `makingAmount` = collateral/USDC side
  - `takingAmount` = outcome shares received
- A previous live attempt used a buffered PM limit price and bought about `21.234566` PM shares per 20-share intended leg. This has since been fixed in code by using direct ask and checking actual filled shares.

## 5. Implemented Safety Guards

The following are implemented:

- Combined depth precheck
- Shares-based sizing
- S2 active guard
- STOP file guard
- `ALLOWED_MARKETS` guard
- Manual confirmation guard
- No S2 if active S2 exists
- No S2 live exit without `original_entry_cost`
- No S2 live exit without `exit_allowed=true`
- PM/HL live order responses are checked for actual filled shares
- PM live buy now uses FAK at direct ask1, not ask plus buffer

## 6. Important Scripts

Monitor:

```powershell
python scripts/run_pm_hl_watchlist_monitor.py --market WC-Portugal-Champion --dry-run --interval-seconds 60
```

Starter dry-run:

```powershell
python scripts/run_pm_hl_start_s1_s2.py --market WC-Portugal-Champion --dry-run --box-shares-per-strategy 20 --max-total-notional-per-strategy 25 --once
```

Starter live:

```powershell
python scripts/run_pm_hl_start_s1_s2.py --market WC-Portugal-Champion --live --box-shares-per-strategy 20 --max-total-notional-per-strategy 25 --once
```

Starter confirmation:

```text
EXECUTE WC PORTUGAL S1 S2 TEST 20 EACH
```

Position report:

```powershell
python scripts/run_pm_hl_read_positions.py
```

S2 exit dry-run:

```powershell
python scripts/run_pm_hl_s2_exit_executor.py --market WC-Portugal-Champion --dry-run --once
```

S2 exit live:

```powershell
python scripts/run_pm_hl_s2_exit_executor.py --market WC-Portugal-Champion --live --once
```

S2 exit confirmation:

```text
EXECUTE WC PORTUGAL S2 EXIT
```

## 7. Current Live / Position State

Latest submitted live entry logs found:

- `logs/pm_hl_s1_entry_20260618_063625.json`
- `logs/pm_hl_s2_entry_20260618_063628.json`

Historical live entry summary:

- Entry timestamp:
  - S1: `2026-06-18T06:36:25+00:00`
  - S2: `2026-06-18T06:36:28+00:00`
- Strategy variants:
  - S1: `S1_HOLD_TO_MATURITY`
  - S2: `S2_EARLY_EXIT`
- Selected direction: `dir1`
- PM leg: PM Portugal YES
- HL leg: HL Portugal NO
- Planned box shares:
  - S1: 20
  - S2: 20
- Planned PM notional per strategy: about `$1.62`
- Planned HL notional per strategy: about `$18.32`
- Planned entry cost per box share: `0.997`
- Planned expected profit per strategy: about `$0.0153`

Historical execution issue:

- S1 and S2 both reached `submitted` status in logs.
- HL filled `20.0` shares for S1 and `20.0` shares for S2.
- PM filled `21.234566` shares for S1 and `21.234566` shares for S2.
- This produced a temporary PM surplus:

```text
PM Portugal YES: about 42.4691 shares
HL Portugal NO: 40 shares
```

- Latest S2 exit dry-run after that attempt logged `orphan_position`.
- Cause: older PM FAK buy logic used `direct ask + 0.005` as limit price, which made PM buy more shares than target. This has been fixed in code.

Latest current position report run during this handoff:

```text
PM public position value: $0.00
PM open positions: 0
HL USDC: 117.687336
HL outcome balances:
  +1041: 891.000000
  no +2051 shown
```

Current inferred PM-HL Portugal state:

- User appears to have cleared the PM/HL Portugal live test positions.
- Current PM position report shows no Portugal PM position.
- Current HL spot report shows no `+2051` Portugal NO balance.
- Old Fed-related `+1041` remains and is unrelated to WC Portugal.

Latest S2 exit dry-run during this handoff:

```text
status: no_position
matched_box_shares: 0.0
exit_allowed: false
```

Therefore, current inferred state:

- S1 live entry was historically tested, but current S1 Portugal position appears closed.
- S2 live entry was historically tested, but current S2 Portugal position appears closed.
- S2 is not currently active.
- S2 exit is not currently allowed because there is no detected S2 position.

If uncertain, re-run:

```powershell
python scripts/run_pm_hl_read_positions.py --dry-run
python scripts/run_pm_hl_s2_exit_executor.py --market WC-Portugal-Champion --dry-run --once
```

## 8. 12-hour Monitor Review

Past review showed:

- WC Portugal rows scanned: about 681
- `dry_run_observed`: about 582
- `observed_not_actionable`: about 99
- Positive net_edge rows: about 582
- S1+S2 20 each depth candidates: about 572
- Median net_edge about `0.002767`
- Mean net_edge about `0.004128`
- Max net_edge about `0.012002`

Latest SQLite summary during this handoff:

- WC Portugal rows: `699`
- `dry_run_observed`: `582`
- `observed_not_actionable`: `105`
- `dry_run_entry_candidate`: `12`
- Positive net_edge rows: `594`
- Median positive net_edge: about `0.003843`
- Mean positive net_edge: about `0.005168`
- Max positive net_edge: about `0.012002`

Interpretation:

WC Portugal has shown many real positive dry-run windows, but live should only execute when current precheck passes.

## 9. Environment Requirements

`.env.local` should contain:

```env
DRY_RUN=false
TRADING_ENABLED=true
REQUIRE_MANUAL_CONFIRMATION=true
MAX_ORDER_NOTIONAL=25
ALLOWED_MARKETS=WC-Portugal-Champion
```

Do not output secret values.

Other required local values, not to be shown in chat or docs:

- `PM_PRIVATE_KEY`
- `PM_RELAYER_API_KEY` if used
- `HL_AGENT_KEY`

## 10. Next Actions For New Agent

The new Agent should:

1. Read this handoff.
2. Do not modify code initially.
3. Do not run live initially.
4. Run or ask user to run:

```powershell
python scripts/run_pm_hl_read_positions.py --dry-run
```

5. Run or ask user to run:

```powershell
python scripts/run_pm_hl_s2_exit_executor.py --market WC-Portugal-Champion --dry-run --once
```

6. Determine whether:
   - S1 live entry is complete
   - S2 live entry is complete
   - S2 is active
   - S2 exit is allowed
7. If S2 position is detected and `exit_allowed=true`, user may manually consider S2 live exit.
8. Do not proceed to PM high fade/trend until PM-HL P0 is closed.

Important warning for new Agent:

- Do not run the starter again without first confirming that there is no active S2 and no existing WC Portugal PM/HL position.
- The script has an S2 active guard, but the Agent should still explicitly inspect current positions before any live suggestion.
- Treat Polymarket `auth/api-key` 400 messages as potentially noisy if subsequent authenticated operations succeed, but do not ignore actual order response failures.

## 11. P0 Close Criteria

P0 can be considered closed when:

- S1 entry live tested
- S2 entry live tested
- Logs are correct
- SQLite records are correct
- Position report is correct
- S2 exit monitor recognizes S2
- If exit opportunity occurs, S2 live exit is tested
- Docs and decision_log are updated

