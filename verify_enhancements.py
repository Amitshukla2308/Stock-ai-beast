import sys
import os
from datetime import datetime
import pytz

# Adjust path to root
sys.path.append(os.getcwd())

from engine.modes.backtest import BacktestMode

def run_verification():
    IST = pytz.timezone('Asia/Kolkata')
    
    # Dec 15, 2021 - Day with expected trade
    start_date = IST.localize(datetime(2021, 12, 15))
    end_date = IST.localize(datetime(2021, 12, 15))





    
    print(f"🚀 Running Verification Backtest for {start_date.date()}...")
    
    # Initialize Backtest Mode
    backtest = BacktestMode(start_date=start_date, end_date=end_date, symbol="NIFTY")
    
    # Run the simulation
    backtest.start()
    
    print("\n✅ Verification Simulation Complete.")

if __name__ == "__main__":
    run_verification()
