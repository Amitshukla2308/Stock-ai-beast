from enum import Enum
from datetime import time

class Action(Enum):
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    EXIT_CALL = "EXIT_CALL"
    EXIT_PUT = "EXIT_PUT"
    HOLD = "HOLD"
    WAIT = "WAIT"
    # LLM Smart Position Adjustments
    ADJUST_SL = "ADJUST_SL"
    ADJUST_TARGET = "ADJUST_TARGET"
    EXIT_NOW = "EXIT_NOW"

class ExitReason(Enum):
    SL = "SL Hit"
    TARGET = "Target Hit"
    AI_EXIT = "AI Logic Exit"
    AI_SMART_EXIT = "AI Smart Exit"  # LLM detected reversal
    TIME_EXIT = "Time-Based Exit"
    FORCE = "Force Square-off"
    EOD = "EOD Square-off"

class HotPathExecutor:
    def __init__(self):
        self.active_instructions = {} 
        self.open_position = None     
        self.trades = []            # Buffer for DB logging
        self.trade_ledger = []      # Permanent list for EOD Audit
        self.balance_monitor = None  # Set by BacktestMode for balance tracking
        self.entry_cutoff = time(14, 45)
        self.force_exit_time = time(15, 15)
        
        # Load momentum thresholds from historical analysis
        import json
        try:
            with open('data/momentum_thresholds.json', 'r') as f:
                thresholds = json.load(f)
                self.momentum_thresholds = {
                    'avg1': thresholds.get('avg1', 408.8),
                    'avg2': thresholds.get('avg2', 568.2),
                    'avg3': thresholds.get('avg3', 787.3)
                }
        except:
            # Fallback to defaults if file not found
            self.momentum_thresholds = {'avg1': 408.8, 'avg2': 568.2, 'avg3': 787.3}
        
        # Intraday momentum tracking
        self.day_high = None
        self.day_low = None
        self.day_open = None
        self.total_upward_movement = 0
        self.total_downward_movement = 0
        self.current_day = None
        
        # Scalping mode
        self.scalping_mode = False
        self.scalping_wins = 0
        self.scalping_losses = 0
        
        # Basic momentum exhaustion tracking (VIX-based)
        self.last_exit_time = None
        self.last_trade_pnl = None
        self.prev_vix = None
        self.current_vix = None
    
    def _round_to_tick(self, price, tick=0.05):
        """Round price to nearest tick size (default 0.05 for NSE)"""
        if price is None: return None
        return round(round(price / tick) * tick, 2)
    
    def _update_momentum_state(self, tick, timestamp):
        """Track intraday momentum for exhaustion detection"""
        from datetime import datetime
        
        current_day = timestamp.date() if hasattr(timestamp, 'date') else datetime.fromisoformat(str(timestamp)).date()
        
        # Reset on new trading day
        if current_day != self.current_day:
            self.day_open = tick.get('open', tick['close'])
            self.day_high = tick.get('high', tick['close'])
            self.day_low = tick.get('low', tick['close'])
            self.current_day = current_day
            print(f"      📅 New Day: {current_day} | Open: {self.day_open:.1f}")
        else:
            # Update intraday extremes
            self.day_high = max(self.day_high or 0, tick.get('high', tick['close']))
            self.day_low = min(self.day_low or 999999, tick.get('low', tick['close']))
        
        # Calculate directional movement from open
        if self.day_open:
            self.total_upward_movement = max(0, self.day_high - self.day_open)
            self.total_downward_movement = max(0, self.day_open - self.day_low)
    
    def _check_momentum_exhaustion(self, action):
        """Check if momentum exhausted. Returns: 'fresh'|'avg1'|'avg2'|'avg3'|'exceeded'"""
        if not self.day_open:
            return 'fresh'
        
        is_bullish = action == "BUY_CALL"
        movement = self.total_upward_movement if is_bullish else self.total_downward_movement
        
        if movement >= self.momentum_thresholds['avg3']:
            return 'exceeded'
        elif movement >= self.momentum_thresholds['avg2']:
            return 'avg3'
        elif movement >= self.momentum_thresholds['avg1']:
            return 'avg2'
        else:
            return 'fresh'
    
    def _is_same_direction_as_last_trade(self, action):
        """Check if proposed trade is in same direction as last trade"""
        if not self.trade_ledger:
            return False
        
        last_trade = self.trade_ledger[-1]
        last_side = last_trade.get('side')
        
        return (action == "BUY_CALL" and last_side == 'CALL') or (action == "BUY_PUT" and last_side == 'PUT')
    
    def _is_reversal_setup(self, action):
        """Check if this is a reversal trade (against recent momentum)"""
        if not self.day_open:
            return False
        
        is_bullish_trade = action == "BUY_CALL"
        has_upward_momentum = self.total_upward_movement > self.total_downward_movement
        
        return is_bullish_trade != has_upward_momentum

    def update_instructions(self, instructions):
        """Received from LLM Tactical Update. Applies risk-gating and logic-guards."""
        action = instructions.get('action', 'HOLD')
        # Use 'or 0' to handle cases where confidence might be explicitly None
        raw_confidence = instructions.get('confidence') if instructions.get('confidence') is not None else 0
        morning_bias = instructions.get('morning_bias', 'NEUTRAL')
        
        # Robust Data Extraction (Handle LLM data flow gaps)
        atr = instructions.get('atr')
        if atr is None or atr == 'N/A':
            atr = 50.0 
            
        vix = instructions.get('vix')
        if vix is None or vix == 'N/A':
            vix = 15.0

        # 1. BRAIN CALIBRATION: (Trust Prompt v4.0's internal multi-step calibration)
        final_confidence = raw_confidence

        # 2. BIAS GATING: (Already handled by Prompt v4.0 logic)
        # We only apply manual penalties if the LLM failed to follow bias alignment
        if morning_bias == "BULLISH" and action == "BUY_PUT":
            final_confidence *= 0.5
        elif morning_bias == "BEARISH" and action == "BUY_CALL":
            final_confidence *= 0.5

        # 3. CONFIDENCE THRESHOLD: Regime-Dependent v4.0
        # COMPLACENT: 0.55 | NORMAL: 0.50 | PANIC: 0.65
        threshold = 0.50
        if vix < 13: threshold = 0.55
        elif vix > 18: threshold = 0.65

        if final_confidence < threshold and action in ["BUY_CALL", "BUY_PUT"]:
            # print(f"      🚫 Filtered: {action} (Conf {final_confidence:.2f} < {threshold})")
            instructions['action'] = "HOLD"
        
        # 3.5 ENTRY LOCATION FILTER: Skip SUBOPTIMAL entries with low confidence
        entry_location = instructions.get('entry_location', 'GOOD')
        if entry_location == 'SUBOPTIMAL' and final_confidence < 0.6 and action in ["BUY_CALL", "BUY_PUT"]:
            print(f"      ⚠️ SUBOPTIMAL entry + low confidence ({final_confidence:.2f}) → SKIP")
            instructions['action'] = "HOLD"
        
        # 3.6 LEVEL CONFIRMATION FILTER: Respect S/P/R with 20pt confirmation
        # Don't enter against a level without confirmation of break
        entry = instructions.get('entry_price') or instructions.get('entry', 0)
        support = instructions.get('support', 0)
        pivot = instructions.get('pivot', 0)
        resistance = instructions.get('resistance', 0)
        
        if entry and action in ["BUY_CALL", "BUY_PUT"] and instructions['action'] != "HOLD":
            # For PUT: Don't enter if within 20pts ABOVE support (risk of bounce)
            if action == "BUY_PUT" and support:
                dist_above_support = entry - support
                if 0 < dist_above_support <= 20:
                    print(f"      ⚠️ PUT entry {entry:.1f} within 20pts above Support {support:.1f} → SKIP (wait for break)")
                    instructions['action'] = "HOLD"
            
            # For CALL: Don't enter if within 20pts BELOW resistance (risk of rejection)
            if action == "BUY_CALL" and resistance:
                dist_below_resistance = resistance - entry
                if 0 < dist_below_resistance <= 20:
                    print(f"      ⚠️ CALL entry {entry:.1f} within 20pts below Resistance {resistance:.1f} → SKIP (wait for break)")
                    instructions['action'] = "HOLD"
            
            # For both: Don't enter within 20pts of pivot (reversal zone)
            if pivot:
                dist_to_pivot = abs(entry - pivot)
                if dist_to_pivot <= 20:
                    print(f"      ⚠️ Entry {entry:.1f} within 20pts of Pivot {pivot:.1f} → SKIP (reversal zone)")
                    instructions['action'] = "HOLD"
        
        # 4. USE LLM's SL/TARGET VALUES (v5.1 - Trust prompt logic)
        # The LLM prompt now calculates proper 2x R:R targets
        # We apply minimum floors AND create fallbacks if LLM didn't provide values
        entry = instructions.get('entry_price') or instructions.get('entry', 0)
        llm_sl = instructions.get('sl')
        llm_target = instructions.get('target')
        
        if entry and action in ["BUY_CALL", "BUY_PUT"] and instructions['action'] != "HOLD":
            # CRITICAL: Create fallback SL if LLM didn't provide one (prevents unlimited losses!)
            if not llm_sl:
                default_sl_dist = 30  # Fixed 30 pt fallback
                if action == "BUY_CALL":
                    instructions['sl'] = self._round_to_tick(entry - default_sl_dist)
                else:
                    instructions['sl'] = self._round_to_tick(entry + default_sl_dist)
                print(f"      ⚠️ No SL from LLM - using fallback: {instructions['sl']}")
            else:
                sl_dist = abs(entry - llm_sl)
                
                # MINIMUM SL floor: 15 pts
                if sl_dist < 15:
                    if action == "BUY_CALL":
                        instructions['sl'] = self._round_to_tick(entry - 15)
                    else:
                        instructions['sl'] = self._round_to_tick(entry + 15)
                    print(f"      ⚠️ SL too tight ({sl_dist:.0f}pts) - capped to 15pts: {instructions['sl']}")
                
                # MAXIMUM SL cap: 50 pts (prevents huge losses like -113 pts!)
                elif sl_dist > 50:
                    if action == "BUY_CALL":
                        instructions['sl'] = self._round_to_tick(entry - 50)
                    else:
                        instructions['sl'] = self._round_to_tick(entry + 50)
                    print(f"      ⚠️ SL too wide ({sl_dist:.0f}pts) - capped to 50pts: {instructions['sl']}")
            
            # CRITICAL: Create fallback Target if LLM didn't provide one
            if not llm_target:
                default_target_dist = 60  # Fixed 60 pt fallback (2x SL)
                if action == "BUY_CALL":
                    instructions['target'] = self._round_to_tick(entry + default_target_dist)
                else:
                    instructions['target'] = self._round_to_tick(entry - default_target_dist)
                print(f"      ⚠️ No Target from LLM - using fallback: {instructions['target']}")
            else:
                # Apply minimum Target floor of 30 pts
                target_dist = abs(entry - llm_target)
                if target_dist < 30:
                    if action == "BUY_CALL":
                        instructions['target'] = self._round_to_tick(entry + 30)
                    else:
                        instructions['target'] = self._round_to_tick(entry - 30)
            
            # 4.1 TARGET LEVEL ADJUSTMENT: Cap target to respect S/P/R levels
            # If a level blocks target path, cap to 15pts before that level
            current_target = instructions.get('target', llm_target)
            if current_target:
                if action == "BUY_PUT":
                    # For PUT: target is below entry - check if support blocks it
                    if support and support > current_target and support < entry:
                        # Support is between entry and target - cap to 15pts before support
                        new_target = support - 15
                        if new_target != current_target:
                            print(f"      📉 Target capped: Support {support:.1f} in way → TGT {current_target:.1f} → {new_target:.1f}")
                            instructions['target'] = new_target
                else:  # BUY_CALL
                    # For CALL: target is above entry - check if resistance blocks it
                    if resistance and resistance < current_target and resistance > entry:
                        # Resistance is between entry and target - cap to 15pts before resistance
                        new_target = resistance - 15
                        if new_target != current_target:
                            print(f"      📈 Target capped: Resistance {resistance:.1f} in way → TGT {current_target:.1f} → {new_target:.1f}")
                            instructions['target'] = new_target

        # === ADAPTIVE MOMENTUM STRATEGY ===
        if action in ["BUY_CALL", "BUY_PUT"] and not self.open_position:
            entry_location = instructions.get('entry_location', 'UNKNOWN')
            vix = instructions.get('vix', 0)
            
            # Update VIX tracking
            self.prev_vix = self.current_vix
            self.current_vix = vix
            
            # Check momentum exhaustion level
            momentum_state = self._check_momentum_exhaustion(action)
            is_same_direction = self._is_same_direction_as_last_trade(action)
            is_reversal = self._is_reversal_setup(action)
            
            # Calculate VIX spike
            vix_spike = False
            if self.prev_vix and self.current_vix:
                vix_change_pct = (self.current_vix - self.prev_vix) / self.prev_vix
                vix_spike = vix_change_pct > 0.05
            
            # Decision tree
            if len(self.trade_ledger) == 0:
                # First trade of the day - use AI recommendation as-is
                pass
            
            elif is_same_direction and momentum_state in ['avg2', 'avg3', 'exceeded']:
                # Momentum exhausted in same direction
                
                if is_reversal:
                    # Catching the reversal - allow trade
                    print(f"      🔄 REVERSAL SETUP: Momentum {momentum_state}, catching turn")
                
                elif entry_location == 'OPTIMAL' and final_confidence >= 0.65:
                    # High quality continuation - SCALPING MODE
                    print(f"      ⚡ SCALPING MODE: Momentum {momentum_state}, tight params")
                    self.scalping_mode = True
                    
                    # Override to scalping parameters
                    entry = instructions.get('entry') or instructions.get('entry_price')
                    if not entry:
                        print("      ⚠️ SCALPING: No entry price, skipping")
                        return
                    if action == "BUY_CALL":
                        instructions['target'] = self._round_to_tick(entry + 30)
                        instructions['sl'] = self._round_to_tick(entry - 15)
                    else:
                        instructions['target'] = self._round_to_tick(entry - 30)
                        instructions['sl'] = self._round_to_tick(entry + 15)
                    instructions['max_hold_minutes'] = 15
                
                elif entry_location == 'SUBOPTIMAL' or final_confidence < 0.60:
                    # Exhausted + poor signal = SKIP
                    movement = self.total_upward_movement if action == "BUY_CALL" else self.total_downward_movement
                    print(f"      ⏸️  MOMENTUM EXHAUSTED: {momentum_state} ({movement:.0f}pts), skipping {entry_location} entry")
                    instructions['action'] = Action.HOLD.value
                    self.active_instructions = instructions
                    return
            
            elif is_same_direction and vix_spike:
                # VIX-based filter (fallback)
                recent_big_win = self.last_trade_pnl and self.last_trade_pnl > 50
                if entry_location == 'SUBOPTIMAL' and final_confidence < 0.60 and recent_big_win:
                    print(f"      ⏸️  VIX SPIKE: {vix_change_pct*100:+.1f}% after +{self.last_trade_pnl:.0f}pt win")
                    instructions['action'] = Action.HOLD.value
                    self.active_instructions = instructions
                    return
        
        # Compact log
        act = instructions.get('action', 'N/A')
        ent = instructions.get('entry_price', 'N/A')
        print(f"      ⚙️ Instr: {act} @{ent} (Conf: {final_confidence:.2f})")
        
        self.active_instructions = instructions


    def process_tick(self, tick):
        price = tick['close']
        timestamp = tick['timestamp']
        current_time_only = timestamp.time() if hasattr(timestamp, 'time') else timestamp
        
        # Update momentum state on every tick
        self._update_momentum_state(tick, timestamp)
        
        # 1. Mandatory 15:15 Square-off
        if current_time_only >= self.force_exit_time and self.open_position:
            self.square_off(price, timestamp, reason=ExitReason.EOD.value)
            return

        # 2. Manage Open Position (Including LLM smart adjustments)
        if self.open_position:
            ai_action = self.active_instructions.get('action')
            pos = self.open_position
            pos_side = pos['side']
            
            # Standard AI exit signals
            if (pos_side == 'CALL' and ai_action == Action.EXIT_CALL.value) or \
               (pos_side == 'PUT' and ai_action == Action.EXIT_PUT.value):
                self.square_off(price, timestamp, reason=ExitReason.AI_EXIT.value)
                return
            
            # NEW: LLM Smart Exit - immediate exit on detected reversal
            if ai_action == Action.EXIT_NOW.value:
                reason_text = self.active_instructions.get('adjustment_reason', 'Reversal detected')
                print(f"      🧠 AI SMART EXIT: {reason_text}")
                self.square_off(price, timestamp, reason=ExitReason.AI_SMART_EXIT.value)
                return
            
            # NEW: LLM SL Adjustment - only allow tightening (towards profit)
            if ai_action == Action.ADJUST_SL.value:
                new_sl = self.active_instructions.get('adjusted_sl')
                current_sl = pos.get('sl')
                if new_sl and current_sl:
                    # Validate: CALL SL can only go UP, PUT SL can only go DOWN
                    if pos_side == 'CALL' and new_sl > current_sl:
                        pos['sl'] = self._round_to_tick(new_sl)
                        reason_text = self.active_instructions.get('adjustment_reason', 'AI trail')
                        print(f"      🧠 AI TRAIL SL: {pos['sl']:.1f} ({reason_text})")
                    elif pos_side == 'PUT' and new_sl < current_sl:
                        pos['sl'] = self._round_to_tick(new_sl)
                        reason_text = self.active_instructions.get('adjustment_reason', 'AI trail')
                        print(f"      🧠 AI TRAIL SL: {pos['sl']:.1f} ({reason_text})")
            
            # NEW: LLM Target Adjustment
            if ai_action == Action.ADJUST_TARGET.value:
                new_target = self.active_instructions.get('adjusted_target')
                if new_target:
                    pos['target'] = self._round_to_tick(new_target)
                    reason_text = self.active_instructions.get('adjustment_reason', 'AI target adjust')
                    print(f"      🧠 AI ADJUST TARGET: {pos['target']:.1f} ({reason_text})")

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
            # Favorable entry: price moved UP from entry (in our direction)
            if entry_level == 0:
                # Immediate entry at open
                self._enter_trade(candle_open, timestamp, 'CALL')
            elif candle_high >= entry_level:
                # Price touched or exceeded entry level
                if candle_open >= entry_level:
                    # Price at or above entry - check if favorable (within 10pts UP)
                    favorable_move = candle_open - entry_level
                    if favorable_move >= 0 and favorable_move <= 10:
                        # Enter at open (price moved in our favor up to 10pts)
                        self._enter_trade(candle_open, timestamp, 'CALL')
                    elif favorable_move > 10:
                        # Price moved too far up, skip - might be exhausted
                        print(f"      ⚠️ SKIP: Price moved {favorable_move:.0f}pts up (too far, might reverse)")
                        self.active_instructions = {}
                        return
                else:
                    # Price traversed UP through entry - fill at exact entry
                    self._enter_trade(entry_level, timestamp, 'CALL')
                    
        elif action == Action.BUY_PUT.value:
            # PUT: Expecting price to go DOWN
            # Favorable entry: price is BELOW entry_level (already moved in our direction)
            if entry_level == 0:
                # Immediate entry at open
                self._enter_trade(candle_open, timestamp, 'PUT')
            elif candle_low <= entry_level:
                # Price touched or went below entry level
                if candle_open <= entry_level:
                    # Price already at or below entry - check if favorable (within 10pts)
                    favorable_move = entry_level - candle_open
                    if favorable_move >= 0 and favorable_move <= 10:
                        # Enter at open (price moved in our favor up to 10pts)
                        # SL will be calculated from actual entry price
                        self._enter_trade(candle_open, timestamp, 'PUT')
                    elif favorable_move > 10:
                        # Price moved too far down, skip - might be exhausted
                        print(f"      ⚠️ SKIP: Price moved {favorable_move:.0f}pts in our favor (too far, might reverse)")
                        self.active_instructions = {}
                        return
                    else:
                        # Price gapped UP (unfavorable), skip
                        print(f"      ⚠️ SKIP: Price gapped up {-favorable_move:.0f}pts (wrong direction)")
                        self.active_instructions = {}
                        return
                else:
                    # Price traversed DOWN through entry - fill at exact entry
                    self._enter_trade(entry_level, timestamp, 'PUT')

    def _enter_trade(self, price, timestamp, side):
        print(f"      🚀 EXECUTION: Entered {side} at {price}")
        
        range_current = self.active_instructions.get('range', 50)  # Get range for trailing
        
        self.open_position = {
            'side': side,
            'entry_price': price,
            'entry_time': timestamp,
            'sl': self.active_instructions.get('sl'),
            'target': self.active_instructions.get('target'),
            'max_hold_minutes': self.active_instructions.get('max_hold_minutes', 30),
            # Trailing SL fields
            'peak_price': price,          # Track best price reached
            'range': range_current,       # For dynamic trail calculation
            'breakeven_set': False,       # Flag: SL moved to breakeven
            'profit_locked': False,       # Flag: Locked +20 pts
            # Fidelity Metrics
            'max_pnl': 0.0,
            'positive_pnls': []           # List of positive PnL ticks
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
        current_price = tick['close']
        
        sl = pos.get('sl')
        target = pos.get('target')
        
        # Calculate and log unrealized PnL
        if pos['side'] == 'CALL':
            unrealized_pnl = current_price - pos['entry_price']
            # Update peak price (for LLM context)
            if current_price > pos.get('peak_price', 0):
                pos['peak_price'] = current_price
        else:
            unrealized_pnl = pos['entry_price'] - current_price
            # Update peak price (for LLM context)
            if pos.get('peak_price') is None or current_price < pos['peak_price']:
                pos['peak_price'] = current_price
        
        # Track fidelity metrics
        if unrealized_pnl > pos['max_pnl']:
            pos['max_pnl'] = unrealized_pnl
        
        # === ADVANCED TRAILING SYSTEM ===
        entry_price = pos['entry_price']
        original_target_dist = pos.get('original_target_dist')
        
        # Store original target distance on first run
        if original_target_dist is None and target:
            if pos['side'] == 'CALL':
                original_target_dist = target - entry_price
            else:
                original_target_dist = entry_price - target
            pos['original_target_dist'] = original_target_dist
        
        # Calculate progress towards target (0-100%)
        target_progress = 0
        if original_target_dist and original_target_dist > 0:
            target_progress = (unrealized_pnl / original_target_dist) * 100
        
        # === SIMPLE SL ADJUSTMENT: At 60% of target, move SL to lock 50% ===
        # No continuous trailing, just one adjustment at the 60% milestone
        if target_progress >= 60 and not pos.get('sl_adjusted'):
            # Calculate 50% of target distance
            locked_profit = int(original_target_dist * 0.5)
            
            if pos['side'] == 'CALL':
                new_sl = entry_price + locked_profit
                if sl is None or new_sl > sl:
                    pos['sl'] = self._round_to_tick(new_sl)
                    pos['sl_adjusted'] = True
                    sl = pos['sl']
                    print(f"      🔒 60% REACHED → SL to +{locked_profit}pts (SL→{sl:.1f})")
            else:  # PUT
                new_sl = entry_price - locked_profit
                if sl is None or new_sl < sl:
                    pos['sl'] = self._round_to_tick(new_sl)
                    pos['sl_adjusted'] = True
                    sl = pos['sl']
                    print(f"      🔒 60% REACHED → SL to +{locked_profit}pts (SL→{sl:.1f})")
        
        # Log position status every candle
        pnl_color = "🟢" if unrealized_pnl >= 0 else "🔴"
        sl_str = f"{sl:.1f}" if sl else "N/A"
        tgt_str = f"{target:.1f}" if target else "N/A"
        prog_str = f" [{target_progress:.0f}% to TGT]" if target_progress > 0 else ""
        print(f"      {pnl_color} {pos['side']} PnL: {unrealized_pnl:+.1f}{prog_str} | Price: {current_price:.1f} | SL: {sl_str} | TGT: {tgt_str}")
        
        exit_price = None
        exit_reason = None
        
        # 0. Time-Based Exit check
        if pos.get('max_hold_minutes'):
            elapsed = (timestamp - pos['entry_time']).total_seconds() / 60
            if elapsed >= pos['max_hold_minutes']:
                exit_price = candle_open
                exit_reason = ExitReason.TIME_EXIT.value
        
        if pos['side'] == 'CALL':
            # CALL: SL < Entry < Target
            sl_hit = sl is not None and candle_low <= sl
            target_hit = target is not None and candle_high >= target
            
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
            sl_hit = sl is not None and candle_high >= sl
            target_hit = target is not None and candle_low <= target
            
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
        pos = self.open_position
        pnl = price - pos['entry_price'] if pos['side'] == 'CALL' else pos['entry_price'] - price
        
        # Track scalping performance
        if self.scalping_mode:
            if pnl > 0:
                self.scalping_wins += 1
                print(f"      ✅ Scalp Win #{self.scalping_wins} ({pnl:+.1f}pts)")
            else:
                self.scalping_losses += 1
                print(f"      ❌ Scalp Loss - exiting scalping mode")
                self.scalping_mode = False
        
        # Calculate final fidelity metrics
        max_pnl = pos.get('max_pnl', 0.0)
        pos_pnls = pos.get('positive_pnls', [])
        mean_open_pnl = sum(pos_pnls) / len(pos_pnls) if pos_pnls else 0.0
        
        print(f"      🛑 EXECUTION: Exiting {pos['side']} at {price} ({reason}) | PnL: {pnl:.1f} | Max: {max_pnl:.1f} | Mean: {mean_open_pnl:.1f}")
        
        # Update balance monitor if available
        if self.balance_monitor:
            new_balance = self.balance_monitor.update_balance(pnl, timestamp)
            rupee_pnl = pnl * 27.5  # 1 pt = ₹27.5
            pnl_str = f"+₹{rupee_pnl:.0f}" if rupee_pnl >= 0 else f"-₹{abs(rupee_pnl):.0f}"
            print(f"      💰 BALANCE: {pnl_str} → ₹{new_balance:,.0f}")
        
        exit_trade = {
            'side': pos['side'],
            'entry_price': pos['entry_price'],
            'entry_time': pos['entry_time'],
            'exit_price': price,
            'exit_time': timestamp,
            'reason': reason,
            'pnl': pnl,
            'max_pnl': max_pnl,
            'mean_open_pnl': mean_open_pnl
        }
        
        self.trades.append({'type': 'EXIT', **exit_trade})
        self.trade_ledger.append(exit_trade)
        
        # Track for momentum exhaustion filter
        self.last_exit_time = timestamp
        self.last_trade_pnl = pnl
        
        self.open_position = None
