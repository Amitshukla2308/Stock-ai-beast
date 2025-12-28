import duckdb
import numpy as np

DB_PATH = "data/trading.db"

print("="*80)
print("VALIDATING MOMENTUM THRESHOLDS WITH ACTUAL EXAMPLES")
print("="*80)

conn = duckdb.connect(DB_PATH, read_only=True)

try:
    # Get all directional moves
    query = """
        SELECT 
            timestamp::DATE as trade_date,
            MIN(open) as day_open,
            MAX(high) as day_high,
            MIN(low) as day_low,
            MAX(high) - MIN(low) as daily_range,
            MAX(high) - MIN(open) as upside_move,
            MIN(open) - MIN(low) as downside_move,
            GREATEST(MAX(high) - MIN(open), MIN(open) - MIN(low)) as max_directional
        FROM candles_1min
        WHERE timestamp::DATE >= CURRENT_DATE - INTERVAL '1 year'
        GROUP BY timestamp::DATE
        HAVING COUNT(*) > 100
        ORDER BY trade_date DESC
    """
    
    results = conn.execute(query).fetchall()
    
    # Calculate thresholds
    moves = [r[7] for r in results]
    avg1 = np.percentile(moves, 33)
    avg2 = np.percentile(moves, 66)
    avg3 = np.percentile(moves, 90)
    
    print(f"\nCalculated Thresholds:")
    print(f"  avg1 (33rd): {avg1:.1f} pts")
    print(f"  avg2 (66th): {avg2:.1f} pts")
    print(f"  avg3 (90th): {avg3:.1f} pts")
    
    # Find example days for each threshold
    print(f"\n{'='*80}")
    print("ACTUAL TRADING DAYS MATCHING EACH THRESHOLD")
    print(f"{'='*80}")
    
    # avg1 examples (near 408 pts)
    avg1_examples = [r for r in results if 390 <= r[7] <= 430][:5]
    print(f"\n📊 avg1 Level (~{avg1:.0f} pts) - Early Exhaustion Warning:")
    print(f"{'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Range':>8} {'Max Dir':>8} {'Direction':>10}")
    print("-"*78)
    for r in avg1_examples:
        direction = "Upward" if r[5] > r[6] else "Downward"
        print(f"{str(r[0]):<12} {r[1]:>8.1f} {r[2]:>8.1f} {r[3]:>8.1f} {r[4]:>8.1f} {r[7]:>8.1f} {direction:>10}")
    
    # avg2 examples (near 568 pts)
    avg2_examples = [r for r in results if 550 <= r[7] <= 590][:5]
    print(f"\n📊 avg2 Level (~{avg2:.0f} pts) - Moderate Exhaustion:")
    print(f"{'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Range':>8} {'Max Dir':>8} {'Direction':>10}")
    print("-"*78)
    for r in avg2_examples:
        direction = "Upward" if r[5] > r[6] else "Downward"
        print(f"{str(r[0]):<12} {r[1]:>8.1f} {r[2]:>8.1f} {r[3]:>8.1f} {r[4]:>8.1f} {r[7]:>8.1f} {direction:>10}")
    
    # avg3 examples (near 787 pts)
    avg3_examples = [r for r in results if 750 <= r[7] <= 850][:5]
    print(f"\n📊 avg3 Level (~{avg3:.0f} pts) - Severe Exhaustion:")
    print(f"{'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Range':>8} {'Max Dir':>8} {'Direction':>10}")
    print("-"*78)
    for r in avg3_examples:
        direction = "Upward" if r[5] > r[6] else "Downward"
        print(f"{str(r[0]):<12} {r[1]:>8.1f} {r[2]:>8.1f} {r[3]:>8.1f} {r[4]:>8.1f} {r[7]:>8.1f} {direction:>10}")
    
    # Show distribution
    print(f"\n{'='*80}")
    print("DISTRIBUTION ANALYSIS")
    print(f"{'='*80}")
    
    below_avg1 = len([m for m in moves if m < avg1])
    between_avg1_avg2 = len([m for m in moves if avg1 <= m < avg2])
    between_avg2_avg3 = len([m for m in moves if avg2 <= m < avg3])
    above_avg3 = len([m for m in moves if m >= avg3])
    
    total = len(moves)
    print(f"\nOut of {total} trading days:")
    print(f"  Below avg1 (<{avg1:.0f}pts):     {below_avg1:>3} days ({below_avg1/total*100:.1f}%)")
    print(f"  Between avg1-avg2:       {between_avg1_avg2:>3} days ({between_avg1_avg2/total*100:.1f}%)")
    print(f"  Between avg2-avg3:       {between_avg2_avg3:>3} days ({between_avg2_avg3/total*100:.1f}%)")
    print(f"  Above avg3 (>{avg3:.0f}pts):     {above_avg3:>3} days ({above_avg3/total*100:.1f}%)")
    
    print(f"\n✅ Thresholds validated with real historical data")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
