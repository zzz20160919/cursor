# PM-HL MVP2 Cross-Venue Scanner v0

Read-only scanner for PM/HL prediction market research. It discovers markets, prints a cross-venue opportunity table, and exports CSV/JSON. It does not place orders, write MVP1 live state, or call the MVP1 executor state machine.

## Usage

```powershell
python scripts/run_pm_hl_mvp2_scanner.py --scan all
```

Useful shorter runs:

```powershell
python scripts/run_pm_hl_mvp2_scanner.py --scan champion --max-champion-markets 20
python scripts/run_pm_hl_mvp2_scanner.py --scan matches --max-match-markets 5
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-match-universe
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-sports-sample --event-slug fifwc-arg-aut-2026-06-22
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-hl-1v1-sample --event-slug fifwc-arg-aut-2026-06-22
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-hl-1v1-monitor --event-slug fifwc-arg-aut-2026-06-22 --duration-minutes 10 --interval-seconds 30
python scripts/run_pm_hl_mvp2_scanner.py --scan pm-hl-op1-dry-run --event-slug fifwc-arg-aut-2026-06-22 --duration-minutes 10 --interval-seconds 30
python scripts/run_pm_hl_mvp2_scanner.py --scan all --no-export
```

Outputs are written to:

```text
outputs/pm_hl_mvp2_scanner/
```

## Scope

- MVP2 primary strategy: World Cup Champion single-outcome cross-venue scanner. It dynamically fetches active Polymarket World Cup winner markets, fetches Hyperliquid `outcomeMeta`, normalizes outcome names, scans the PM/HL intersection, and computes gross edge, estimated fee, net edge, depth, capacity, risk score, and recommendation.
- MVP2 research track: World Cup 1v1 cross-venue scanner. It reads Hyperliquid 3-way match questions, attempts to map matching Polymarket outcomes with normalized team names and home/away tolerance, and reports candidates, parsed markets, matched markets, failures, and failure reasons.
- Single-venue deviations are diagnostics only. Champion all-yes/all-no deviations and 1v1 three-way sum deviations are exported for data quality and research, but they are not MVP2 strategy signals and do not drive trade recommendations.
- Champion diagnostics have two scopes:
  - `*_subset_*` fields are computed over the current scanner subset, for example after `--max-champion-markets`.
  - `*_full_*` fields are computed over each venue's full discovered World Cup Champion universe and are the preferred market-wide diagnostic.
- `--scan pm-match-universe` exports the Polymarket World Cup 1v1/3-way candidate universe for manual crosswalk against HL. A zero-row PM universe is a valid discovery result if no PM active markets match the current title/rule patterns.
- `--scan pm-sports-sample --event-slug <slug>` is a narrow debug path for one PM sports event. It only discovers the parent event's Moneyline child markets, fetches CLOB top-of-book, and exports JSON. It intentionally ignores Exact Score, Totals, Spread, Halftime, Second Half, and other child events.
- `--scan pm-hl-1v1-sample` evaluates the single Argentina vs Austria Moneyline sample across PM and HL. It aligns Argentina/Draw/Austria, computes single-outcome cross-venue spreads and complement basket cost relationships, and exports JSON. It is still read-only research, not a live strategy.
- `--scan pm-hl-1v1-monitor` runs a dynamic monitor for the same Argentina vs Austria Moneyline sample. Defaults are 10 minutes and 30 seconds between scans. Each iteration prints four small tables (`direct_no_complete_set`, `single_outcome`, `complement_basket`, and `single_venue_three_way_sum_diagnostic`) and updates one JSON file, one flat CSV, and one terminal-style text log with all snapshots.
- op1 strategy design is documented in `docs/pm_hl_mvp2_op1_strategy_design.md`. Only `cross_venue_direct_no_complete_set` is treated as a future live-candidate family; the other 1v1 opportunity groups remain monitoring/diagnostic only.
- `--scan pm-hl-op1-dry-run` runs the op1 strategy dry-run decision monitor. It scores Argentina/Draw/Austria, ranks all three, selects top 1 by default, and reports whether S1/S2 would pass entry gates. It includes a dry-run `--execution-enabled` gate flag, but live order submission is not implemented.
- Fees use the existing PM taker approximation `0.03 * price * (1 - price)`. HL fee uses `HL_TAKER_FEE` from env and defaults to `0`.
- Execution schemas are reserved conceptually for future work. MVP2 does not generate trade intents or execution results.

## Explicit Non-Goals

- No MVP1 live executor changes.
- No S1/S2 state machine changes.
- No FULL_ENTRY or trade intent execution.
- No writes to `logs/pm_hl/` or `data/lab.sqlite`.
- No single-venue basket/all-yes/all-no strategy in MVP2.
- No PM-only or HL-only trade recommendation from diagnostic deviations.
- SQLite is intentionally left as a TODO until the scanner schema stabilizes.

## Output Notes

Champion rows include cross-venue opportunity fields plus subset diagnostic fields:

```text
pm_subset_sum_yes, pm_subset_sum_yes_deviation_from_1,
pm_subset_sum_no, pm_subset_sum_no_deviation_from_n_minus_1,
hl_subset_sum_yes, hl_subset_sum_yes_deviation_from_1,
hl_subset_sum_no, hl_subset_sum_no_deviation_from_n_minus_1,
completeness_flag, completeness_note
```

Champion rows also include full-market diagnostic fields:

```text
pm_full_outcome_count, pm_full_sum_yes,
pm_full_sum_yes_deviation_from_1,
pm_full_sum_no,
pm_full_sum_no_deviation_from_n_minus_1,
pm_full_has_other, pm_full_other_labels,
pm_full_placeholder_count,
pm_full_completeness_flag, pm_full_completeness_note,
hl_full_outcome_count, hl_full_sum_yes,
hl_full_sum_yes_deviation_from_1,
hl_full_sum_no,
hl_full_sum_no_deviation_from_n_minus_1,
hl_full_has_other, hl_full_other_labels,
hl_full_placeholder_count,
hl_full_completeness_flag, hl_full_completeness_note
```

1v1 rows include research diagnostics:

```text
pm_sum_three_way, pm_sum_three_way_deviation_from_1,
hl_sum_three_way, hl_sum_three_way_deviation_from_1,
completeness_flag, completeness_note
```

These fields are for diagnostics only.

The PM 1v1 universe export writes:

```text
outputs/pm_hl_mvp2_scanner/pm_world_cup_match_universe_*.csv
outputs/pm_hl_mvp2_scanner/pm_world_cup_match_universe_*.json
outputs/pm_hl_mvp2_scanner/pm_hl_world_cup_match_crosswalk_template_*.csv
```

The crosswalk template intentionally leaves PM fields blank for manual review.

The PM sports sample discovery writes:

```text
outputs/pm_hl_mvp2_scanner/pm_sports_moneyline_<event_slug>_*.json
```

For `fifwc-arg-aut-2026-06-22`, it resolves the parent event and the three Moneyline binary child markets: Argentina, Draw, and Austria.

The PM-HL 1v1 sample evaluator writes:

```text
outputs/pm_hl_mvp2_scanner/pm_hl_1v1_moneyline_<event_slug>_*.json
```

It compares only the Moneyline outcomes for one sample match. It does not scan other games and does not include Exact Score, Totals, Spread, Halftime, or Second Half markets.

The 1v1 sample evaluator uses explicit formulas:

```text
opportunity type 1: cross_venue_single_outcome
single buy_pm_yes_sell_hl_yes:
gross_edge = hl_yes_bid - pm_yes_ask
net_edge = gross_edge - pm_fee(pm_yes_ask) - hl_taker_fee

single buy_hl_yes_sell_pm_yes:
gross_edge = pm_yes_bid - hl_yes_ask
net_edge = gross_edge - pm_fee(pm_yes_bid) - hl_taker_fee

opportunity type 2: cross_venue_direct_no_complete_set
PM X yes + HL X no:
gross_edge = 1 - (pm_X_yes_ask + hl_X_no_ask)
net_edge = gross_edge - pm_fee(pm_X_yes_ask) - hl_taker_fee

HL X yes + PM X no:
gross_edge = 1 - (hl_X_yes_ask + pm_X_no_ask)
net_edge = gross_edge - pm_fee(pm_X_no_ask) - hl_taker_fee

opportunity type 3: cross_venue_complement_basket
complement for outcome X with other outcomes Y/Z:
pm single + hl complement:
gross_edge = 1 - (pm_X_yes_ask + hl_Y_yes_ask + hl_Z_yes_ask)
net_edge = gross_edge - pm_fee(pm_X_yes_ask) - 2 * hl_taker_fee

hl single + pm complement:
gross_edge = 1 - (hl_X_yes_ask + pm_Y_yes_ask + pm_Z_yes_ask)
net_edge = gross_edge - pm_fee(pm_Y_yes_ask) - pm_fee(pm_Z_yes_ask) - hl_taker_fee

opportunity type 4: single_venue_three_way_sum_diagnostic
sum_ask = Argentina_yes_ask + Draw_yes_ask + Austria_yes_ask
deviation_from_1 = sum_ask - 1
```

The `sell_*` labels are price-comparison labels against displayed bids, not execution instructions. Execution, inventory, shorting/No mechanics, maker orders, deeper book walking, sequencing, and single-venue internal arbitrage are out of scope.
The single-venue three-way sum is diagnostic only and does not produce trade recommendations.

The 1v1 monitor writes:

```text
outputs/pm_hl_mvp2_scanner/pm_hl_1v1_moneyline_monitor_<event_slug>_*.json
outputs/pm_hl_mvp2_scanner/pm_hl_1v1_moneyline_monitor_<event_slug>_*.csv
outputs/pm_hl_mvp2_scanner/pm_hl_mvp2_overnight_monitor_<event_slug>_*.log
```

Each snapshot includes grouped opportunity rows and single-venue diagnostics. The CSV is flat with `timestamp`, `iteration`, `op_group`, `key`, `side`, `gross`, `fee`, `net`, `depth`, `capacity_usd`, `sum_ask`, `sum_bid`, and `note`. The `.log` file appends the same op1-op4 terminal tables round by round for direct overnight review. If one iteration fails to fetch data, it records a warning and continues to the next interval.

The op1 strategy dry-run writes:

```text
outputs/pm_hl_mvp2_scanner/pm_hl_op1_strategy_dry_run_<event_slug>_*.json
outputs/pm_hl_mvp2_scanner/pm_hl_op1_strategy_dry_run_<event_slug>_*.csv
```

Each iteration includes a ranking table, gate table, and top1 dry-run decision. It only evaluates `cross_venue_direct_no_complete_set` and never places orders.

