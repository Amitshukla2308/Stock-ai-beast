import argparse
from engine.modes.backtest import BacktestMode
from engine.modes.mock import MockMode
from engine.modes.live import LiveMode
from datetime import datetime, timedelta

def get_engine(mode, args=None):
    """
    Factory to create the appropriate engine instance.
    """
    if mode == 'backtest':
        symbol = args.symbol if args else "BANKNIFTY"
        
        if args and args.start_date and args.end_date:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
            days = (end_date - start_date).days + 1
        else:
            days = args.days if args else 5
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

        # AUTO-PREFILL: Ensure data exists before simulating
        try:
            print(f"⏳ Ensuring Data Availability for {symbol} (Auto-Prefill: {days} days)...")
            from data.prefill import run as run_prefill
            run_prefill(
                days=days, 
                symbol=symbol, 
                resolution="1", 
                start_date=start_date if 'start_date' in locals() else None,
                end_date=end_date if 'end_date' in locals() else None
            )
        except Exception as e:
            print(f"⚠️ Prefill Warning: {e}")
        
        balance = args.balance if args and hasattr(args, 'balance') else 30000
        return BacktestMode(start_date=start_date, end_date=end_date, symbol=symbol, initial_balance=balance)
        
    elif mode == 'mock':
        debug = args.debug_schedule if args else False
        symbol = args.symbol if args else "BANKNIFTY"
        return MockMode(debug_schedule=debug, symbol=symbol)
        
    elif mode == 'live':
        debug = args.debug_schedule if args else False
        symbol = args.symbol if args else "BANKNIFTY"
        return LiveMode(debug_schedule=debug, symbol=symbol)
        
    else:
        raise ValueError(f"Unknown mode: {mode}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock AI Beast Gateway")
    parser.add_argument("mode", choices=['backtest', 'mock', 'live'], help="Trading Mode")
    parser.add_argument("--days", type=int, default=5, help="Days for backtest")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default="BANKNIFTY", help="Ticker symbol (e.g. NIFTY, BANKNIFTY)")
    parser.add_argument("--balance", type=int, default=30000, help="Starting balance in rupees")
    parser.add_argument("--debug-schedule", action="store_true", help="Fast schedule for debugging")
    
    args = parser.parse_args()
    
    print(f"🔌 Gateway calling Service: {args.mode.upper()}")
    
    engine = get_engine(args.mode, args)
    engine.start()
