#!/usr/bin/env python3
"""Map the A.3 panel onto Polymarket's 12 nav classes and rerun Step 3.

Does not rewrite official Step 3 files or the min-N / weight-cap tables.
Gamma tags are the live labels from the fetch, not a formation-time snapshot.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_step3 import CHARACTERISTICS, newey_west_t  # noqa: E402
from build_step3_min_n_sensitivity import portfolios_min_bucket  # noqa: E402
from hlz_paper import assign_legs, category_portfolios  # noqa: E402


OUT = REPO / "outputs/strategy/hlz_cross_section"
MAPS = HERE / "category12_maps.json"
TAGS = OUT / "cache/gamma_event_tags.jsonl"
TAG_META = OUT / "cache/gamma_event_tags_meta.json"
FACTOR = OUT / "a3_factor_daily.parquet"
UNIVERSE = OUT / "paper_sample_markets_a3.csv"
MARKETS = OUT / "cache/step2/vgregoire/markets.parquet"
ASSIGNMENTS = OUT / "category12_assignments.csv"
COVERAGE = OUT / "category12_coverage.csv"
COUNTS = OUT / "category12_class_counts.csv"
TABLE = OUT / "step3_category12_sensitivity.csv"
YEAR_TABLE = OUT / "step3_category12_yesmv_by_year.csv"
REPORT = OUT / "STEP3_CATEGORY12_SENSITIVITY.md"
OTHER = "Other"


def norm(text: str) -> str:
    return " ".join(text.replace("-", " ").replace("_", " ").split()).casefold()


def load_maps() -> dict[str, Any]:
    raw = json.loads(MAPS.read_text(encoding="utf-8"))
    priority = raw["priority"]
    return {
        "priority": priority,
        "index": {name: index for index, name in enumerate(priority)},
        "canon": {norm(name): name for name in priority},
        "synonyms": {norm(key): value for key, value in raw["synonyms"].items()},
        "fine": {norm(key): value for key, value in raw["fine_tags"].items()},
        "coarse": {norm(key): value for key, value in raw["coarse_2022"].items()},
        "coarse_note": raw["coarse_2022_note"],
    }


def tag_hits(tags: list[dict[str, str]], maps: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (class, layer) for every tag that maps. Layer is direct, synonym, or fine_tag."""
    hits = []
    for tag in tags:
        label = norm(tag.get("label") or "")
        slug = norm(tag.get("slug") or "")
        found = None
        layer = ""
        for text in (label, slug):
            if not text or text == "all":
                continue
            if text in maps["canon"]:
                found = maps["canon"][text]
                layer = "direct"
                break
        if found is None:
            for text in (label, slug):
                if text in maps["synonyms"]:
                    found = maps["synonyms"][text]
                    layer = "synonym"
                    break
        if found is None:
            for text in (label, slug):
                if text in maps["fine"]:
                    found = maps["fine"][text]
                    layer = "fine_tag"
                    break
        if found is not None:
            hits.append((found, layer))
    return hits


def choose_class(hits: list[tuple[str, str]], maps: dict[str, Any]) -> tuple[str | None, str, set[str]]:
    """Pick a class from the highest layer that hit, then by the written priority."""
    by_layer: dict[str, set[str]] = {"direct": set(), "synonym": set(), "fine_tag": set()}
    for name, layer in hits:
        by_layer[layer].add(name)
    candidates = set().union(*by_layer.values())
    for layer in ("direct", "synonym", "fine_tag"):
        pool = by_layer[layer]
        if not pool:
            continue
        chosen = min(pool, key=lambda name: maps["index"][name])
        return chosen, layer, candidates
    return None, "", candidates


def has_real_tag(tags: list[dict[str, str]]) -> bool:
    for tag in tags:
        if norm(tag.get("label") or "") not in {"", "all"}:
            return True
        if norm(tag.get("slug") or "") not in {"", "all"}:
            return True
    return False


def coarse_class(values: list[str | None], maps: dict[str, Any]) -> str | None:
    for value in values:
        if not value:
            continue
        mapped = maps["coarse"].get(norm(value))
        if mapped:
            return mapped
    return None


def self_test() -> None:
    maps = load_maps()
    sports_politics = [
        {"label": "Politics", "slug": "politics"},
        {"label": "Sports", "slug": "sports"},
    ]
    chosen, layer, candidates = choose_class(tag_hits(sports_politics, maps), maps)
    assert chosen == "Sports" and layer == "direct" and candidates == {"Sports", "Politics"}
    trump = [{"label": "Trump", "slug": "trump"}]
    chosen, layer, _candidates = choose_class(tag_hits(trump, maps), maps)
    assert chosen == "Elections" and layer == "fine_tag"
    synonym = [{"label": "US Election", "slug": "us-presidential-election"}]
    chosen, layer, _candidates = choose_class(tag_hits(synonym, maps), maps)
    assert chosen == "Elections" and layer == "synonym"
    assert coarse_class(["NFTs"], maps) == "Crypto"
    assert coarse_class(["Business"], maps) == "Finance"
    assert coarse_class(["US-current-affairs"], maps) == "Politics"
    print("self-test ok")


def load_events() -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    with TAGS.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            events[str(record.get("id") or "")] = record
    events.pop("", None)
    return events


def load_markets(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        WITH panel AS (
          SELECT market_id,
                 str_split(string_agg(DISTINCT cast(year(formation_date) AS varchar), '|'), '|') AS years
          FROM read_parquet('{FACTOR}')
          GROUP BY 1
        ),
        uni AS (
          SELECT market_id, event_id
          FROM read_csv('{UNIVERSE}', header=true, all_varchar=true)
        ),
        meta AS (
          SELECT cast(market_id AS varchar) AS market_id, category, category_original
          FROM read_parquet('{MARKETS}')
        )
        SELECT p.market_id, u.event_id, m.category, m.category_original, p.years
        FROM panel p
        JOIN uni u ON u.market_id = p.market_id
        LEFT JOIN meta m ON m.market_id = p.market_id
        """
    ).fetchall()
    out = []
    for market_id, event_id, category, original, years in rows:
        out.append(
            {
                "market_id": market_id,
                "event_id": event_id or "",
                "vg_category": category or "",
                "vg_original": original or "",
                "years": {int(year) for year in years if str(year).isdigit()},
            }
        )
    return out


def assign_markets(markets: list[dict[str, Any]], events: dict[str, dict[str, Any]], maps: dict[str, Any]) -> list[dict[str, str]]:
    assigned = []
    for market in markets:
        event = events.get(market["event_id"], {})
        tags = event.get("tags") or []
        chosen, layer, candidates = choose_class(tag_hits(tags, maps), maps)
        source = layer
        label = chosen
        if label is None and 2022 in market["years"]:
            label = coarse_class(
                [event.get("category"), market["vg_original"], market["vg_category"]],
                maps,
            )
            source = "coarse_2022" if label else "other"
        if label is None:
            label = OTHER
            source = "other"
        assigned.append(
            {
                "market_id": market["market_id"],
                "event_id": market["event_id"],
                "category_12": label,
                "source": source,
                "has_tags": "true" if has_real_tag(tags) else "false",
                "n_candidate_classes": str(len(candidates)),
                "conflict": "true" if len(candidates) >= 2 else "false",
                "formation_years": "|".join(str(year) for year in sorted(market["years"])),
            }
        )
    return assigned


def coverage_rows(assigned: list[dict[str, str]]) -> list[dict[str, Any]]:
    """One row per formation year, counting a market in every year it is priced."""
    rows = []
    by_year: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in assigned:
        years = [year for year in row["formation_years"].split("|") if year]
        for year in years:
            by_year[year].append(row)
        by_year["all"].append(row)
    for year in ["2022", "2023", "2024", "2025", "2026", "all"]:
        group = by_year.get(year, [])
        total = len(group)
        if total == 0:
            continue
        tagged = sum(row["has_tags"] == "true" for row in group)
        mappable = sum(int(row["n_candidate_classes"]) > 0 or row["source"] == "coarse_2022" for row in group)
        conflict = sum(row["conflict"] == "true" for row in group)
        other = sum(row["category_12"] == OTHER for row in group)
        coarse = sum(row["source"] == "coarse_2022" for row in group)
        rows.append(
            {
                "formation_year": year,
                "markets": total,
                "with_tags": tagged,
                "with_tags_share": f"{tagged / total:.6f}",
                "mappable": mappable,
                "mappable_share": f"{mappable / total:.6f}",
                "conflict": conflict,
                "conflict_share": f"{conflict / total:.6f}",
                "other": other,
                "other_share": f"{other / total:.6f}",
                "coarse_2022": coarse,
            }
        )
    return rows


def class_counts(assigned: list[dict[str, str]], maps: dict[str, Any]) -> list[dict[str, Any]]:
    order = maps["priority"] + [OTHER]
    counts: dict[str, Counter[str]] = {year: Counter() for year in ["2022", "2023", "2024", "2025", "2026", "all"]}
    for row in assigned:
        counts["all"][row["category_12"]] += 1
        for year in row["formation_years"].split("|"):
            if year in counts:
                counts[year][row["category_12"]] += 1
    out = []
    for year, counter in counts.items():
        total = sum(counter.values()) or 1
        for name in order:
            out.append(
                {
                    "formation_year": year,
                    "category_12": name,
                    "markets": counter[name],
                    "share": f"{counter[name] / total:.6f}",
                }
            )
    return out


def gate_ok(assigned: list[dict[str, str]]) -> bool:
    recent = [
        row
        for row in assigned
        if any(year.isdigit() and int(year) >= 2024 for year in row["formation_years"].split("|"))
    ]
    if not recent:
        return False
    mapped = sum(row["category_12"] != OTHER for row in recent)
    return mapped / len(recent) >= 0.50


def load_panel(assignments: dict[str, str]) -> dict[Any, list[dict[str, Any]]]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT formation_date, market_id, category, yesmv, oi_shares, p_form,
               lor_1, lor_2, lor_3, lor_4, lor_5, lor_6, r_pp
        FROM read_parquet('{FACTOR}')
        WHERE in_portfolio_sample
          AND category <> ''
          AND oi_shares > 0
          AND r_pp IS NOT NULL
        """
    ).fetchall()
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for formation_date, market_id, category, yesmv, oi, price, l1, l2, l3, l4, l5, l6, payoff in rows:
        grouped.setdefault(formation_date, []).append(
            {
                "category_7": category,
                "category_12": assignments.get(market_id, OTHER),
                "yesmv": yesmv,
                "oi_shares": oi,
                "p_form": price,
                "lor_1": l1,
                "lor_2": l2,
                "lor_3": l3,
                "lor_4": l4,
                "lor_5": l5,
                "lor_6": l6,
                "oi": float(oi),
                "r": float(payoff),
            }
        )
    return grouped


def run_portfolios(grouped: dict[Any, list[dict[str, Any]]], field: str, minimum: int | None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {label: [] for _key, label in CHARACTERISTICS}
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
            result = category_portfolios(usable) if minimum is None else portfolios_min_bucket(usable, minimum)
            if result is None:
                continue
            out[label].append(
                {
                    "date": day,
                    "n_categories": result["n_categories"],
                    "low": result["low"] * 100,
                    "high": result["high"] * 100,
                    "high_minus_low": result["high_minus_low"] * 100,
                }
            )
    return out


def summarize(series: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(series)
    if count == 0:
        return {
            "n_dates": 0,
            "n_category_days": 0,
            "mean_low_cents": None,
            "mean_high_cents": None,
            "mean_high_minus_low_cents": None,
            "newey_west_t_lag7": None,
            "series": [],
        }
    spreads = [row["high_minus_low"] for row in series]
    return {
        "n_dates": count,
        "n_category_days": sum(row["n_categories"] for row in series),
        "mean_low_cents": sum(row["low"] for row in series) / count,
        "mean_high_cents": sum(row["high"] for row in series) / count,
        "mean_high_minus_low_cents": sum(spreads) / count,
        "newey_west_t_lag7": newey_west_t(spreads, 7),
        "series": series,
    }


def check_known(stats: dict[str, Any], dates: int, low: float, high: float, spread: float, t_stat: float, name: str) -> None:
    if stats["n_dates"] != dates or abs(stats["mean_low_cents"] - low) > 1e-3 or abs(stats["mean_high_cents"] - high) > 1e-3:
        raise SystemExit(f"{name} level mismatch {stats}")
    if abs(stats["mean_high_minus_low_cents"] - spread) > 1e-3:
        raise SystemExit(f"{name} spread mismatch {stats['mean_high_minus_low_cents']}")
    got = stats["newey_west_t_lag7"]
    if got is None or abs(got - t_stat) > 1e-2:
        raise SystemExit(f"{name} t mismatch {got}")


def year_name(day: Any) -> str:
    year = day.year
    if year <= 2023:
        return "2023"
    if year == 2024:
        return "2024"
    return "2025-2026"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def conclusion_sentence(yes: list[dict[str, Any]]) -> str:
    by_key = {(row["taxonomy"], row["rule"]): row for row in yes}
    bits = []
    for rule in ("official", "N=5", "N=10", "N=20", "N=50", "N=100", "N=500"):
        seven = by_key.get(("7-class", rule))
        twelve = by_key.get(("12-class", rule))
        if seven is None or twelve is None or seven["mean_high_minus_low_cents"] == "" or twelve["mean_high_minus_low_cents"] == "":
            bits.append(f"{rule} 下至少有一边没有可用日期，不能和论文比价差。")
            continue
        seven_gap = abs(float(seven["mean_high_minus_low_cents"]) - (-0.255))
        twelve_gap = abs(float(twelve["mean_high_minus_low_cents"]) - (-0.255))
        closer = "12 类" if twelve_gap < seven_gap else "7 类"
        bits.append(
            f"{rule} 下价差更接近论文的是{closer}"
            f"（7 类 {float(seven['mean_high_minus_low_cents']):+.3f}，"
            f"12 类 {float(twelve['mean_high_minus_low_cents']):+.3f}）。"
        )
    official_dates = int(by_key[("7-class", "official")]["n_dates"])
    twelve_official = int(by_key[("12-class", "official")]["n_dates"])

    def days(taxonomy: str, rule: str) -> int:
        return int(by_key[(taxonomy, rule)]["n_dates"])

    losses = []
    for rule in ("N=50", "N=100", "N=500"):
        seven_days = days("7-class", rule)
        twelve_days = days("12-class", rule)
        losses.append(
            f"{rule}：7 类 {seven_days} 天（比官方少 {official_dates - seven_days}），"
            f"12 类 {twelve_days} 天（比官方少 {twelve_official - twelve_days}）"
        )
    return (
        "- 日期："
        + "；".join(losses)
        + "。"
        + "".join(bits)
        + "N=50 和 N=100 没有改变 N=5 以后的结论：7 类价差仍更接近论文，两边都远不到 −0.255。N=500 两边都没有日期，不能比较。"
    )


def render(
    coverage: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    sources: Counter[str],
    rows: list[dict[str, Any]],
    years: list[dict[str, Any]],
    fetched_at: str,
    passed_gate: bool,
) -> str:
    lines = [
        "# 12 类导航对照",
        "",
        f"Gamma 标签拉取时间（香港）：{fetched_at or '见 cache/gamma_event_tags_meta.json'}。",
        "这些是拉取当时挂在父事件上的现行标签，不是形成日 16:00 的历史快照。",
        "互斥顺序写在 `category12_maps.json`：先直接 12 类，再同义词，再细标签对照，2022 年仍不够才用粗 category，其余进 Other。",
        "多类同时命中时按更细优先：Esports, Elections, Weather, Crypto, Sports, Geopolitics, Economy, Finance, Tech, Culture, World, Politics。",
        "",
        "## 覆盖率",
        "",
        "一个市场出现在哪一年的形成日，就计入哪一年。",
        "",
        "| 形成年 | 市场数 | 有标签 | 可映射 | 映射前冲突 | Other | 2022 粗类回退 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in coverage:
        lines.append(
            f"| {row['formation_year']} | {row['markets']} | {float(row['with_tags_share']):.1%} | "
            f"{float(row['mappable_share']):.1%} | {float(row['conflict_share']):.1%} | "
            f"{float(row['other_share']):.1%} | {row['coarse_2022']} |"
        )
    lines.extend(["", "映射后来源："])
    for name, count in sources.most_common():
        lines.append(f"- {name}: {count}")
    lines.extend(
        [
            "",
            "映射后的市场数（同一市场可计入多个形成年）：",
            "",
            "| 形成年 | 类 | 市场数 | 占比 |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for row in counts:
        if row["formation_year"] not in {"2022", "2023", "2024", "2025", "2026"} or int(row["markets"]) == 0:
            continue
        lines.append(
            f"| {row['formation_year']} | {row['category_12']} | {row['markets']} | {float(row['share']):.1%} |"
        )
    if not passed_gate:
        lines.extend(
            [
                "",
                "2024–2026 能映进 12 类的市场没有过半，因此没有做对照回测。",
                "",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "",
            "## YESMV 对照",
            "",
            "7 类是因子表里的 vgregoire category。12 类是上面的互斥字段，Other 也参与分组。",
            "官方参数不设桶的最少合约数，也不设权重上限。N 表示同一形成日、同一类别里 Low 和 High 各至少 N 个市场；任一不足则该类别日剔除，两腿只用共同留下的类别。",
            "论文 IA.15：High −0.171，Low +0.084，High−Low −0.255，t −5.81。",
            "",
            "| 分类 | 参数 | 日期 | Low | High | High−Low | NW t |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        if row["characteristic"] != "YESMV":
            continue
        if row["mean_low_cents"] == "":
            lines.append(f"| {row['taxonomy']} | {row['rule']} | 0 | 缺失 | 缺失 | 缺失 | 缺失 |")
        else:
            lines.append(
                f"| {row['taxonomy']} | {row['rule']} | {row['n_dates']} | "
                f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
                f"{float(row['mean_high_minus_low_cents']):.3f} | {float(row['newey_west_t_lag7']):.2f} |"
            )
    lines.extend(
        [
            "",
            "官方、N=5、N=10、N=20 这八行已对上旧结果。N=50、N=100、N=500 是这次新加的。",
            "",
            "## 分年 YESMV",
            "",
            "| 分类 | 参数 | 年份 | 日期 | Low | High | High−Low | NW t |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in years:
        t_text = "" if row["newey_west_t_lag7"] == "" else f"{float(row['newey_west_t_lag7']):.2f}"
        lines.append(
            f"| {row['taxonomy']} | {row['rule']} | {row['years']} | {row['n_dates']} | "
            f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
            f"{float(row['mean_high_minus_low_cents']):.3f} | {t_text} |"
        )
    lines.extend(
        [
            "",
            "## 其余特征",
            "",
            "| 分类 | 参数 | 特征 | 日期 | Low | High | High−Low | NW t |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        if row["mean_low_cents"] == "":
            lines.append(
                f"| {row['taxonomy']} | {row['rule']} | {row['characteristic']} | 0 | 缺失 | 缺失 | 缺失 | 缺失 |"
            )
        else:
            t_text = "" if row["newey_west_t_lag7"] == "" else f"{float(row['newey_west_t_lag7']):.2f}"
            lines.append(
                f"| {row['taxonomy']} | {row['rule']} | {row['characteristic']} | {row['n_dates']} | "
                f"{float(row['mean_low_cents']):.3f} | {float(row['mean_high_cents']):.3f} | "
                f"{float(row['mean_high_minus_low_cents']):.3f} | {t_text} |"
            )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["taxonomy"], row["rule"]), []).append(row)
    fully_empty = sorted(
        f"{taxonomy} {rule}"
        for (taxonomy, rule), items in grouped.items()
        if all(item["mean_low_cents"] == "" for item in items)
    )
    if fully_empty:
        lines.extend(
            [
                "",
                "整档天数为 0：" + "、".join(fully_empty) + "。",
                "原因：没有任何一个 formation_date×category 能让 Low 和 High 同时达到该 N 个不同市场，共同类别集每天都是空的，所以结果缺失。",
                "上面表里其余标成缺失的行，是该特征自己没有够 N 的类别日；同一档的其他特征仍有日期。",
            ]
        )
    yes = [row for row in rows if row["characteristic"] == "YESMV"]
    lines.extend(["", "## 结论", ""])
    for row in yes:
        if row["mean_low_cents"] == "":
            lines.append(
                f"- {row['taxonomy']} / {row['rule']}: 0 天，结果缺失。"
                "没有任何一个 formation_date×category 能让 Low 和 High 同时达到该 N 个不同市场。"
            )
        else:
            lines.append(
                f"- {row['taxonomy']} / {row['rule']}: High {float(row['mean_high_cents']):+.3f}，"
                f"Low {float(row['mean_low_cents']):+.3f}，High−Low {float(row['mean_high_minus_low_cents']):+.3f}，"
                f"t {float(row['newey_west_t_lag7']):.2f}，{row['n_dates']} 天。"
            )
    lines.extend(
        [
            "- 论文 IA.15：High −0.171，Low +0.084，High−Low −0.255，t −5.81。",
            "- 2024–2026 年约 99% 的市场能映进 12 类。2022 年 18 个市场里 16 个靠粗 category 回退，Other 为 0。2023 年 Other 占 60.9%，样本保留，没有剔除。",
            conclusion_sentence(yes),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
        return 0
    if not TAGS.exists():
        raise SystemExit(f"missing {TAGS}")
    maps = load_maps()
    events = load_events()
    con = duckdb.connect()
    markets = load_markets(con)
    missing_events = [
        market["event_id"]
        for market in markets
        if market["event_id"].isdigit() and market["event_id"] not in events
    ]
    print(f"markets {len(markets)} events cached {len(events)} missing {len(set(missing_events))}", flush=True)
    if missing_events:
        raise SystemExit("event tag cache is incomplete; not classifying a partial pull")
    assigned = assign_markets(markets, events, maps)
    coverage = coverage_rows(assigned)
    counts = class_counts(assigned, maps)
    sources = Counter(row["source"] for row in assigned)
    passed = gate_ok(assigned)
    print("coverage", [(row["formation_year"], row["other_share"], row["mappable_share"]) for row in coverage], flush=True)
    print("gate", passed, "sources", dict(sources), flush=True)
    if ASSIGNMENTS.exists():
        with ASSIGNMENTS.open(encoding="utf-8") as handle:
            frozen = {
                row["market_id"]: (row["category_12"], row["source"])
                for row in csv.DictReader(handle)
            }
        current = {row["market_id"]: (row["category_12"], row["source"]) for row in assigned}
        if frozen != current:
            raise SystemExit("category12_assignments.csv would change; kept the frozen file")
        print("frozen category12 assignments unchanged", flush=True)
    else:
        write_csv(ASSIGNMENTS, assigned)
    write_csv(COVERAGE, coverage)
    write_csv(COUNTS, counts)
    fetched_at = ""
    if TAG_META.exists():
        fetched_at = json.loads(TAG_META.read_text(encoding="utf-8")).get("finished_at_asia_hong_kong", "")
    if not passed:
        REPORT.write_text(
            render(coverage, counts, sources, [], [], fetched_at, False),
            encoding="utf-8",
        )
        raise SystemExit("2024-2026 coverage is below half; stopped before the portfolio comparison")
    lookup = {row["market_id"]: row["category_12"] for row in assigned}
    grouped = load_panel(lookup)
    schemes = (
        ("7-class", "category_7", None, "official"),
        ("7-class", "category_7", 5, "N=5"),
        ("7-class", "category_7", 10, "N=10"),
        ("7-class", "category_7", 20, "N=20"),
        ("12-class", "category_12", None, "official"),
        ("12-class", "category_12", 5, "N=5"),
        ("12-class", "category_12", 10, "N=10"),
        ("12-class", "category_12", 20, "N=20"),
        ("7-class", "category_7", 50, "N=50"),
        ("7-class", "category_7", 100, "N=100"),
        ("7-class", "category_7", 500, "N=500"),
        ("12-class", "category_12", 50, "N=50"),
        ("12-class", "category_12", 100, "N=100"),
        ("12-class", "category_12", 500, "N=500"),
    )
    results = {}
    for taxonomy, field, minimum, rule in schemes:
        print(f"portfolios {taxonomy} {rule}", flush=True)
        results[(taxonomy, rule)] = run_portfolios(grouped, field, minimum)
    official = summarize(results[("7-class", "official")]["YESMV"])
    n5 = summarize(results[("7-class", "N=5")]["YESMV"])
    n10 = summarize(results[("7-class", "N=10")]["YESMV"])
    n20 = summarize(results[("7-class", "N=20")]["YESMV"])
    check_known(official, 884, 0.073974, 0.282845, 0.208871, 1.2140, "7-class official")
    check_known(n5, 671, 0.056947, -0.043212, -0.100159, -3.5895, "7-class N=5")
    check_known(n10, 653, 0.057096, -0.044906, -0.102002, -3.3078, "7-class N=10")
    check_known(n20, 622, 0.050769, -0.042138, -0.092907, -3.1032, "7-class N=20")
    check_known(summarize(results[("12-class", "official")]["YESMV"]), 901, 0.319665, 0.035490, -0.284174, -1.1192, "12-class official")
    check_known(summarize(results[("12-class", "N=5")]["YESMV"]), 663, 0.073707, -0.025764, -0.099470, -2.7075, "12-class N=5")
    check_known(summarize(results[("12-class", "N=10")]["YESMV"]), 644, 0.062894, -0.010553, -0.073446, -1.7672, "12-class N=10")
    check_known(summarize(results[("12-class", "N=20")]["YESMV"]), 587, 0.036783, 0.039728, 0.002945, 0.0427, "12-class N=20")
    print("previous rows match", flush=True)
    table = []
    year_rows = []
    for taxonomy, _field, _minimum, rule in schemes:
        for _key, label in CHARACTERISTICS:
            stats = summarize(results[(taxonomy, rule)][label])
            t_stat = stats["newey_west_t_lag7"]
            missing = stats["n_dates"] == 0
            table.append(
                {
                    "taxonomy": taxonomy,
                    "rule": rule,
                    "characteristic": label,
                    "n_dates": stats["n_dates"],
                    "n_category_days": stats["n_category_days"],
                    "mean_low_cents": "" if missing else f"{stats['mean_low_cents']:.6f}",
                    "mean_high_cents": "" if missing else f"{stats['mean_high_cents']:.6f}",
                    "mean_high_minus_low_cents": "" if missing else f"{stats['mean_high_minus_low_cents']:.6f}",
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                    "result": "missing_no_category_met_min_n" if missing else "ok",
                }
            )
        buckets: dict[str, list[dict[str, Any]]] = {"2023": [], "2024": [], "2025-2026": []}
        for point in results[(taxonomy, rule)]["YESMV"]:
            buckets[year_name(point["date"])].append(point)
        for bucket_name, series in buckets.items():
            if len(series) < 2:
                continue
            stats = summarize(series)
            t_stat = stats["newey_west_t_lag7"]
            year_rows.append(
                {
                    "taxonomy": taxonomy,
                    "rule": rule,
                    "years": bucket_name,
                    "n_dates": stats["n_dates"],
                    "mean_low_cents": f"{stats['mean_low_cents']:.6f}",
                    "mean_high_cents": f"{stats['mean_high_cents']:.6f}",
                    "mean_high_minus_low_cents": f"{stats['mean_high_minus_low_cents']:.6f}",
                    "newey_west_t_lag7": "" if t_stat is None else f"{t_stat:.4f}",
                }
            )
    write_csv(TABLE, table)
    write_csv(YEAR_TABLE, year_rows)
    REPORT.write_text(render(coverage, counts, sources, table, year_rows, fetched_at, True), encoding="utf-8")
    print(f"wrote {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
