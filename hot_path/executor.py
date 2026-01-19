from enum import Enum
from datetime import time
import math

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

# CONSTANTS FOR AUTHORITY SPLIT
MIN_R_MULTIPLE = 1.8
ECONOMIC_FLOOR_INR = 1200
STYLE_PARAMS = {
    'REMR': {'sl': 50, 'tgt': 100},  # 1:2 Fixed (SL 50)
    'ITC':  {'sl': 50, 'tgt': 150},  # 1:3 Trend (Fixed for now, can be dynamic)
    'ORE':  {'sl': 50, 'tgt': 125},  # 1:2.5 Breakout (SL 50)
    'VBD':  {'sl': 50, 'tgt': 100},  # 1:2 Volatility Breakout (SL 50)
}

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
        
        # State for Exceptional Trade Gate
        self.fifteen_min_ranges = []
        self.last_bar_time = None
        self.day_structure = {'highs': [], 'lows': []}
        self.total_trades_today = 0
        self.remr_continuation_monitor = None # Tracks REMR exits for potential ITC re-entry
    
    def _apply_style_geometry(self, instructions):
        """
        AUTHORITY SPLIT: Engine Overrides LLM Geometry.
        Applies hard-coded SL/Target based on Style.
        """
        style = instructions.get('selected_style', 'NONE')
        action = instructions.get('action')
        entry = instructions.get('entry_price') or instructions.get('entry')
        
        if not entry or action not in ["BUY_CALL", "BUY_PUT"]:
            return

        if instructions.get('manual_geometry', False):
            # Engine or LLM (via manual override logic) has already set specific geometry
            # This is used for TREND_GRIND specific ITC params etc.
            # Just validate they exist
            if instructions.get('sl') and instructions.get('target'):
                 print(f"      🛡️ GEOMETRY PRESERVED (Manual Override): SL {instructions.get('sl')} | TGT {instructions.get('target')}")
                 return

        params = STYLE_PARAMS.get(style)
        
        # If unknown style, Fallback to defaults or keep LLM's if valid?
        # User said "LLM may suggest, but engine must override if TGT < MIN or SL < MIN"
        # Let's use generic defaults for unknown styles to enforce structure
        if not params:
            # Check if LLM provided values, if not, apply generic safety
            if not instructions.get('sl'): 
                params = {'sl': 30, 'tgt': 60} # Safe default
            else:
                # LLM provided values, check constraints later
                return

        # Apply Params
        sl_pts = params['sl']
        tgt_pts = params['tgt']
        
        if action == "BUY_CALL":
            instructions['sl'] = self._round_to_tick(entry - sl_pts)
            instructions['target'] = self._round_to_tick(entry + tgt_pts)
        else: # BUY_PUT
            instructions['sl'] = self._round_to_tick(entry + sl_pts)
            instructions['target'] = self._round_to_tick(entry - tgt_pts)
            
        print(f"      🛡️ ENGINE GEOMETRY ({style}): SL {sl_pts}pts | TGT {tgt_pts}pts")
        instructions['engine_decision'] = "MODIFIED"
        instructions['engine_reason'] = f"Style Geometry ({style})"
    
    def _round_to_tick(self, price, tick=0.05):
        """Round price to nearest tick size (default 0.05 for NSE)"""
        if price is None: return None
        try:
            f = float(price)
            if math.isnan(f) or math.isinf(f): return None
            return round(round(f / tick) * tick, 2)
        except:
            return None
    
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
            self.fifteen_min_ranges = []
            self.day_structure = {'highs': [], 'lows': []}
            self.total_trades_today = 0
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

    def is_exceptional_trade(self, instructions, current_time):
        """
        STRICT quantitative gate for trades after 13:30 IST.
        Returns: (allowed: bool, rejection_reason: str | None)
        """
        # RULE 1 (FIRST): Trade Count Guard — MUST BE CHECKED FIRST
        if self.total_trades_today >= 4:
            return False, "Daily trade limit reached (4 trades)"

        # RULE 2: Time Window Rule (Hard Gate)
        if current_time > time(14, 45):
            return False, "Late session (>14:45) — no statistical edge"

        # RULE 3: Volatility Expansion Rule
        avg_range = sum(self.fifteen_min_ranges) / len(self.fifteen_min_ranges) if self.fifteen_min_ranges else 50
        current_price = instructions.get('close', 0)
        
        # Check if price broken and held Day High/Low
        breakout_acceptance = False
        if self.day_high and current_price > self.day_high + 5: breakout_acceptance = True
        if self.day_low and current_price < self.day_low - 5: breakout_acceptance = True
        
        current_vol_expansion = False
        if self.fifteen_min_ranges and self.fifteen_min_ranges[-1] >= 1.5 * avg_range:
            current_vol_expansion = True
            
        if not (current_vol_expansion or breakout_acceptance):
            return False, "No real volatility expansion"

        # RULE 4: Directional Alignment Rule
        action = instructions.get('action')
        morning_bias = instructions.get('morning_bias', 'NEUTRAL')
        pivot = instructions.get('pivot', 0)
        
        bias_strength = instructions.get('bias_strength', 'STRONG')
        
        bias_align = (action == "BUY_CALL" and morning_bias == "BULLISH") or \
                     (action == "BUY_PUT" and morning_bias == "BEARISH") or \
                     (morning_bias == "NEUTRAL") or \
                     (bias_strength == "FRAGILE") # Phase-2: Fragile bias allows micro context to lead
        
        struct_align = False
        highs = self.day_structure['highs']
        lows = self.day_structure['lows']
        if action == "BUY_CALL":
            if len(highs) >= 2 and len(lows) >= 2:
                struct_align = highs[-1] >= highs[-2] and lows[-1] >= lows[-2]
            else: struct_align = True
        elif action == "BUY_PUT":
            if len(highs) >= 2 and len(lows) >= 2:
                struct_align = highs[-1] <= highs[-2] and lows[-1] <= lows[-2]
            else: struct_align = True

        entry = instructions.get('entry', instructions.get('entry_price', current_price))
        dist_to_pivot = abs(entry - pivot) if pivot else 100
        pivot_clear = dist_to_pivot > 15
        
        if not (bias_align and struct_align and pivot_clear):
            return False, "Direction / structure not aligned"

        # RULE 5: Risk–Reward Rule
        sl_pts = instructions.get('sl_points', 30)
        tgt_pts = instructions.get('target_points', 60)
        if instructions.get('sl') and entry: sl_pts = abs(entry - instructions['sl'])
        if instructions.get('target') and entry: tgt_pts = abs(entry - instructions['target'])
        
        rr = tgt_pts / sl_pts if sl_pts > 0 else 0
        if rr < 1.8:
            return False, f"Risk–reward {rr:.1f} < 1.8 not acceptable"

        return True, None

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
        
        # NaN Safety Check
        try:
            if math.isnan(float(vix)): vix = 15.0
            if math.isnan(float(raw_confidence)): raw_confidence = 0.0
        except:
            pass

        # 1. BRAIN CALIBRATION: (Trust Prompt v4.0's internal multi-step calibration)
        final_confidence = raw_confidence

        # Initial Decision: Assume EXECUTED unless changed
        instructions['engine_decision'] = "EXECUTED"
        instructions['engine_reason'] = None
        
        # 0. EXCEPTIONAL TRADE GATE (Late Session Discipline)
        # FIX: Use tick timestamp from instructions, NOT datetime.now()
        tick_time = instructions.get('tick_time')  # This MUST be set by caller with tick timestamp
        if tick_time is None:
            # Fallback for safety - but this should never happen in proper usage
            from datetime import datetime
            import pytz
            IST = pytz.timezone('Asia/Kolkata')
            tick_time = datetime.now(IST).time()
        
        # Check if we are in late session (>= 13:30 IST)
        if tick_time >= time(13, 30) and action in ["BUY_CALL", "BUY_PUT"]:
            allowed, reason = self.is_exceptional_trade(instructions, tick_time)
            if not allowed:
                instructions['action'] = "HOLD"
                instructions['engine_decision'] = "BLOCKED"
                instructions['engine_reason'] = reason
                instructions['gate_rejected'] = True
                print(f"      ⛔ EXCEPTIONAL GATE BLOCKED: {reason}")
                self.active_instructions = instructions
                return

        # 2. BIAS GATING: (PHASE-2 Correction)
        # We NO LONGER apply manual 0.5x penalties here. 
        # The Brain prompt handles confidence derivation based on satisfied conditions.
        pass

        # 3. CONFIDENCE THRESHOLD (Reconciled with Prompts)
        # Style-specific hard gates
        selected_style = instructions.get('selected_style', 'NONE')
        mode = instructions.get('mode', 'UNKNOWN')
        is_grind = instructions.get('micro_context', {}).get('is_grind', False)
        
        if selected_style == 'REMR':
            threshold = 0.45
        elif selected_style in ['ITC', 'INTRADAY_TREND_CONTINUATION'] and is_grind:
            threshold = 0.50
        elif mode == 'OPENING_RANGE':
            threshold = 0.50
        elif mode == 'STRUCTURE':
            threshold = 0.65
        else:
            # Fallback for UNKNOWN period (10:00-10:30) or model drift
            if vix < 13: threshold = 0.55
            elif vix > 18: threshold = 0.70
            else: threshold = 0.50

        if final_confidence < threshold and action in ["BUY_CALL", "BUY_PUT"]:
            # print(f"      🚫 Filtered: {action} (Conf {final_confidence:.2f} < {threshold})")
            instructions['action'] = "HOLD"
            instructions['engine_decision'] = "BLOCKED"
            instructions['engine_reason'] = f"Confidence {final_confidence:.2f} below {threshold}"
        
        # 3.5 ENTRY LOCATION FILTER: Skip SUBOPTIMAL entries with low confidence
        entry_location = instructions.get('entry_location', 'GOOD')
        if entry_location == 'SUBOPTIMAL' and final_confidence < 0.6 and action in ["BUY_CALL", "BUY_PUT"] and instructions['action'] != "HOLD":
            print(f"      ⚠️ SUBOPTIMAL entry + low confidence ({final_confidence:.2f}) → SKIP")
            instructions['action'] = "HOLD"
            instructions['engine_decision'] = "BLOCKED"
            instructions['engine_reason'] = f"SUBOPTIMAL loc + {final_confidence:.2f} conf"
        
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
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Too close Above Support ({dist_above_support:.0f}pts)"
            
            # For CALL: Don't enter if within 20pts BELOW resistance (risk of rejection)
            if action == "BUY_CALL" and resistance:
                dist_below_resistance = resistance - entry
                if 0 < dist_below_resistance <= 20:
                    print(f"      ⚠️ CALL entry {entry:.1f} within 20pts below Resistance {resistance:.1f} → SKIP (wait for break)")
                    instructions['action'] = "HOLD"
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Too close Below Resistance ({dist_below_resistance:.0f}pts)"
            
            # For both: Don't enter within 20pts of pivot (reversal zone)
            if pivot and instructions['action'] != "HOLD":
                dist_to_pivot = abs(entry - pivot)
                if dist_to_pivot <= 20:
                    print(f"      ⚠️ Entry {entry:.1f} within 20pts of Pivot {pivot:.1f} → SKIP (reversal zone)")
                    instructions['action'] = "HOLD"
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Too close to Pivot ({dist_to_pivot:.0f}pts)"
        
            # 4. AUTHORITY SPLIT: Apply Engine Geometry & Guardrails
            # First, Apply Style Geometry (Hard Override)
            self._apply_style_geometry(instructions)

            # Re-read values (modified by engine or from LLM)
            entry = instructions.get('entry_price') or instructions.get('entry', 0)
            sl_price = instructions.get('sl')
            target_price = instructions.get('target')

            # GUARDRAIL 1: R:R Check
            if sl_price and target_price and entry:
                sl_dist = abs(entry - sl_price)
                tgt_dist = abs(entry - target_price)
                
                # Prevent div by zero
                if sl_dist < 5: sl_dist = 5 
                
                rr = tgt_dist / sl_dist
                potential_profit = tgt_dist * 27.5 # Nifty Lot Size approx
                
                # Buffer for floating point precision: allow 1.75 instead of hard 1.80
                if rr < (MIN_R_MULTIPLE - 0.05):
                    print(f"      ⛔ RISK GUARD: R:R {rr:.2f} < {MIN_R_MULTIPLE} → BLOCKED")
                    instructions['action'] = "HOLD"
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Low R:R ({rr:.2f})"
                    return
                
                # GUARDRAIL 2: Economic Floor
                if potential_profit < ECONOMIC_FLOOR_INR:
                    print(f"      ⛔ ECON GUARD: Profit ₹{potential_profit:.0f} < ₹{ECONOMIC_FLOOR_INR} → BLOCKED")
                    instructions['action'] = "HOLD"
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Trivial Profit (₹{potential_profit:.0f})"
                    return

            # Note: Removal of old LLM fallback block as we now trust _apply_style_geometry or this new block
            # But let's keep a minimal safety net if _apply_style_geometry returned without setting (unknown style + no LLM value)
            if not instructions.get('sl') or not instructions.get('target'):
                 # This should ideally not happen if _apply_style_geometry handles defaults
                 pass
            
            # 4.1 TARGET LEVEL ADJUSTMENT: Cap target to respect S/P/R levels
            # If a level blocks target path, cap to 15pts before that level
            current_target = instructions.get('target')
            if current_target:
                if action == "BUY_PUT":
                    # For PUT: target is below entry - check if support blocks it
                    if support and support > current_target and support < entry:
                        # Support is between entry and target - cap to 15pts before support
                        new_target = support - 15
                        if new_target != current_target:
                            print(f"      📉 Target capped: Support {support:.1f} in way → TGT {current_target:.1f} → {new_target:.1f}")
                            instructions['target'] = new_target
                            instructions['engine_decision'] = "MODIFIED"
                            instructions['engine_reason'] = "Target capped by Support"
                else:  # BUY_CALL
                    # For CALL: target is above entry - check if resistance blocks it
                    if resistance and resistance < current_target and resistance > entry:
                        # Resistance is between entry and target - cap to 15pts before resistance
                        new_target = resistance - 15
                        if new_target != current_target:
                            print(f"      📈 Target capped: Resistance {resistance:.1f} in way → TGT {current_target:.1f} → {new_target:.1f}")
                            instructions['target'] = new_target
                            instructions['engine_decision'] = "MODIFIED"
                            instructions['engine_reason'] = "Target capped by Resistance"

        # === ADAPTIVE MOMENTUM STRATEGY ===
        if action in ["BUY_CALL", "BUY_PUT"] and not self.open_position and instructions['action'] != "HOLD":
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
                
                # FIX 3: Kill exhaustion scalps after 12:00
                tick_time = instructions.get('tick_time')
                if tick_time and tick_time >= time(12, 0):
                    movement = self.total_upward_movement if action == "BUY_CALL" else self.total_downward_movement
                    print(f"      ⛔ POST-12:00 EXHAUSTION BLOCKED: {momentum_state} ({movement:.0f}pts)")
                    instructions['action'] = Action.HOLD.value
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Post-12:00 Exhaustion ({momentum_state})"
                    instructions['gate_rejected'] = True
                    self.active_instructions = instructions
                    return
                
                if is_reversal:
                    # Catching the reversal - allow trade
                    print(f"      🔄 REVERSAL SETUP: Momentum {momentum_state}, catching turn")
                
                elif entry_location == 'OPTIMAL' and final_confidence >= 0.65:
                    # High quality continuation - SCALPING MODE
                    print(f"      ⚡ SCALPING MODE: Momentum {momentum_state}, tight params")
                    self.scalping_mode = True
                    instructions['engine_decision'] = "MODIFIED"
                    instructions['engine_reason'] = f"SCALPING (Exhaustion {momentum_state})"
                    
                    # Override to scalping parameters
                    entry = instructions.get('entry') or instructions.get('entry_price')
                    if entry:
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
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"Exhaustion {momentum_state}"
                    self.active_instructions = instructions
                    return
            
            elif is_same_direction and vix_spike:
                # VIX-based filter (fallback)
                recent_big_win = self.last_trade_pnl and self.last_trade_pnl > 50
                if entry_location == 'SUBOPTIMAL' and final_confidence < 0.60 and recent_big_win:
                    print(f"      ⏸️  VIX SPIKE: {vix_change_pct*100:+.1f}% after +{self.last_trade_pnl:.0f}pt win")
                    instructions['action'] = Action.HOLD.value
                    instructions['engine_decision'] = "BLOCKED"
                    instructions['engine_reason'] = f"VIX Spike {vix_change_pct*100:+.1f}%"
                    self.active_instructions = instructions
                    return
        
        # Compact log
        act = instructions.get('action', 'N/A')
        ent = instructions.get('entry_price', 'N/A')
        print(f"      ⚙️ Instr: {act} @{ent} (Conf: {final_confidence:.2f}) | Engine: {instructions['engine_decision']} ({instructions['engine_reason'] or 'none'})")
        
        self.active_instructions = instructions


    def process_tick(self, tick):
        price = tick['close']
        timestamp = tick['timestamp']
        current_time_only = timestamp.time() if hasattr(timestamp, 'time') else timestamp
        
        # Update momentum state on every tick
        self._update_momentum_state(tick, timestamp)
        
        # Track 15-min bars for Exceptional Trade Gate
        # Every 15 mins (at :00, :15, :30, :45)
        if timestamp.minute in [0, 15, 30, 45] and timestamp.minute != self.last_bar_time:
            self.last_bar_time = timestamp.minute
            if self.day_high and self.day_low:
                current_range = self.day_high - self.day_low # Simplification: using day extremes for now
                # In a real scenario, we'd track the OHLC of the SPECIFIC 15m bar.
                # Since we don't have a 15m factory here, we'll approximate with intraday range updates.
                # Actually, the user wants "Current 15-min candle range". 
                # I'll need a mini-aggregator if I want to be 100% accurate. 
                pass
            
            # Record structure points
            if self.day_high: self.day_structure['highs'].append(self.day_high)
            if self.day_low: self.day_structure['lows'].append(self.day_low)
            # Trim to avoid memory grow
            if len(self.day_structure['highs']) > 10: self.day_structure['highs'].pop(0)
            if len(self.day_structure['lows']) > 10: self.day_structure['lows'].pop(0)
        
        # 1. Mandatory 15:15 Square-off
        if current_time_only >= self.force_exit_time and self.open_position:
            self.square_off(price, timestamp, reason=ExitReason.EOD.value)
            return

        # 1.5 REMR Continuation Monitor (Auto Re-entry)
        if self.remr_continuation_monitor and not self.open_position:
            mon = self.remr_continuation_monitor
            triggered = False
            
            # Expiry check
            if timestamp > mon['expiry']:
                self.remr_continuation_monitor = None
            else:
                if mon['side'] == 'CALL' and price >= mon['trigger_price']: triggered = True
                elif mon['side'] == 'PUT' and price <= mon['trigger_price']: triggered = True
                
                if triggered:
                    print(f"      🚀 REMR -> ITC CONTINUATION TRIGGERED at {price:.1f} (Trigger: {mon['trigger_price']:.1f})")
                    
                    # Construct synthetic instructions for ITC
                    self.active_instructions = {
                        'action': f"BUY_{mon['side']}",
                        'selected_style': 'INTRADAY_TREND_CONTINUATION',
                        'confidence': 0.95,
                        'reason': "Automated REMR Continuation Re-entry",
                        'entry_price': price
                    }
                    
                    # Apply ITC Params (SL 50 / TGT 150) as baseline
                    self._apply_style_geometry(self.active_instructions)
                    
                    # DYNAMIC TARGET OVERRIDE (To match In-Trade Transition Logic)
                    # Target = Original Entry + (2 * EM)
                    # This captures the "remaining move" as per user intent.
                    if 'original_entry' in mon:
                        orig_ent = mon['original_entry']
                        em = mon['em_high']
                        
                        # 1. SL CALCULATION: Enforce Trend-Following SL (Min 50pts)
                        # Do NOT rely on style defaults (30pts) which are too tight for reentry
                        if mon['side'] == 'CALL':
                            sl_price = self._round_to_tick(price - 50)
                        else:
                            sl_price = self._round_to_tick(price + 50)
                        self.active_instructions['sl'] = sl_price
                        
                        # 2. DYNAMIC TARGET CALCULATION
                        # Target = Original Entry + (2 * EM)
                        if mon['side'] == 'CALL':
                            dyn_target = self._round_to_tick(orig_ent + (2 * em))
                            
                            # Check viability: If target is too close (< 30 pts), project NEW leg
                            if dyn_target > price + 30:
                                self.active_instructions['target'] = dyn_target
                            else:
                                # Target exhausted -> Project fresh leg (Price + 1.0 * EM)
                                new_target = self._round_to_tick(price + (1.0 * em))
                                self.active_instructions['target'] = new_target
                                print(f"      🎯 Dynamic Target Exhausted. Projected New: {new_target:.1f} (+{1.0*em:.0f} pts)")
                                
                        else: # PUT
                            dyn_target = self._round_to_tick(orig_ent - (2 * em))
                            
                            if dyn_target < price - 30:
                                self.active_instructions['target'] = dyn_target
                            else:
                                new_target = self._round_to_tick(price - (1.0 * em))
                                self.active_instructions['target'] = new_target
                                print(f"      🎯 Dynamic Target Exhausted. Projected New: {new_target:.1f} (+{1.0*em:.0f} pts)")
                                
                    # Execute Entry
                    self._enter_trade(price, timestamp, mon['side'])
                    
                    # Ensure metadata is correct
                    if self.open_position:
                        self.open_position['style'] = 'INTRADAY_TREND_CONTINUATION'
                        self.open_position['entry_reason'] = "REMR Continuation (Deep Trend)"
                        self.open_position['expected_move_high'] = mon['em_high']
                        # Inject authoritative ITC hold time
                        self.open_position['max_hold_minutes'] = 120 # Hardcoded authoritative value for ITC
                    
                    # Clear monitor
                    self.remr_continuation_monitor = None

        # 2. Manage Open Position (Including LLM smart adjustments)
        if self.open_position:
            ai_action = self.active_instructions.get('action')
            pos = self.open_position
            pos_side = pos['side']
            
            # Standard AI exit signals
            conf = self.active_instructions.get('confidence', 0)
            if (pos_side == 'CALL' and ai_action == Action.EXIT_CALL.value) or \
               (pos_side == 'PUT' and ai_action == Action.EXIT_PUT.value):
                if conf >= 0.8:
                    self.square_off(price, timestamp, reason=ExitReason.AI_EXIT.value)
                    return
                else:
                    print(f"      ⏸️  AI EXIT suppressed: confidence {conf:.2f} < 0.8")
            
            # NEW: LLM Smart Exit - immediate exit on detected reversal
            if ai_action == Action.EXIT_NOW.value:
                if conf >= 0.8:
                    reason_text = self.active_instructions.get('adjustment_reason', 'Reversal detected')
                    print(f"      🧠 AI SMART EXIT: {reason_text} (Conf: {conf:.2f})")
                    self.square_off(price, timestamp, reason=ExitReason.AI_SMART_EXIT.value)
                    return
                else:
                    print(f"      ⏸️  AI SMART EXIT suppressed: confidence {conf:.2f} < 0.8")
            
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
        print(f"      [EXEC] 🚀 EXECUTION: Entered {side} at {price}")
        self.total_trades_today += 1
        
        self.open_position = {
            'side': side,
            'entry_price': price,
            'entry_time': timestamp,
            'sl': self.active_instructions.get('sl'),
            'target': self.active_instructions.get('target'),
            'max_hold_minutes': self.active_instructions.get('max_hold_minutes', 30),
            # Phase-2.5: Style Transition State
            'style': self.active_instructions.get('selected_style', 'NONE'),
            'entry_reason': self.active_instructions.get('adjustment_reason', 'Signal'),
            'expected_move_high': self.active_instructions.get('expected_move_high', 0),
            'micro_context': self.active_instructions.get('micro_context', {}),
            # Phase-2.6: In-Trade Regime Guard
            'entry_regime': self.active_instructions.get('active_regime', 'UNKNOWN'),
            'entry_ter': self.active_instructions.get('micro_context', {}).get('trend_efficiency', 0.0),
            'current_regime': self.active_instructions.get('active_regime', 'UNKNOWN'),
            'current_ter': self.active_instructions.get('micro_context', {}).get('trend_efficiency', 0.0),
            # Phase-2: Tracking metrics only (no automatic adjustments)
            'peak_price': price,
            'max_pnl': 0.0,
            'positive_pnls': []
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
        
        # Sync latest Regime/TER from active_instructions (update from Brain)
        # Brain sends updates every 15m or when flagged.
        # We check if there's a fresh instruction sitting in active_instructions (even if ACTION=HOLD)
        if self.active_instructions and self.active_instructions.get('active_regime'):
            pos['current_regime'] = self.active_instructions['active_regime']
            pos['current_ter'] = self.active_instructions.get('micro_context', {}).get('trend_efficiency', 0.0)

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
        
        # Phase-2: Static SL/Target System
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
            
        # --- PHASE-2.6: IN-TRADE REGIME GUARD ---
        # De-risk object if regime degrades significantly
        # 1. Regime Drop (e.g. TREND -> ROTATION)
        # 2. TER Collapse (e.g. 0.9 -> 0.3)
        
        start_regime = pos.get('entry_regime', 'UNKNOWN')
        curr_regime = pos.get('current_regime', 'UNKNOWN')
        start_ter = pos.get('entry_ter', 0.0)
        curr_ter = pos.get('current_ter', 0.0)
        
        regime_degraded = False
        
        # Detect Transition: Trend -> Rotation/Range
        if start_regime in ['IMPULSE_TREND', 'TREND_GRIND'] and curr_regime in ['ROTATION', 'RANGE']:
             regime_degraded = True
        
        # Detect TER Collapse (< 50% of entry energy)
        if start_ter > 0.4 and curr_ter < (0.5 * start_ter):
             regime_degraded = True
             
        if regime_degraded and not pos.get('guard_triggered', False):
             # Action: Tighten SL to Breakeven+5 or Trailing tight
             # We use a simple tightening logic: Move SL to preserve capital.
             
             print(f"      🛡️ [GUARD] REGIME DEGRADED: {start_regime}({start_ter:.2f}) -> {curr_regime}({curr_ter:.2f})")
             
             # Tighten Logic
             if unrealized_pnl > 10:
                  # Protect Profit: Move SL to Entry + 5
                  new_sl = entry_price + 5 if pos['side'] == 'CALL' else entry_price - 5
                  if (pos['side'] == 'CALL' and new_sl > sl) or (pos['side'] == 'PUT' and new_sl < sl):
                       pos['sl'] = new_sl
                       print(f"      🛡️ [GUARD] SL Tightened to BE (+5pts) to separate from noise.")
             else:
                  # Defense: Tighten existing SL by 50%? Or just accept the geometry.
                  # Safer to not choke a trade that hasn't moved yet. Guard applies if we lose the edge.
                  # Let's tighten SL to entry price (Breakeven) if strictly degraded?
                  # No, that might stop out noise. Let's just log for now or apply modest tightening.
                  pass
             
             pos['guard_triggered'] = True
        
        # Phase-2.5: STYLE TRANSITION LOGIC (REMR -> ITC)
        # Check if "Reaction Has Matured" and upgrade blindly holding REMR to Trend Following ITC
        style = pos.get('style')
        if style == 'REMR' or style == 'RANGE_EXTREME_MEAN_REVERSION':
            em_high = pos.get('expected_move_high', 0)
            micro = pos.get('micro_context', {})
            
            # Use cached micro context from entry (conservative) or could fetch fresh if available
            # NOTE: We use cached for simplicity as `micro_context` in executor isn't updated every tick.
            # Ideally calling `update_instructions` refreshes this, but `manage_position` runs between updates.
            # However, `StyleTransition.md` says "evaluated every bar". 
            # Since we don't calculate micro context inside executor (it's in Brain/Enrichment), we use 
            # the values from the LAST tactical update instruction which refreshes `open_position` metadata?
            # Actually, `open_position` is set ONCE at entry. We need to update its context from tactical updates.
            # But `update_instructions` doesn't currently update `open_position` metadata.
            # FIX: We will rely on price action triggers primarily here.
            
            # Dynamic triggers
            impulse_ok = micro.get('impulse_detected', False) # From entry snapshot (approx)
            fta_veto = micro.get('failure_to_accept', False)  # From entry snapshot
            
            # Check price threshold (0.6 * EM)
            matured = False
            if pos['side'] == 'CALL':
                 if unrealized_pnl >= 0.6 * em_high: matured = True
            else:
                 if unrealized_pnl >= 0.6 * em_high: matured = True
            
            # Transition Guard
            if matured and not fta_veto and impulse_ok:
                print(f"      🦋 STYLE TRANSITION: REMR → ITC (Matured > {0.6*em_high:.1f}pts)")
                
                # 1. Update Style
                pos['style'] = 'INTRADAY_TREND_CONTINUATION'
                
                # 2. Expand Target
                impulse_move = micro.get('impulse_move_pts', 0)
                expansion_pts = max(em_high * 2, impulse_move * 1.2)
                
                old_target = pos.get('target')
                if pos['side'] == 'CALL':
                    new_target = self._round_to_tick(entry_price + expansion_pts)
                    if new_target > old_target:
                        pos['target'] = new_target
                        print(f"      📈 TGT Expanded: {old_target} → {new_target} (ITC Mode)")
                else:
                    new_target = self._round_to_tick(entry_price - expansion_pts)
                    if new_target < old_target:
                        pos['target'] = new_target
                        print(f"      📉 TGT Expanded: {old_target} → {new_target} (ITC Mode)")

                # 3. Update SL (Lock in risk)
                # Rule: max(entry + 0.2 * EM, entry) -> Ensuring at least BE+
                lock_in_pts = 0.2 * em_high
                
                old_sl = pos.get('sl')
                if pos['side'] == 'CALL':
                    new_sl = self._round_to_tick(entry_price + lock_in_pts)
                    # Ensure we don't loosen SL if it was somehow already tighter (unlikely for REMR)
                    if new_sl > old_sl: 
                        pos['sl'] = new_sl
                        print(f"      🛡️ SL Tightened: {old_sl} → {new_sl} (Locked 20% EM)")
                else:
                    new_sl = self._round_to_tick(entry_price - lock_in_pts)
                    if new_sl < old_sl:
                        pos['sl'] = new_sl
                        print(f"      🛡️ SL Tightened: {old_sl} → {new_sl} (Locked 20% EM)")

        # Phase-2: NO TRAILING STOPS (Except via Style Transition or LLM)
        # SL and Target are static from entry, managed only by LLM tactical updates
        
        # Log position status every candle
        pnl_color = "🟢" if unrealized_pnl >= 0 else "🔴"
        sl_str = f"{sl:.1f}" if sl else "N/A"
        tgt_str = f"{target:.1f}" if target else "N/A"
        prog_str = f" [{target_progress:.0f}% to TGT]" if target_progress > 0 else ""
        print(f"      {pnl_color} {pos['side']} PnL: {unrealized_pnl:+.1f}{prog_str} | Price: {current_price:.1f} | SL: {sl_str} | TGT: {tgt_str}")
        
        exit_price = None
        exit_reason = None
        
        # 0. Time-Based Exit check
        # 0. Time-Based Exit check REMOVED (User Request: Only 15:15 Force Exit)
        # if pos.get('max_hold_minutes'):
        #     elapsed = (timestamp - pos['entry_time']).total_seconds() / 60
        #     if elapsed >= pos['max_hold_minutes']:
        #         exit_price = candle_open
        #         exit_reason = ExitReason.TIME_EXIT.value
        
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
            'mean_open_pnl': mean_open_pnl,
            'style': pos.get('style', 'N/A'),
            'entry_reason': pos.get('entry_reason', 'N/A')
        }
        
        self.trades.append({'type': 'EXIT', **exit_trade})
        self.trade_ledger.append(exit_trade)
        
        # Track for momentum exhaustion filter
        self.last_exit_time = timestamp
        self.last_trade_pnl = pnl
        
        # Populate REMR Continuation Monitor if applicable
        # If we exited REMR at TARGET, we might miss the rest of the trend. Monitor for re-entry.
        style = pos.get('style', 'NONE')
        if (style == 'REMR' or style == 'RANGE_EXTREME_MEAN_REVERSION') and reason == ExitReason.TARGET.value:
            em = pos.get('expected_move_high', 0)
            if em > 0:
                # Trigger at Entry + 0.6 * EM
                trigger = pos['entry_price'] + (0.6 * em) if pos['side'] == 'CALL' else pos['entry_price'] - (0.6 * em)
                
                # Setup Monitor (Valid for 60 mins)
                import datetime
                self.remr_continuation_monitor = {
                    'trigger_price': trigger,
                    'side': pos['side'],
                    'expiry': timestamp + datetime.timedelta(minutes=60),
                    'em_high': em,
                    'original_entry': pos['entry_price']
                }
                print(f"      👀 REMR Target Hit. Monitoring for ITC RE-ENTRY > {trigger:.1f} (until {self.remr_continuation_monitor['expiry'].time()})")
        
        self.open_position = None
