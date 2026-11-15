#!/usr/bin/env python3
"""Three Step 3 scenarios. Does not rewrite the official Step 3 files.

Official remains 7-class, N=5, no weight cap. These scenarios use the same
panel, the frozen 12-class assignments, and the same portfolio rule.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_category12_sensitivity import load_panel  # noqa: E402
from build_step3 import CHARACTERISTICS, PAPER, newey_west_t  # noqa: E402
from build_step3_min_n_sensitivity import portfolios_min_bucket  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
ASSIGNMENTS = OUT / "category12_assignments.csv"
OFFICIAL = OUT / "step3_spreads.csv"
PRIOR = OUT / "step3_category12_sensitivity.csv"
TABLE = OUT / "step3_scenarios.csv"
REPORT = OUT / "STEP3_SCENARIOS.md"

SCENARIOS = (
    ("7-class N=10", "7-class", "category_7", 10),
    ("12-class N=5", "12-class", "category_12", 5),
    ("12-class N=10", "12-class", "category_12", 10),
)

YESMV_KNOWN = {
    "7-class N=10": (653, 0.057096, -0.044906, -0.102002, -3.3078),
    "12-class N=5": (663, 0.073707, -0.025764, -0.099470, -2.7075),
    "12-class N=10": (644, 0.062894, -0.010553, -0.073446, -1.7672),
}

COMPARE = ("YESMV", "LOR(1)", "LOR(2)", "LOR(3)", "LOR(4)", "LOR(5)", "LOR(6)")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_assignments() -> dict[str, str]:
    if not ASSIGNMENTS.exists():
        raise SystemExit(f"missing frozen assignments {ASSIGNMENTS}")
    found = {}
    for row in read_csv(ASSIGNMENTS):
        found[row["market_id"]] = row["category_12"]
    if not found:
        raise SystemExit("frozen category12 assignments are empty")
    return found


def run_one(grouped: dict[Any, list[dict[str, Any]]], field: str, minimum: int) -> dict[str, dict[str, Any]]:
    series: dict[str, list[dict[str, float]]] = {label: [] for _key, label in CHARACTERISTICS}
    for day in sorted(grouped):
        members = grouped[day]
        for key, label in CHARACTERISTICS:
            usable = []
            for member in members:
                value = member[key]
                if value is None:
                    continue
                usable.append(
                    {
                        "category": member[field],
                        "x": float(value),
                        "oi": member["oi"],
                        "r": member["r"],
                    }
                )
            result = portfolios_min_bucket(usable, minimum)
            if result is None:
                continue
            series[label].append(
                {
                    "low": result["low"] * 100,
                    "middle": result["middle"] * 100,
                    "high": result["high"] * 100,
                    "high_minus_low": result["high_minus_low"] * 100,
                }
            )
    out = {}
    for _key, label in CHARACTERISTICS:
        rows = series[label]
        count = len(rows)
        if count == 0:
            raise SystemExit(f"{field} N={minimum} {label} has no dates")
        spreads = [row["high_minus_low"] for row in rows]
        out[label] = {
            "n_dates": count,
            "mean_low_cents": sum(row["low"] for row in rows) / count,
            "mean_middle_cents": sum(row["middle"] for row in rows) / count,
            "mean_high_cents": sum(row["high"] for row in rows) / count,
            "mean_high_minus_low_cents": sum(spreads) / count,
            "newey_west_t_lag7": newey_west_t(spreads, 7),
        }
    return out


def close_enough(got: float, expected: float, tolerance: float) -> bool:
    return abs(got - expected) <= tolerance


def check_official(recomputed: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    official = {row["characteristic"]: row for row in read_csv(OFFICIAL)}
    for _key, label in CHARACTERISTICS:
        stats = recomputed[label]
        prior = official[label]
        if stats["n_dates"] != int(prior["n_dates"]):
            raise SystemExit(f"official {label} dates {stats['n_dates']} != {prior['n_dates']}")
        for name, column in (
            ("mean_low_cents", "mean_low_cents"),
            ("mean_high_cents", "mean_high_cents"),
            ("mean_high_minus_low_cents", "mean_high_minus_low_cents"),
        ):
            if not close_enough(stats[name], float(prior[column]), 5e-4):
                raise SystemExit(f"official {label} {name} {stats[name]} != {prior[column]}")
        got_t = stats["newey_west_t_lag7"]
        if got_t is None or not close_enough(got_t, float(prior["newey_west_t_lag7"]), 5e-4):
            raise SystemExit(f"official {label} t {got_t} != {prior['newey_west_t_lag7']}")
    return official


def check_yesmv(results: dict[str, dict[str, dict[str, Any]]]) -> None:
    for name, (n_dates, low, high, spread, t_stat) in YESMV_KNOWN.items():
        row = results[name]["YESMV"]
        if row["n_dates"] != n_dates:
            raise SystemExit(f"{name} YESMV dates {row['n_dates']} != {n_dates}")
        for label, got, expected in (
            ("low", row["mean_low_cents"], low),
            ("high", row["mean_high_cents"], high),
            ("high-low", row["mean_high_minus_low_cents"], spread),
        ):
            if not close_enough(got, expected, 5e-4):
                raise SystemExit(f"{name} YESMV {label} {got:.6f} != {expected:.6f}")
        got_t = row["newey_west_t_lag7"]
        if got_t is None or not close_enough(got_t, t_stat, 5e-4):
            raise SystemExit(f"{name} YESMV t {got_t} != {t_stat}")


def check_prior(results: dict[str, dict[str, dict[str, Any]]]) -> None:
    """The other factors must match the existing category comparison."""
    prior = {
        (row["taxonomy"], row["rule"], row["characteristic"]): row
        for row in read_csv(PRIOR)
    }
    for scenario, taxonomy, _field, minimum in SCENARIOS:
        rule = f"N={minimum}"
        for _key, label in CHARACTERISTICS:
            old = prior[(taxonomy, rule, label)]
            stats = results[scenario][label]
            if stats["n_dates"] != int(old["n_dates"]):
                raise SystemExit(f"{scenario} {label} dates changed")
            for name, column in (
                ("mean_low_cents", "mean_low_cents"),
                ("mean_high_cents", "mean_high_cents"),
                ("mean_high_minus_low_cents", "mean_high_minus_low_cents"),
            ):
                if not close_enough(stats[name], float(old[column]), 5e-4):
                    raise SystemExit(f"{scenario} {label} {name} changed from {old[column]}")
            got_t = stats["newey_west_t_lag7"]
            if got_t is None or not close_enough(got_t, float(old["newey_west_t_lag7"]), 5e-4):
                raise SystemExit(f"{scenario} {label} t changed")


def num(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}"


def signed(value: float, digits: int = 6) -> str:
    return f"{value:+.{digits}f}"


def write_table(rows: list[dict[str, Any]]) -> None:
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def scenario_rows(results: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for scenario, taxonomy, _field, minimum in SCENARIOS:
        for _key, label in CHARACTERISTICS:
            stats = results[scenario][label]
            t_stat = stats["newey_west_t_lag7"]
            rows.append(
                {
                    "row_kind": "scenario",
                    "scenario": scenario,
                    "taxonomy": taxonomy,
                    "min_n": minimum,
                    "characteristic": label,
                    "n_dates": stats["n_dates"],
                    "mean_low_cents": num(stats["mean_low_cents"]),
                    "mean_high_cents": num(stats["mean_high_cents"]),
                    "mean_high_minus_low_cents": num(stats["mean_high_minus_low_cents"]),
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                }
            )
    return rows


def comparison_rows(
    results: dict[str, dict[str, dict[str, Any]]],
    official: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for label in COMPARE:
        prior = official[label]
        rows.append(
            {
                "row_kind": "comparison",
                "scenario": "official 7-class N=5",
                "taxonomy": "7-class",
                "min_n": 5,
                "characteristic": label,
                "n_dates": prior["n_dates"],
                "mean_low_cents": prior["mean_low_cents"],
                "mean_high_cents": prior["mean_high_cents"],
                "mean_high_minus_low_cents": prior["mean_high_minus_low_cents"],
                "newey_west_t_lag7": prior["newey_west_t_lag7"],
            }
        )
        for scenario, taxonomy, _field, minimum in SCENARIOS:
            stats = results[scenario][label]
            t_stat = stats["newey_west_t_lag7"]
            rows.append(
                {
                    "row_kind": "comparison",
                    "scenario": scenario,
                    "taxonomy": taxonomy,
                    "min_n": minimum,
                    "characteristic": label,
                    "n_dates": stats["n_dates"],
                    "mean_low_cents": num(stats["mean_low_cents"]),
                    "mean_high_cents": num(stats["mean_high_cents"]),
                    "mean_high_minus_low_cents": num(stats["mean_high_minus_low_cents"]),
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                }
            )
        paper = PAPER[label]
        rows.append(
            {
                "row_kind": "comparison",
                "scenario": "IA.15",
                "taxonomy": "",
                "min_n": "",
                "characteristic": label,
                "n_dates": "",
                "mean_low_cents": f"{paper['low']:.3f}",
                "mean_high_cents": f"{paper['high']:.3f}",
                "mean_high_minus_low_cents": f"{paper['hl']:.3f}",
                "newey_west_t_lag7": f"{paper['t']:.2f}",
            }
        )
    return rows


def markdown_table(headers: list[str], body: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" if index < 2 else "---:" for index, _header in enumerate(headers)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render(
    results: dict[str, dict[str, dict[str, Any]]],
    official: dict[str, dict[str, str]],
) -> str:
    yes = official["YESMV"]
    lines = [
        "# 第三步情景",
        "",
        "这三组不覆盖官方 Step 3。官方仍是 7 类、N=5、无权重上限。",
        (
            f"官方 YESMV：{yes['n_dates']} 天，Low {signed(float(yes['mean_low_cents']))}，"
            f"High {signed(float(yes['mean_high_cents']))}，"
            f"High−Low {signed(float(yes['mean_high_minus_low_cents']))}，"
            f"t {float(yes['newey_west_t_lag7']):.4f}。"
        ),
        "同一 Step 2 面板，12 类用冻结的 `category12_assignments.csv`。没有重跑价格或持仓，也没有重拉 Gamma。",
        "N 是每个 formation_date×category 里 Low 和 High 各至少 N 个不同市场；任一不足则该类别日剔除，两腿使用共同类别集。没有权重上限。",
        "其余与官方相同：1% / 99% winsorize，30% / 70% 分位只决定成员身份，raw open interest 两阶段加权，下一期 YES 价格变动（美分/张），Newey–West 滞后 7 期。",
        "",
    ]
    for scenario, _taxonomy, _field, _minimum in SCENARIOS:
        lines.extend(
            [
                f"## {scenario}",
                "",
                *markdown_table(
                    ["特征", "天数", "Low", "High", "H−L", "t"],
                    [
                        [
                            label,
                            str(results[scenario][label]["n_dates"]),
                            signed(results[scenario][label]["mean_low_cents"]),
                            signed(results[scenario][label]["mean_high_cents"]),
                            signed(results[scenario][label]["mean_high_minus_low_cents"]),
                            f"{results[scenario][label]['newey_west_t_lag7']:.4f}",
                        ]
                        for _key, label in CHARACTERISTICS
                    ],
                ),
                "",
            ]
        )
    compare_body = []
    for label in COMPARE:
        prior = official[label]
        compare_body.append(
            [
                "官方 7 类 N=5",
                label,
                prior["n_dates"],
                signed(float(prior["mean_low_cents"])),
                signed(float(prior["mean_high_cents"])),
                signed(float(prior["mean_high_minus_low_cents"])),
                f"{float(prior['newey_west_t_lag7']):.4f}",
            ]
        )
        for scenario, _taxonomy, _field, _minimum in SCENARIOS:
            stats = results[scenario][label]
            compare_body.append(
                [
                    scenario,
                    label,
                    str(stats["n_dates"]),
                    signed(stats["mean_low_cents"]),
                    signed(stats["mean_high_cents"]),
                    signed(stats["mean_high_minus_low_cents"]),
                    f"{stats['newey_west_t_lag7']:.4f}",
                ]
            )
        paper = PAPER[label]
        compare_body.append(
            [
                "IA.15",
                label,
                "",
                signed(paper["low"], 3),
                signed(paper["high"], 3),
                signed(paper["hl"], 3),
                f"{paper['t']:.2f}",
            ]
        )
    lines.extend(
        [
            "## 对照",
            "",
            "论文 IA.15 没有披露天数。LOR 的论文 High−Low 依次是 −0.725、−0.603、−0.538、−0.553、−0.566、−0.501。",
            "",
            *markdown_table(["情景", "特征", "天数", "Low", "High", "H−L", "t"], compare_body),
            "",
            "YESMV 三组与已有敏感性数字一致：7 类 N=10 为 653 天、H−L −0.102002、t −3.3078；12 类 N=5 为 663 天、H−L −0.099470、t −2.7075；12 类 N=10 为 644 天、H−L −0.073446、t −1.7672。",
            "三组 YESMV 的 High−Low 都在 −0.07 到 −0.10，方向与论文相同，幅度仍小于论文的 −0.255。LOR 的 High−Low 仍远小于论文。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if not OFFICIAL.exists() or not PRIOR.exists():
        raise SystemExit("missing official Step 3 or the existing category comparison")
    assignments = load_assignments()
    grouped = load_panel(assignments)
    print("check official 7-class N=5", flush=True)
    official_again = run_one(grouped, "category_7", 5)
    official = check_official(official_again)
    results = {}
    for scenario, _taxonomy, field, minimum in SCENARIOS:
        print(f"scenario {scenario}", flush=True)
        results[scenario] = run_one(grouped, field, minimum)
    check_yesmv(results)
    check_prior(results)
    rows = scenario_rows(results) + comparison_rows(results, official)
    write_table(rows)
    REPORT.write_text(render(results, official), encoding="utf-8")
    print(f"wrote {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
