import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from statistics import mean, median

def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def get_calc(row):
    try:
        raw = json.loads(row["raw_json"] or "{}")
    except Exception:
        raw = {}
    calc = raw.get("calculation", raw)
    return raw, calc

def fnum(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

parser = argparse.ArgumentParser()
parser.add_argument("--market", default="WC-Portugal-Champion")
parser.add_argument("--hours", type=float, default=12)
parser.add_argument("--per-strategy-notional", type=float, default=20)
args = parser.parse_args()

db = "data/lab.sqlite"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
select id, run_id, strategy_id, ts, status, gross_edge, estimated_cost, net_edge,
       executable_size, notes, raw_json
from opportunities
order by id asc
""").fetchall()

cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)

filtered = []
for r in rows:
    ts = parse_ts(r["ts"])
    raw, calc = get_calc(r)
    market = calc.get("market") or raw.get("market") or ""
    if args.market and market != args.market:
        continue
    if ts and ts < cutoff:
        continue
    filtered.append((r, raw, calc, ts))

print("=" * 80)
print(f"PM-HL MONITOR REVIEW")
print(f"market: {args.market}")
print(f"hours: last {args.hours}")
print(f"rows: {len(filtered)}")
print("=" * 80)

if not filtered:
    print("No rows found.")
    raise SystemExit

statuses = {}
positive = []
actionable = []
gross_pos_net_neg = []
candidate_s1s2 = []

for r, raw, calc, ts in filtered:
    status = r["status"] or calc.get("status") or raw.get("status") or "unknown"
    statuses[status] = statuses.get(status, 0) + 1

    net = fnum(calc.get("net_edge"), fnum(r["net_edge"]))
    gross = fnum(calc.get("gross_edge"), fnum(r["gross_edge"]))
    fee = fnum(calc.get("estimated_cost"), fnum(r["estimated_cost"]))
    size = fnum(calc.get("executable_size"), fnum(r["executable_size"]))
    entry_cost = fnum(calc.get("entry_cost"), None)
    if entry_cost is None:
        cost = fnum(calc.get("cost"), None)
        entry_cost = cost
    if entry_cost is None and gross is not None:
        entry_cost = 1 - gross

    if gross is not None and net is not None and gross > 0 and net <= 0:
        gross_pos_net_neg.append((r, raw, calc, ts))

    if net is not None and net > 0:
        positive.append((r, raw, calc, ts))

    if status == "dry_run_observed" or (net is not None and net > 0):
        actionable.append((r, raw, calc, ts))

    if net is not None and net > 0 and entry_cost and size:
        s1_shares = args.per_strategy_notional / entry_cost
        s2_shares = args.per_strategy_notional / entry_cost
        combined_required = s1_shares + s2_shares
        if size >= combined_required:
            candidate_s1s2.append((r, raw, calc, ts, combined_required))

print("\nSTATUS COUNTS")
for k, v in sorted(statuses.items()):
    print(f"  {k}: {v}")

nets = [fnum(c.get("net_edge"), fnum(r["net_edge"])) for r, raw, c, ts in filtered]
nets = [x for x in nets if x is not None]
if nets:
    print("\nNET EDGE SUMMARY")
    print(f"  min:    {min(nets):.6f}")
    print(f"  median: {median(nets):.6f}")
    print(f"  mean:   {mean(nets):.6f}")
    print(f"  max:    {max(nets):.6f}")

print("\nCOUNTS")
print(f"  positive net_edge rows:        {len(positive)}")
print(f"  actionable/dry_run rows:       {len(actionable)}")
print(f"  gross positive but net <= 0:   {len(gross_pos_net_neg)}")
print(f"  S1+S2 20 each depth candidates:{len(candidate_s1s2)}")

def print_row(label, item, include_combined=False):
    if include_combined:
        r, raw, calc, ts, combined_required = item
    else:
        r, raw, calc, ts = item
        combined_required = None

    gross = fnum(calc.get("gross_edge"), fnum(r["gross_edge"]))
    fee = fnum(calc.get("estimated_cost"), fnum(r["estimated_cost"]))
    net = fnum(calc.get("net_edge"), fnum(r["net_edge"]))
    size = fnum(calc.get("executable_size"), fnum(r["executable_size"]))
    exp = fnum(calc.get("expected_profit"), fnum(calc.get("net_profit")))
    cost = fnum(calc.get("entry_cost"), fnum(calc.get("cost")))
    if cost is None and gross is not None:
        cost = 1 - gross
    direction = calc.get("selected_dir") or calc.get("taker_dir") or calc.get("dir") or ""
    print(f"{label} id={r['id']} ts={r['ts']} dir={direction} cost={cost} gross={gross} fee={fee} net={net} size={size} exp={exp} status={r['status']}")
    if combined_required is not None:
        print(f"       combined_required_shares_for_S1S2={combined_required:.4f}")

if positive:
    best = max(positive, key=lambda x: fnum(x[2].get("net_edge"), fnum(x[0]["net_edge"], -999)))
    print("\nBEST POSITIVE ROW")
    print_row("BEST", best)

if candidate_s1s2:
    best_c = max(candidate_s1s2, key=lambda x: fnum(x[2].get("net_edge"), fnum(x[0]["net_edge"], -999)))
    print("\nBEST S1+S2 20 EACH DEPTH CANDIDATE")
    print_row("BEST_COMBINED", best_c, include_combined=True)

print("\nLAST 20 ROWS")
for item in filtered[-20:]:
    print_row("ROW", item)

print("\nTOP 20 POSITIVE NET EDGE ROWS")
top_pos = sorted(positive, key=lambda x: fnum(x[2].get("net_edge"), fnum(x[0]["net_edge"], -999)), reverse=True)[:20]
for item in top_pos:
    print_row("POS", item)

print("\nTOP 20 S1+S2 DEPTH CANDIDATES")
top_c = sorted(candidate_s1s2, key=lambda x: fnum(x[2].get("net_edge"), fnum(x[0]["net_edge"], -999)), reverse=True)[:20]
for item in top_c:
    print_row("CAND", item, include_combined=True)

conn.close()
