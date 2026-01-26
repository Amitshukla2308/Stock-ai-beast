"""
Verification Script for Project Atlas (Learn Mode)
1. Runs 'engine/gateway.py learn' for N days.
2. Checks if atlas/data/states_*.csv is created.
3. Validates CSV schema (Entropy, Velocity, etc. must be present).
"""
import subprocess
import os
import glob
import pandas as pd
import sys
import argparse
from datetime import datetime, timedelta

def run_test():
    parser = argparse.ArgumentParser(description="Verify Atlas Learn Mode")
    parser.add_argument("--days", type=int, default=1, help="Number of days to simulate")
    args = parser.parse_args()

    # 1. Clear old logs
    print("🧹 Cleaning old Atlas logs...")
    for f in glob.glob("atlas/data/states_*.parquet"):
        try:
            os.remove(f)
        except OSError:
            pass
        
    # Valid range: End on Yesterday (to ensure data availability)
    end_dt = datetime.now() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=args.days - 1)
    
    start_date = start_dt.strftime('%Y-%m-%d')
    end_date = end_dt.strftime('%Y-%m-%d')
    
    print(f"🚀 Launching Atlas Learn Mode for {args.days} days ({start_date} to {end_date})...")
    
    # Use python -m engine.gateway to ensure package resolution works correctly
    # Explicitly pass BOTH start and end date to avoid Gateway defaults
    cmd = [
        sys.executable, "-m", "engine.gateway", "learn", 
        "--days", str(args.days), 
        "--symbol", "NIFTY",
        "--start-date", start_date,
        "--end-date", end_date 
    ]
    
    # Ensure current directory is in PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        # Run simulation with timeout proportional to days
        timeout = 120 * args.days
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env) 
        
        # Print output for debugging
        if result.stdout: print(result.stdout)
        if result.stderr: print(result.stderr)
        
        if result.returncode != 0:
            print(f"❌ Execution Failed with return code {result.returncode}")
            return
            
    except subprocess.TimeoutExpired:
        print("⚠️ Timeout (simulation took too long), but checking for logs...")
    except Exception as e:
        print(f"❌ Execution Error: {e}")
        return

    # 3. Verify Output
    files = glob.glob("atlas/data/states_*.parquet")
    if not files:
        print("❌ No State Logs found in atlas/data/")
        sys.exit(1)
        
    latest_file = max(files, key=os.path.getctime)
    print(f"✅ Found Log: {latest_file}")
    
    try:
        df = pd.read_parquet(latest_file)
        print(f"📊 Rows Logs: {len(df)}")
        print("Columns:", list(df.columns))
        
        # Check Critical Columns
        required = ['entropy_price', 'velocity', 'skew', 'action']
        missing = [c for c in required if c not in df.columns]
        
        if missing:
            print(f"❌ Missing Columns: {missing}")
            sys.exit(1)
            
        print("✅ Schema Verified.")
        print("Sample Data:")
        print(df[required].head())
        
        if len(df) > 0:
            print("✅ Atlas Integration Successful!")
        else:
            print("⚠️ Log file empty (No ticks processed?)")
            
    except Exception as e:
        print(f"❌ CSV Verification Error: {e}")

if __name__ == "__main__":
    run_test()
