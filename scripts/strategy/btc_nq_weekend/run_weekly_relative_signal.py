from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IS_DATASET = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_20241215_20260316_raw_contract.csv"
DEFAULT_OOS_DATASET = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset_oos_20260317_20260618_raw_contract.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/btc_nq_weekend/weekly_relative_signal"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategies/btc_nq_weekend/weekly_relative_signal_report.md"

DEFAULT_NQ_CONTRACT_PATHS = {
    "NQH5": Path("D:/cursor/202604_stra/data/processed/databento/nq/NQH5_1m_20241211_20250322_clean.csv"),
    "NQM5": Path("D:/cursor/202604_stra/data/processed/databento/nq/NQM5_1m_20250312_20250621_clean.csv"),
    "NQU5": Path("D:/cursor/202604_stra/data/processed/databento/nq/NQU5_1m_20250611_20250920_clean.csv"),
    "NQZ5": Path("D:/cursor/202604_stra/data/processed/databento/nq/NQZ5_1m_20250910_20251220_clean.csv"),
    "NQH6": Path("D:/cursor/202604_stra/data/processed/databento/nq/NQH6_1m_20251219_20260320_clean.csv"),
    "NQM6": PROJECT_ROOT / "data/processed/databento/nq/NQM6_1m_20260320_20260620_clean.csv",
    "NQU6": PROJECT_ROOT / "data/processed/databento/nq/NQU6_1m_20260620_latest_clean.csv",
}

SIGNAL_MODES = ("btc_threshold_0p5", "relative_underreaction", "btc_minus_nq_spread_0p5")
NQ_TARGETS = ("nq_fwd_1h", "nq_fwd_4h", "nq_fwd_to_1600_same_day")
BTC_THRESHOLD = 0.005
NQ_UNDERREACTION_THRESHOLD = 0.001
SPREAD_THRESHOLD = 0.005
DEFAULT_COST_RATE = 0.001
TRADES_PER_YEAR = 52.0
LOW_SAMPLE_WARN_THRESHOLD = 20
OOS_START_LOCAL_DATE = "2026-03-23"
NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class ContractCoverage:
    close: pd.Series
    first_utc: pd.Timestamp
    last_utc: pd.Timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-NQ weekly relative signal test.")
    parser.add_argument("--is-dataset", type=Path, default=DEFAULT_IS_DATASET)
    parser.add_argument("--oos-dataset", type=Path, default=DEFAULT_OOS_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def detect_timestamp(frame: pd.DataFrame) -> pd.Series:
    for column in ("timestamp", "ts_event_utc", "ts_event", "open_time_utc", "open_time"):
        if column not in frame.columns:
            continue
        values = frame[column]
        if pd.api.types.is_numeric_dtype(values):
            numeric = pd.to_numeric(values, errors="coerce")
            unit = "ms" if float(numeric.dropna().max()) >= 1e11 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(values, utc=True, errors="coerce")
    raise ValueError(f"could not detect timestamp column from {list(frame.columns)}")


def load_contracts() -> dict[str, ContractCoverage]:
    contracts: dict[str, ContractCoverage] = {}
    for symbol, path in DEFAULT_NQ_CONTRACT_PATHS.items():
        if not path.exists():
            raise FileNotFoundError(f"NQ contract file not found: {symbol} {path}")
        frame = pd.read_csv(path)
        timestamps = detect_timestamp(frame)
        close = pd.to_numeric(frame["close"], errors="coerce")
        out = pd.DataFrame({"timestamp_utc": timestamps, "close": close}).dropna()
        out = out.sort_values("timestamp_utc", kind="mergesort")
        series = out.set_index("timestamp_utc")["close"].astype(float)
        contracts[symbol] = ContractCoverage(close=series, first_utc=series.index.min(), last_utc=series.index.max())
    return contracts


def lookup(series: pd.Series, ts: pd.Timestamp) -> float | None:
    if ts in series.index:
        value = float(series.loc[ts])
        if math.isfinite(value) and value > 0:
            return value
    return None


def load_events(path: Path, sample_period: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"event dataset not found: {path}")
    frame = pd.read_csv(path)
    frame = frame.loc[frame["event_name"] == "monday_0930"].copy()
    frame["sample_period"] = sample_period
    frame["event_time_ny_dt"] = pd.to_datetime(frame["event_time_ny"], utc=True, errors="coerce").dt.tz_convert(
        "America/New_York"
    )
    frame["event_time_utc_dt"] = pd.to_datetime(frame["event_time_utc"], utc=True, errors="coerce")
    for column in ("btc_ret_1h", "nq_px_t0", "nq_fwd_1h", "nq_fwd_4h"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("event_time_utc_dt", kind="mergesort").reset_index(drop=True)


def add_nq_pre_ret(events: pd.DataFrame, contracts: dict[str, ContractCoverage]) -> pd.DataFrame:
    out = events.copy()
    pre_values: list[float] = []
    start_px_values: list[float] = []
    end_px_values: list[float] = []
    missing: list[bool] = []
    missing_reason: list[str] = []
    for _, row in out.iterrows():
        active = str(row["active_contract"])
        t0 = pd.Timestamp(row["event_time_utc_dt"]).floor("1min")
        start = t0 - pd.Timedelta(hours=1)
        if active not in contracts:
            pre_values.append(float("nan"))
            start_px_values.append(float("nan"))
            end_px_values.append(float("nan"))
            missing.append(True)
            missing_reason.append("missing_active_contract_series")
            continue
        series = contracts[active].close
        start_px = lookup(series, start)
        end_px = lookup(series, t0)
        start_px_values.append(start_px if start_px is not None else float("nan"))
        end_px_values.append(end_px if end_px is not None else float("nan"))
        if start_px is None or end_px is None:
            pre_values.append(float("nan"))
            missing.append(True)
            missing_reason.append("nq_pre_endpoint_missing")
        else:
            pre_values.append(float(math.log(end_px / start_px)))
            missing.append(False)
            missing_reason.append("")
    out["nq_pre_ret_1h"] = pre_values
    out["nq_pre_px_start_1h"] = start_px_values
    out["nq_pre_px_end_1h"] = end_px_values
    out["nq_pre_missing"] = missing
    out["nq_pre_missing_reason"] = missing_reason
    out["btc_minus_nq_1h"] = out["btc_ret_1h"] - out["nq_pre_ret_1h"]
    return out


def target_return(row: pd.Series, target: str, contracts: dict[str, ContractCoverage]) -> tuple[float, str, float | None, bool]:
    if target != "nq_fwd_to_1600_same_day":
        value = row.get(target)
        end_col = f"{target}_end_utc"
        end_px_col = f"nq_px_end_{target.removeprefix('nq_fwd_')}"
        return (
            float(value) if pd.notna(value) else float("nan"),
            str(row.get(end_col) or ""),
            float(row.get(end_px_col)) if pd.notna(row.get(end_px_col)) else None,
            pd.isna(value),
        )
    event_time_ny = pd.Timestamp(row["event_time_ny_dt"])
    target_local = pd.Timestamp.combine(event_time_ny.date(), pd.Timestamp("16:00").time()).tz_localize(NEW_YORK)
    target_utc = target_local.tz_convert(UTC)
    active = str(row["active_contract"])
    start_px = float(row["nq_px_t0"]) if pd.notna(row["nq_px_t0"]) else float("nan")
    if active not in contracts or not math.isfinite(start_px) or start_px <= 0:
        return float("nan"), target_utc.isoformat(), None, True
    end_px = lookup(contracts[active].close, target_utc)
    if end_px is None:
        return float("nan"), target_utc.isoformat(), None, True
    return float(math.log(end_px / start_px)), target_utc.isoformat(), end_px, False


def signal_action(row: pd.Series, signal_mode: str) -> tuple[str, str]:
    btc = row.get("btc_ret_1h")
    nq_pre = row.get("nq_pre_ret_1h")
    spread = row.get("btc_minus_nq_1h")
    if pd.isna(btc):
        return "skip", "btc_missing"
    btc = float(btc)
    if signal_mode == "btc_threshold_0p5":
        if btc > BTC_THRESHOLD:
            return "long", ""
        if btc < -BTC_THRESHOLD:
            return "short", ""
        return "no_trade", "btc_threshold_not_met"
    if pd.isna(nq_pre):
        return "skip", "nq_pre_missing"
    nq_pre = float(nq_pre)
    if signal_mode == "relative_underreaction":
        if btc > BTC_THRESHOLD:
            if nq_pre <= NQ_UNDERREACTION_THRESHOLD:
                return "long", ""
            return "no_trade", "nq_already_priced_in"
        if btc < -BTC_THRESHOLD:
            if nq_pre >= -NQ_UNDERREACTION_THRESHOLD:
                return "short", ""
            return "no_trade", "nq_already_priced_in"
        return "no_trade", "btc_threshold_not_met"
    if pd.isna(spread):
        return "skip", "nq_pre_missing"
    spread = float(spread)
    if spread > SPREAD_THRESHOLD:
        return "long", ""
    if spread < -SPREAD_THRESHOLD:
        return "short", ""
    return "no_trade", "spread_threshold_not_met"


def build_records(events: pd.DataFrame, contracts: dict[str, ContractCoverage]) -> tuple[pd.DataFrame, pd.DataFrame]:
    trade_rows: list[dict[str, object]] = []
    skip_rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        for signal_mode in SIGNAL_MODES:
            action, reason = signal_action(event, signal_mode)
            for target in NQ_TARGETS:
                target_log, target_end_utc, target_end_px, endpoint_missing = target_return(event, target, contracts)
                final_action = action
                final_reason = reason
                gross = float("nan")
                net = float("nan")
                if final_action in {"long", "short"} and endpoint_missing:
                    final_action = "skip"
                    final_reason = "endpoint_missing"
                if final_action in {"long", "short"} and math.isfinite(target_log):
                    simple = math.exp(target_log) - 1.0
                    gross = simple if final_action == "long" else -simple
                    net = gross - DEFAULT_COST_RATE
                    trade_rows.append(
                        {
                            "strategy_id": f"{signal_mode}__{target}",
                            "signal_mode": signal_mode,
                            "nq_target": target,
                            "sample_period": event["sample_period"],
                            "event_id": event["event_id"],
                            "event_time_ny": event["event_time_ny"],
                            "event_time_utc": event["event_time_utc"],
                            "active_contract": event["active_contract"],
                            "btc_ret_1h": event["btc_ret_1h"],
                            "nq_pre_ret_1h": event["nq_pre_ret_1h"],
                            "btc_minus_nq_1h": event["btc_minus_nq_1h"],
                            "action": final_action,
                            "side": final_action,
                            "target_log_return": target_log,
                            "target_simple_return": simple,
                            "target_end_utc": target_end_utc,
                            "target_end_px": target_end_px,
                            "cost_rate": DEFAULT_COST_RATE,
                            "strategy_return_gross": gross,
                            "strategy_return_net": net,
                        }
                    )
                skip_rows.append(
                    {
                        "strategy_id": f"{signal_mode}__{target}",
                        "signal_mode": signal_mode,
                        "nq_target": target,
                        "sample_period": event["sample_period"],
                        "event_id": event["event_id"],
                        "event_time_ny": event["event_time_ny"],
                        "event_time_utc": event["event_time_utc"],
                        "active_contract": event["active_contract"],
                        "btc_ret_1h": event["btc_ret_1h"],
                        "nq_pre_ret_1h": event["nq_pre_ret_1h"],
                        "btc_minus_nq_1h": event["btc_minus_nq_1h"],
                        "action": final_action,
                        "no_trade_reason": final_reason,
                        "gross_return": gross,
                        "net_return": net,
                        "endpoint_missing": bool(endpoint_missing),
                        "nq_pre_missing": bool(event["nq_pre_missing"]),
                        "btc_missing": bool(pd.isna(event["btc_ret_1h"])),
                    }
                )
    return pd.DataFrame(trade_rows), pd.DataFrame(skip_rows)


def max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return float("nan")
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(equity)
    return float(np.min(equity / peaks - 1.0))


def sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return float("nan")
    sd = float(np.std(returns, ddof=1))
    if sd == 0:
        return float("nan")
    return float(np.mean(returns) / sd * math.sqrt(52.0))


def summarize(trades: pd.DataFrame, skips: pd.DataFrame, *, strategy_id: str, sample_mode: str, sample_name: str) -> dict[str, object]:
    sub = trades.loc[trades["strategy_id"] == strategy_id].copy()
    skip = skips.loc[skips["strategy_id"] == strategy_id].copy()
    gross = sub["strategy_return_gross"].to_numpy(dtype=float)
    net = sub["strategy_return_net"].to_numpy(dtype=float)
    return {
        "sample_mode": sample_mode,
        "strategy_id": strategy_id,
        "signal_mode": strategy_id.split("__", 1)[0],
        "nq_target": strategy_id.split("__", 1)[1],
        "sample_name": sample_name,
        "total_events": int(skip["event_id"].nunique()),
        "trade_count": int(len(sub)),
        "no_trade_count": int((skip["action"] == "no_trade").sum()),
        "endpoint_missing_count": int((skip["no_trade_reason"] == "endpoint_missing").sum()),
        "nq_pre_missing_count": int((skip["no_trade_reason"] == "nq_pre_missing").sum()),
        "btc_missing_count": int((skip["no_trade_reason"] == "btc_missing").sum()),
        "long_count": int((sub["side"] == "long").sum()),
        "short_count": int((sub["side"] == "short").sum()),
        "average_gross_return": float(np.mean(gross)) if gross.size else float("nan"),
        "average_net_return": float(np.mean(net)) if net.size else float("nan"),
        "cumulative_gross_return": float(np.prod(1 + gross) - 1) if gross.size else float("nan"),
        "cumulative_net_return": float(np.prod(1 + net) - 1) if net.size else float("nan"),
        "net_win_rate": float(np.mean(net > 0)) if net.size else float("nan"),
        "max_drawdown_net": max_drawdown(net),
        "sharpe_net": sharpe(net),
        "low_sample_warning": str(len(sub) < LOW_SAMPLE_WARN_THRESHOLD).lower(),
    }


def strategy_ids() -> list[str]:
    return [f"{mode}__{target}" for mode in SIGNAL_MODES for target in NQ_TARGETS]


def split_ids(skip_base: pd.DataFrame) -> dict[str, set[str]]:
    events = skip_base.drop_duplicates("event_id").sort_values("event_time_utc")
    is_events = events.loc[events["sample_period"] == "is"]
    oos_events = events.loc[events["sample_period"] == "oos"]
    half = len(is_events) // 2
    return {
        "first_half": set(is_events.iloc[:half]["event_id"]),
        "second_half": set(is_events.iloc[half:]["event_id"]),
        "oos": set(oos_events["event_id"]),
    }


def build_summary(trades: pd.DataFrame, skips: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    return pd.DataFrame([summarize(trades, skips, strategy_id=sid, sample_mode=sample_mode, sample_name="full_is_oos") for sid in strategy_ids()])


def build_subsample(trades: pd.DataFrame, skips: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    base = skips.loc[skips["strategy_id"] == strategy_ids()[0]]
    for sample_name, ids in split_ids(base).items():
        t = trades.loc[trades["event_id"].isin(ids)].copy()
        s = skips.loc[skips["event_id"].isin(ids)].copy()
        for sid in strategy_ids():
            row = summarize(t, s, strategy_id=sid, sample_mode=sample_mode, sample_name=sample_name)
            row["event_count"] = len(ids)
            rows.append(row)
    return pd.DataFrame(rows)


def build_side(trades: pd.DataFrame, *, sample_mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sid in strategy_ids():
        combo = trades.loc[trades["strategy_id"] == sid]
        for name, side in (("long_only", "long"), ("short_only", "short"), ("symmetric", None)):
            sub = combo.copy() if side is None else combo.loc[combo["side"] == side].copy()
            fake_skips = pd.DataFrame({"strategy_id": [sid] * len(sub), "event_id": sub["event_id"], "action": "trade", "no_trade_reason": ""})
            row = summarize(sub, fake_skips, strategy_id=sid, sample_mode=sample_mode, sample_name=name)
            row["strategy_name"] = name
            rows.append(row)
    return pd.DataFrame(rows)


def common_ids(skips: pd.DataFrame) -> set[str]:
    valid_ids: set[str] | None = None
    for sid in strategy_ids():
        sub = skips.loc[skips["strategy_id"] == sid]
        ids = set(sub.loc[~sub["no_trade_reason"].isin(["endpoint_missing", "nq_pre_missing", "btc_missing"]), "event_id"])
        valid_ids = ids if valid_ids is None else valid_ids & ids
    return valid_ids or set()


def filter_counterfactual(skips: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    threshold_trades = skips.loc[skips["signal_mode"] == "btc_threshold_0p5"].copy()
    for mode in ("relative_underreaction", "btc_minus_nq_spread_0p5"):
        for target in NQ_TARGETS:
            rel = skips.loc[(skips["signal_mode"] == mode) & (skips["nq_target"] == target)]
            thresh = threshold_trades.loc[(threshold_trades["nq_target"] == target) & (threshold_trades["action"].isin(["long", "short"]))]
            filtered_ids = set(thresh["event_id"]) & set(rel.loc[rel["action"] == "no_trade", "event_id"])
            filtered = thresh.loc[thresh["event_id"].isin(filtered_ids)]
            kept_ids = set(thresh["event_id"]) & set(rel.loc[rel["action"].isin(["long", "short"]), "event_id"])
            kept = thresh.loc[thresh["event_id"].isin(kept_ids)]
            for label, subset in (("filtered_threshold_trades", filtered), ("kept_threshold_trades", kept)):
                returns = pd.to_numeric(subset["net_return"], errors="coerce").dropna().to_numpy(dtype=float)
                rows.append(
                    {
                        "signal_mode": mode,
                        "nq_target": target,
                        "group": label,
                        "event_count": int(len(subset)),
                        "average_net_return": float(np.mean(returns)) if returns.size else float("nan"),
                        "cumulative_net_return": float(np.prod(1 + returns) - 1) if returns.size else float("nan"),
                        "net_win_rate": float(np.mean(returns > 0)) if returns.size else float("nan"),
                    }
                )
    return pd.DataFrame(rows)


def plot_nav(trades: pd.DataFrame, output_path: Path, candidates_only: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(14, 8))
    oos_start = pd.Timestamp(f"{OOS_START_LOCAL_DATE}T09:30:00", tz=NEW_YORK)
    plot_ids = strategy_ids()
    if candidates_only:
        plot_ids = [
            "btc_threshold_0p5__nq_fwd_1h",
            "btc_threshold_0p5__nq_fwd_to_1600_same_day",
            "relative_underreaction__nq_fwd_1h",
            "relative_underreaction__nq_fwd_to_1600_same_day",
            "btc_minus_nq_spread_0p5__nq_fwd_1h",
            "btc_minus_nq_spread_0p5__nq_fwd_to_1600_same_day",
        ]
    for sid in plot_ids:
        sub = trades.loc[trades["strategy_id"] == sid].sort_values("event_time_utc")
        if sub.empty:
            continue
        nav = (1 + sub["strategy_return_net"]).cumprod()
        x = pd.to_datetime(sub["event_time_ny"], utc=True).dt.tz_convert("America/New_York")
        ax.plot(x, nav, linewidth=1.8, label=sid)
    ax.axvline(oos_start, linestyle="--", color="black", linewidth=1.2)
    ax.annotate(
        f"OOS start: {OOS_START_LOCAL_DATE}",
        xy=(oos_start, ax.get_ylim()[1]),
        xytext=(8, -24),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "black", "lw": 0.8},
    )
    ax.set_title("BTC-NQ weekly relative signal NAV" + (" candidates" if candidates_only else ""))
    ax.set_xlabel("Event time")
    ax.set_ylabel("Cumulative net NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not math.isfinite(number):
        return "nan"
    return f"{number:.6%}"


def report_lines(summary: pd.DataFrame, subsample: pd.DataFrame, counter: pd.DataFrame) -> list[str]:
    lines = [
        "# BTC-NQ Weekly Relative Signal Report",
        "",
        "Scope: weekly MVP only. Event is `monday_0930`, BTC lookback is `btc_ret_1h`, NQ mode is `old_raw_contract`, cost is `0.001`. No PM-HL, Futu, live/paper trading, QQQ proxy, daily strategy, data download, external API call, continuous NQ, beta scaling, z-score, vol adjustment, or extra thresholds were used.",
        "",
        "## Summary",
        "",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"- {row.strategy_id}: trades={row.trade_count}, no_trade={row.no_trade_count}, cum net={pct(row.cumulative_net_return)}, net win={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## OOS", ""])
    oos_rows = subsample.loc[(subsample["sample_mode"] == "available") & (subsample["sample_name"] == "oos")]
    for row in oos_rows.itertuples(index=False):
        lines.append(
            f"- {row.strategy_id}: OOS trades={row.trade_count}, no_trade={row.no_trade_count}, cum net={pct(row.cumulative_net_return)}, net win={pct(row.net_win_rate)}."
        )
    lines.extend(["", "## Filtered Counterfactual", ""])
    for row in counter.itertuples(index=False):
        lines.append(
            f"- {row.signal_mode} {row.nq_target} {row.group}: events={row.event_count}, avg net={pct(row.average_net_return)}, cum net={pct(row.cumulative_net_return)}."
        )
    return lines


def main() -> int:
    args = parse_args()
    contracts = load_contracts()
    events = pd.concat([load_events(args.is_dataset, "is"), load_events(args.oos_dataset, "oos")], ignore_index=True)
    events = add_nq_pre_ret(events, contracts)
    trades, skips = build_records(events, contracts)
    common = common_ids(skips)
    common_trades = trades.loc[trades["event_id"].isin(common)].copy()
    common_skips = skips.loc[skips["event_id"].isin(common)].copy()

    summary = build_summary(trades, skips, sample_mode="available")
    common_summary = build_summary(common_trades, common_skips, sample_mode="common")
    subsample = pd.concat(
        [build_subsample(trades, skips, sample_mode="available"), build_subsample(common_trades, common_skips, sample_mode="common")],
        ignore_index=True,
    )
    side = pd.concat([build_side(trades, sample_mode="available"), build_side(common_trades, sample_mode="common")], ignore_index=True)
    counter = filter_counterfactual(skips)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_dir / "weekly_relative_signal_summary.csv", index=False)
    common_summary.to_csv(args.output_dir / "weekly_relative_signal_common_sample_summary.csv", index=False)
    subsample.to_csv(args.output_dir / "weekly_relative_signal_subsample_stats.csv", index=False)
    side.to_csv(args.output_dir / "weekly_relative_signal_side_attribution.csv", index=False)
    skips.to_csv(args.output_dir / "weekly_relative_signal_skip_attribution.csv", index=False)
    trades.to_csv(args.output_dir / "weekly_relative_signal_event_trades.csv", index=False)
    counter.to_csv(args.output_dir / "weekly_relative_signal_filtered_counterfactual.csv", index=False)
    plot_nav(trades, args.output_dir / "weekly_relative_signal_nav.png", candidates_only=False)
    plot_nav(trades, args.output_dir / "weekly_relative_signal_candidate_comparison_nav.png", candidates_only=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines(summary, subsample, counter)), encoding="utf-8")

    print(f"Wrote weekly relative signal outputs: {args.output_dir}")
    print(f"Wrote report: {args.report}")
    print("No daily strategy, continuous NQ, downloads, API calls, or extra thresholds were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
