from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import connect, get_row_counts, init_db, insert_row  # noqa: E402


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def smoke_json(kind: str) -> str:
    return json.dumps({"source": "smoke_test", "kind": kind}, sort_keys=True)


def main() -> None:
    db_path = init_db()
    ts = now_iso()
    run_id = f"smoke_test_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    with connect(db_path) as conn:
        insert_row(
            conn,
            "runs",
            {
                "run_id": run_id,
                "run_type": "smoke_test",
                "strategy_id": "smoke_test",
                "started_at": ts,
                "finished_at": ts,
                "status": "completed",
                "notes": "smoke_test run",
                "created_at": ts,
            },
        )

        asset_id = insert_row(
            conn,
            "assets",
            {
                "symbol": "SMOKE_TEST",
                "asset_class": "test",
                "venue": "smoke_test",
                "description": "smoke_test asset",
                "created_at": ts,
            },
        )

        insert_row(
            conn,
            "market_snapshots",
            {
                "asset_id": asset_id,
                "ts": ts,
                "source": "smoke_test",
                "price": 1.0,
                "bid": 0.99,
                "ask": 1.01,
                "volume": 100.0,
                "raw_json": smoke_json("market_snapshot"),
                "created_at": ts,
            },
        )

        insert_row(
            conn,
            "strategy_signals",
            {
                "run_id": run_id,
                "strategy_id": "smoke_test",
                "asset_id": asset_id,
                "ts": ts,
                "signal": "observe",
                "confidence": 1.0,
                "reason": "smoke_test signal",
                "raw_json": smoke_json("strategy_signal"),
                "created_at": ts,
            },
        )

        insert_row(
            conn,
            "opportunities",
            {
                "run_id": run_id,
                "strategy_id": "smoke_test",
                "ts": ts,
                "venue_1": "smoke_test_venue_1",
                "venue_2": "smoke_test_venue_2",
                "instrument_1": "SMOKE_TEST_A",
                "instrument_2": "SMOKE_TEST_B",
                "opportunity_type": "smoke_test",
                "gross_edge": 0.02,
                "estimated_cost": 0.005,
                "net_edge": 0.015,
                "executable_size": 10.0,
                "status": "observed",
                "notes": "smoke_test opportunity",
                "raw_json": smoke_json("opportunity"),
                "created_at": ts,
            },
        )

        conn.commit()
        counts = get_row_counts(conn)

    print(f"Smoke test inserted run_id: {run_id}")
    print("Row counts:")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
