import argparse
import subprocess
import time
import sys

def run_command(command):
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")

def kill_existing():
    print("🧹 Cleaning up existing processes...")
    try:
        subprocess.run("docker exec beast_engine pkill -f python", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run("docker exec beast_producer pkill -f python", shell=True, stderr=subprocess.DEVNULL)
    except:
        pass
    time.sleep(1)

def trigger(mode, days, debug, symbol="BANKNIFTY"):
    kill_existing()
    print(f"🔥 Triggering Mode: {mode.upper()} for {symbol}")

    if mode == "backtest":
        print(f"   📜 Running Historical Backtest for {days} days...")
        # Run blocking using the new gateway
        run_command(f"docker exec beast_engine python -m engine.gateway backtest --days {days} --symbol {symbol}")

    elif mode == "mock":
        print(f"   🎭 Starting MOCK Session (Replaying last {days} days for {symbol})...")
        # 1. Start Producer (Mock) with Log Redirection
        cmd_producer = f'docker exec -d beast_producer sh -c "python -m workers.stream_producer --mock --days {days} --symbol {symbol} > /proc/1/fd/1 2>/proc/1/fd/1"'
        run_command(cmd_producer)
        print("      ✅ Producer Started (Adversarial Data)")
        
        # Give producer time to initialize
        print("      ⏳ Waiting 3s for producer to start streaming...")
        time.sleep(3)
        
        # 2. Start Engine with Log Redirection
        flags = f"--symbol {symbol}"
        if debug:
            flags += " --debug-schedule"
        
        cmd_engine = f'docker exec -d beast_engine sh -c "python -u -m engine.gateway mock {flags} > /proc/1/fd/1 2>/proc/1/fd/1"'
        run_command(cmd_engine)
        print(f"      ✅ Engine Started (Mock Mode{', Debug Schedule' if debug else ''})")
        print("\n👀 Monitor logs with: docker logs -f beast_engine")

    elif mode == "live":
        print(f"   ⚠️ STARTING REAL LIVE TRADING for {symbol} ⚠️")
        confirm = input("   Are you sure? (type 'YES'): ")
        if confirm != "YES":
            print("   ❌ Aborted.")
            return

        # 1. Start Producer (Live)
        cmd_producer = f'docker exec -d beast_producer sh -c "python -m workers.stream_producer --symbol {symbol} > /proc/1/fd/1 2>/proc/1/fd/1"'
        run_command(cmd_producer)
        print("      ✅ Producer Started (Fyers WebSocket)")
        
        # 2. Start Engine (Live Exec)
        cmd_engine = f'docker exec -d beast_engine sh -c "python -m engine.gateway live --symbol {symbol} > /proc/1/fd/1 2>/proc/1/fd/1"'
        run_command(cmd_engine)
        print("      ✅ Engine Started (REAL MONEY EXECUTION)")
        print("\n👀 Monitor logs with: docker logs -f beast_engine")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock AI Beast Control Plane")
    parser.add_argument("mode", choices=["backtest", "mock", "live"], help="Execution Mode")
    parser.add_argument("--days", type=int, default=5, help="Days for backtest/mock")
    parser.add_argument("--symbol", type=str, default="BANKNIFTY", help="Ticker symbol")
    parser.add_argument("--debug", action="store_true", help="Enable fast schedule for testing")
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
        
    args = parser.parse_args()
    trigger(args.mode, args.days, args.debug, args.symbol)
