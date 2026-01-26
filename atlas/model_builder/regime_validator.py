import pandas as pd
import numpy as np
import os

def run_economic_validation(data_dir="atlas/data"):
    print("📊 Running Economic Validation of Regimes...")
    
    # 1. Load Data
    clusters_path = os.path.join(data_dir, "trade_clusters.parquet")
    outcomes_path = os.path.join(data_dir, "outcomes.parquet")
    
    if not os.path.exists(clusters_path):
        print(f"❌ Error: {clusters_path} not found. Please run atlas_profiler.py first.")
        return
    
    if not os.path.exists(outcomes_path):
        print(f"❌ Error: {outcomes_path} not found.")
        return
        
    df_clusters = pd.read_parquet(clusters_path)
    df_outcomes = pd.read_parquet(outcomes_path)
    
    # 2. Join
    print(f"🔗 Joining {len(df_outcomes)} outcomes with {len(df_clusters)} assignments...")
    df = df_outcomes.merge(df_clusters, on="trade_id", how="inner")
    
    if df.empty:
        print("❌ Error: Merge resulted in empty dataframe. Check trade_id alignment.")
        return

    # 3. Aggregate
    print("🧮 Computing Regime Economics...")
    # We use 'pnl_points' from outcomes (assuming that represents the raw PnL)
    # If the column is just 'pnl', we'll handle that.
    pnl_col = 'pnl_points' if 'pnl_points' in df.columns else 'pnl'
    
    summary = (
        df.groupby("cluster_id")
          .agg(
              mean_pnl=(pnl_col, "mean"),
              std_pnl=(pnl_col, "std"),
              hit_rate=(pnl_col, lambda x: (x > 0).mean()),
              max_dd=(pnl_col, lambda x: x.cumsum().min()), # Simple session drawdown approximation
              count=(pnl_col, "count")
          )
    )
    
    summary["sharpe_proxy"] = summary["mean_pnl"] / summary["std_pnl"].replace(0, np.nan)
    
    # 4. temporal consistency check (Optional but recommended by us)
    # We'll split by index thirds as a proxy for time if sorted
    n = len(df)
    df['period'] = pd.cut(df.index, bins=3, labels=['Early', 'Mid', 'Late'])
    
    period_stats = df.groupby(['cluster_id', 'period'])[pnl_col].mean().unstack()
    
    # 5. Format and Report
    print("\n--- 💰 REGIME ECONOMIC REPORT (Grand Partition K=12) 💰 ---")
    
    # Reorder columns
    display_cols = ["count", "hit_rate", "mean_pnl", "std_pnl", "sharpe_proxy", "max_dd"]
    formatted = summary[display_cols].copy()
    
    formatted['hit_rate'] = formatted['hit_rate'].apply(lambda x: f"{x:.1%}")
    formatted['mean_pnl'] = formatted['mean_pnl'].round(2)
    formatted['std_pnl'] = formatted['std_pnl'].round(2)
    formatted['sharpe_proxy'] = formatted['sharpe_proxy'].round(3)
    formatted['max_dd'] = formatted['max_dd'].round(1)
    
    print(formatted.to_string())
    
    print("\n--- Temporal Consistency (Mean PnL) ---")
    print(period_stats.round(2).to_string())
    
    # 6. Interpretive Heuristics
    print("\n--- AUTOMATED INTERPRETATION ---")
    
    # Check for dispersion in mean_pnl
    pnl_spread = summary['mean_pnl'].max() - summary['mean_pnl'].min()
    print(f"PnL Spread: {pnl_spread:.2f} points (Target: > 10)")
    
    # Check for Sharpe divergence
    sharpe_std = summary['sharpe_proxy'].std()
    print(f"Sharpe Volatility: {sharpe_std:.3f} (Target: > 0.05)")
    
    best_regime = summary['mean_pnl'].idxmax()
    worst_regime = summary['mean_pnl'].idxmin()
    print(f"Best: Regime {best_regime} ({summary.loc[best_regime, 'mean_pnl']:.2f})")
    print(f"Worst: Regime {worst_regime} ({summary.loc[worst_regime, 'mean_pnl']:.2f})")

if __name__ == "__main__":
    run_economic_validation()
