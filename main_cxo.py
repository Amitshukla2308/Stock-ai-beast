import time
import os
from datetime import datetime, timedelta
import pandas as pd

# Brokers
from brokers.fyers.connector import get_fyers_model
from brokers.paper.connector import PaperBroker

# Workers (Hot Path)
from workers import technicals
from workers import guardrails
from workers import oms

# Brain (Cold Path)
from brain import prompt_manager
from brain import cxo_llm

# Config
# Ideally load from .env
TRADING_MODE = os.getenv("TRADING_MODE", "PAPER") # PAPER or LIVE
SYMBOL = "NSE:NIFTYBANK-INDEX"
QUANTITY = 15

def get_live_data_dataframe(fyers, symbol):
    """
    Fetches historical data from Fyers to warm up indicators.
    Returns a DataFrame with 'close' column.
    """
    if fyers is None:
        # Fallback to mock data if broker is offline
        print("⚠️ Broker null. Using Mock Data.")
        data = {
            'close': [44900 + i*10 for i in range(50)]
        }
        return pd.DataFrame(data)

    # Calculate date range for last 100 candles (approx 100 min)
    # Note: For Day candles, range should be longer. For Intraday (1), 1 day range is enough for 100 candles.
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5) # ample buffer
    
    # Fyers Date Format: YYYY-MM-DD
    # For History API
    data_input = {
        "symbol": symbol,
        "resolution": "1", # 1 minute
        "date_format": "1", # 1 = epoch timestamp, 0 = YYYY-MM-DD
        "range_from": start_date.strftime('%Y-%m-%d'),
        "range_to": end_date.strftime('%Y-%m-%d'),
        "cont_flag": "1"
    }

    try:
        # Fyers History API
        response = fyers.history(data=data_input)
        
        if response.get('s') != 'ok':
            print(f"❌ Data Fetch Error: {response.get('message')}")
            return pd.DataFrame() # Empty DF triggers logic to wait
            
        candles = response.get('candles', [])
        
        # Candles format: [timestamp, open, high, low, close, volume]
        # We need 'close' for technicals
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Convert timestamp to datetime if needed, or just use as is. 
        # technicals.py only uses 'close' column values.
        
        # Taking the last 100 to ensure we have enough for rolling windows
        return df.tail(100).reset_index(drop=True)

    except Exception as e:
        print(f"❌ Data Fetch Exception: {e}")
        return pd.DataFrame()

def run_orchestrator():
    print("🚀 Starting CXO-Worker Orchestrator...")
    print(f"⚙️  Mode: {TRADING_MODE}")
    
    # 1. Connect Data Broker (Always Fyers for now)
    try:
        data_client = get_fyers_model()
        print("✅ Data Broker Online (Fyers).")
    except Exception as e:
        print("⚠️ Data Broker Offline. Running with Mock Data fallback.")
        data_client = None

    # 2. Connect Execution Broker
    if TRADING_MODE == "LIVE":
        execution_client = data_client # Valid Fyers Token required
        print("🚨 LIVE TRADING ENABLED 🚨")
    else:
        execution_client = PaperBroker()
        print("📝 Paper Trading Enabled.")

    # Portfolio State (Mock or Real?)
    # Valid question: Should we sync portfolio with broker? 
    # For now, PaperBroker has internal state. Fyers has remote state.
    # guardrails.risk_gate uses 'portfolio'.
    portfolio = {"cash": 100000, "positions": {}}
    
    while True:
        try:
            print("\n--- New Tick Cycle ---")
            
            # 1. Get Data (From Data Client)
            df = get_live_data_dataframe(data_client, SYMBOL)
            
            # 2. Worker: Technical Analysis (Hot Path)
            tech_state = technicals.calculate_technical_state(df)
            
            if not tech_state:
                print("⚠️ Not enough data for technicals. Waiting...")
                time.sleep(10)
                continue

            print(f"📊 Technicals: {tech_state['trend']} | RSI: {tech_state['rsi']:.1f}")
            
            # 3. Brain: Construct Context (Cold Path Preparation)
            prompt = prompt_manager.construct_prompt(tech_state, news_summary="")
            
            # 4. Brain: CXO Decision (Cold Path Inference)
            print("🧠 Asking CXO...")
            decision = cxo_llm.get_cxo_decision(prompt)
            print(f"💡 CXO Says: {decision.get('action')} (Conf: {decision.get('confidence')})")
            print(f"   Reason: {decision.get('reasoning')}")
            
            # 5. Worker: Guardrails (Deterministic Safety Layer)
            is_safe = guardrails.risk_gate(decision, tech_state, portfolio)
            
            # 6. Worker: OMS (Execution)
            if is_safe and decision.get("action") in ["BUY", "SELL"]:
                oms.execute_order(
                    broker_model=execution_client,
                    symbol=SYMBOL,
                    action=decision.get("action"),
                    quantity=QUANTITY,
                    reason=decision.get("reasoning"),
                    market_price=tech_state.get('current_price', 0)
                )
            elif not is_safe:
                print("🛑 Trade Skipped by Safety Workers.")
            else:
                print("💤 Holding...")

            time.sleep(60) # Wait for next cycle
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_orchestrator()
