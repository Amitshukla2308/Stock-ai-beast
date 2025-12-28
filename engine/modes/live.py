from engine.modes.mock import MockMode
from brokers.fyers.auth import load_token
import os

class LiveMode(MockMode):
    """
    Inherits from MockMode because logic is identical 
    EXCEPT for Execution (on_tick trade handling).
    """
    def __init__(self, debug_schedule=False, symbol="BANKNIFTY"):
        super().__init__(debug_schedule, symbol=symbol)
        
        # Initialize Broker
        print("   🔴 Initializing LIVE Broker (Fyers)")
        from fyers_apiv3 import fyersModel
        token = load_token()
        client_id = os.getenv("FYERS_CLIENT_ID")
        self.broker = fyersModel.FyersModel(client_id=client_id, token=token, is_async=False, log_path="")

    def start(self):
        print("🚀 Starting LIVE Mode (REAL MONEY)")
        super().start()

    def on_tick(self, message):
        """Handle Live Tick with REAL Execution"""
        # ... (Parsing logic same as Mock/Base) ...
        # Duplicating parsing for safety to avoid multiple inheritance complexity for now
        # or call super().on_tick if refactored to separate signal vs execution.
        
        # NOTE: To be clean, we should decouple Signal Generation from Execution in BaseMode.
        # For this refactor step, I will override on_tick completely to ensure safety.
        
        from dateutil import parser as date_parser
        from datetime import datetime
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        
        def safe_float(val):
            try: return float(val)
            except: return 0.0

        try:
             ts = date_parser.parse(message.get('timestamp'))
        except:
             ts = datetime.now(IST)
             
        tick = {
            'timestamp': ts,
            'close': safe_float(message.get('ltp')),
            'open': safe_float(message.get('open')),
            'high': safe_float(message.get('high')),
            'low': safe_float(message.get('low'))
        }
        self.last_tick = tick
        self.hot_path.process_tick(tick)
        
        # HEARTBEAT LOGGING
        if not hasattr(self, 'last_heartbeat_time'): self.last_heartbeat_time = ts
        time_since_hb = (ts - self.last_heartbeat_time).total_seconds() / 60
        if time_since_hb >= 5:
            instr = self.hot_path.active_instructions.get('action', 'WAIT')
            entry = self.hot_path.active_instructions.get('entry_price', 'N/A')
            print(f"   [{ts.strftime('%H:%M')}] 💓 Monitor: Price {tick['close']:.1f} | Instr: {instr} ({entry})")
            self.last_heartbeat_time = ts
        
        if self.hot_path.trades:
             for trade in self.hot_path.trades:
                  is_entry = (trade.get('type') == 'ENTRY')
                  
                  if is_entry:
                      action = "BUY"
                      from engine.contract_selector import select_option_contract
                      symbol = select_option_contract(trade['side'], tick['close'])
                      trade['symbol'] = symbol
                  else:
                      action = "SELL"
                      symbol = trade.get('symbol', 'UNKNOWN')
                  
                  # EXECUTE REAL ORDER
                  from workers.oms import execute_order
                  print(f"   ⚠️ LIVE ORDER: {action} {symbol} @ {tick['close']:.1f}")
                  
                  result = execute_order(
                      broker_model=self.broker,
                      symbol=symbol,
                      action=action,
                      quantity=15, # TODO: Configurable
                      reason=trade.get('reason', 'Strategy'),
                      market_price=tick['close']
                  )
                  
                  trade['order_status'] = result.get('status')
                  
                  # Update Internal Portfolio for shadow comparison
                  if result.get('status') in ['FILLED', 'SUBMITTED']:
                       self.portfolio.process_fill(
                           order_type='ENTRY' if is_entry else 'EXIT',
                           symbol=symbol,
                           quantity=15,
                           price=tick['close'],
                           side=trade['side']
                       )
                  
                  self.journal.log_trade(trade)
             self.hot_path.trades = []
