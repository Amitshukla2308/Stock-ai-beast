import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data.prefill import run as run_prefill
from datetime import datetime, timedelta

def main():
    print("="*60)
    print("🚀 BEAST DATA INTEGRITY CHECK")
    print("="*60)
    
    # 1. Nifty 1min (Last 7 days - Tick Level)
    print("\n[1/3] Checking NIFTY (1min)...")
    run_prefill(days=7, symbol="NIFTY", resolution="1")
    
    # 2. Nifty 5min (Last 7 days - Context)
    print("\n[2/3] Checking NIFTY (5min)...")
    run_prefill(days=7, symbol="NIFTY", resolution="5")
    
    # 3. India VIX 5min (Last 7 days - Regime)
    print("\n[3/3] Checking INDIAVIX...")
    run_prefill(days=7, symbol="NSE:INDIAVIX-INDEX", resolution="5")
    
    print("\n✅ Data Check Complete.\n")

if __name__ == "__main__":
    main()
