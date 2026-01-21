# Removed legacy duckdb import
import pandas as pd
import pandas_ta as ta
import numpy as np
import scipy.stats as si
from datetime import datetime
from data.database import get_connection

def calculate_greeks(S, K, T, r, sigma, option_type='call'):
    """
    Black-Scholes Greeks Approximation.
    S: Spot Price
    K: Strike Price (Assuming ATM for feature proxy, so K=S)
    T: Time to expiry (years)
    r: Risk-free rate
    sigma: Volatility (annualized)
    """
    # Safety
    if T <= 0 or sigma <= 0:
        return 0, 0, 0, 0

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = (np.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

    if option_type == 'call':
        delta = si.norm.cdf(d1, 0.0, 1.0)
        theta = - (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * si.norm.cdf(d2, 0.0, 1.0)
    else:
        delta = -si.norm.cdf(-d1, 0.0, 1.0)
        theta = - (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * si.norm.cdf(-d2, 0.0, 1.0)

    gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * sigma * np.sqrt(T))
    vega = S * np.sqrt(T) * si.norm.pdf(d1, 0.0, 1.0)

    return delta, gamma, theta, vega

def compute_features(symbol="NSE:NIFTYBANK-INDEX"):
    conn = get_connection()
    
    print("⏳ Loading candles from DB...")
    # Load candles
    df = pd.read_sql_query("SELECT * FROM candles_5min WHERE symbol = ? ORDER BY timestamp", conn, params=(symbol,))
    
    if df.empty:
        print("❌ No data found in candles_5min.")
        conn.close()
        return

    print(f"📊 Processing {len(df)} candles...")

    # Load VIX data
    print("⏳ Loading VIX data...")
    df_vix = pd.read_sql_query("SELECT timestamp, close as vix_close FROM candles_vix ORDER BY timestamp", conn)
    
    # Merge VIX
    # SQLite timestamps are strings, but read_sql_query usually handles it if converted
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df_vix['timestamp'] = pd.to_datetime(df_vix['timestamp'])
    df = pd.merge(df, df_vix, on='timestamp', how='left')
    
    # Fill missing VIX with ffill or mean
    df['vix_close'] = df['vix_close'].ffill().fillna(15.0) # Default 15 if no data
    
    # Technicals with pandas_ta
    # Trend
    df['sma_fast'] = ta.sma(df['close'], length=10)
    df['sma_slow'] = ta.sma(df['close'], length=50)
    
    # Momentum
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # Volatility
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    
    # Robustly get BB columns (names can vary by version/params)
    # Expected: BBU_20_2.0, BBL_20_2.0 or similar
    if bb is not None and not bb.empty:
        # Find columns ending with specific patterns if exact match fails
        cols_bb = bb.columns.tolist()
        upper_col = next((c for c in cols_bb if c.startswith('BBU')), None)
        lower_col = next((c for c in cols_bb if c.startswith('BBL')), None)
        
        if upper_col and lower_col:
            df['bb_upper'] = bb[upper_col]
            df['bb_lower'] = bb[lower_col]
        else:
            print(f"⚠️ Warning: Could not find BB columns in {cols_bb}")
            df['bb_upper'] = df['close'] # Fallback
            df['bb_lower'] = df['close']
    else:
        df['bb_upper'] = np.nan
        df['bb_lower'] = np.nan
    
    # Volatility for Greeks
    # If we have VIX, use it. VIX is percentage, so div by 100.
    # VIX represents expected annual volatility over next 30 days.
    df['volatility'] = df['vix_close'] / 100.0

    # Greeks Simulation (ATM Proxy)
    # Assume 7 days to expiry (0.019 years) constant for training proxy unless we have expiry data
    T = 7 / 365.0 
    r = 0.07 # 7% risk free
    
    # We simulate ATM Call Greeks
    greeks = df.apply(lambda row: calculate_greeks(
        S=row['close'], 
        K=row['close'], # ATM
        T=T, 
        r=r, 
        sigma=row['volatility'] if pd.notnull(row['volatility']) and row['volatility'] > 0 else 0.15
    ), axis=1)
    
    df['delta'] = [x[0] for x in greeks]
    df['gamma'] = [x[1] for x in greeks]
    df['theta'] = [x[2] for x in greeks]
    df['vega'] = [x[3] for x in greeks]
    
    # Regime
    # Simple rule: If close > sma_slow and rsi > 50 => TRENDING_UP
    # If bb_width is low => CONTRACTION
    # Implementation later
    df['regime'] = "UNKNOWN"
    
    # Store features
    # Drop NaNs
    df.dropna(inplace=True)
    
    print("💾 Saving features to DB...")
    
    # Upsert logic is hard in bulk, so we delete and insert for this symbol range or just append
    # For now, simple append with ignore
    # Selecting columns matching schema
    cols_to_save = ['timestamp', 'symbol', 'sma_fast', 'sma_slow', 'trend', 
                    'rsi', 'atr', 'volatility', 'bb_upper', 'bb_lower', 
                    'delta', 'gamma', 'theta', 'vega', 'regime']
    
    # Fill missing columns
    df['trend'] = df.apply(lambda row: 'UP' if row['close'] > row['sma_slow'] else 'DOWN', axis=1)
    
    # Ensure timestamp is string for SQLite
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    insert_data = df[cols_to_save]
    
    # Use pandas to_sql for speed (if table exists)
    try:
        insert_data.to_sql('features', conn, if_exists='append', index=False)
    except Exception as e:
        print(f"⚠️ to_sql Error: {e}. Falling back to row-by-row.")
        # Fallback row-by-row
        for _, row in insert_data.iterrows():
            conn.execute(f"INSERT OR IGNORE INTO features ({','.join(cols_to_save)}) VALUES ({','.join(['?']*len(cols_to_save))})", tuple(row))
    
    conn.commit()
    conn.close()
    print("✅ Feature Engineering Complete.")

if __name__ == "__main__":
    compute_features()
