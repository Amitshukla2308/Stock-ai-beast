import time
from datetime import datetime
import os

# Import modules
from brokers.fyers.connector import get_fyers_model
from services.risk.ai_manager import analyze_market_regime

SYMBOL = "NSE:NIFTYBANK-INDEX"
QUANTITY = 15 

def get_latest_candle(fyers, symbol):
    # Mocking live fetch
    print(f"Fetching live candle for {symbol}...")
    return {
        "close": 45000.0,
        "high": 45050.0,
        "low": 44950.0,
        "volume": 5000,
        "timestamp": datetime.now()
    }

def calculate_indicators(close_prices):
    return {
        "rsi": 55,
        "ma_fast": 44980,
        "ma_slow": 44900
    }

def place_order(fyers, symbol, side, qty):
    print(f"🚀 PLACING ORDER: {side} {qty} x {symbol}")
    return True

def run_live_bot():
    print("🤖 Starting Beast Live Trader...")
    
    try:
        fyers = get_fyers_model()
        print("✅ Broker Connected.")
    except Exception as e:
        print(f"⚠️ Broker Connection Failed: {e}")
        print("Running in PAPER MODE (No Broker)")
        fyers = None

    last_ai_check = 0
    current_regime = "UNKNOWN"
    cash_buffer = 1.0 
    
    while True:
        try:
            now = time.time()
            if now - last_ai_check > 900:
                print("🧠 Consulting The Beast (AI Risk Manager)...")
                tech_summary = "Trend is Up. Volatility is rising." 
                news_summary = "No major news."
                
                ai_decision = analyze_market_regime(tech_summary, news_summary)
                current_regime = ai_decision.get("regime", "UNKNOWN")
                cash_buffer = ai_decision.get("suggested_cash_buffer", 1.0)
                
                print(f"AI Decision: {current_regime} | Cash Buffer: {cash_buffer}")
                last_ai_check = now

            candle = get_latest_candle(fyers, SYMBOL)
            close_price = candle['close']
            
            indicators = calculate_indicators([close_price])
            
            signal = None
            if indicators['ma_fast'] > indicators['ma_slow']:
                signal = "BUY"
            elif indicators['ma_fast'] < indicators['ma_slow']:
                signal = "SELL"
                
            if signal == "BUY":
                if current_regime in ["BULLISH", "SIDEWAYS"] and cash_buffer < 0.5:
                    place_order(fyers, SYMBOL, "BUY", QUANTITY)
                else:
                    print(f"🛑 AI BLOCKED BUY signal. Regime: {current_regime}")
            elif signal == "SELL":
                if current_regime in ["BEARISH", "SIDEWAYS"]:
                    place_order(fyers, SYMBOL, "SELL", QUANTITY)
            
            print(f"Waiting for next candle...")
            time.sleep(60)
            
        except KeyboardInterrupt:
            print("Stopping Bot...")
            break
        except Exception as e:
            print(f"Error in loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_live_bot()
