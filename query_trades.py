import duckdb
import pandas as pd
import sys

# Connect to DB
try:
    conn = duckdb.connect('data/trading.db', read_only=True)
except Exception as e:
    print(f"Error connecting to DB: {e}")
    sys.exit(1)

session_id = 'BACKTEST_20260117_150509'

query = f"""
    SELECT * 
    FROM simulation_trades 
    WHERE session_id = '{session_id}' 
    ORDER BY entry_time ASC
"""

try:
    df = conn.execute(query).fetchdf()
    if df.empty:
        print(f"No trades found for session: {session_id}")
    else:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.max_rows', None)
        # Select key columns for readability
        cols = ['entry_time', 'side', 'entry_price', 'exit_price', 'pnl', 'style', 'reason']
        # Check intersection with actual columns
        actual_cols = df.columns.tolist()
        final_cols = [c for c in cols if c in actual_cols]
        if not final_cols: final_cols = actual_cols # Fallback
        
        print(df[final_cols].to_string(index=False))
except Exception as e:
    print(f"Query failed: {e}")
finally:
    conn.close()
