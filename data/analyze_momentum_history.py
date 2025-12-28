import duckdb
import json
from datetime import datetime, timedelta
import numpy as np

DB_PATH = "data/trading.db"
OUTPUT_FILE = "data/momentum_thresholds.json"

print("="*80)
print("NIFTY HISTORICAL MOMENTUM ANALYSIS")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Get date range available
    date_range = conn.execute("""
        SELECT MIN(timestamp::DATE) as min_date, MAX(timestamp::DATE) as max_date
        FROM candles_1min
    """).fetchone()
    
    print(f"\nData Range: {date_range[0]} to {date_range[1]}")
    
    # Calculate daily momentum statistics
    print("\nCalculating daily momentum metrics...")
    
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
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '4 years'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100  -- Ensure full trading day
        ORDER BY trade_date
    """
    
    results = conn.execute(query).fetchall()
    
    print(f"Analyzed {len(results)} trading days")
    
    if len(results) == 0:
        print("\n⚠️ No historical data available. Using default thresholds.")
        thresholds = {
            "avg1": 130,
            "avg2": 220,
            "avg3": 310,
            "data_source": "default",
            "sample_size": 0
        }
    else:
        # Extract momentum metrics
        daily_ranges = [r[4] for r in results]
        upside_moves = [r[5] for r in results]
        downside_moves = [r[6] for r in results]
        max_directional = [r[7] for r in results]
        
        # Calculate percentiles
        avg1 = np.percentile(max_directional, 33)
        avg2 = np.percentile(max_directional, 66)
        avg3 = np.percentile(max_directional, 90)
        
        # Additional statistics
        median_range = np.median(daily_ranges)
        mean_range = np.mean(daily_ranges)
        max_ever = np.max(max_directional)
        
        thresholds = {
            "avg1": round(avg1, 1),
            "avg2": round(avg2, 1),
            "avg3": round(avg3, 1),
            "median_daily_range": round(median_range, 1),
            "mean_daily_range": round(mean_range, 1),
            "max_directional_ever": round(max_ever, 1),
            "data_source": "historical_analysis",
            "sample_size": len(results),
            "analysis_date": datetime.now().isoformat()
        }
        
        # Display results
        print("\n" + "="*80)
        print("MOMENTUM EXHAUSTION THRESHOLDS")
        print("="*80)
        print(f"\n📊 Based on {len(results)} trading days:")
        print(f"\n  avg1 (33rd percentile): {avg1:>6.1f} pts - Early exhaustion warning")
        print(f"  avg2 (66th percentile): {avg2:>6.1f} pts - Moderate exhaustion")
        print(f"  avg3 (90th percentile): {avg3:>6.1f} pts - Severe exhaustion")
        print(f"\n📈 Daily Range Statistics:")
        print(f"  Median: {median_range:>6.1f} pts")
        print(f"  Mean:   {mean_range:>6.1f} pts")
        print(f"  Max:    {max_ever:>6.1f} pts")
        
        # Distribution analysis
        print(f"\n📉 Movement Distribution:")
        below_avg1 = sum(1 for x in max_directional if x < avg1)
        between_avg1_avg2 = sum(1 for x in max_directional if avg1 <= x < avg2)
        between_avg2_avg3 = sum(1 for x in max_directional if avg2 <= x < avg3)
        above_avg3 = sum(1 for x in max_directional if x >= avg3)
        
        print(f"  < avg1 ({avg1:.0f}pts):     {below_avg1:>4} days ({below_avg1/len(results)*100:.1f}%)")
        print(f"  avg1 - avg2:      {between_avg1_avg2:>4} days ({between_avg1_avg2/len(results)*100:.1f}%)")
        print(f"  avg2 - avg3:      {between_avg2_avg3:>4} days ({between_avg2_avg3/len(results)*100:.1f}%)")
        print(f"  > avg3 ({avg3:.0f}pts):     {above_avg3:>4} days ({above_avg3/len(results)*100:.1f}%)")
    
    # Save to file
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
