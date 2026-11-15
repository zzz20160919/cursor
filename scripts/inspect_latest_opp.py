import sqlite3
import json

DB = "data/lab.sqlite"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

row = conn.execute("""
select
  id, run_id, strategy_id, ts,
  venue_1, venue_2,
  instrument_1, instrument_2,
  opportunity_type,
  gross_edge, estimated_cost, net_edge,
  executable_size, status, notes, raw_json
from opportunities
order by id desc
limit 1
""").fetchone()

if row is None:
    print("No opportunity rows found.")
    raise SystemExit

for k in row.keys():
    if k != "raw_json":
        print(f"{k}: {row[k]}")

print("\nraw_json:")
try:
    print(json.dumps(json.loads(row["raw_json"]), indent=2, ensure_ascii=False))
except Exception:
    print(row["raw_json"])

conn.close()
