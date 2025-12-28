import duckdb
import json
import numpy as np
from datetime import datetime

DB_PATH = "data/trading.db"
OUTPUT_FILE = "data/momentum_thresholds.json"

print("="*80)
print("NIFTY MOMENTUM ANALYSIS - 5MIN CANDLES (CORRECTED)")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Check candles_5min table
    print("\n1. Checking candles_5min table...")
    
    # Get date range
    date_range = conn.execute("""
        SELECT 
            MIN(timestamp::DATE) as min_date,
            MAX(timestamp::DATE) as max_date,
            COUNT(DISTINCT timestamp::DATE) as total_days
        FROM candles_5min
    """).fetchone()
    
    print(f"   Date Range: {date_range[0]} to {date_range[1]}")
    print(f"   Total Days: {date_range[2]}")
    
    # Analyze daily momentum from 5min candles
    print("\n2. Calculating daily momentum from 5min candles...")
    
    query = """
        SELECT 
            timestamp::DATE as trade_date,
            MIN(open) as day_open,
            MAX(high) as day_high,
            MIN(low) as day_low,
            MAX(high) - MIN(low) as daily_range,
            MAX(high) - MIN(open) as upside_from_open,
            MIN(open) - MIN(low) as downside_from_open,
            GREATEST(MAX(high) - MIN(open), MIN(open) - MIN(low)) as max_directional_move,
            COUNT(*) as candle_count
        FROM candles_5min
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '4 years'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 20  -- At least 20 5min candles = ~2 hours of data
        ORDER BY trade_date DESC
    """
    
    results = conn.execute(query).fetchall()
    
    print(f"   Analyzed: {len(results)} trading days\n")
    
    # Show samples
    print("3. Recent Sample Days:")
    print(f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Range':>8} {'Max Dir':>8} {'Candles':>8}")
    print("-"*76)
    for r in results[:15]:
        print(f"{str(r[0]):<12} {r[1]:>10.1f} {r[2]:>10.1f} {r[3]:>10.1f} {r[4]:>8.1f} {r[7]:>8.1f} {r[8]:>8}")
    
    if len(results) < 50:
        print(f"\n⚠️ WARNING: Only {len(results)} days found - insufficient for reliable analysis")
        print("   Using conservative defaults...")
        
        thresholds = {
            "instrument": "NIFTY (insufficient data)",
            "avg1": 150.0,
            "avg2": 250.0,
            "avg3": 350.0,
            "data_source": "conservative_defaults",
            "sample_size": len(results)
        }
    else:
        # Calculate thresholds
        max_directional = [r[7] for r in results]
        
        avg1 = np.percentile(max_directional, 33)
        avg2 = np.percentile(max_directional, 66)
        avg3 = np.percentile(max_directional, 90)
        
        median_range = np.median([r[4] for r in results])
        mean_range = np.mean([r[4] for r in results])
        max_ever = np.max(max_directional)
        
        thresholds = {
            "instrument": "NIFTY (from 5min candles)",
            "avg1": round(avg1, 1),
            "avg2": round(avg2, 1),
            "avg3": round(avg3, 1),
            "median_daily_range": round(median_range, 1),
            "mean_daily_range": round(mean_range, 1),
            "max_directional_ever": round(max_ever, 1),
            "data_source": "nifty_5min_historical_analysis",
            "sample_size": len(results),
            "analysis_date": datetime.now().isoformat()
        }
        
        print("\n" + "="*80)
        print("NIFTY MOMENTUM THRESHOLDS (FROM 5MIN CANDLES)")
        print("="*80)
        print(f"\n📊 Based on {len(results)} NIFTY trading days:")
        print(f"\n  avg1 (33rd percentile): {avg1:>6.1f} pts")
        print(f"  avg2 (66th percentile): {avg2:>6.1f} pts")
        print(f"  avg3 (90th percentile): {avg3:>6.1f} pts")
        print(f"\n📈 Daily Range Statistics:")
        print(f"  Median: {median_range:>6.1f} pts")
        print(f"  Mean:   {mean_range:>6.1f} pts")
        print(f"  Max:    {max_ever:>6.1f} pts")
        
        # Distribution
        below_avg1 = len([m for m in max_directional if m < avg1])
        between_avg1_avg2 = len([m for m in max_directional if avg1 <= m < avg2])
        between_avg2_avg3 = len([m for m in max_directional if avg2 <= m < avg3])
        above_avg3 = len([m for m in max_directional if m >= avg3])
        
        total = len(max_directional)
        print(f"\n📉 Distribution:")
        print(f"  < avg1:        {below_avg1:>4} days ({below_avg1/total*100:.1f}%)")
        print(f"  avg1 - avg2:   {between_avg1_avg2:>4} days ({between_avg1_avg2/total*100:.1f}%)")
        print(f"  avg2 - avg3:   {between_avg2_avg3:>4} days ({between_avg2_avg3/total*100:.1f}%)")
        print(f"  > avg3:        {above_avg3:>4} days ({above_avg3/total*100:.1f}%)")
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(thresholds, f, indent=2)
    
    print(f"\n✅ Thresholds saved to: {OUTPUT_FILE}")
    print("="*80)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
