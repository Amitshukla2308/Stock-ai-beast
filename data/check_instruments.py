import duckdb

DB_PATH = "data/trading.db"

print("="*80)
print("CHECKING AVAILABLE INSTRUMENTS IN DATABASE")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Check what data we have
    print("\n1. Tables in database:")
    tables = conn.execute("SHOW TABLES").fetchall()
    for table in tables:
        print(f"  - {table[0]}")
    
    # Check candles_1min data
    print("\n2. Sample data from candles_1min:")
    sample = conn.execute("""
        SELECT timestamp, open, high, low, close
        FROM candles_1min
        ORDER BY timestamp DESC
        LIMIT 5
    """).fetchall()
    
    print(f"{'Timestamp':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
    print("-"*70)
    for row in sample:
        print(f"{str(row[0]):<20} {row[1]:>10.2f} {row[2]:>10.2f} {row[3]:>10.2f} {row[4]:>10.2f}")
    
    # Check price range to determine instrument
    price_range = conn.execute("""
        SELECT 
            MIN(close) as min_price,
            MAX(close) as max_price,
            AVG(close) as avg_price
        FROM candles_1min
        WHERE timestamp >= CURRENT_DATE - INTERVAL '30 days'
    """).fetchone()
    
    print(f"\n3. Price Range (last 30 days):")
    print(f"  Min: {price_range[0]:,.2f}")
    print(f"  Max: {price_range[1]:,.2f}")
    print(f"  Avg: {price_range[2]:,.2f}")
    
    # Determine instrument
    avg_price = price_range[2]
    if avg_price > 50000:
        instrument = "NIFTY INDEX (~59,000)"
    elif avg_price > 40000:
        instrument = "BANKNIFTY INDEX (~52,000)"
    elif avg_price > 20000:
        instrument = "NIFTY FUTURES (~23,000)"
    else:
        instrument = "Unknown"
    
    print(f"\n4. Detected Instrument: {instrument}")
    
    # Check if there's a symbol column or multiple instruments
    try:
        symbols = conn.execute("""
            SELECT DISTINCT symbol
            FROM candles_1min
            LIMIT 10
        """).fetchall()
        print(f"\n5. Symbols found:")
        for sym in symbols:
            print(f"  - {sym[0]}")
    except:
        print(f"\n5. No 'symbol' column found - single instrument database")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
