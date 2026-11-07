# Strategy Catalog

This file is the master index for strategies inside `2026_strategy_lab`.

Long-term management unit: `strategy_id`
Agent is only a temporary working session.

| ID                     | Strategy                                         | Asset Class                         | Status             | Priority | Next Action                                              | Notes                                                                  |
| ---------------------- | ------------------------------------------------ | ----------------------------------- | ------------------ | -------- | -------------------------------------------------------- | ---------------------------------------------------------------------- |
| `pm_hl`                | Polymarket vs Hyperliquid cross-market arbitrage | Prediction markets / crypto         | P0 live validation | P0       | Finish S1/S2 live validation and close P0                | Active market: `WC-Portugal-Champion`; S1/S2 implemented; S3-S6 paused |
| `pm_high_fade_trend`   | Polymarket high fade / trend                     | Prediction markets                  | Not migrated       | P1       | Inventory old project `D:\cursor\202605_pm_trading`      | Start after PM-HL P0 is closed                                         |
| `pm_single_market_arb` | Polymarket single-market arbitrage               | Prediction markets                  | Not migrated       | P1/P2    | Build scanner for YES+NO / multi-outcome arb             | Scanner only first; no live                                            |
| `btc_nq_weekend`       | BTC weekend signal to predict NQ                 | Crypto / equities                   | Not migrated       | P1       | Restore old logic and prepare Futu paper bridge          | Source likely `D:\cursor\202604_stra`                                  |
| `btc_event_cpi`        | BTC/NQ CPI event continuation                    | Crypto / equities / macro           | Backlog            | P2       | Review old event-driven module                           | Lower priority due to low event frequency                              |
| `tqqq_orb`             | TQQQ opening range breakout                      | Equities / ETF                      | Backlog            | P2/P3    | Inventory old project `D:\cursor\202605_tt_orb_strategy` | Paper first, no live                                                   |
| `pm_binary_iv_deribit` | Polymarket binary IV vs Deribit vol              | Prediction markets / crypto options | Backlog            | P3       | Research design later                                    | Needs Deribit vol and PM binary markets                                |
| `btc_regime_timing`    | BTC regime allocation / timing                   | Crypto allocation                   | Paused             | Paused   | Do not work on now                                       | Too broad for current phase                                            |

## Current Focus

| Date       | Main Focus                                 | Secondary                    |
| ---------- | ------------------------------------------ | ---------------------------- |
| 2026-06-18 | PM-HL Arb P0                               | Framework cleanup            |
| 2026-06-19 | PM-HL close + PM high fade/trend inventory | None                         |
| 2026-06-20 | PM high fade/trend migration               | PM single-market arb if time |
| 2026-06-21 | BTC-NQ + Futu paper bridge                 | TQQQ ORB only if blocked     |

## Agent Management Rule

| Rule                                                            | Meaning                                                       |
| --------------------------------------------------------------- | ------------------------------------------------------------- |
| One agent should handle one strategy or one phase of a strategy | Avoid mixing PM-HL, PM high fade, BTC-NQ, etc.                |
| One strategy may have multiple agents over time                 | Use handoff docs when context gets full                       |
| All long-term outputs must be saved in project files            | Do not rely on Agent memory                                   |
| Old projects are read-only sources during inventory             | Do not directly copy secrets, temp files, or obsolete scripts |

## Suggested Agent Names

| Agent Name      | Scope                                                |
| --------------- | ---------------------------------------------------- |
| `pm_hl_arb1`    | Initial migration / dry-run / S1-S2 design           |
| `pm_hl_arb2`    | Live validation / position reconciliation / P0 close |
| `pm_high_fade1` | Inventory old `202605_pm_trading`                    |
| `pm_high_fade2` | Migrate high fade / trend monitor                    |
| `btc_nq1`       | Inventory old BTC-NQ logic                           |
| `btc_nq2`       | Futu paper bridge                                    |
| `tqqq_orb1`     | Inventory / restore TQQQ ORB                         |
