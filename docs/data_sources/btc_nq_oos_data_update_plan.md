# BTC-NQ OOS Data Update Plan

Current owner: `data_btc_nq1`

Status: **inventory + dry-run only** (2026-06-20). No downloads executed in this pass. No Databento API calls. No strategy / backtest / OOS runs.

## Scope and Baseline Lock

- OOS reproduction and forward evaluation must use **`old_raw_contract`** NQ mode (not `continuous`).
- Locked strategy baseline is unchanged:
  - `data/strategy/btc_nq_weekend/event_dataset_20241215_20260316_raw_contract.csv`
  - `reports/btc_nq_weekend/old_output_reproduction/old_focused_validation_reproduction_summary.json`
  - `scripts/strategy/btc_nq_weekend/smoke_test_old_output_reproduction.py`
- OOS provisional start: **`2026-03-17`** (first events after locked event dataset).
- Target data horizon: **through latest complete market data**, aiming near **`2026-06-20`**, without assuming that calendar date is complete for CME NQ sessions.

---

## 1. Current BTC Data Coverage

| Location | Path | Format | Start (UTC) | End (UTC) | Rows | old_raw_contract usable |
|---|---|---:|---|---:|---:|---|
| Old project (baseline) | `D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet` | parquet | 2020-01-01 00:00 | 2026-03-31 23:59 | 3,286,080 | **Yes** (BTC leg; 24/7 perp 1m) |
| Current repo | *(none under `data/market_data/`)* | — | — | — | — | — |

**Schema (baseline parquet):** `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `quote_asset_volume`, `number_of_trades`, `taker_buy_base_asset_volume`, `taker_buy_quote_asset_volume`, `ignore`, `open_time_utc`, `close_time_utc`, `source_month`

**Binance Vision availability probe (HEAD, 2026-06-20):**

| Source | Period | HTTP |
|---|---|---|
| Monthly ZIP | `2026-04` | 200 |
| Monthly ZIP | `2026-05` | 200 |
| Monthly ZIP | `2026-06` | 404 (month incomplete) |
| Daily ZIP | `2026-06-18` | 200 |
| Daily ZIP | `2026-06-19` | 404 |

Latest Binance Vision BTCUSDT UM 1m appears available through **2026-06-18 UTC** (daily). Current downloader uses **monthly** ZIPs only.

---

## 2. Current NQ Raw Contract Data Coverage

All raw-contract files found in **old project only**. Current repo has **no** NQ market-data files.

Roll chain confirmed for baseline: **`NQH5 → NQM5 → NQU5 → NQZ5 → NQH6`**

Preferred files for `old_raw_contract`: **`data/processed/databento/nq/*_clean.csv`** (same schema as raw after clean step).

| Symbol | Path (clean) | Format | Start (UTC) | End (UTC) | Rows | Columns | old_raw_contract usable |
|---|---|---:|---|---:|---:|---|---|
| NQH5 | `D:\cursor\202604_stra\data\processed\databento\nq\NQH5_1m_20241211_20250322_clean.csv` | csv | 2024-12-11 00:02 | 2025-03-21 13:29 | 94,758 | timestamp, open, high, low, close, volume, symbol | **Yes** |
| NQM5 | `...\NQM5_1m_20250312_20250621_clean.csv` | csv | 2025-03-12 00:00 | 2025-06-20 13:29 | 96,769 | same | **Yes** |
| NQU5 | `...\NQU5_1m_20250611_20250920_clean.csv` | csv | 2025-06-11 00:00 | 2025-09-19 13:29 | 97,647 | same | **Yes** |
| NQZ5 | `...\NQZ5_1m_20250910_20251220_clean.csv` | csv | 2025-09-10 00:04 | 2025-12-19 14:29 | 97,036 | same | **Yes** |
| NQH6 | `...\NQH6_1m_20251219_20260320_clean.csv` | csv | 2025-12-19 00:00 | **2026-03-19 23:57** | 86,101 | same | **Yes** |

Matching **raw** CSVs exist under `D:\cursor\202604_stra\data\raw\databento\nq\` with identical row counts and UTC ranges.

**Not found anywhere** (repo + old project search): **`NQM6`**, **`NQU6`**, **`NQZ6`**, **`NQH7`**.

Chicago session note (NQH6 summary): last bar **2026-03-19 18:57 America/Chicago** — aligns with UTC end above.

---

## 3. NQ Continuous Coverage (Reference Only)

| Location | Path | Format | Start (UTC) | End (UTC) | Rows | old_raw_contract usable |
|---|---|---:|---|---:|---:|---|
| Old project | `D:\cursor\202604_stra\data\market_data\databento\GLBX.MDP3\NQ\1m\nq_continuous_volume_front_1m_2020_2026.parquet` | parquet | 2020-01-01 23:00 | 2026-04-30 23:59 | 2,233,693 | **No** (research branch only) |

**Schema:** `ts_event`, `rtype`, `publisher_id`, `instrument_id`, `open`, `high`, `low`, `close`, `volume`, `symbol`, `ts_event_utc`

---

## 4. OOS BTC Data Gap

Locked event dataset ends **2026-03-16**. OOS needs BTC 1m from **2026-03-17** onward.

Because baseline BTC parquet already runs through **2026-03-31 23:59 UTC**, the **incremental download gap** is:

| Gap start (inclusive) | Gap end (target) | Notes |
|---|---|---|
| **2026-04-01 00:00 UTC** | **latest available** (~2026-06-18 UTC on Binance Vision daily) | Mar 17–31 already in baseline file |

Estimated missing rows (Apr 1 – Jun 18): ~**112,320** minutes (78 days × 1440), subject to exact clip boundaries.

**June 2026:** monthly ZIP not published; daily ZIPs exist through **2026-06-18**. Current `download_btcusdt_um_1m.py` does **not** fetch daily files — Apr+May via monthly is straightforward; June requires script extension or a separate daily fetch step.

---

## 5. OOS NQ Raw Contract Gap

For `old_raw_contract` OOS through ~June 2026:

| Contract | Status | Needed window (approx, UTC exclusive end) | Reason |
|---|---|---|---|
| NQH5–NQH6 | **Present** (old project) | Baseline reproduction | Already used in locked smoke test |
| **NQM6** | **Missing** | **2026-03-20 → ~2026-06-20** | NQH6 ends 2026-03-19; OOS events after roll need NQM6 |
| **NQU6** | **Missing** | **2026-06-20 → ~2026-09-19** | Required only if OOS events extend past NQM6 roll; verify against last complete CME session |
| NQZ6 | Missing | Later | Not needed for near-term OOS through June |

Strategy roll chain in code currently ends at **`NQH6`** (`research/weekend_btc_nq/nq_contracts.py` in old project). **`btc_nq_strategy1` must extend roll chain to include NQM6 (and NQU6 if needed)** after data lands — out of scope for this data-layer task.

---

## 6. Can BTC Be Updated Directly?

**Yes**, with safe staging:

- Downloader: `scripts/data/binance/download_btcusdt_um_1m.py`
- **No API key** required (Binance Vision public data)
- Writes to user-specified `--output`; does not touch old baseline if output path is new
- Validates via `scripts/data/binance/validate_btcusdt_um_1m.py`

### Recommended staging command (Apr–May 2026, monthly-only)

```powershell
python scripts/data/binance/download_btcusdt_um_1m.py `
  --start 2026-04-01 `
  --end 2026-06-01 `
  --start-month 2026-04 `
  --end-month 2026-05 `
  --output "D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet"
```

Post-download validation:

```powershell
python scripts/data/binance/validate_btcusdt_um_1m.py `
  --input "D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet"
```

**Do not overwrite:** `D:\cursor\202604_stra\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_2020_2026.parquet`

**June partial (2026-06-01 .. ~2026-06-18):** not covered by current monthly downloader. Options for a follow-up task:

1. Extend downloader with daily Binance Vision support, or
2. Wait for `BTCUSDT-1m-2026-06.zip` monthly publication.

---

## 7. Does NQ OOS Require Databento API?

**Yes.** Raw single-contract NQ 1m for `NQM6` / `NQU6` is not present locally. Databento Historical API is the established source (old project: `stra/data/download_databento_nq_1m.py`).

Current repo downloader **`scripts/data/databento/download_nq_continuous_1m.py` supports continuous (`NQ.v.0`) only** — **insufficient for OOS baseline**.

**Action needed (future task):** port or add `scripts/data/databento/download_nq_raw_contract_1m.py` mirroring old-project raw-symbol flow (`stype_in=raw_symbol`), with the same dry-run / credit-confirmation guardrails as the continuous script.

**Credential check (2026-06-20):** `DATABENTO_API_KEY` — **credential appears available** in environment. Key content not inspected or printed.

---

## 8. Databento Dry-Run Download Plan (No API Called)

Based on old-project contract calendar (`stra/data/download_databento_nq_1m.py` header). Verify exact roll dates against CME expiry before executing.

### NQM6 (required for OOS through June)

| Field | Value |
|---|---|
| dataset | `GLBX.MDP3` |
| schema | `ohlcv-1m` |
| stype_in | `raw_symbol` |
| symbol | `NQM6` |
| start | `2026-03-20` (UTC, inclusive; day after NQH6 window) |
| end | `2026-06-20` (UTC, exclusive; adjust to latest complete session) |
| raw output | `data/raw/market_data/databento/GLBX.MDP3/NQ/1m/NQM6_1m_20260320_20260620.csv` |
| clean output (after clean step) | `data/processed/market_data/databento/GLBX.MDP3/NQ/1m/NQM6_1m_20260320_20260620_clean.csv` |
| API key | Required — read from env var `DATABENTO_API_KEY` |
| credits | Yes — consumed on `--execute` |

Example (old-project script pattern; **do not run without user confirmation**):

```powershell
# Requires porting clean pipeline to new repo paths first
python stra/data/download_databento_nq_1m.py --symbol NQM6 --start 2026-03-20 --end 2026-06-20
python stra/data/clean_check_databento_nq_1m.py --raw data/raw/databento/nq/NQM6_1m_20260320_20260620.csv
```

### NQU6 (conditional — if OOS extends past NQM6 roll)

| Field | Value |
|---|---|
| symbol | `NQU6` |
| start | `2026-06-20` |
| end | `2026-09-19` (exclusive) |
| raw output | `data/raw/market_data/databento/GLBX.MDP3/NQ/1m/NQU6_1m_20260620_20260919.csv` |

### Continuous (reference / research branch only)

Existing dry-run (already verified):

```powershell
python scripts/data/databento/download_nq_continuous_1m.py `
  --start 2026-05-01 `
  --end 2026-07-01 `
  --output "D:\cursor\2026_strategy_lab\data\market_data\databento\GLBX.MDP3\NQ\1m\nq_continuous_volume_front_1m_20260501_20260701.parquet"
```

No API call unless both `--execute` and `--confirm-use-api-credits` are passed.

---

## 9. User Confirmation Checklist Before Real Downloads

1. **Approve BTC staging download** (Apr–May monthly; decide on June daily extension).
2. **Approve Databento credit spend** for `NQM6` (and `NQU6` if needed).
3. **Confirm OOS end date** — use latest **complete CME session**, not calendar `2026-06-20` blindly.
4. **Confirm roll chain extension** — strategy layer must add `NQM6` (+ `NQU6`) to `old_raw_contract` chain.
5. **Confirm data landing paths** in `2026_strategy_lab` vs symlink/copy from `202604_stra` baseline files.
6. **Do not overwrite** old baseline parquets/CSVs or smoke-test inputs.

---

## 10. Handoff to `btc_nq_strategy1` After Data Update

Once market data is staged and validated, strategy owner should:

1. Extend NQ roll chain: `NQH5 → NQM5 → NQU5 → NQZ5 → NQH6 → **NQM6**` (+ `NQU6` if window requires).
2. Point `old_raw_contract` loader at new clean CSV paths (or copied files under `2026_strategy_lab/data/processed/...`).
3. Merge / reference updated BTC parquet (baseline + staging tranche, or unified non-destructive combined file).
4. Regenerate **OOS event dataset** from `2026-03-17` forward (strategy task — not done here).
5. Re-run smoke test on **locked baseline** unchanged; run separate OOS evaluation on new events only.

---

## Current Repo Strategy Artifacts (unchanged)

| File | Rows | Notes |
|---|---:|---|
| `data/strategy/btc_nq_weekend/event_dataset_20241215_20260316_raw_contract.csv` | 132 | Locked baseline events; last active contract `NQH6` |
| `data/strategy/btc_nq_weekend/event_dataset_20241215_20260316.csv` | 131 | Non-raw-contract variant |

---

## Execution Log (this task)

| Action | Done? |
|---|---|
| Read-only inventory | Yes |
| Databento API called | **No** |
| Databento credits used | **No** |
| BTC downloaded | **No** |
| NQ downloaded | **No** |
| Strategy / backtest / OOS | **No** |
| Baseline files overwritten | **No** |

---

## Execution Log (2026-06-20 — BTC staging + NQ raw-symbol pipeline)

### 1. BTC Apr–May staging download

| Field | Result |
|---|---|
| Download success | **Yes** |
| Output path | `data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_20260401_20260601.parquet` |
| Rows | 87,840 |
| Range (UTC) | 2026-04-01 00:00 → 2026-05-31 23:59 |
| Validation | **PASS** |
| Old baseline overwritten | **No** |

Command used:

```powershell
python scripts/data/binance/download_btcusdt_um_1m.py `
  --start 2026-04-01 `
  --end 2026-06-01 `
  --start-month 2026-04 `
  --end-month 2026-05 `
  --output "D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet"

python scripts/data/binance/validate_btcusdt_um_1m.py `
  --input "D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet"
```

Remaining BTC gap: **2026-06-01 → latest** (June daily or monthly when published).

### 2. New NQ raw-symbol scripts

| Script | Purpose |
|---|---|
| `scripts/data/databento/download_nq_raw_contract_1m.py` | Raw-symbol downloader; dry-run by default |
| `scripts/data/databento/clean_nq_raw_contract_1m.py` | Raw CSV → clean CSV for `old_raw_contract` |
| `scripts/data/databento/validate_nq_raw_contract_1m.py` | Validate clean CSV/parquet schema and quality |

Dry-run default: no API call unless both `--execute` and `--confirm-use-api-credits` are passed.
API key read from `DATABENTO_API_KEY` environment variable only.

`validate_nq_raw_contract_1m.py` smoke-tested against old-project `NQH6` clean CSV: **PASS**.

### 3. NQM6 dry-run command (do not run with `--execute` without user credit approval)

```powershell
python scripts/data/databento/download_nq_raw_contract_1m.py `
  --symbol NQM6 `
  --start 2026-03-20 `
  --end 2026-06-20 `
  --output "D:\cursor\2026_strategy_lab\data\raw\databento\GLBX.MDP3\NQ\raw_symbol\NQM6\NQM6_1m_20260320_20260620.csv"
```

After download (future, with credit approval):

```powershell
python scripts/data/databento/clean_nq_raw_contract_1m.py `
  --input "D:\cursor\2026_strategy_lab\data\raw\databento\GLBX.MDP3\NQ\raw_symbol\NQM6\NQM6_1m_20260320_20260620.csv" `
  --output "D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQM6_1m_20260320_20260620_clean.csv"

python scripts/data/databento/validate_nq_raw_contract_1m.py `
  --input "D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQM6_1m_20260320_20260620_clean.csv"
```

Adjust `--end` to latest complete CME session before executing.

### 4. NQU6 optional dry-run command (conditional — only if OOS extends past NQM6 roll)

```powershell
python scripts/data/databento/download_nq_raw_contract_1m.py `
  --symbol NQU6 `
  --start 2026-06-20 `
  --end 2026-09-19 `
  --output "D:\cursor\2026_strategy_lab\data\raw\databento\GLBX.MDP3\NQ\raw_symbol\NQU6\NQU6_1m_20260620_20260919.csv"
```

### 5. User confirmation required before NQ download

1. Explicit approval to spend **Databento credits** for `NQM6` (and `NQU6` if needed).
2. Confirm `--end` date against latest complete CME session.
3. Run with both `--execute` and `--confirm-use-api-credits`.

### 6. This pass execution summary

| Action | Done? |
|---|---|
| BTC Apr–May staging downloaded | **Yes** |
| BTC validation PASS | **Yes** |
| NQ raw-symbol scripts added | **Yes** |
| Databento API called | **No** |
| NQ data downloaded | **No** |
| Strategy / backtest / OOS | **No** |

---

## Execution Log (2026-06-20 — NQM6 / NQU6 Databento download)

User authorized Databento credits for **`NQM6`** and **`NQU6`** only.

### License constraint

Databento `GLBX.MDP3` subscription available end was approximately **`2026-06-19T23:16:58Z`**. Script `--end` is **exclusive** (`YYYY-MM-DD` midnight UTC).

| Request | Adjustment |
|---|---|
| NQM6 `--end 2026-06-20` | Failed (`dataset_unavailable_range`); retried with **`--end 2026-06-19`** |
| NQU6 `--start 2026-06-20` | Failed (`data_start_after_available_end`); retried with **`--start 2026-06-18 --end 2026-06-19`** |

### NQM6 results

| Field | Value |
|---|---|
| Download success | **Yes** (end adjusted) |
| API `--start` / `--end` | `2026-03-20` / `2026-06-19` (exclusive) |
| Raw path | `data/raw/databento/GLBX.MDP3/NQ/raw_symbol/NQM6/NQM6_1m_20260320_20260620.csv` |
| Clean path | `data/processed/databento/nq/NQM6_1m_20260320_20260620_clean.csv` |
| Rows | 88,063 |
| First timestamp (UTC) | 2026-03-20 00:00:00 |
| Last timestamp (UTC) | 2026-06-18 13:29:00 |
| Validation | **PASS** |
| Gaps > 1m | 301 (expected CME session breaks) |

### NQU6 results

| Field | Value |
|---|---|
| Download success | **Partial** — only pre-roll overlap day within license window |
| API `--start` / `--end` | `2026-06-18` / `2026-06-19` (exclusive; nominal roll start 2026-06-20 not yet licensed) |
| Raw path | `data/raw/databento/GLBX.MDP3/NQ/raw_symbol/NQU6/NQU6_1m_20260620_latest.csv` |
| Clean path | `data/processed/databento/nq/NQU6_1m_20260620_latest_clean.csv` |
| Rows | 1,380 |
| First timestamp (UTC) | 2026-06-18 00:00:00 |
| Last timestamp (UTC) | 2026-06-18 23:59:00 |
| Validation | **PASS** |
| Gaps > 1m | 1 (maintenance break) |

**Note:** NQU6 does **not** yet cover post-roll OOS window (2026-06-20+). Re-download when Databento license extends.

### Execution summary

| Action | Done? |
|---|---|
| Databento API called | **Yes** |
| Databento credits used | **Yes** |
| NQM6 downloaded / cleaned / validated | **Yes / Yes / PASS** |
| NQU6 downloaded / cleaned / validated | **Partial / Yes / PASS** |
| Other NQ contracts downloaded | **No** |
| Strategy / backtest / OOS | **No** |

### Handoff paths for `btc_nq_strategy1`

Extend `old_raw_contract` roll chain with:

| Symbol | Clean CSV path |
|---|---|
| NQH5–NQH6 | `D:\cursor\202604_stra\data\processed\databento\nq\` (existing baseline) |
| **NQM6** | `D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQM6_1m_20260320_20260620_clean.csv` |
| **NQU6** | `D:\cursor\2026_strategy_lab\data\processed\databento\nq\NQU6_1m_20260620_latest_clean.csv` (partial; extend later) |

BTC staging (already available):

- Apr–May: `D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260401_20260601.parquet`
- June daily: `D:\cursor\2026_strategy_lab\data\market_data\binance\futures\um\klines\BTCUSDT\1m\btcusdt_um_1m_20260601_20260618_daily.parquet`

---

## Execution Log (2026-06-20 — BTC June daily staging)

### Downloader change

`scripts/data/binance/download_btcusdt_um_1m.py` now supports **`--mode daily`** in addition to default **`--mode monthly`**.

Daily mode uses Binance Vision USD-M futures daily klines:

`https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{YYYY-MM-DD}.zip`

Raw ZIP cache default: `data/raw/market_data/binance/futures/um/daily/klines/BTCUSDT/1m/`

### Download results

| Field | Value |
|---|---|
| Command mode | `--mode daily --start 2026-06-01 --end 2026-06-20` |
| Downloaded dates | 2026-06-01 through **2026-06-18** (18 days) |
| Unavailable dates | **2026-06-19** (HTTP 404; optional trailing day) |
| Output path | `data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_20260601_20260618_daily.parquet` |
| Rows | 25,920 |
| First timestamp (UTC) | 2026-06-01 00:00:00 |
| Last timestamp (UTC) | 2026-06-18 23:59:00 |
| Validation | **PASS** (0 gaps; 24/7 continuity) |

### Current BTC coverage (for strategy handoff)

| Tranche | Path | End (UTC) |
|---|---|---|
| Old baseline | `202604_stra/.../btcusdt_um_1m_2020_2026.parquet` | 2026-03-31 23:59 |
| Apr–May staging | `2026_strategy_lab/.../btcusdt_um_1m_20260401_20260601.parquet` | 2026-05-31 23:59 |
| June daily staging | `2026_strategy_lab/.../btcusdt_um_1m_20260601_20260618_daily.parquet` | 2026-06-18 23:59 |

**Gap:** 2026-06-19+ until Binance Vision publishes next daily/monthly ZIP.

### Execution summary

| Action | Done? |
|---|---|
| Daily mode added | **Yes** |
| June daily downloaded | **Yes** (through 2026-06-18) |
| Validation PASS | **Yes** |
| Old baseline overwritten | **No** |
| Apr–May staging overwritten | **No** |
| NQ / Databento | **No** |
| Strategy / backtest / OOS | **No** |
