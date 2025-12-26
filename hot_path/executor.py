from enum import Enum
from datetime import time

class Action(Enum):
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    EXIT_CALL = "EXIT_CALL"
    EXIT_PUT = "EXIT_PUT"
    HOLD = "HOLD"
    WAIT = "WAIT"

class ExitReason(Enum):
    SL = "SL Hit"
    TARGET = "Target Hit"
    AI_EXIT = "AI Logic Exit"
    FORCE = "Force Square-off"
    EOD = "EOD Square-off"

class HotPathExecutor:
    def __init__(self):
        self.active_instructions = {} 
        self.open_position = None     
        self.trades = []            # Buffer for DB logging
        self.trade_ledger = []      # Permanent list for EOD Audit
        self.entry_cutoff = time(14, 45)
        self.force_exit_time = time(15, 15)

    def update_instructions(self, instructions):
        """Received from LLM Tactical Update"""
        action = instructions.get('action', 'N/A')
        entry = instructions.get('entry_price', 'N/A')
        # Compact log: action + entry only
        print(f"      ⚙️ Instr: {action} @{entry}")
        self.active_instructions = instructions

    def process_tick(self, tick):
        price = tick['close']
        timestamp = tick['timestamp']
        current_time_only = timestamp.time() if hasattr(timestamp, 'time') else timestamp
        
        # 1. Mandatory 15:15 Square-off
        if current_time_only >= self.force_exit_time and self.open_position:
            self.square_off(price, timestamp, reason=ExitReason.EOD.value)
            return

        # 2. Manage Open Position (Including proactive AI exits)
        if self.open_position:
            # Check for AI signaling an exit
            ai_action = self.active_instructions.get('action')
            pos_side = self.open_position['side']
            
            if (pos_side == 'CALL' and ai_action == Action.EXIT_CALL.value) or \
               (pos_side == 'PUT' and ai_action == Action.EXIT_PUT.value):
                # Exit at current close price
                self.square_off(price, timestamp, reason=ExitReason.AI_EXIT.value)
                return

            self._manage_position(tick, timestamp)
            return

        # 3. Check Entry Triggers (Strictly before 14:45)
        if current_time_only > self.entry_cutoff:
            return

        if not self.active_instructions:
            return

        action = self.active_instructions.get('action')
        entry_level = self.active_instructions.get('entry_price', 0)
        
        # Use full OHLC for realistic entry price determination
        candle_open = tick.get('open', price)
        candle_high = tick.get('high', price)
        candle_low = tick.get('low', price)
        
        if action == Action.BUY_CALL.value:
            # CALL: Expecting price to go UP
            if entry_level == 0:
                # Immediate entry at open
                self._enter_trade(candle_open, timestamp, 'CALL')
            elif candle_high >= entry_level:
                # Entry level was reached this candle
                if candle_open >= entry_level:
                    # Gap up beyond entry - fill at open (slippage)
                    self._enter_trade(candle_open, timestamp, 'CALL')
                else:
                    # Price traversed UP through entry - fill at exact entry
                    self._enter_trade(entry_level, timestamp, 'CALL')
                    
        elif action == Action.BUY_PUT.value:
            # PUT: Expecting price to go DOWN
            if entry_level == 0:
                # Immediate entry at open
                self._enter_trade(candle_open, timestamp, 'PUT')
            elif candle_low <= entry_level:
                # Entry level was reached this candle
                if candle_open <= entry_level:
                    # Gap down beyond entry - fill at open (slippage)
                    self._enter_trade(candle_open, timestamp, 'PUT')
                else:
                    # Price traversed DOWN through entry - fill at exact entry
                    self._enter_trade(entry_level, timestamp, 'PUT')

    def _enter_trade(self, price, timestamp, side):
        print(f"      🚀 EXECUTION: Entered {side} at {price}")
        
        self.open_position = {
            'side': side,
            'entry_price': price,
            'entry_time': timestamp,
            'sl': self.active_instructions.get('sl'),
            'target': self.active_instructions.get('target')
        }
        
        entry_signal = {
            'type': 'ENTRY',
            'side': side,
            'entry_price': price,
            'entry_time': timestamp,
            'sl': self.active_instructions.get('sl'),
            'target': self.active_instructions.get('target')
        }
        self.trades.append(entry_signal)
        # self.trade_ledger is updated on EXIT for session summary
        
        # Clear instruction after entry
        self.active_instructions = {}

    def _manage_position(self, tick, timestamp):
        """Manage open position SL/Target with realistic OHLC-based exit prices."""
        pos = self.open_position
        if not pos: return
        
        # Skip SL/Target check on the same candle as entry (prevent false immediate exits)
        if pos.get('entry_time') == timestamp:
            return
        
        candle_open = tick.get('open', tick['close'])
        candle_high = tick.get('high', tick['close'])
        candle_low = tick.get('low', tick['close'])
        
        sl = pos.get('sl')
        target = pos.get('target')
        
        exit_price = None
        exit_reason = None
        
        if pos['side'] == 'CALL':
            # CALL: SL < Entry < Target
            sl_hit = sl and candle_low <= sl
            target_hit = target and candle_high >= target
            
            if sl_hit and target_hit:
                # Both hit - determine priority based on Open proximity
                if abs(candle_open - sl) < abs(candle_open - target):
                    # Closer to SL, likely hit first
                    exit_price = sl if candle_open > sl else candle_open
                    exit_reason = ExitReason.SL.value
                else:
                    # Closer to Target, likely hit first
                    exit_price = target if candle_open < target else candle_open
                    exit_reason = ExitReason.TARGET.value
            elif sl_hit:
                # SL hit only
                if candle_open <= sl:
                    exit_price = candle_open  # Gap down - slippage
                else:
                    exit_price = sl  # Traversed down to SL
                exit_reason = ExitReason.SL.value
            elif target_hit:
                # Target hit only
                if candle_open >= target:
                    exit_price = candle_open  # Gap up - favorable
                else:
                    exit_price = target  # Traversed up to Target
                exit_reason = ExitReason.TARGET.value
                
        elif pos['side'] == 'PUT':
            # PUT: Target < Entry < SL
            sl_hit = sl and candle_high >= sl
            target_hit = target and candle_low <= target
            
            if sl_hit and target_hit:
                # Both hit - determine priority based on Open proximity
                if abs(candle_open - sl) < abs(candle_open - target):
                    exit_price = sl if candle_open < sl else candle_open
                    exit_reason = ExitReason.SL.value
                else:
                    exit_price = target if candle_open > target else candle_open
                    exit_reason = ExitReason.TARGET.value
            elif sl_hit:
                # SL hit only
                if candle_open >= sl:
                    exit_price = candle_open  # Gap up - slippage
                else:
                    exit_price = sl  # Traversed up to SL
                exit_reason = ExitReason.SL.value
            elif target_hit:
                # Target hit only
                if candle_open <= target:
                    exit_price = candle_open  # Gap down - favorable
                else:
                    exit_price = target  # Traversed down to Target
                exit_reason = ExitReason.TARGET.value
            
        if exit_price and exit_reason:
            self.square_off(exit_price, timestamp, reason=exit_reason)

    def square_off(self, price, timestamp, reason="Exit"):
        if not self.open_position: return
        
        pos = self.open_position
        pnl = price - pos['entry_price'] if pos['side'] == 'CALL' else pos['entry_price'] - price
        
        print(f"      🛑 EXECUTION: Exiting {pos['side']} at {price} ({reason}) | PnL: {pnl:.1f}")
        
        exit_trade = {
            'side': pos['side'],
            'entry_price': pos['entry_price'],
            'entry_time': pos['entry_time'],
            'exit_price': price,
            'exit_time': timestamp,
            'reason': reason,
            'pnl': pnl
        }
        
        self.trades.append({'type': 'EXIT', **exit_trade})
        self.trade_ledger.append(exit_trade)
        self.open_position = None
