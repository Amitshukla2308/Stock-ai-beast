import time
import os
import shutil
import duckdb
import pandas as pd
import sys
from datetime import datetime

# Configuration
DB_PATH = "data/trading.db"
TEMP_DB = "data/trading_watch.db"
REFRESH_RATE = 2  # seconds

def clear_screen():
    # ANSI escape code for clear screen (works in most docker TTYs)
    print("\033[H\033[J", end="")

def get_latest_session_id(conn):
    # Try finding latest by ID timestamp
    try:
        res = conn.execute("SELECT session_id, start_date, end_date FROM simulation_sessions ORDER BY session_id DESC LIMIT 1").fetchone()
        if res: return res[0], res[1], res[2]
    except: pass
    
    # Fallback to trades
    try:
        res = conn.execute("SELECT session_id, exit_time FROM simulation_trades ORDER BY exit_time DESC LIMIT 1").fetchone()
        if res: return res[0], None, None
    except: pass
    return None, None, None

def calculate_metrics(df):
    if df.empty:
        return {}
    
    total_trades = len(df)
    pnl = df['pnl'].sum()
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    win_rate = (len(wins) / total_trades * 100)
    
    avg_win = wins['pnl'].mean() if not wins.empty else 0
    avg_loss = losses['pnl'].mean() if not losses.empty else 0
    
    gross_win = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss != 0 else 99.99
    
    # Drawdown
    df = df.sort_values('exit_time')
    df['cum_pnl'] = df['pnl'].cumsum()
    df['peak'] = df['cum_pnl'].cummax()
    df['dd'] = df['cum_pnl'] - df['peak']
    max_dd = df['dd'].min()
    
    current_streak = 0
    for pnl_val in df['pnl'][::-1]:
        if pnl_val > 0: current_streak += 1
        else: break
        
    return {
        'total_trades': total_trades,
        'total_pnl': pnl,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'max_dd': max_dd,
        'streak': current_streak,
        'last_trade_time': df['exit_time'].max()
    }

def main():
    print("Starting Backtest Watcher...")
    while True:
        try:
            # 1. Snapshot DB
            if not os.path.exists(DB_PATH):
                print("Waiting for DB...")
                time.sleep(REFRESH_RATE)
                continue
                
            shutil.copy2(DB_PATH, TEMP_DB)
            
            # 2. Analyze
            conn = duckdb.connect(TEMP_DB)
            
            session_id, start_date, end_date = get_latest_session_id(conn)
            
            if not session_id:
                print("No active session found.")
                conn.close()
                time.sleep(REFRESH_RATE)
                continue
                
            # Fetch trades with Style extraction (Correlated extraction from Logs)
            # We look for the latest TACTICAL log before entry
            query = f"""
                SELECT 
                    t.*,
                    (
                        SELECT json_extract_string(content, '$.selected_style')
                        FROM simulation_logs l 
                        WHERE l.session_id = t.session_id 
                          AND l.event_type = 'TACTICAL' 
                          AND l.timestamp <= t.entry_time 
                          AND l.timestamp >= t.entry_time - INTERVAL '30 minutes'
                        ORDER BY l.timestamp DESC 
                        LIMIT 1
                    ) as style
                FROM simulation_trades t 
                WHERE t.session_id = '{session_id}' 
                ORDER BY t.exit_time ASC
            """
            trades_df = conn.execute(query).fetchdf()
            
            # Fill missing styles
            trades_df['style'] = trades_df['style'].fillna('UNKNOWN')
            
            metrics = calculate_metrics(trades_df)
            
            conn.close()
            
            # 3. Display
            clear_screen()
            print("="*80)
            print(f"🔥 LIVE BACKTEST MONITOR  |  {datetime.now().strftime('%H:%M:%S')}")
            print("="*80)
            print(f"🆔 Session:      {session_id}")
            if metrics:
                print(f"📅 Sim Date:     {metrics['last_trade_time']}")
                print("-" * 80)
                # Row 1
                print(f"💰 PnL: {metrics['total_pnl']:>+10.2f} pts  |  📉 DD: {metrics['max_dd']:>10.2f} pts  |  ⚖️ PF: {metrics['profit_factor']:>6.2f}")
                # Row 2
                print(f"🔢 Trades: {metrics['total_trades']:<6}       |  🎯 WR: {metrics['win_rate']:>9.1f}%     |  🔥 Streak: {metrics['streak']}")
                print("-" * 80)
                print(f"🟢 Avg Win: {metrics['avg_win']:>+8.1f}      |  🔴 Avg Loss: {metrics['avg_loss']:>+8.1f}")
                
                # --- NEW: STYLES ANALYTICS ---
                print("\n🎭 STYLE ANALYTICS:")
                style_stats = trades_df.groupby('style').agg(
                    Count=('pnl', 'count'),
                    PnL=('pnl', 'sum'),
                    WinRate=('pnl', lambda x: (x > 0).mean() * 100),
                    Avg=('pnl', 'mean')
                ).sort_values('PnL', ascending=False)
                
                # Format table
                # Fixed width formatting for cleanliness
                print(f"{'STYLE':<30} | {'CNT':<4} | {'PnL':<10} | {'WR%':<5} | {'AVG':<6}")
                print("-" * 70)
                for style_name, row in style_stats.iterrows():
                    # Truncate style name if too long
                    s_name = (style_name[:28] + '..') if len(str(style_name)) > 28 else str(style_name)
                    print(f"{s_name:<30} | {row['Count']:<4} | {row['PnL']:>+10.1f} | {row['WinRate']:>5.1f} | {row['Avg']:>+6.1f}")
                
                print("\n📜 RECENT TRADES (Last 10):")
                if not trades_df.empty:
                    last_10 = trades_df.tail(10)[['exit_time', 'side', 'style', 'pnl', 'reason']]
                    # Rename columns for display
                    last_10.columns = ['Time', 'Side', 'Style', 'PnL', 'Exit Method']
                    # Clean output
                    print(last_10.to_string(index=False, header=True, justify='left'))
            else:
                print("Waiting for first trade...")
                
        except Exception as e:
            # print(f"Error: {e}")
            pass
            
        time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        if os.path.exists(TEMP_DB):
            os.remove(TEMP_DB)
