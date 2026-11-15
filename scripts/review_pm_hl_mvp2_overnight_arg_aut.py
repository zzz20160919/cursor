from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"
DOC_PATH = PROJECT_ROOT / "docs" / "pm_hl_mvp2_overnight_review_arg_aut.md"

TEXT_LOG_PATH = OUTPUT_DIR / "pm_hl_mvp2_overnight_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.log"
JSON_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.json"
CSV_PATH = OUTPUT_DIR / "pm_hl_1v1_moneyline_monitor_fifwc-arg-aut-2026-06-22_20260622_155136.csv"

SUMMARY_CSV_PATH = OUTPUT_DIR / "review_arg_aut_summary.csv"
OP1_SUMMARY_CSV_PATH = OUTPUT_DIR / "review_arg_aut_op1_by_outcome.csv"

UTC8 = timezone(timedelta(hours=8))
MATCH_FINAL_UTC8 = datetime(2026, 6, 23, 3, 22, tzinfo=UTC8)
NEAR_MISS_THRESHOLD = -0.002


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_utc8(value: datetime) -> datetime:
    return value.astimezone(UTC8)


def fmt_dt(value: datetime | None) -> str:
    return value.astimezone(UTC8).strftime("%Y-%m-%d %H:%M:%S UTC+8") if value else ""


def fmt_num(value: Any, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def ffloat(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def read_json() -> dict[str, Any]:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def read_csv_rows() -> list[dict[str, Any]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_log_text() -> str:
    return TEXT_LOG_PATH.read_text(encoding="utf-8", errors="replace")


def warning_summary(payload: dict[str, Any], log_text: str) -> dict[str, Any]:
    snapshots = payload.get("snapshots", [])
    total_iterations = len(snapshots)
    ok_snapshots = [row for row in snapshots if row.get("status") == "ok"]
    warning_snapshots = [row for row in snapshots if row.get("status") == "warning"]
    first_warning = warning_snapshots[0] if warning_snapshots else None
    first_warning_ts = parse_ts(first_warning["timestamp"]) if first_warning else None
    first_warning_iter = int(first_warning["iteration"]) if first_warning else None
    last_good_iter = max((int(row["iteration"]) for row in ok_snapshots), default=None)
    warning_iterations = {int(row["iteration"]) for row in warning_snapshots}
    continuous_after_first = False
    if first_warning_iter is not None:
        continuous_after_first = all(
            iteration in warning_iterations
            for iteration in range(first_warning_iter, total_iterations + 1)
        )
    delta_minutes = None
    if first_warning_ts:
        delta_minutes = (to_utc8(first_warning_ts) - MATCH_FINAL_UTC8).total_seconds() / 60.0
    interpretation = (
        "Warnings start after the reported final time and then continue, which supports a post-final HL lifecycle/question discovery failure explanation."
        if delta_minutes is not None and delta_minutes >= 0 and continuous_after_first
        else "Warnings do not cleanly line up with a continuous post-final failure; inspect raw logs before attributing the cause."
    )
    return {
        "total_iterations": total_iterations,
        "completed_iterations": len(ok_snapshots),
        "total_warnings": len(warning_snapshots),
        "log_warn_count": log_text.count("WARN:"),
        "first_warning_iteration": first_warning_iter,
        "first_warning_timestamp_utc8": fmt_dt(first_warning_ts),
        "last_good_iteration": last_good_iter,
        "warning_ratio": len(warning_snapshots) / total_iterations if total_iterations else 0.0,
        "warnings_continuous_after_first": continuous_after_first,
        "match_final_time_utc8": MATCH_FINAL_UTC8.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "warning_vs_final_time_delta_minutes": delta_minutes,
        "preliminary_interpretation": interpretation,
    }


def op1_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("op_group") != "cross_venue_direct_no_complete_set":
            continue
        out.append(
            {
                **row,
                "ts": parse_ts(row["timestamp"]),
                "ts_utc8": to_utc8(parse_ts(row["timestamp"])),
                "iteration": int(row["iteration"]),
                "gross": ffloat(row.get("gross")),
                "fee": ffloat(row.get("fee")),
                "net": ffloat(row.get("net")),
                "depth": ffloat(row.get("depth")),
                "capacity_usd": ffloat(row.get("capacity_usd")),
            }
        )
    return out


def diagnostic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("op_group") != "single_venue_three_way_sum_diagnostic":
            continue
        sum_ask = ffloat(row.get("sum_ask"))
        sum_bid = ffloat(row.get("sum_bid"))
        out.append(
            {
                **row,
                "ts": parse_ts(row["timestamp"]),
                "ts_utc8": to_utc8(parse_ts(row["timestamp"])),
                "iteration": int(row["iteration"]),
                "venue": row["key"],
                "sum_ask": sum_ask,
                "sum_bid": sum_bid,
                "sum_ask_minus_1": None if sum_ask is None else sum_ask - 1.0,
                "sum_bid_minus_1": None if sum_bid is None else sum_bid - 1.0,
            }
        )
    return out


def top1_by_iteration(op1: list[dict[str, Any]]) -> dict[int, str]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in op1:
        grouped[row["iteration"]].append(row)
    return {
        iteration: max(items, key=lambda row: row["net"] if row["net"] is not None else -999.0)["key"]
        for iteration, items in grouped.items()
    }


def rank_by_iteration(op1: list[dict[str, Any]]) -> dict[int, dict[str, int]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    ranks: dict[int, dict[str, int]] = {}
    for row in op1:
        grouped[row["iteration"]].append(row)
    for iteration, items in grouped.items():
        ordered = sorted(items, key=lambda row: row["net"] if row["net"] is not None else -999.0, reverse=True)
        ranks[iteration] = {row["key"]: rank for rank, row in enumerate(ordered, start=1)}
    return ranks


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def op1_summary(op1: list[dict[str, Any]], top1_counts: Counter[str]) -> list[dict[str, Any]]:
    summary = []
    for outcome in ("Argentina", "Draw", "Austria"):
        rows = [row for row in op1 if row["key"] == outcome]
        nets = [row["net"] for row in rows if row["net"] is not None]
        gross = [row["gross"] for row in rows if row["gross"] is not None]
        fees = [row["fee"] for row in rows if row["fee"] is not None]
        depths = [row["depth"] for row in rows if row["depth"] is not None]
        near = [row for row in rows if row["net"] is not None and row["net"] > NEAR_MISS_THRESHOLD]
        positive = [row for row in rows if row["net"] is not None and row["net"] > 0]
        max_row = max(rows, key=lambda row: row["net"] if row["net"] is not None else -999)
        summary.append(
            {
                "outcome": outcome,
                "max_net": max(nets) if nets else None,
                "max_net_timestamp_utc8": fmt_dt(max_row["ts"]),
                "min_net": min(nets) if nets else None,
                "mean_net": mean(nets),
                "median_net": median(nets),
                "max_gross": max(gross) if gross else None,
                "mean_fee": mean(fees),
                "max_depth": max(depths) if depths else None,
                "near_miss_count": len(near),
                "positive_net_count": len(positive),
                "top1_count": top1_counts[outcome],
            }
        )
    return summary


def top1_explanation(op1: list[dict[str, Any]], top1_counts: Counter[str], ranks: dict[int, dict[str, int]]) -> list[dict[str, Any]]:
    rows_out = []
    for outcome in ("Argentina", "Draw", "Austria"):
        rows = [row for row in op1 if row["key"] == outcome]
        gross = [row["gross"] for row in rows if row["gross"] is not None]
        fees = [row["fee"] for row in rows if row["fee"] is not None]
        nets = [row["net"] for row in rows if row["net"] is not None]
        depths = [row["depth"] for row in rows if row["depth"] is not None]
        outcome_ranks = [rank_map[outcome] for rank_map in ranks.values() if outcome in rank_map]
        rows_out.append(
            {
                "outcome": outcome,
                "top1_count": top1_counts[outcome],
                "avg_rank": mean([float(value) for value in outcome_ranks]),
                "avg_gross": mean(gross),
                "avg_fee": mean(fees),
                "avg_net": mean(nets),
                "avg_depth": mean(depths),
                "main_reason": "",
            }
        )
    best_net = max(rows_out, key=lambda row: row["avg_net"] if row["avg_net"] is not None else -999)
    lowest_fee = min(rows_out, key=lambda row: row["avg_fee"] if row["avg_fee"] is not None else 999)
    for row in rows_out:
        reasons = []
        if row["outcome"] == best_net["outcome"]:
            reasons.append("best average net")
        if row["outcome"] == lowest_fee["outcome"]:
            reasons.append("lowest average fee")
        if row["top1_count"] == max(top1_counts.values()):
            reasons.append("most frequent top1")
        row["main_reason"] = ", ".join(reasons) if reasons else "worse net after gross/fee combination"
    return rows_out


def op4_summary(diag: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_out = []
    for venue in ("polymarket", "hyperliquid"):
        rows = [row for row in diag if row["venue"] == venue]
        pre_rows = [row for row in rows if row["ts_utc8"] <= MATCH_FINAL_UTC8]
        post_rows = [row for row in rows if row["ts_utc8"] > MATCH_FINAL_UTC8]
        ask = [row["sum_ask"] for row in rows if row["sum_ask"] is not None]
        bid = [row["sum_bid"] for row in rows if row["sum_bid"] is not None]
        ask_dev = [row["sum_ask_minus_1"] for row in rows if row["sum_ask_minus_1"] is not None]
        bid_dev = [row["sum_bid_minus_1"] for row in rows if row["sum_bid_minus_1"] is not None]
        pre_ask_dev = [row["sum_ask_minus_1"] for row in pre_rows if row["sum_ask_minus_1"] is not None]
        post_ask_dev = [row["sum_ask_minus_1"] for row in post_rows if row["sum_ask_minus_1"] is not None]
        ask_range = (max(ask_dev) - min(ask_dev)) if ask_dev else None
        comment = (
            "very stable, near constant spread around 1"
            if ask_range is not None and ask_range < 0.003
            else "noticeable movement, inspect time series around final"
        )
        rows_out.append(
            {
                "venue": venue,
                "mean_sum_ask": mean(ask),
                "mean_sum_bid": mean(bid),
                "mean_sum_ask_minus_1": mean(ask_dev),
                "mean_sum_bid_minus_1": mean(bid_dev),
                "pre_final_mean_sum_ask_minus_1": mean(pre_ask_dev),
                "post_final_mean_sum_ask_minus_1": mean(post_ask_dev),
                "min_sum_ask_minus_1": min(ask_dev) if ask_dev else None,
                "max_sum_ask_minus_1": max(ask_dev) if ask_dev else None,
                "stability_comment": comment,
            }
        )
    return rows_out


def utc8_axis(ax: Any) -> None:
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=UTC8))
    ax.tick_params(axis="x", rotation=30)


def save_warning_plot(payload: dict[str, Any], path: Path) -> None:
    snapshots = payload.get("snapshots", [])
    xs = [to_utc8(parse_ts(row["timestamp"])) for row in snapshots]
    flags = [1 if row.get("status") == "warning" else 0 for row in snapshots]
    cumulative = []
    count = 0
    for flag in flags:
        count += flag
        cumulative.append(count)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(xs, cumulative, label="Cumulative warnings")
    ax.axvline(MATCH_FINAL_UTC8, linestyle="--", label="Match final 03:22 UTC+8")
    ax.set_title("Warning Timeline")
    ax.set_xlabel("Time (UTC+8)")
    ax.set_ylabel("Cumulative warnings (count)")
    ax.legend()
    utc8_axis(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_op1_net_plot(op1: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for outcome in ("Argentina", "Draw", "Austria"):
        rows = [row for row in op1 if row["key"] == outcome]
        ax.plot([row["ts_utc8"] for row in rows], [row["net"] for row in rows], label=outcome)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(NEAR_MISS_THRESHOLD, linestyle="--", linewidth=0.8, label=f"near-miss {NEAR_MISS_THRESHOLD}")
    ax.set_title("op1 Net Time Series by Outcome")
    ax.set_xlabel("Time (UTC+8)")
    ax.set_ylabel("Net edge (USD per complete-set unit)")
    ax.legend()
    utc8_axis(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_top1_plot(top1_counts: Counter[str], path: Path) -> None:
    outcomes = ["Argentina", "Draw", "Austria"]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(outcomes, [top1_counts[outcome] for outcome in outcomes])
    ax.set_title("Top1 Outcome Distribution")
    ax.set_xlabel("Outcome")
    ax.set_ylabel("Top1 count (iterations)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_op4_plot(diag: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for venue in ("polymarket", "hyperliquid"):
        rows = [row for row in diag if row["venue"] == venue]
        ax.plot([row["ts_utc8"] for row in rows], [row["sum_ask_minus_1"] for row in rows], label=f"{venue} ask-1")
        ax.plot([row["ts_utc8"] for row in rows], [row["sum_bid_minus_1"] for row in rows], linestyle="--", label=f"{venue} bid-1")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(MATCH_FINAL_UTC8, linestyle=":", label="Match final 03:22 UTC+8")
    ax.set_title("PM vs HL Three-Way Sum Diagnostics")
    ax.set_xlabel("Time (UTC+8)")
    ax.set_ylabel("Deviation from 1 (USD)")
    ax.legend(ncol=2)
    utc8_axis(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_gross_fee_plot(summary: list[dict[str, Any]], path: Path) -> None:
    outcomes = [row["outcome"] for row in summary]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(outcomes))
    ax.bar([v - 0.2 for v in x], [row["max_gross"] for row in summary], width=0.4, label="Best gross")
    ax.bar([v + 0.2 for v in x], [row["mean_fee"] for row in summary], width=0.4, label="Mean fee")
    ax.set_xticks(list(x), outcomes)
    ax.set_title("op1 Gross vs Fee Decomposition")
    ax.set_xlabel("Outcome")
    ax.set_ylabel("USD per complete-set unit")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_depth_plot(op1: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for outcome in ("Argentina", "Draw", "Austria"):
        rows = [row for row in op1 if row["key"] == outcome]
        ax.plot([row["ts_utc8"] for row in rows], [row["depth"] for row in rows], label=outcome)
    ax.set_title("op1 Depth Time Series by Outcome")
    ax.set_xlabel("Time (UTC+8)")
    ax.set_ylabel("Top-of-book depth (shares)")
    ax.legend()
    utc8_axis(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt_num(row.get(col)) for col in columns) + " |")
    return "\n".join(lines)


def write_summary_csv(warn: dict[str, Any], top1: list[dict[str, Any]], op4: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for key, value in warn.items():
        rows.append({"table": "warning_summary", "entity": "all", "metric": key, "value": value})
    for row in top1:
        for key, value in row.items():
            if key != "outcome":
                rows.append({"table": "top1_ranking_explanation", "entity": row["outcome"], "metric": key, "value": value})
    for row in op4:
        for key, value in row.items():
            if key != "venue":
                rows.append({"table": "op4_venue_structure", "entity": row["venue"], "metric": key, "value": value})
    write_dict_csv(SUMMARY_CSV_PATH, rows)


def write_report(
    warn: dict[str, Any],
    op1_sum: list[dict[str, Any]],
    top1_expl: list[dict[str, Any]],
    op4_sum: list[dict[str, Any]],
    chart_paths: dict[str, Path],
) -> None:
    first_warning = warn.get("first_warning_timestamp_utc8") or "none"
    first_warning_iter = warn.get("first_warning_iteration")
    delta = warn.get("warning_vs_final_time_delta_minutes")
    delta_text = f"{delta:.1f} minutes" if isinstance(delta, float) else "n/a"
    top_row = max(top1_expl, key=lambda row: row["top1_count"])
    top_outcome = top_row["outcome"]
    closest = max(op1_sum, key=lambda row: row["max_net"] if row["max_net"] is not None else -999)
    positive_counts = {row["outcome"]: row.get("positive_net_count", 0) for row in op1_sum}
    report = f"""# PM-HL MVP2 Overnight Review: Argentina vs Austria

## Conclusions First

- Warnings began at **{first_warning}**, iteration **{first_warning_iter}**, about **{delta_text}** after the referenced final time of **2026-06-23 03:22:00 UTC+8**.
- The warnings are continuous after they start, supporting the explanation that post-final HL lifecycle/question discovery stopped returning the expected sample structure.
- For op1, **{closest['outcome']}** came closest to zero by max net and had the strongest positive spike; **{top_outcome}** was the most frequent top1, but only by a small margin over Argentina.
- op1 had positive net rows before final: `{positive_counts}`. These are monitoring rows, not execution records.
- PM ask stayed above 1 and was relatively steady before final, but PM post-final `sum_ask` became unavailable in the flat CSV. HL ask was somewhat farther above 1 before final, then moved closer to 1 post-final.

## Table 1: Warning Summary

{md_table([warn], ['total_iterations', 'completed_iterations', 'total_warnings', 'first_warning_iteration', 'first_warning_timestamp_utc8', 'last_good_iteration', 'warning_ratio', 'match_final_time_utc8', 'warning_vs_final_time_delta_minutes', 'preliminary_interpretation'])}

## Table 2: op1 by Outcome Summary

Near-miss threshold: `net > {NEAR_MISS_THRESHOLD}`.

{md_table(op1_sum, ['outcome', 'max_net', 'max_net_timestamp_utc8', 'min_net', 'mean_net', 'median_net', 'max_gross', 'mean_fee', 'max_depth', 'near_miss_count', 'positive_net_count', 'top1_count'])}

## Table 3: Top1 Ranking Explanation

{md_table(top1_expl, ['outcome', 'top1_count', 'avg_rank', 'avg_gross', 'avg_fee', 'avg_net', 'avg_depth', 'main_reason'])}

## Table 4: op4 Venue Structure Summary

{md_table(op4_sum, ['venue', 'mean_sum_ask', 'mean_sum_bid', 'mean_sum_ask_minus_1', 'mean_sum_bid_minus_1', 'pre_final_mean_sum_ask_minus_1', 'post_final_mean_sum_ask_minus_1', 'min_sum_ask_minus_1', 'max_sum_ask_minus_1', 'stability_comment'])}

## Charts

![Warning timeline]({chart_paths['warning'].as_posix()})

![op1 net time series]({chart_paths['op1_net'].as_posix()})

![Top1 distribution]({chart_paths['top1'].as_posix()})

![op4 structure]({chart_paths['op4'].as_posix()})

![Gross vs fee]({chart_paths['gross_fee'].as_posix()})

![Depth time series]({chart_paths['depth'].as_posix()})

## Interpretation

### 1. Warning timing

The monitor has two phases: a normal phase with usable op1/op4 rows, then a warning phase. The first warning starts after the reported final time, and warnings continue afterward. That supports the post-final lifecycle hypothesis: the market outcome metadata or question discovery path no longer matched the pre-final structure.

### 2. op1 near-miss behavior

The closest-to-action periods are where op1 net is highest. Argentina had the strongest positive net spike around its max timestamp; Austria had the most near-miss rows and the best average net. These are top-of-book monitor rows only, not proof that a complete live execution would have filled.

### 3. Why Austria was often top1

Austria's advantage is mostly fee plus steadier net: its relevant PM leg often carried a lower PM quadratic fee, and its average net was less negative. It was top1 most often, but the count was close to Argentina, so this is a plurality rather than overwhelming dominance. Depth was not the main source of the ranking; it mainly affected capacity.

### 4. op4 structure

PM ask-side three-way sum was stable around a positive spread before final, but PM post-final ask diagnostics are blank in the flat CSV. HL ask-side sum was farther above 1 before final and closer to 1 after final. Bid-side sums stayed below or near 1, consistent with spread rather than an executable single-venue strategy in this MVP2 scope.

## Source Files

- JSON: `{JSON_PATH}`
- CSV: `{CSV_PATH}`
- TEXT_LOG: `{TEXT_LOG_PATH}`
"""
    DOC_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    payload = read_json()
    csv_rows = read_csv_rows()
    log_text = read_log_text()
    warn = warning_summary(payload, log_text)
    op1 = op1_rows(csv_rows)
    diag = diagnostic_rows(csv_rows)
    top1_map = top1_by_iteration(op1)
    top1_counts = Counter(top1_map.values())
    ranks = rank_by_iteration(op1)
    op1_sum = op1_summary(op1, top1_counts)
    top1_expl = top1_explanation(op1, top1_counts, ranks)
    op4_sum = op4_summary(diag)

    chart_paths = {
        "warning": OUTPUT_DIR / "review_arg_aut_warning_timeline.png",
        "op1_net": OUTPUT_DIR / "review_arg_aut_op1_net_timeseries.png",
        "top1": OUTPUT_DIR / "review_arg_aut_top1_distribution.png",
        "op4": OUTPUT_DIR / "review_arg_aut_op4_structure.png",
        "gross_fee": OUTPUT_DIR / "review_arg_aut_gross_fee.png",
        "depth": OUTPUT_DIR / "review_arg_aut_depth_timeseries.png",
    }
    save_warning_plot(payload, chart_paths["warning"])
    save_op1_net_plot(op1, chart_paths["op1_net"])
    save_top1_plot(top1_counts, chart_paths["top1"])
    save_op4_plot(diag, chart_paths["op4"])
    save_gross_fee_plot(op1_sum, chart_paths["gross_fee"])
    save_depth_plot(op1, chart_paths["depth"])

    write_summary_csv(warn, top1_expl, op4_sum)
    write_dict_csv(OP1_SUMMARY_CSV_PATH, op1_sum)
    write_report(warn, op1_sum, top1_expl, op4_sum, chart_paths)

    print(f"Markdown: {DOC_PATH}")
    print(f"Summary CSV: {SUMMARY_CSV_PATH}")
    print(f"op1 CSV: {OP1_SUMMARY_CSV_PATH}")
    for key, path in chart_paths.items():
        print(f"{key}: {path}")
    print(
        "Warning summary:",
        warn["total_iterations"],
        warn["completed_iterations"],
        warn["total_warnings"],
        warn["first_warning_timestamp_utc8"],
    )


if __name__ == "__main__":
    main()

