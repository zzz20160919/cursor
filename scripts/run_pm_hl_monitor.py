from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import connect, get_row_counts, init_db, insert_row  # noqa: E402
from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402
from src.strategies.pm_hl.opportunity_model import (  # noqa: E402
    load_markets,
    mock_scan_result,
    scan_market,
    to_opportunity_row,
)


STRATEGY_ID = "pm_hl"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return f"pm_hl_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def scan_once(use_mock: bool) -> tuple[dict, bool]:
    if use_mock:
        return mock_scan_result(), True

    markets = load_markets(include_world_cup=True)
    errors: list[str] = []
    for market in markets:
        try:
            result = scan_market(market)
            if result:
                return result, False
        except Exception as exc:
            errors.append(f"{market.get('name')}: {str(exc)[:100]}")

    print("Live scan did not produce an opportunity snapshot; using mock dry-run sample.")
    if errors:
        print("Scan errors:")
        for error in errors[:5]:
            print(f"  {error}")
    return mock_scan_result(), True


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor PM-HL opportunities and write SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="Safe mode; no orders are placed.")
    parser.add_argument("--mock", action="store_true", help="Force mock opportunity input.")
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    db_path = init_db()
    rid = run_id()
    ts = now_iso()

    if pm.missing_env(("PM_PRIVATE_KEY",)):
        print("Missing optional PM secret(s): PM_PRIVATE_KEY")
    if hl.missing_env(("HL_AGENT_KEY",)):
        print("Missing optional HL secret(s): HL_AGENT_KEY")
    print("Monitor mode: DRY/RISK-OFF. This script does not place orders.")

    result, used_mock = scan_once(use_mock=args.mock)
    row = to_opportunity_row(rid, STRATEGY_ID, result)
    if used_mock:
        raw = json.loads(row["raw_json"])
        raw["source"] = "pm_hl_monitor_mock"
        raw["mock"] = True
        row["raw_json"] = json.dumps(raw, sort_keys=True)
        row["notes"] = row["notes"] + " (mock)"

    with connect(db_path) as conn:
        insert_row(
            conn,
            "runs",
            {
                "run_id": rid,
                "run_type": "pm_hl_monitor",
                "strategy_id": STRATEGY_ID,
                "started_at": ts,
                "finished_at": now_iso(),
                "status": "dry_run_completed",
                "notes": "pm_hl monitor dry_run",
                "created_at": ts,
            },
        )
        opportunity_id = insert_row(conn, "opportunities", row)
        conn.commit()
        counts = get_row_counts(conn)

    print(f"SQLite database: {db_path}")
    print(f"Inserted opportunity id: {opportunity_id}")
    print(f"run_id: {rid}")
    print(f"market: {result.get('market')}")
    print(f"net_edge: {float(result.get('net_edge') or 0):.6f}")
    print(f"apr: {float(result.get('apr') or 0):.6f}")
    print("Row counts:")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
