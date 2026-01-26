import sys
import os
import io
from contextlib import redirect_stdout
from datetime import datetime
import pandas as pd

sys.path.append(os.getcwd())

from engine.modes.backtest import BacktestMode

def verify_telegram_signals():
    print("🧪 Starting Telegram Signal Verification...")
    
    # We will capture stdout to check for "<<<TELEGRAM" signals
    f = io.StringIO()
    
    backtest = BacktestMode(
        start_date=datetime(2026, 1, 8),
        end_date=datetime(2026, 1, 9), # 1 day
        symbol="NIFTY",
        resolution="5",
        initial_balance=100000
    )
    
    try:
        with redirect_stdout(f):
            backtest.start()
    except Exception as e:
        # Restore stdout
        sys.stdout = sys.__stdout__
        print(f"❌ Backtest crashed: {e}")
        return

    output = f.getvalue()
    
    # Normalize stdout for printing
    print(output[-1000:]) # Print last bit for context
    
    signals = []
    for line in output.split('\n'):
        if "<<<TELEGRAM" in line:
            signals.append(line)
            
    if signals:
        print(f"\n✅ Captured {len(signals)} Telegram Signals.")
        print("Sample Signals:")
        for s in signals[:5]:
            print(f"  {s}")
            
        # Check specific types
        monitors = [s for s in signals if "TRADE_MONITOR" in s]
        triggers = [s for s in signals if "EXIT_TRIGGER" in s]
        deaths = [s for s in signals if "EDGE_DEATH" in s]
        
        print(f"\n📊 Stats:")
        print(f"  MONITOR: {len(monitors)}")
        print(f"  EXIT: {len(triggers)}")
        print(f"  DEATH: {len(deaths)}")
        
        if len(monitors) > 0 and len(triggers) > 0:
             print("\n✅ Verification SUCCESS: Signals are flowing.")
        else:
             print("\n⚠️ Verification WARNING: Some signal types missing.")
    else:
        print("\n❌ No Telegram Signals captured.")

if __name__ == "__main__":
    verify_telegram_signals()
