import pandas as pd
import numpy as np

def calculate_technical_state(df: pd.DataFrame) -> dict:
    """
    Process the Data (Cold/Hot path split starts here).
    Returns a dictionary of technical states.
    """
    if df.empty:
        return {}
    
    close = df['close']
    
    # 1. Simple Moving Averages
    ma_fast = close.rolling(10).mean().iloc[-1]
    ma_slow = close.rolling(50).mean().iloc[-1]
    
    # 2. RSI (Simple implementation)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    
    # 3. Volatility (ATR-like or StdDev)
    # Using 20-period rolling std dev of percent change
    volatility = close.pct_change().rolling(20).std().iloc[-1] * 100 
    
    # 4. Trend Determination (Deterministic)
    trend = "SIDEWAYS"
    if ma_fast > ma_slow * 1.001: # Small buffer
        trend = "UP"
    elif ma_fast < ma_slow * 0.999:
        trend = "DOWN"
        
    return {
        "current_price": close.iloc[-1],
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "rsi": rsi,
        "volatility": volatility,
        "trend": trend
    }
