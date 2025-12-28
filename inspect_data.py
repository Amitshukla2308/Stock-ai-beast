import duckdb
import pandas as pd
from data.database import get_connection

def inspect_features():
    conn = get_connection()
    try:
        # Get row count
        count = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        print(f"✅ Total Feature Rows: {count}")
        
        # Get sample data
        print("\n🔍 Recent 5 rows Data Snapshot:")
        df = conn.execute("SELECT * FROM features ORDER BY timestamp DESC LIMIT 5").fetchdf()
        
        # Display specific columns of interest
        cols = ['timestamp', 'symbol', 'close', 'rsi', 'volatility', 'delta', 'gamma', 'theta']
        # Note: close/symbol might not be in features table definition in database.py? 
        # Let's check the schema in database.py again or just select *
        # Schema in database.py: timestamp, symbol, sma_fast, sma_slow, trend, rsi, atr, volatility, bb_upper, bb_lower, delta, gamma, theta, vega, regime
        
        # Adjust cols to what we actually stored
        display_cols = ['timestamp', 'symbol', 'rsi', 'volatility', 'delta', 'gamma', 'theta', 'vega']
        print(df[display_cols].to_string(index=False))
        
    except Exception as e:
        print(f"❌ Error inspecting DB: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect_features()
