import duckdb
import json

conn = duckdb.connect('/app/data/trading.db', read_only=True)

# Get all experience records with their PnL
print("=== EXPERIENCE REPLAY DATA ===")
records = conn.execute("""
    SELECT session_id, date, symbol, total_pnl, eod_audit 
    FROM experience_replay 
    ORDER BY total_pnl DESC
""").fetchall()

print(f"Total records: {len(records)}")
print("\n=== BY PROFITABILITY ===")
for sid, date, sym, pnl, audit_json in records:
    pnl_icon = "✅" if pnl > 0 else "❌"
    print(f"{pnl_icon} {date} | {sym} | PnL: {pnl:+.1f}")
    
    # Parse EOD audit if available
    if audit_json:
        try:
            audit = json.loads(audit_json)
            # Look for nuggets inside the audit
            if audit.get('nugget_good'):
                print(f"   GOOD: {audit['nugget_good'][:80]}")
            if audit.get('nugget_bad'):
                print(f"   BAD: {audit['nugget_bad'][:80]}")
            if audit.get('final_online_feedback'):
                print(f"   FEEDBACK: {audit['final_online_feedback'][:80]}")
        except:
            pass
    print()

conn.close()
