import argparse

from datetime import datetime, timedelta
from engine.auth_fyers import validate_token_file, validate_live_session
import logging
import sys
import os
from engine.comm import emit_telegram_signal

# Configure Logging (Dual Output)
# Configure Logging (Dual Output: File=DEBUG, Console=INFO)
log_dir = os.path.join(os.getcwd(), "logs_v2")
os.makedirs(log_dir, exist_ok=True)

# File Handler (Detailed)
# File Handler (Detailed)
file_handler = None
try:
    file_handler = logging.FileHandler("logs_v2/beast_engine.log", mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
except PermissionError:
    print("⚠️ Warning: Could not write to log file (Permission Denied). Switched to Console Only.")
except Exception as e:
    print(f"⚠️ Warning: Log file init failed: {e}")

# Console Handler (Clean UI)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
# Use a simpler format for console if desired, or keep standard
console_handler.setFormatter(logging.Formatter('%(message)s')) # Cleaner message-only for console

handlers = [console_handler]
if file_handler:
    handlers.append(file_handler)

logging.basicConfig(
    level=logging.DEBUG, # Capture all at root level
    handlers=handlers
)
# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

def check_token():
    token = validate_token_file()
    if not token:
        logging.error("❌ Fyers Token Missing or Expired (File Check)!")
        raise Exception("Fyers Token Missing or Expired! Please run /login first.")
    
    # Strict Live Validation
    if not validate_live_session(token):
        logging.error("❌ Fyers Token Invalid (Live Check Failed)!")
        # Attempt to delete the invalid file to force refresh next time
        try: os.remove("fyers_token.json") 
        except: pass
        raise Exception("Login required (Token Invalid)")
        
    logging.info("✅ Fyers Token is Valid & Live.")

def get_engine(mode, args=None):
    """
    Factory to create the appropriate engine instance.
    """
    if mode == 'backtest':
        os.environ["BEAST_DB_NAME"] = "simulation.db"
        from engine.modes.backtest import BacktestMode as EngineClass
            
        symbol = args.symbol if args else "NIFTY"
        
        if args and args.start_date:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
            if args.end_date:
                end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
                days = (end_date - start_date).days + 1
            else:
                # Start Date + Days (default 1)
                days = args.days if args and args.days else 1
                end_date = start_date + timedelta(days=days-1)
        else:
            # Lookback Mode (End Date + Days OR Default)
            days = args.days if args and args.days else 5
            if args and args.end_date:
                end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
            else:
                end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = end_date - timedelta(days=days-1)

        # AUTO-PREFILL: Ensure data exists before simulating
        try:
            logging.debug(f"      ⏭️ Skipping Fyers Token validation for {mode.capitalize()} Mode.")

            emit_telegram_signal("STATUS", {"msg": f"⏳ Prefilling Data for {symbol} ({days} days)..."})
            from data.prefill import run as run_prefill
            
            # Smart Resolution Choice: Use 5-min for multi-year, 1-min for short term
            res = "5"
            if days > 100: res = "5" # Force 5min for speed on large ranges
            
            run_prefill(
                days=days, 
                symbol=symbol, 
                resolution=res, 
                start_date=start_date,
                end_date=end_date
            )
            emit_telegram_signal("STATUS", {"msg": "✅ Data Ready. Starting Simulation..."})
            
        except Exception as e:
            # Emit Warning Status
            err_msg = str(e).replace('"', "'")
            emit_telegram_signal("STATUS", {"msg": f"⚠️ Prefill Warning: {err_msg}"})
            logging.warning(f"⚠️ Prefill failed (Simulation will proceed with existing data): {e}")
            if mode != 'backtest':
                raise e # CRITICAL for Live/Mock, but Non-Fatal for Backtest
        
        # 2. Return Engine Instance (Always)
        return EngineClass(
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            resolution=res,
            initial_balance=args.balance if args else 30000,
            use_gpu=args.gpu if args else False
        )
        
    elif mode == 'mock':
        os.environ["BEAST_DB_NAME"] = "trading.db" # Mock uses Gold Source (Live Data)
        from engine.modes.live import LiveMode
        debug = args.debug_schedule if args else False
        symbol = args.symbol if args else "NIFTY"
        replay = args.replay if hasattr(args, 'replay') else False
        return LiveMode(debug_schedule=debug, symbol=symbol, chat_id=args.chat_id, mock=True, replay=replay)
        
    elif mode == 'live':
        os.environ["BEAST_DB_NAME"] = "trading.db"
        from engine.modes.live import LiveMode
        debug = args.debug_schedule if args else False
        symbol = args.symbol if args else "NIFTY"
        return LiveMode(debug_schedule=debug, symbol=symbol, chat_id=args.chat_id, mock=False)
        
    else:
        raise ValueError(f"Unknown mode: {mode}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock AI Beast Gateway")
    parser.add_argument('mode', choices=['live', 'backtest', 'mock'], help='beast operation mode')
    parser.add_argument("--days", type=int, default=5, help="Days for backtest")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default="NIFTY", help="Ticker symbol (e.g. NIFTY, BANKNIFTY)")
    parser.add_argument("--balance", type=int, default=30000, help="Starting balance in rupees")
    parser.add_argument("--chat-id", type=str, default=os.getenv("TELEGRAM_CHAT_ID"), help="Telegram Chat ID for notifications")
    parser.add_argument("--debug-schedule", action="store_true", help="Fast schedule for debugging")
    parser.add_argument("--validate-auth", action="store_true", help="Only validate auth and exit")
    parser.add_argument("--gpu", action="store_true", help="Enable VRAM (GPU) Acceleration via RAPIDS")
    parser.add_argument("--replay", action="store_true", help="Run in Historical Replay Mode (Adversarial) for mock mode")
    
    args = parser.parse_args()

    if args.validate_auth:
        try:
            check_token()
            print("✅ AUTH_OK")
            sys.exit(0)
        except Exception as e:
            print(f"❌ AUTH_FAILED: {e}")
            sys.exit(1)
    
    if not args.validate_auth and not args.mode:
        parser.error("the following arguments are required: mode")
    
    if args.validate_auth:
        try:
            check_token()
            print("✅ AUTH_OK")
            sys.exit(0)
        except Exception as e:
            print(f"❌ AUTH_FAILED: {e}")
            sys.exit(1)
    
    print(f"🔌 Gateway calling Service: {args.mode.upper()}")
    
    engine = get_engine(args.mode, args)
    engine.start()
