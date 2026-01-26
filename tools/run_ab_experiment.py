import os
import sys
import subprocess
import argparse
from tools.compare_sessions_db import analyze_sessions

def run_backtest(variant_name, enable_d2, days, symbol):
    print(f"\n🚀 STARTING VARIANT: {variant_name} (D2={'ON' if enable_d2 else 'OFF'})")
    print("=" * 60)
    
    # Copy current env and override D2 flag
    env = os.environ.copy()
    env["ATLAS_ENABLE_D2"] = "true" if enable_d2 else "false"
    
    cmd = [
        sys.executable, "-m", "engine.gateway", "backtest",
        "--days", str(days),
        "--symbol", symbol
    ]
    
    try:
        # Run subprocess with stdout passing through
        result = subprocess.run(cmd, env=env, check=True)
        print(f"✅ VARIANT {variant_name} COMPLETED.")
    except subprocess.CalledProcessError as e:
        print(f"❌ VARIANT {variant_name} FAILED: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Run Paired A/B Test for D2 Model")
    parser.add_argument("--days", type=int, default=2, help="Number of days to backtest")
    parser.add_argument("--symbol", type=str, default="NIFTY", help="Symbol to trade")
    args = parser.parse_args()
    
    print(f"\n🔬 STARTING PAIRED A/B EXPERIMENT ({args.days} days, {args.symbol})")
    print("Objective: Compare Participation Rate and Win Rate with D2 Filter ON vs OFF.")
    
    # Run Variant A (Baseline)
    run_backtest("A (Baseline)", enable_d2=False, days=args.days, symbol=args.symbol)
    
    # Run Variant B (Test)
    run_backtest("B (D2 Enabled)", enable_d2=True, days=args.days, symbol=args.symbol)
    
    # Generate Comparison
    print("\n📊 GENERATING REPORT...")
    analyze_sessions(limit=2)

if __name__ == "__main__":
    main()
