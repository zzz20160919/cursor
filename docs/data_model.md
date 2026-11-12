# SQLite Data Model

P0 uses one local SQLite database at `data/lab.sqlite`.

Scope:
- Use Python standard library `sqlite3`
- Keep 5 core tables only
- Do not use an ORM
- Do not connect to external APIs
- Do not store live trading orders, fills, positions, paper orders, or risk events

## Tables

### runs

Records each script, research, or strategy run.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Internal row id |
| run_id | TEXT UNIQUE NOT NULL | External run id, for example `pm_hl_20260615_001` |
| run_type | TEXT | Script, research, import, smoke_test |
| strategy_id | TEXT | Strategy identifier |
| started_at | TEXT | ISO timestamp |
| finished_at | TEXT | ISO timestamp |
| status | TEXT | Run status |
| notes | TEXT | Free-form notes |
| created_at | TEXT | ISO timestamp |

### assets

Registers assets, markets, contracts, or instruments.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Internal row id |
| symbol | TEXT | Symbol or market id |
| asset_class | TEXT | Asset class |
| venue | TEXT | Venue or source |
| description | TEXT | Free-form description |
| created_at | TEXT | ISO timestamp |

### market_snapshots

Stores prices, order book fields, volume, and source-specific raw data.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Internal row id |
| asset_id | INTEGER | References `assets.id` |
| ts | TEXT | Observation timestamp |
| source | TEXT | Data source |
| price | REAL | Last or reference price |
| bid | REAL | Best bid |
| ask | REAL | Best ask |
| volume | REAL | Volume |
| raw_json | TEXT | Source-specific JSON string |
| created_at | TEXT | ISO timestamp |

### strategy_signals

Stores strategy-level signals. A signal is not necessarily a tradable opportunity.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Internal row id |
| run_id | TEXT | References `runs.run_id` |
| strategy_id | TEXT | Strategy identifier |
| asset_id | INTEGER | References `assets.id` |
| ts | TEXT | Signal timestamp |
| signal | TEXT | Signal label |
| confidence | REAL | Optional confidence score |
| reason | TEXT | Short explanation |
| raw_json | TEXT | Strategy-specific JSON string |
| created_at | TEXT | ISO timestamp |

### opportunities

Stores discovered arbitrage or trading opportunities.

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Internal row id |
| run_id | TEXT | References `runs.run_id` |
| strategy_id | TEXT | Strategy identifier |
| ts | TEXT | Opportunity timestamp |
| venue_1 | TEXT | First venue |
| venue_2 | TEXT | Second venue |
| instrument_1 | TEXT | First instrument |
| instrument_2 | TEXT | Second instrument |
| opportunity_type | TEXT | Opportunity category |
| gross_edge | REAL | Gross edge before costs |
| estimated_cost | REAL | Estimated total cost |
| net_edge | REAL | Net edge after costs |
| executable_size | REAL | Estimated executable size |
| status | TEXT | Candidate, observed, rejected, etc. |
| notes | TEXT | Free-form notes |
| raw_json | TEXT | Opportunity-specific JSON string |
| created_at | TEXT | ISO timestamp |

## Extension Rules

- New venues should first use `assets.venue` and `market_snapshots.raw_json`.
- New strategy opportunities should first use `opportunities`.
- Keep `strategy_signals` and `opportunities` separate: signals are strategy judgments; opportunities are tradable candidates for evaluation and review.
- Add specialized tables only after a data shape becomes stable.
- Add `orders`, `fills`, `positions`, `paper_orders`, or `risk_events` only when the project explicitly moves beyond P0 research infrastructure.
