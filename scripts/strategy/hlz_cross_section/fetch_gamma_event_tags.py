#!/usr/bin/env python3
"""Fetch current Gamma tags for events in the A.3 priced panel.

Tags are the live Gamma labels, not a formation-time snapshot.
Single-event GET is used because repeated id query parameters are ignored.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = REPO / "outputs/strategy/hlz_cross_section"
CACHE = OUT / "cache/gamma_event_tags.jsonl"
META = OUT / "cache/gamma_event_tags_meta.json"
FACTOR = OUT / "a3_factor_daily.parquet"
UNIVERSE = OUT / "paper_sample_markets_a3.csv"
HK = ZoneInfo("Asia/Hong_Kong")
_LIMIT = threading.Lock()
_NEXT = 0.0


def wait_turn() -> None:
    global _NEXT
    with _LIMIT:
        now = time.monotonic()
        slot = max(now, _NEXT)
        _NEXT = slot + 0.04  # about 25 requests per second
        delay = slot - now
    if delay > 0:
        time.sleep(delay)


def event_ids() -> list[str]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        WITH priced AS (
          SELECT DISTINCT market_id
          FROM read_parquet('{FACTOR}')
        ),
        uni AS (
          SELECT market_id, event_id
          FROM read_csv('{UNIVERSE}', header=true, all_varchar=true)
        )
        SELECT DISTINCT u.event_id
        FROM priced p
        JOIN uni u ON u.market_id = p.market_id
        WHERE u.event_id IS NOT NULL AND u.event_id <> ''
        ORDER BY 1
        """
    ).fetchall()
    return [row[0] for row in rows]


def cached_ids() -> set[str]:
    found: set[str] = set()
    if not CACHE.exists():
        return found
    with CACHE.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            found.add(str(record.get("id") or ""))
    found.discard("")
    return found


def fetch_one(event_id: str) -> dict:
    url = f"https://gamma-api.polymarket.com/events/{event_id}"
    request = urllib.request.Request(url, headers={"User-Agent": "hlz-cat12", "Accept-Encoding": "gzip"})
    delay = 1.0
    last: Exception | None = None
    for _attempt in range(5):
        wait_turn()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                payload = json.loads(raw.decode())
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"id": event_id, "missing": True, "tags": [], "category": None}
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 20)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 20)
    else:
        raise RuntimeError(f"event {event_id} failed") from last
    tags = []
    for tag in payload.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        tags.append({"label": tag.get("label") or "", "slug": tag.get("slug") or ""})
    return {
        "id": str(payload.get("id") or event_id),
        "category": payload.get("category"),
        "tags": tags,
    }


def main() -> int:
    ids = event_ids()
    have = cached_ids()
    needed = [event_id for event_id in ids if event_id not in have and event_id.isdigit()]
    started = datetime.now(HK).isoformat(timespec="seconds")
    print(f"events {len(ids)} cached {len(have)} remaining {len(needed)} started {started}", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    done = 0
    with CACHE.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(fetch_one, event_id) for event_id in needed]
            for future in as_completed(futures):
                record = future.result()
                with lock:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                done += 1
                if done % 500 == 0 or done == len(needed):
                    print(f"tags {done}/{len(needed)}", flush=True)
    finished = datetime.now(HK).isoformat(timespec="seconds")
    META.write_text(
        json.dumps(
            {
                "started_at_asia_hong_kong": started,
                "finished_at_asia_hong_kong": finished,
                "n_events": len(ids),
                "note": "Gamma tags are the live event labels at fetch time, not a 4:00 p.m. formation snapshot.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"done {finished}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
