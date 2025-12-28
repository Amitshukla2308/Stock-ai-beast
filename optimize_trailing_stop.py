import duckdb
import json

DB_PATH = "data/trading.db"
conn = duckdb.connect(DB_PATH)

# Original session with full fidelity metrics
session_id = "BACKTEST_20251228_040232"

print("="*80)
print("TRAILING STOP OPTIMIZATION - DATA-DRIVEN ANALYSIS")
print("="*80)

# Get all trades with their metrics
query = """
    SELECT 
        entry_time,
        exit_time,
        side,
        entry_price,
        exit_price,
        pnl as actual_pnl,
        max_pnl,
        mean_open_pnl,
        reason
    FROM simulation_trades 
    WHERE session_id = ?
    ORDER BY entry_time
"""

trades = conn.execute(query, (session_id,)).fetchall()
conn.close()

print(f"\nAnalyzing {len(trades)} trades from session: {session_id}\n")

# Test different trailing stop strategies
strategies = {
    "NO_PROTECTION": {"breakeven_threshold": None, "profit_lock_pct": None},
    "BE_20%": {"breakeven_threshold": 0.20, "profit_lock_pct": 0},
    "BE_30%": {"breakeven_threshold": 0.30, "profit_lock_pct": 0},
    "BE_40%": {"breakeven_threshold": 0.40, "profit_lock_pct": 0},
    "BE_50%": {"breakeven_threshold": 0.50, "profit_lock_pct": 0},
    "LOCK_30%@30%": {"breakeven_threshold": 0.30, "profit_lock_pct": 0.30},
    "LOCK_50%@30%": {"breakeven_threshold": 0.30, "profit_lock_pct": 0.50},
    "LOCK_70%@30%": {"breakeven_threshold": 0.30, "profit_lock_pct": 0.70},
    "LOCK_30%@50%": {"breakeven_threshold": 0.50, "profit_lock_pct": 0.30},
    "LOCK_50%@50%": {"breakeven_threshold": 0.50, "profit_lock_pct": 0.50},
}

results = {}

for strategy_name, params in strategies.items():
    total_pnl = 0
    wins = 0
    losses = 0
    breakevens = 0
    
    for trade in trades:
        entry_time, exit_time, side, entry, exit, actual_pnl, max_pnl, mean_pnl, reason = trade
        
        # Calculate original SL distance (assume 50 pts for simplicity)
        sl_distance = 50
        
        # Simulate trailing stop
        if params["breakeven_threshold"] is None:
            # No protection - use actual PnL
            simulated_pnl = actual_pnl
        else:
            # Check if peak profit exceeded threshold
            threshold_pts = sl_distance * params["breakeven_threshold"]
            
            if max_pnl > threshold_pts:
                # Protection would have triggered
                if params["profit_lock_pct"] == 0:
                    # Breakeven only
                    simulated_pnl = 0
                else:
                    # Lock percentage of peak profit
                    locked_profit = max_pnl * params["profit_lock_pct"]
                    simulated_pnl = locked_profit
            else:
                # Never triggered - use actual PnL
                simulated_pnl = actual_pnl
        
        total_pnl += simulated_pnl
        
        if simulated_pnl > 0:
            wins += 1
        elif simulated_pnl < 0:
            losses += 1
        else:
            breakevens += 1
    
    win_rate = wins / len(trades) * 100 if trades else 0
    avg_pnl = total_pnl / len(trades) if trades else 0
    
    results[strategy_name] = {
        "total_pnl": total_pnl,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl
    }

# Sort by total PnL
sorted_results = sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True)

print("\nRESULTS (Sorted by Total PnL):")
print("-" * 80)
print(f"{'Strategy':<20} {'Total PnL':>12} {'Win Rate':>10} {'Wins':>6} {'Losses':>8} {'BE':>4}")
print("-" * 80)

for strategy, metrics in sorted_results:
    print(f"{strategy:<20} {metrics['total_pnl']:>+11.1f}pts {metrics['win_rate']:>9.1f}% "
          f"{metrics['wins']:>6} {metrics['losses']:>8} {metrics['breakevens']:>4}")

print("-" * 80)

# Show best strategy details
best_strategy, best_metrics = sorted_results[0]
print(f"\n🏆 OPTIMAL STRATEGY: {best_strategy}")
print(f"   Total PnL: {best_metrics['total_pnl']:+.1f} pts")
print(f"   Win Rate: {best_metrics['win_rate']:.1f}%")
print(f"   Avg PnL/Trade: {best_metrics['avg_pnl']:+.1f} pts")

# Compare to original
original_pnl = sum(t[5] for t in trades)  # actual_pnl is index 5
improvement = best_metrics['total_pnl'] - original_pnl
print(f"\n📈 vs. Original (No Protection): {improvement:+.1f} pts ({improvement/original_pnl*100:+.1f}%)")
