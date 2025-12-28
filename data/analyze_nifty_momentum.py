import duckdb
import json
import numpy as np
from datetime import datetime

DB_PATH = "data/trading.db"
OUTPUT_FILE = "data/momentum_thresholds.json"

print("="*80)
print("NIFTY-ONLY MOMENTUM ANALYSIS (CORRECTED)")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Analyze NIFTY only
    print("\nFiltering for: NSE:NIFTY50-INDEX")
    
    query = """
        SELECT 
            timestamp::DATE as trade_date,
            MIN(open) as day_open,
            MAX(high) as day_high,
            MIN(low) as day_low,
            MAX(high) - MIN(low) as daily_range,
            MAX(high) - MIN(open) as upside_from_open,
            MIN(open) - MIN(low) as downside_from_open,
            GREATEST(MAX(high) - MIN(open), MIN(open) - MIN(low)) as max_directional_move
        FROM candles_1min
        WHERE symbol = 'NSE:NIFTY50-INDEX'
          AND timestamp::DATE >= CURRENT_DATE - INTERVAL '4 years'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100
        ORDER BY trade_date DESC
    """
    
    results = conn.execute(query).fetchall()
    
    print(f"Analyzed {len(results)} NIFTY trading days\n")
    
    if len(results) == 0:
        print("⚠️ No NIFTY data found. Check symbol name.")
    else:
        # Show recent samples
        print("Recent NIFTY Days:")
        print(f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Range':>8} {'Max Dir':>8}")
        print("-"*68)
        for r in results[:10]:
            print(f"{str(r[0]):<12} {r[1]:>10.1f} {r[2]:>10.1f} {r[3]:>10.1f} {r[4]:>8.1f} {r[7]:>8.1f}")
        
        # Calculate thresholds
        max_directional = [r[7] for r in results]
        
        avg1 = np.percentile(max_directional, 33)
        avg2 = np.percentile(max_directional, 66)
        avg3 = np.percentile(max_directional, 90)
        
        median_range = np.median([r[4] for r in results])
        mean_range = np.mean([r[4] for r in results])
        max_ever = np.max(max_directional)
        
        thresholds = {
            "instrument": "NSE:NIFTY50-INDEX",
            "avg1": round(avg1, 1),
            "avg2": round(avg2, 1),
            "avg3": round(avg3, 1),
            "median_daily_range": round(median_range, 1),
            "mean_daily_range": round(mean_range, 1),
            "max_directional_ever": round(max_ever, 1),
            "data_source": "nifty_only_historical_analysis",
            "sample_size": len(results),
            "analysis_date": datetime.now().isoformat()
        }
        
        print("\n" + "="*80)
        print("CORRECTED NIFTY MOMENTUM THRESHOLDS")
        print("="*80)
        print(f"\n📊 Based on {len(results)} NIFTY trading days:")
        print(f"\n  avg1 (33rd percentile): {avg1:>6.1f} pts")
        print(f"  avg2 (66th percentile): {avg2:>6.1f} pts")
        print(f"  avg3 (90th percentile): {avg3:>6.1f} pts")
        print(f"\n📈 Daily Range Statistics:")
        print(f"  Median: {median_range:>6.1f} pts")
        print(f"  Mean:   {mean_range:>6.1f} pts")
        print(f"  Max:    {max_ever:>6.1f} pts")
        
        # Save
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(thresholds, f, indent=2)
        
        print(f"\n✅ NIFTY-specific thresholds saved to: {OUTPUT_FILE}")
        print("="*80)
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
