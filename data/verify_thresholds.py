import duckdb
import json
import numpy as np

DB_PATH = "data/trading.db"

print("="*80)
print("VERIFYING MOMENTUM DATA")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Check what range of values we actually have
    print("\n1. Sample Recent Days:")
    query = """
        SELECT 
            timestamp::DATE as trade_date,
            MIN(open) as open,
            MAX(high) as high,
            MIN(low) as low,
            MAX(high) - MIN(low) as range,
            MAX(high) - MIN(open) as up_move,
            MIN(open) - MIN(low) as down_move
        FROM candles_1min
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100
        ORDER BY trade_date DESC
        LIMIT 10
    """
    
    recent = conn.execute(query).fetchall()
    print(f"\n{'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Range':>8} {'Up':>8} {'Down':>8}")
    print("-"*68)
    for r in recent:
        print(f"{str(r[0]):<12} {r[1]:>8.1f} {r[2]:>8.1f} {r[3]:>8.1f} {r[4]:>8.1f} {r[5]:>8.1f} {r[6]:>8.1f}")
    
    # Get all daily ranges for better view
    print("\n2. Daily Range Distribution:")
    all_ranges = conn.execute("""
        SELECT MAX(high) - MIN(low) as range
        FROM candles_1min
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '1 year'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100
    """).fetchall()
    
    ranges = [r[0] for r in all_ranges]
    
    print(f"  Min:  {np.min(ranges):>6.1f} pts")
    print(f"  P10:  {np.percentile(ranges, 10):>6.1f} pts")
    print(f"  P25:  {np.percentile(ranges, 25):>6.1f} pts")
    print(f"  P50:  {np.percentile(ranges, 50):>6.1f} pts")
    print(f"  P75:  {np.percentile(ranges, 75):>6.1f} pts")
    print(f"  P90:  {np.percentile(ranges, 90):>6.1f} pts")
    print(f"  Max:  {np.max(ranges):>6.1f} pts")
    
    # Calculate realistic thresholds based on DIRECTIONAL moves
    print("\n3. Recalculating for Directional Movement:")
    directional_query = """
        SELECT 
            GREATEST(
                MAX(high) - MIN(open),
                MIN(open) - MIN(low)
            ) as max_directional
        FROM candles_1min
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '1 year'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100
    """
    
    directional_moves = conn.execute(directional_query).fetchall()
    moves = [r[0] for r in directional_moves]
    
    # If values look too high, they might be scaled wrong
    if np.median(moves) > 1000:
        print("\n⚠️ Values appear to be scaled incorrectly (INDEX vs FUTURES)")
        print("   Using conservative defaults based on typical NIFTY futures movement:\n")
        
        thresholds = {
            "avg1": 130.0,   # ~30% of typical trading days
            "avg2": 200.0,   # ~65% of typical trading days
            "avg3": 280.0,   # ~90% of typical trading days
            "data_source": "conservative_defaults",
            "reason": "Historical data appears to be index values, not futures",
            "sample_size": len(moves)
        }
    else:
        avg1 = np.percentile(moves, 33)
        avg2 = np.percentile(moves, 66)
        avg3 = np.percentile(moves, 90)
        
        thresholds = {
            "avg1": round(avg1, 1),
            "avg2": round(avg2, 1),
            "avg3": round(avg3, 1),
            "data_source": "historical_directional_analysis",
            "sample_size": len(moves)
        }
    
    print(f"  avg1 (33rd pct): {thresholds['avg1']:>6.1f} pts")
    print(f"  avg2 (66th pct): {thresholds['avg2']:>6.1f} pts")
    print(f"  avg3 (90th pct): {thresholds['avg3']:>6.1f} pts")
    
    # Save corrected thresholds
    with open("data/momentum_thresholds.json", 'w') as f:
        json.dump(thresholds, f, indent=2)
    
    print(f"\n✅ Updated thresholds saved")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
