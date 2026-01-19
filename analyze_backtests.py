import duckdb
import pandas as pd
import numpy as np
import json
import os

def calculate_metrics(df, initial_capital=30000):
    if df.empty:
        return {"Error": "No trades"}
    
    # Calculate daily PnL
    df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
    daily_pnl = df.groupby('exit_date')['pnl'].sum().reset_index()
    
    # Total PnL points (Nifty lot size is not factored in for 'points' but for INR we do)
    # The 'pnl' in simulation_trades seems to be points.
    total_pnl_pts = df['pnl'].sum()
    
    # Win Rate
    wins = df[df['pnl'] > 0]
    win_rate = (len(wins) / len(df)) * 100
    
    # Profit Factor
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(df[df['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else 99.9
    
    # Performance Stats
    avg_win = wins['pnl'].mean() if not wins.empty else 0
    avg_loss = df[df['pnl'] < 0]['pnl'].mean() if len(df[df['pnl'] < 0]) > 0 else 0
    
    # Drawdown
    # We use lot size 27.5 for INR calculation
    LOT_SIZE = 27.5
    df['pnl_inr'] = df['pnl'] * LOT_SIZE
    df['equity'] = initial_capital + df['pnl_inr'].cumsum()
    peak = df['equity'].cummax()
    dd = (df['equity'] - peak)
    max_dd_inr = dd.min()
    
    # Sharpe/Sortino (daily returns)
    # Construct daily equity
    all_dates = pd.date_range(start=df['exit_date'].min(), end=df['exit_date'].max(), freq='D')
    daily_equity = pd.Series(index=all_dates, data=np.nan)
    for date, group in df.groupby('exit_date'):
        daily_equity.loc[date] = group['equity'].iloc[-1]
    
    daily_equity = daily_equity.ffill().fillna(initial_capital)
    daily_returns = daily_equity.pct_change().dropna()
    
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() != 0 else 0
    
    downside_std = daily_returns[daily_returns < 0].std()
    sortino = (daily_returns.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0

    return {
        "Total_PnL_Pts": round(total_pnl_pts, 2),
        "Total_PnL_INR": round(total_pnl_pts * LOT_SIZE, 2),
        "Win_Rate_Pct": round(win_rate, 2),
        "Profit_Factor": round(profit_factor, 2),
        "Max_Drawdown_INR": round(max_dd_inr, 2),
        "Sharpe_Ratio": round(sharpe, 2),
        "Sortino_Ratio": round(sortino, 2),
        "Trade_Count": len(df),
        "Avg_Win_Pts": round(avg_win, 2),
        "Avg_Loss_Pts": round(avg_loss, 2)
    }

conn = duckdb.connect('/app/data/trading.db')

# Compare: Sniper (2025), High-Freq (2025), Baseline (2-Year)
target_sessions = [
    'BACKTEST_20260119_055050', # Sniper 
    'BACKTEST_20260118_214047', # High-Freq
    'BACKTEST_20260116_052512'  # Baseline (Old)
]
results = {}

for session in target_sessions:
    trades_df = conn.execute(f"SELECT * FROM simulation_trades WHERE session_id = '{session}'").df()
    if trades_df.empty: continue
    
    session_metrics = calculate_metrics(trades_df)
    
    # Opportunity Analysis
    logs = conn.execute(f"SELECT content FROM simulation_logs WHERE session_id = '{session}' AND event_type = 'TACTICAL'").fetchall()
    reasons = []
    for l in logs:
        try:
            c = json.loads(l[0])
            if c.get('engine_decision') == 'BLOCKED' or c.get('action') == 'HOLD':
                r = c.get('engine_reason') or c.get('reason') or "Unknown"
                # Standardize categories
                if "Confidence" in r or "conf" in r.lower(): r = "C1: Low Confidence"
                elif "TER" in r or "Efficiency" in r: r = "C2: Low Trend Quality (TER)"
                elif "REMR" in r: r = "C3: Mean Reversion Guard"
                elif "Momentum" in r: r = "C4: Momentum Mismatch"
                elif "Exhaustion" in r: r = "C5: Overextended (Exhaustion)"
                elif "Target" in r: r = "C6: Target Guard (S/R Blocked)"
                elif "Cooling" in r: r = "C7: Intra-day Cooling Period"
                elif "volatile" in r.lower() or "volatility" in r.lower(): r = "C8: Volatility Filter"
                reasons.append(r)
        except: continue
    
    counts = pd.Series(reasons).value_counts().head(8).to_dict()
    session_metrics['OpportunityLoss_Distribution'] = counts
    results[session] = session_metrics

# Buy & Hold Comparison (NIFTY 2025)
nifty = conn.execute("SELECT timestamp, close FROM candles_5min WHERE symbol = 'NSE:NIFTY50-INDEX' AND timestamp BETWEEN '2025-01-01' AND '2025-12-31' ORDER BY timestamp").df()
if not nifty.empty:
    start_p = nifty['close'].iloc[0]
    end_p = nifty['close'].iloc[-1]
    nifty_return = (end_p - start_p) / start_p * 100
    results['MARKET_BENCHMARK_2025'] = {
        "NIFTY_Return_Pct": round(nifty_return, 2),
        "Market_Volatility_Std": round(nifty['close'].pct_change().std() * np.sqrt(252 * 75) * 100, 2)
    }

def convert_to_serializable(obj):
    if isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(i) for i in obj]
    elif isinstance(obj, (np.float32, np.float64, float)):
        return round(float(obj), 2)
    elif isinstance(obj, (np.int32, np.int64, int)):
        return int(obj)
    return obj

outputs = convert_to_serializable(results)
print(json.dumps(outputs, indent=4))
conn.close()
