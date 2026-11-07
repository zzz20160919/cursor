from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


PM_RAW_DIR = PROJECT_ROOT / "data" / "mvp3_pm_predictfun" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "mvp3_pm_predictfun"
PD_API_BASE = os.environ.get("PREDICT_API_BASE", "https://api.predict.fun").rstrip("/")
PD_API_KEY_ENV = "PREDICT_API_KEY"

CSV_FIELDS = [
    "venue",
    "query",
    "market_id",
    "market_title",
    "outcome_name",
    "token_or_outcome_id",
    "can_fetch_orderbook",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "no_price_source",
    "notes",
]

WINNER_COMPARE_FIELDS = [
    "timestamp",
    "team",
    "mapping_status",
    "pm_outcome_name",
    "pd_outcome_name",
    "pm_token_yes",
    "pm_token_no",
    "pd_outcome_id",
    "pd_market_id",
    "pm_market_id",
    "pm_yes_ask1",
    "pm_yes_bid1",
    "pm_no_ask1",
    "pm_no_bid1",
    "pd_yes_ask1",
    "pd_yes_bid1",
    "pd_no_ask1",
    "pd_no_bid1",
    "diff_yes_ask_pm_minus_pd",
    "diff_yes_bid_pm_minus_pd",
    "diff_no_ask_pm_minus_pd",
    "diff_no_bid_pm_minus_pd",
    "edge_pm_yes_pd_no",
    "edge_pd_yes_pm_no",
    "pm_yes_ask_size1",
    "pm_yes_bid_size1",
    "pm_no_ask_size1",
    "pm_no_bid_size1",
    "pd_yes_ask_size1",
    "pd_yes_bid_size1",
    "pd_no_ask_size1",
    "pd_no_bid_size1",
    "pd_no_price_source",
    "pm_orderbook_ok",
    "pd_orderbook_ok",
    "notes",
]

WINNER_TEAMS = [
    "France",
    "Argentina",
    "Spain",
    "England",
    "Brazil",
    "Portugal",
    "Morocco",
    "Colombia",
    "Germany",
    "Netherlands",
    "Belgium",
    "United States",
    "Mexico",
]

TEAM_ALIASES = {
    "usa": "unitedstates",
    "us": "unitedstates",
    "u s a": "unitedstates",
    "united states": "unitedstates",
    "united states of america": "unitedstates",
    "arg": "argentina",
    "aus": "australia",
    "bel": "belgium",
    "bih": "bosniaandherzegovina",
    "bra": "brazil",
    "can": "canada",
    "che": "switzerland",
    "civ": "ivorycoast",
    "col": "colombia",
    "cro": "croatia",
    "cvi": "capeverde",
    "deu": "germany",
    "egy": "egypt",
    "eng": "england",
    "fra": "france",
    "gha": "ghana",
    "ger": "germany",
    "mar": "morocco",
    "mex": "mexico",
    "ned": "netherlands",
    "nld": "netherlands",
    "nor": "norway",
    "por": "portugal",
    "sen": "senegal",
    "spa": "spain",
    "esp": "spain",
    "sui": "switzerland",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def write_winner_compare_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=WINNER_COMPARE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in WINNER_COMPARE_FIELDS})


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = TEAM_ALIASES.get(text, text)
    return re.sub(r"[^a-z0-9]+", "", text)


def text_blob(row: dict[str, Any]) -> str:
    parts = [
        row.get("title"),
        row.get("question"),
        row.get("slug"),
        row.get("description"),
        row.get("categorySlug"),
        row.get("marketVariant"),
        row.get("marketType"),
    ]
    team = row.get("team")
    if isinstance(team, dict):
        parts.extend([team.get("name"), team.get("alias"), team.get("league")])
    variant_data = row.get("variantData")
    if isinstance(variant_data, dict):
        parts.extend(str(value) for value in variant_data.values() if value is not None)
    return " ".join(str(part or "") for part in parts).lower()


def matches_query(row: dict[str, Any], query: str) -> bool:
    blob = text_blob(row)
    return all(term in blob for term in query.lower().split())


def is_world_cup_winner_like(row: dict[str, Any]) -> bool:
    blob = text_blob(row)
    return "world cup" in blob and any(term in blob for term in ("winner", "win", "champion"))


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_float(value: float | None) -> float | str:
    if value is None:
        return ""
    return round(value, 10)


def diff(left: float | None, right: float | None) -> float | str:
    if left is None or right is None:
        return ""
    return round(left - right, 10)


def edge(yes_ask: float | None, no_ask: float | None) -> float | str:
    if yes_ask is None or no_ask is None:
        return ""
    return round(1.0 - yes_ask - no_ask, 10)


def first_level(levels: Any, reverse: bool = False) -> tuple[float | None, float | None]:
    parsed: list[tuple[float, float]] = []
    for level in levels if isinstance(levels, list) else []:
        if isinstance(level, dict):
            price = safe_float(level.get("price"))
            size = safe_float(level.get("size") or level.get("quantity"))
        elif isinstance(level, list | tuple) and len(level) >= 2:
            price = safe_float(level[0])
            size = safe_float(level[1])
        else:
            continue
        if price is not None and size is not None:
            parsed.append((price, size))
    if not parsed:
        return None, None
    parsed.sort(key=lambda item: item[0], reverse=reverse)
    return parsed[0]


def complement(price: float | None, decimal_precision: int | None) -> float | None:
    if price is None:
        return None
    raw = 1.0 - price
    if decimal_precision is None:
        return raw
    return round(raw, decimal_precision)


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 12) -> Any:
    req_headers = {
        "Accept": "application/json",
        "User-Agent": "2026-strategy-lab-mvp3-a-probe",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def error_payload(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
    }
    if isinstance(exc, urllib.error.HTTPError):
        payload["status_code"] = exc.code
        try:
            payload["body"] = exc.read().decode(errors="replace")[:2000]
        except Exception:
            payload["body"] = ""
    return payload


def pm_search_markets(query: str, max_markets: int) -> dict[str, Any]:
    pages = max(3, min(25, (max_markets // 100) + 10))
    page_size = 100
    all_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for page in range(pages):
        params = {
            "limit": page_size,
            "offset": page * page_size,
            "active": "true",
            "closed": "false",
            "enableOrderBook": "true",
        }
        url = f"{pm.GAMMA_API}/markets?{urllib.parse.urlencode(params)}"
        try:
            batch = pm.http_json(url)
        except Exception as exc:
            errors.append({"url": url, **error_payload(exc)})
            break
        if not isinstance(batch, list) or not batch:
            break
        all_rows.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < page_size:
            break

    matched = [
        row
        for row in all_rows
        if (matches_query(row, query) or is_world_cup_winner_like(row))
        and parse_json_list(row.get("clobTokenIds"))
    ]
    matched = matched[:max_markets]
    return {
        "fetched_at": now_iso(),
        "venue": "polymarket",
        "query": query,
        "source": f"{pm.GAMMA_API}/markets",
        "total_scanned": len(all_rows),
        "returned_count": len(matched),
        "errors": errors,
        "markets": matched,
    }


def token_ids_for_pm_market(market: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
    token_ids = [str(item) for item in parse_json_list(market.get("clobTokenIds"))]
    outcomes = [str(item) for item in parse_json_list(market.get("outcomes"))]
    lowered = [item.lower() for item in outcomes]
    yes_index = lowered.index("yes") if "yes" in lowered else 0
    no_index = lowered.index("no") if "no" in lowered else 1
    yes_token = token_ids[yes_index] if len(token_ids) > yes_index else None
    no_token = token_ids[no_index] if len(token_ids) > no_index else None
    return yes_token, no_token, outcomes


def pm_fetch_orderbook_samples(markets: list[dict[str, Any]], sample_orderbooks: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for market in markets[:sample_orderbooks]:
        yes_token, no_token, outcomes = token_ids_for_pm_market(market)
        market_sample = {
            "market_id": str(market.get("id") or ""),
            "market_title": str(market.get("question") or market.get("title") or ""),
            "slug": str(market.get("slug") or ""),
            "outcomes": outcomes,
            "yes_token": yes_token,
            "no_token": no_token,
            "books": {},
        }
        for side, token in (("yes", yes_token), ("no", no_token)):
            if not token:
                market_sample["books"][side] = {"error": "missing_token"}
                continue
            try:
                bids, asks, raw = pm.book(token)
                market_sample["books"][side] = {
                    "token_id": token,
                    "best_bid": bids[0] if bids else None,
                    "best_ask": asks[0] if asks else None,
                    "raw": raw,
                }
            except Exception as exc:
                market_sample["books"][side] = {"token_id": token, **error_payload(exc)}
        samples.append(market_sample)
    return {
        "fetched_at": now_iso(),
        "venue": "polymarket",
        "sample_count": len(samples),
        "samples": samples,
    }


def pd_headers() -> dict[str, str]:
    api_key = os.environ.get(PD_API_KEY_ENV)
    return {"x-api-key": api_key} if api_key else {}


def pd_auth_blocker() -> str:
    if PD_API_BASE == "https://api.predict.fun" and not os.environ.get(PD_API_KEY_ENV):
        return f"missing_{PD_API_KEY_ENV}_for_predict_fun_mainnet"
    return ""


def pd_search_markets(query: str, max_markets: int) -> dict[str, Any]:
    blocker = pd_auth_blocker()
    if blocker:
        return {
            "fetched_at": now_iso(),
            "venue": "predict.fun",
            "query": query,
            "api_base": PD_API_BASE,
            "returned_count": 0,
            "errors": [{"error": blocker}],
            "markets": [],
        }

    headers = pd_headers()
    requests = [
        {"first": str(max(max_markets, 20)), "status": "OPEN", "marketVariant": "SPORTS_FIFA_WORLD_CUP"},
        {"first": str(max(max_markets, 20)), "status": "OPEN"},
    ]
    seen: set[str] = set()
    matched: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for params in requests:
        url = f"{PD_API_BASE}/v1/markets?{urllib.parse.urlencode(params)}"
        try:
            data = http_json(url, headers=headers)
        except Exception as exc:
            errors.append({"url": url, **error_payload(exc)})
            continue
        raw_responses.append({"url": url, "response": data})
        rows = data.get("data") if isinstance(data, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            market_id = str(row.get("id") or "")
            if not market_id or market_id in seen:
                continue
            if matches_query(row, query) or is_world_cup_winner_like(row):
                seen.add(market_id)
                matched.append(row)
            if len(matched) >= max_markets:
                break
        if len(matched) >= max_markets:
            break

    return {
        "fetched_at": now_iso(),
        "venue": "predict.fun",
        "query": query,
        "api_base": PD_API_BASE,
        "returned_count": len(matched),
        "errors": errors,
        "raw_responses": raw_responses,
        "markets": matched[:max_markets],
    }


def pd_fetch_orderbook_samples(markets: list[dict[str, Any]], sample_orderbooks: int) -> dict[str, Any]:
    blocker = pd_auth_blocker()
    if blocker:
        return {
            "fetched_at": now_iso(),
            "venue": "predict.fun",
            "api_base": PD_API_BASE,
            "sample_count": 0,
            "errors": [{"error": blocker}],
            "samples": [],
        }

    samples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for market in markets[:sample_orderbooks]:
        market_id = str(market.get("id") or "")
        if not market_id:
            continue
        url = f"{PD_API_BASE}/v1/markets/{urllib.parse.quote(market_id)}/orderbook"
        try:
            data = http_json(url, headers=pd_headers())
            samples.append(
                {
                    "market_id": market_id,
                    "market_title": str(market.get("title") or market.get("question") or ""),
                    "decimalPrecision": market.get("decimalPrecision"),
                    "url": url,
                    "raw": data,
                }
            )
        except Exception as exc:
            error = {"market_id": market_id, "url": url, **error_payload(exc)}
            samples.append(error)
            errors.append(error)
    return {
        "fetched_at": now_iso(),
        "venue": "predict.fun",
        "api_base": PD_API_BASE,
        "sample_count": len(samples),
        "errors": errors,
        "samples": samples,
    }


def pd_slug_from_url(url: str | None, fallback: str | None = None) -> str:
    if fallback:
        return fallback.strip().strip("/")
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if "market" in parts:
        index = parts.index("market")
        if len(parts) > index + 1:
            return parts[index + 1]
    return parts[-1] if parts else ""


def pd_find_markets_by_slug(slug: str, max_markets: int) -> dict[str, Any]:
    blocker = pd_auth_blocker()
    if blocker:
        return {
            "fetched_at": now_iso(),
            "venue": "predict.fun",
            "api_base": PD_API_BASE,
            "pd_market_slug": slug,
            "returned_count": 0,
            "errors": [{"error": blocker}],
            "markets": [],
        }

    matched: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    slug_lower = slug.lower()
    request_sets = [
        {"first": "100", "status": "OPEN", "marketVariant": "SPORTS_FIFA_WORLD_CUP"},
        {"first": "100", "status": "OPEN"},
    ]
    for base_params in request_sets:
        after = ""
        for _page in range(20):
            params = dict(base_params)
            if after:
                params["after"] = after
            url = f"{PD_API_BASE}/v1/markets?{urllib.parse.urlencode(params)}"
            try:
                data = http_json(url, headers=pd_headers())
            except Exception as exc:
                errors.append({"url": url, **error_payload(exc)})
                break
            raw_responses.append({"url": url, "response": data})
            rows = data.get("data") if isinstance(data, dict) else []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                market_id = str(row.get("id") or "")
                category_slug = str(row.get("categorySlug") or "").lower()
                if market_id and market_id not in seen and (
                    category_slug == slug_lower or slug_lower in text_blob(row)
                ):
                    seen.add(market_id)
                    matched.append(row)
            if len(matched) >= max_markets:
                break
            cursor = data.get("cursor") if isinstance(data, dict) else ""
            if not cursor or cursor == after:
                break
            after = str(cursor)
        if matched:
            break

    return {
        "fetched_at": now_iso(),
        "venue": "predict.fun",
        "api_base": PD_API_BASE,
        "pd_market_slug": slug,
        "returned_count": len(matched[:max_markets]),
        "errors": errors,
        "raw_responses": raw_responses,
        "markets": matched[:max_markets],
    }


def pd_outcome_id(market: dict[str, Any]) -> str:
    for outcome in market.get("outcomes", []) if isinstance(market.get("outcomes"), list) else []:
        if isinstance(outcome, dict) and str(outcome.get("name") or "").lower() == "yes":
            return str(outcome.get("onChainId") or outcome.get("indexSet") or "")
    return str(market.get("id") or "")


def pd_market_team(market: dict[str, Any]) -> str:
    title = str(market.get("title") or "").strip()
    if title and normalize_name(title) not in {"draw", "other"}:
        return title
    question = str(market.get("question") or "").strip()
    match = re.search(r"^Will\s+(.+?)\s+win\b", question, re.I)
    if match:
        return match.group(1).strip()
    outcomes = market.get("outcomes")
    for outcome in outcomes if isinstance(outcomes, list) else []:
        variant_data = outcome.get("variantData") if isinstance(outcome, dict) else None
        team = variant_data.get("team") if isinstance(variant_data, dict) else None
        name = team.get("name") if isinstance(team, dict) else None
        if name:
            return str(name)
    return title or question


def pm_market_team(market: dict[str, Any]) -> str:
    label = str(market.get("groupItemTitle") or "").strip()
    if label:
        return label
    question = str(market.get("question") or "")
    match = re.search(r"^Will\s+(.+?)\s+win the 2026 FIFA World Cup", question, re.I)
    return match.group(1).strip() if match else question


def detailed_pm_tops(sample: dict[str, Any]) -> dict[str, Any]:
    yes_book = sample.get("books", {}).get("yes", {})
    no_book = sample.get("books", {}).get("no", {})
    yes_bid = yes_book.get("best_bid") if isinstance(yes_book, dict) else None
    yes_ask = yes_book.get("best_ask") if isinstance(yes_book, dict) else None
    no_bid = no_book.get("best_bid") if isinstance(no_book, dict) else None
    no_ask = no_book.get("best_ask") if isinstance(no_book, dict) else None
    ok = bool(
        isinstance(yes_book, dict)
        and isinstance(no_book, dict)
        and "raw" in yes_book
        and "raw" in no_book
        and not yes_book.get("error")
        and not no_book.get("error")
    )
    return {
        "ok": ok,
        "yes_bid": yes_bid[0] if isinstance(yes_bid, list | tuple) else None,
        "yes_bid_size": yes_bid[1] if isinstance(yes_bid, list | tuple) else None,
        "yes_ask": yes_ask[0] if isinstance(yes_ask, list | tuple) else None,
        "yes_ask_size": yes_ask[1] if isinstance(yes_ask, list | tuple) else None,
        "no_bid": no_bid[0] if isinstance(no_bid, list | tuple) else None,
        "no_bid_size": no_bid[1] if isinstance(no_bid, list | tuple) else None,
        "no_ask": no_ask[0] if isinstance(no_ask, list | tuple) else None,
        "no_ask_size": no_ask[1] if isinstance(no_ask, list | tuple) else None,
    }


def detailed_pd_tops(sample: dict[str, Any]) -> dict[str, Any]:
    raw = sample.get("raw") if isinstance(sample, dict) else None
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "no_price_source": "UNKNOWN / NEEDS_RECHECK"}
    yes_bid, yes_bid_size = first_level(data.get("bids"), reverse=True)
    yes_ask, yes_ask_size = first_level(data.get("asks"), reverse=False)
    try:
        precision_int = int(sample.get("decimalPrecision"))
    except (TypeError, ValueError):
        precision_int = None
    if precision_int is None:
        return {
            "ok": bool(yes_bid is not None or yes_ask is not None),
            "yes_bid": yes_bid,
            "yes_bid_size": yes_bid_size,
            "yes_ask": yes_ask,
            "yes_ask_size": yes_ask_size,
            "no_bid": None,
            "no_bid_size": None,
            "no_ask": None,
            "no_ask_size": None,
            "no_price_source": "UNKNOWN / NEEDS_RECHECK",
        }
    return {
        "ok": True,
        "yes_bid": yes_bid,
        "yes_bid_size": yes_bid_size,
        "yes_ask": yes_ask,
        "yes_ask_size": yes_ask_size,
        "no_bid": complement(yes_ask, precision_int),
        "no_bid_size": yes_ask_size,
        "no_ask": complement(yes_bid, precision_int),
        "no_ask_size": yes_bid_size,
        "no_price_source": "derived_from_yes_book",
    }


def book_tops_from_pm_sample(sample: dict[str, Any]) -> dict[str, Any]:
    yes_book = sample.get("books", {}).get("yes", {})
    no_book = sample.get("books", {}).get("no", {})
    yes_bid = yes_book.get("best_bid") if isinstance(yes_book, dict) else None
    yes_ask = yes_book.get("best_ask") if isinstance(yes_book, dict) else None
    no_bid = no_book.get("best_bid") if isinstance(no_book, dict) else None
    no_ask = no_book.get("best_ask") if isinstance(no_book, dict) else None
    yes_fetched = isinstance(yes_book, dict) and "raw" in yes_book and not yes_book.get("error")
    no_fetched = isinstance(no_book, dict) and "raw" in no_book and not no_book.get("error")
    return {
        "yes_best_bid": yes_bid[0] if isinstance(yes_bid, list | tuple) else None,
        "yes_best_ask": yes_ask[0] if isinstance(yes_ask, list | tuple) else None,
        "no_best_bid": no_bid[0] if isinstance(no_bid, list | tuple) else None,
        "no_best_ask": no_ask[0] if isinstance(no_ask, list | tuple) else None,
        "can_fetch_orderbook": bool(yes_fetched and no_fetched),
    }


def book_tops_from_pd_sample(sample: dict[str, Any]) -> dict[str, Any]:
    raw = sample.get("raw") if isinstance(sample, dict) else None
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {
            "can_fetch_orderbook": False,
            "yes_best_bid": None,
            "yes_best_ask": None,
            "no_best_bid": None,
            "no_best_ask": None,
            "no_price_source": "UNKNOWN / NEEDS_RECHECK",
        }
    yes_bid, _yes_bid_size = first_level(data.get("bids"), reverse=True)
    yes_ask, _yes_ask_size = first_level(data.get("asks"), reverse=False)
    precision = sample.get("decimalPrecision")
    try:
        precision_int = int(precision) if precision is not None else None
    except (TypeError, ValueError):
        precision_int = None
    return {
        "can_fetch_orderbook": True,
        "yes_best_bid": yes_bid,
        "yes_best_ask": yes_ask,
        "no_best_bid": complement(yes_ask, precision_int),
        "no_best_ask": complement(yes_bid, precision_int),
        "no_price_source": "derived_from_yes_book",
    }


def build_csv_rows(
    query: str,
    pm_markets: list[dict[str, Any]],
    pm_books: dict[str, Any],
    pd_markets: list[dict[str, Any]],
    pd_books: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pm_samples = {str(sample.get("market_id") or ""): sample for sample in pm_books.get("samples", [])}
    for market in pm_markets:
        market_id = str(market.get("id") or "")
        yes_token, no_token, outcomes = token_ids_for_pm_market(market)
        tops = book_tops_from_pm_sample(pm_samples.get(market_id, {}))
        notes = []
        if [item.lower() for item in outcomes] != ["yes", "no"]:
            notes.append("outcomes_index_needs_recheck")
        for outcome_name, token in (("Yes", yes_token), ("No", no_token)):
            rows.append(
                {
                    "venue": "polymarket",
                    "query": query,
                    "market_id": market_id,
                    "market_title": str(market.get("question") or market.get("title") or ""),
                    "outcome_name": outcome_name,
                    "token_or_outcome_id": token or "",
                    "can_fetch_orderbook": tops["can_fetch_orderbook"],
                    "yes_best_bid": tops["yes_best_bid"],
                    "yes_best_ask": tops["yes_best_ask"],
                    "no_best_bid": tops["no_best_bid"],
                    "no_best_ask": tops["no_best_ask"],
                    "no_price_source": "direct_pm_no_token",
                    "notes": ";".join(notes),
                }
            )

    pd_samples = {str(sample.get("market_id") or ""): sample for sample in pd_books.get("samples", [])}
    for market in pd_markets:
        market_id = str(market.get("id") or "")
        sample = pd_samples.get(market_id, {})
        tops = book_tops_from_pd_sample(sample)
        notes = ["predict_fun_orderbook_docs_say_yes_side_book"]
        if market.get("decimalPrecision") is None:
            notes.append("decimalPrecision_missing_UNKNOWN_NEEDS_RECHECK")
        rows.append(
            {
                "venue": "predict.fun",
                "query": query,
                "market_id": market_id,
                "market_title": str(market.get("title") or market.get("question") or ""),
                "outcome_name": "Yes book; No derived if precision is known",
                "token_or_outcome_id": market_id,
                "can_fetch_orderbook": tops["can_fetch_orderbook"],
                "yes_best_bid": tops["yes_best_bid"],
                "yes_best_ask": tops["yes_best_ask"],
                "no_best_bid": tops["no_best_bid"],
                "no_best_ask": tops["no_best_ask"],
                "no_price_source": tops["no_price_source"],
                "notes": ";".join(notes),
            }
        )
    return rows


def write_summary(
    path: Path,
    *,
    query: str,
    pm_markets: dict[str, Any],
    pm_books: dict[str, Any],
    pd_markets: dict[str, Any],
    pd_books: dict[str, Any],
) -> None:
    pm_market_found = bool(pm_markets.get("markets"))
    pm_orderbook_count = sum(
        1
        for sample in pm_books.get("samples", [])
        if book_tops_from_pm_sample(sample).get("can_fetch_orderbook")
    )
    pd_market_found = bool(pd_markets.get("markets"))
    pd_orderbook_count = sum(
        1
        for sample in pd_books.get("samples", [])
        if book_tops_from_pd_sample(sample).get("can_fetch_orderbook")
    )
    pd_has_key = bool(os.environ.get(PD_API_KEY_ENV))
    pd_auth_issue = pd_auth_blocker()
    pd_yes_no_clear = pd_orderbook_count > 0
    precision_missing = any(row.get("decimalPrecision") is None for row in pd_markets.get("markets", []))
    blockers: list[str] = []
    if not pm_market_found:
        blockers.append("PM World Cup market not found")
    if pm_market_found and pm_orderbook_count == 0:
        blockers.append("PM orderbook sample not fetched")
    if pd_auth_issue:
        blockers.append(pd_auth_issue)
    elif not pd_market_found:
        blockers.append("Predict.fun World Cup market not found")
    elif pd_orderbook_count == 0:
        blockers.append("Predict.fun orderbook sample not fetched")
    if precision_missing:
        blockers.append("Predict.fun decimalPrecision missing for at least one market")
    if not pd_yes_no_clear:
        blockers.append("Predict.fun YES/NO expression not verified from live raw orderbook")

    recommend_mvp3_b = pm_market_found and pm_orderbook_count > 0 and pd_market_found and pd_orderbook_count > 0
    biggest_blocker = blockers[0] if blockers else "none"
    content = f"""# MVP3-A PM vs Predict.fun Probe Summary

- checked_at: {now_iso()}
- query: {query}
- live_allowed: false
- orders_submitted: false
- scanner_or_candidate_generated: false

## Required Answers

1. PM market found: {str(pm_market_found).lower()} ({len(pm_markets.get("markets", []))})
2. PM orderbook fetched: {str(pm_orderbook_count > 0).lower()} ({pm_orderbook_count}/{len(pm_books.get("samples", []))})
3. Predict.fun market found: {str(pd_market_found).lower()} ({len(pd_markets.get("markets", []))})
4. Predict.fun orderbook fetched: {str(pd_orderbook_count > 0).lower()} ({pd_orderbook_count}/{len(pd_books.get("samples", []))})
5. Predict.fun YES/NO expression clear: {str(pd_yes_no_clear).lower()}
   - Docs say `/v1/markets/{{id}}/orderbook` stores prices based on the Yes outcome.
   - This probe marks derived NO prices as `pd_no_source = derived_from_yes_book`.
   - Precision still needs recheck if `decimalPrecision` is missing.
6. Biggest blocker: {biggest_blocker}
7. Recommend entering MVP3-B: {str(recommend_mvp3_b).lower()}

## Predict.fun API Notes

- api_base: {PD_API_BASE}
- mainnet_api_key_present: {str(pd_has_key).lower()}
- market_endpoint: GET /v1/markets
- orderbook_endpoint: GET /v1/markets/{{id}}/orderbook
- orderbook_shape_from_docs: Yes-side `bids` and `asks` arrays of `[price, size]`

## UNKNOWN / NEEDS_RECHECK

- Predict.fun fee schedule.
- Predict.fun tick size and min order size / notional.
- Predict.fun settlement, cancellation, void, and dispute rules.
- Predict.fun quote freshness semantics beyond `updateTimestampMs`.
- Predict.fun exact decimal precision and complement rounding for any market missing `decimalPrecision`.
- Predict.fun market-to-Polymarket rule equivalence for World Cup Winner.
- PM exact fee/min-size rules before any future execution.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_winner_price_rows(
    *,
    pm_markets: list[dict[str, Any]],
    pm_books: dict[str, Any],
    pd_markets: list[dict[str, Any]],
    pd_books: dict[str, Any],
) -> list[dict[str, Any]]:
    timestamp = now_iso()
    pm_by_team = {normalize_name(pm_market_team(row)): row for row in pm_markets}
    pd_by_team = {normalize_name(pd_market_team(row)): row for row in pd_markets}
    pm_samples = {str(sample.get("market_id") or ""): sample for sample in pm_books.get("samples", [])}
    pd_samples = {str(sample.get("market_id") or ""): sample for sample in pd_books.get("samples", [])}
    ordered_keys = [normalize_name(team) for team in WINNER_TEAMS]
    ordered_keys.extend(
        key
        for key in sorted(set(pm_by_team) | set(pd_by_team))
        if key not in set(ordered_keys) and key not in {"draw", "other"}
    )

    rows: list[dict[str, Any]] = []
    for key in ordered_keys:
        pm_market = pm_by_team.get(key)
        pd_market = pd_by_team.get(key)
        display_team = next((team for team in WINNER_TEAMS if normalize_name(team) == key), None)
        display_team = display_team or pm_market_team(pm_market or {}) or pd_market_team(pd_market or {}) or key
        pm_market_id = str((pm_market or {}).get("id") or "")
        pd_market_id = str((pd_market or {}).get("id") or "")
        pm_yes_token, pm_no_token, _outcomes = token_ids_for_pm_market(pm_market or {})
        pm_top = detailed_pm_tops(pm_samples.get(pm_market_id, {}))
        pd_top = detailed_pd_tops(pd_samples.get(pd_market_id, {}))

        notes: list[str] = []
        if not pm_market:
            notes.append("pm_outcome_missing")
        if not pd_market:
            notes.append("pd_outcome_missing")
        if pm_market and not pm_top.get("ok"):
            notes.append("pm_orderbook_missing_or_unsampled")
        if pd_market and not pd_top.get("ok"):
            notes.append("pd_orderbook_missing_or_unsampled")
        if pd_top.get("no_price_source") == "derived_from_yes_book":
            notes.append("pd_no_size_mirrors_yes_book_side_NEEDS_RECHECK")

        if pm_market and pd_market:
            mapping_status = "matched"
        elif pm_market:
            mapping_status = "pm_only"
        elif pd_market:
            mapping_status = "pd_only"
        else:
            mapping_status = "missing"

        row = {
            "timestamp": timestamp,
            "team": display_team,
            "mapping_status": mapping_status,
            "pm_outcome_name": pm_market_team(pm_market or {}) if pm_market else "",
            "pd_outcome_name": pd_market_team(pd_market or {}) if pd_market else "",
            "pm_token_yes": pm_yes_token or "",
            "pm_token_no": pm_no_token or "",
            "pd_outcome_id": pd_outcome_id(pd_market or {}) if pd_market else "",
            "pd_market_id": pd_market_id,
            "pm_market_id": pm_market_id,
            "pm_yes_ask1": fmt_float(pm_top.get("yes_ask")),
            "pm_yes_bid1": fmt_float(pm_top.get("yes_bid")),
            "pm_no_ask1": fmt_float(pm_top.get("no_ask")),
            "pm_no_bid1": fmt_float(pm_top.get("no_bid")),
            "pd_yes_ask1": fmt_float(pd_top.get("yes_ask")),
            "pd_yes_bid1": fmt_float(pd_top.get("yes_bid")),
            "pd_no_ask1": fmt_float(pd_top.get("no_ask")),
            "pd_no_bid1": fmt_float(pd_top.get("no_bid")),
            "diff_yes_ask_pm_minus_pd": diff(pm_top.get("yes_ask"), pd_top.get("yes_ask")),
            "diff_yes_bid_pm_minus_pd": diff(pm_top.get("yes_bid"), pd_top.get("yes_bid")),
            "diff_no_ask_pm_minus_pd": diff(pm_top.get("no_ask"), pd_top.get("no_ask")),
            "diff_no_bid_pm_minus_pd": diff(pm_top.get("no_bid"), pd_top.get("no_bid")),
            "edge_pm_yes_pd_no": edge(pm_top.get("yes_ask"), pd_top.get("no_ask")),
            "edge_pd_yes_pm_no": edge(pd_top.get("yes_ask"), pm_top.get("no_ask")),
            "pm_yes_ask_size1": fmt_float(pm_top.get("yes_ask_size")),
            "pm_yes_bid_size1": fmt_float(pm_top.get("yes_bid_size")),
            "pm_no_ask_size1": fmt_float(pm_top.get("no_ask_size")),
            "pm_no_bid_size1": fmt_float(pm_top.get("no_bid_size")),
            "pd_yes_ask_size1": fmt_float(pd_top.get("yes_ask_size")),
            "pd_yes_bid_size1": fmt_float(pd_top.get("yes_bid_size")),
            "pd_no_ask_size1": fmt_float(pd_top.get("no_ask_size")),
            "pd_no_bid_size1": fmt_float(pd_top.get("no_bid_size")),
            "pd_no_price_source": pd_top.get("no_price_source", "UNKNOWN / NEEDS_RECHECK"),
            "pm_orderbook_ok": bool(pm_top.get("ok")),
            "pd_orderbook_ok": bool(pd_top.get("ok")),
            "notes": ";".join(notes),
        }
        rows.append(row)
    return rows


def numeric(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def top_abs_diff(row: dict[str, Any]) -> float | None:
    values = [
        abs(value)
        for value in (
            numeric(row.get("diff_yes_ask_pm_minus_pd")),
            numeric(row.get("diff_yes_bid_pm_minus_pd")),
            numeric(row.get("diff_no_ask_pm_minus_pd")),
            numeric(row.get("diff_no_bid_pm_minus_pd")),
        )
        if value is not None
    ]
    return max(values) if values else None


def write_winner_review(
    path: Path,
    *,
    pd_slug: str,
    pm_markets: dict[str, Any],
    pd_markets: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    matched = [row for row in rows if row.get("mapping_status") == "matched"]
    matched_with_books = [
        row
        for row in matched
        if str(row.get("pm_orderbook_ok")).lower() == "true"
        and str(row.get("pd_orderbook_ok")).lower() == "true"
    ]
    closest = sorted(
        [row for row in matched_with_books if top_abs_diff(row) is not None],
        key=lambda row: top_abs_diff(row) or 999,
    )[:5]
    largest = sorted(
        [row for row in matched_with_books if top_abs_diff(row) is not None],
        key=lambda row: top_abs_diff(row) or -1,
        reverse=True,
    )[:5]
    positive_edges = [
        row
        for row in matched_with_books
        if (numeric(row.get("edge_pm_yes_pd_no")) or -999) > 0
        or (numeric(row.get("edge_pd_yes_pm_no")) or -999) > 0
    ]
    pd_winner_found = bool(pd_markets.get("markets"))
    pm_winner_found = bool(pm_markets.get("markets"))
    pd_errors = pd_markets.get("errors") if isinstance(pd_markets.get("errors"), list) else []
    pd_blocker = "; ".join(str(error.get("error") or error) for error in pd_errors) or "none"
    main_teams = ["France", "Argentina", "Spain", "England", "Brazil", "Portugal"]
    main_lines = []
    for team in main_teams:
        key = normalize_name(team)
        row = next((item for item in rows if normalize_name(str(item.get("team") or "")) == key), None)
        if not row:
            continue
        main_lines.append(
            "- "
            f"{team}: PM yes {row.get('pm_yes_bid1')}/{row.get('pm_yes_ask1')}, "
            f"PM no {row.get('pm_no_bid1')}/{row.get('pm_no_ask1')}; "
            f"PD yes {row.get('pd_yes_bid1')}/{row.get('pd_yes_ask1')}, "
            f"PD no {row.get('pd_no_bid1')}/{row.get('pd_no_ask1')}; "
            f"edges {row.get('edge_pm_yes_pd_no')}/{row.get('edge_pd_yes_pm_no')}"
        )

    def format_rows(items: list[dict[str, Any]]) -> str:
        if not items:
            return "- none"
        return "\n".join(
            f"- {row['team']}: max_abs_diff={top_abs_diff(row)}, "
            f"yes_ask_diff={row['diff_yes_ask_pm_minus_pd']}, "
            f"no_ask_diff={row['diff_no_ask_pm_minus_pd']}"
            for row in items
        )

    recommend = bool(pd_winner_found and pm_winner_found and len(matched_with_books) >= 5)
    readiness = "READY_FOR_MVP3_B_DESIGN" if recommend else "NOT_READY"
    if positive_edges:
        readiness = "PARTIAL_READY_REVIEW_SIGNALS_ONLY"
    interpretation = (
        "PM and PD YES bid/ask prices are on the same 0-1 scale for matched rows."
        if pd_winner_found
        else "PM prices are available, but PD winner prices are unavailable in this run because the Predict.fun API did not return winner markets."
    )
    content = f"""# MVP3-A3 Winner Price Compare Review

- reviewed_at: {now_iso()}
- pd_market_slug: {pd_slug}
- live_allowed: false
- orders_submitted: false
- execution_called: false
- formal_arbitrage_candidates_generated: false

## Required Answers

1. Predict.fun winner market located: {str(pd_winner_found).lower()} ({len(pd_markets.get("markets", []))} outcome markets)
2. PM winner market located: {str(pm_winner_found).lower()} ({len(pm_markets.get("markets", []))} outcome markets)
3. Country mappings matched: {len(matched)}
4. Country mappings with both orderbooks: {len(matched_with_books)}
5. PD NO price source: `derived_from_yes_book` when `decimalPrecision` and YES book are present.
6. Positive edge sanity signals: {len(positive_edges)} (`potential_signal_for_review`, not candidates)
7. MVP3-B scanner recommendation: {readiness}
8. Current PD blocker: {pd_blocker}

## Predict.fun Winner Market Metadata

- pd_market_id: {"per-country market IDs, not one single aggregate market ID in the API response" if pd_winner_found else "PD_WINNER_MARKET_NOT_FOUND"}
- pd_market_slug: {pd_slug}
- pd_market_title: {"2026 FIFA World Cup Winner page / per-country titles" if pd_winner_found else "UNKNOWN / NEEDS_RECHECK"}
- pd_market_type/category: {"`categorySlug=" + pd_slug + "`" if pd_winner_found else "UNKNOWN / NEEDS_RECHECK"}
- pd_status: {"see per-market `status` / `tradingStatus`" if pd_winner_found else "UNKNOWN / NEEDS_RECHECK"}
- pd_outcome_count: {len(pd_markets.get("markets", []))}
- pd_decimal_precision: checked per row; used for NO derivation when present
- pd_tick_size: UNKNOWN / NEEDS_RECHECK
- pd_min_order_size: `shareThreshold` present per market, exact order minimum semantics NEEDS_RECHECK

## PM Winner Market Metadata

- pm_market_id: per-country PM market IDs
- pm_market_slug: per-country PM market slugs under event `world-cup-winner`
- pm_market_title: World Cup Winner / 2026 FIFA World Cup Winner
- pm_status: active/open/accepting orders for discovered rows
- pm_outcome_count: {len(pm_markets.get("markets", []))}

## Main Countries

{chr(10).join(main_lines) if main_lines else "- none"}

## Closest PM-PD Prices

{format_rows(closest)}

## Largest PM-PD Price Differences

{format_rows(largest)}

## Interpretation

{interpretation}

When PD winner orderbooks are available, sampled NO prices should be derived from the YES-side book using:

```text
pd_no_bid1 = round(1 - pd_yes_ask1, decimalPrecision)
pd_no_ask1 = round(1 - pd_yes_bid1, decimalPrecision)
```

Any positive `edge_pm_yes_pd_no` or `edge_pd_yes_pm_no` is only a `potential_signal_for_review`. This script does not generate formal scanner candidates and does not call execution.

## UNKNOWN / NEEDS_RECHECK

- Locate Predict.fun winner outcome markets through API. Current blocker: {pd_blocker}.
- Confirm whether API `shareThreshold` is the effective min order size.
- Confirm Predict.fun tick size if it differs from `decimalPrecision`.
- Confirm full-depth derived NO size semantics.
- Confirm quote freshness policy using `updateTimestampMs`.
- Confirm PM/PD settlement, cancellation, void, and dispute rules are equivalent for each country.
- Confirm Predict.fun fee interpretation from `feeRateBps`.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP3-A read-only PM vs Predict.fun data probe.")
    parser.add_argument("--query", default="World Cup")
    parser.add_argument("--max-markets", type=int, default=20)
    parser.add_argument("--sample-orderbooks", type=int, default=5)
    parser.add_argument("--pd-market-url", default="")
    parser.add_argument("--pd-market-slug", default="")
    parser.add_argument("--compare-winner-prices", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    max_markets = max(1, args.max_markets)
    sample_orderbooks = max(0, args.sample_orderbooks)
    PM_RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pm.load_env()

    pm_markets = pm_search_markets(args.query, max_markets)
    pm_books = pm_fetch_orderbook_samples(pm_markets.get("markets", []), sample_orderbooks)
    pd_slug = pd_slug_from_url(args.pd_market_url, args.pd_market_slug)
    if args.compare_winner_prices and pd_slug:
        pd_markets = pd_find_markets_by_slug(pd_slug, max_markets)
    else:
        pd_markets = pd_search_markets(args.query, max_markets)
    pd_books = pd_fetch_orderbook_samples(pd_markets.get("markets", []), sample_orderbooks)

    write_json(PM_RAW_DIR / "pm_markets_raw.json", pm_markets)
    write_json(PM_RAW_DIR / "pm_orderbook_sample_raw.json", pm_books)
    write_json(PM_RAW_DIR / "pd_markets_raw.json", pd_markets)
    write_json(PM_RAW_DIR / "pd_orderbook_sample_raw.json", pd_books)
    if args.compare_winner_prices:
        write_json(PM_RAW_DIR / "pd_winner_markets_raw.json", pd_markets)
        write_json(PM_RAW_DIR / "pd_winner_orderbook_sample_raw.json", pd_books)

    rows = build_csv_rows(
        args.query,
        pm_markets.get("markets", []),
        pm_books,
        pd_markets.get("markets", []),
        pd_books,
    )
    write_csv(OUTPUT_DIR / "mvp3_a_market_candidates.csv", rows)
    write_summary(
        OUTPUT_DIR / "mvp3_a_probe_summary.md",
        query=args.query,
        pm_markets=pm_markets,
        pm_books=pm_books,
        pd_markets=pd_markets,
        pd_books=pd_books,
    )
    if args.compare_winner_prices:
        winner_rows = build_winner_price_rows(
            pm_markets=pm_markets.get("markets", []),
            pm_books=pm_books,
            pd_markets=pd_markets.get("markets", []),
            pd_books=pd_books,
        )
        write_winner_compare_csv(OUTPUT_DIR / "mvp3_a3_winner_price_compare.csv", winner_rows)
        write_winner_review(
            OUTPUT_DIR / "mvp3_a3_winner_price_compare_review.md",
            pd_slug=pd_slug,
            pm_markets=pm_markets,
            pd_markets=pd_markets,
            rows=winner_rows,
        )

    print("MVP3-A PM vs Predict.fun probe complete (read-only).")
    print(f"PM markets: {len(pm_markets.get('markets', []))}")
    print(f"PM orderbook samples: {len(pm_books.get('samples', []))}")
    print(f"Predict.fun markets: {len(pd_markets.get('markets', []))}")
    print(f"Predict.fun orderbook samples: {len(pd_books.get('samples', []))}")
    if args.compare_winner_prices:
        print(f"Winner compare CSV: {OUTPUT_DIR / 'mvp3_a3_winner_price_compare.csv'}")
        print(f"Winner compare review: {OUTPUT_DIR / 'mvp3_a3_winner_price_compare_review.md'}")
    print(f"Raw JSON dir: {PM_RAW_DIR}")
    print(f"Summary: {OUTPUT_DIR / 'mvp3_a_probe_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
