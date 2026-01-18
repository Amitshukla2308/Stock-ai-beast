# engine/enrichment.py
import math
from datetime import datetime, time

# Style-Specific Economic Minimums (Authoritative - Canonical Spec)
STYLE_ECONOMICS = {
    "OPENING_RANGE_EXPANSION": {"min_pnl": 1000, "max_hold_min": 105},
    "RANGE_EXTREME_MEAN_REVERSION": {"min_pnl": 500, "max_hold_min": 80},
    "INTRADAY_TREND_CONTINUATION": {"min_pnl": 1500, "max_hold_min": 120},
    "VOLATILITY_BREAK": {"min_pnl": 1800, "max_hold_min": 90},
    "LATE_SESSION_RISK_OFF": {"min_pnl": float("inf"), "max_hold_min": 0},
    # Short Codes Support
    "ORE": {"min_pnl": 1000, "max_hold_min": 105},
    "REMR": {"min_pnl": 500, "max_hold_min": 80},
    "ITC": {"min_pnl": 1500, "max_hold_min": 120},
    "VBD": {"min_pnl": 1800, "max_hold_min": 90}, 
}

# ============================================================================
# CANONICAL SECTION 1: TIME & SESSION CONTEXT
# ============================================================================
def calculate_time_context(current_time_str):
    """
    Compute session phase and minutes since market open.
    Canonical compliance: Section 1️⃣
    
    Returns:
        {
            "minutes_since_open": int,
            "session_phase": "OPENING" | "MIDDAY" | "LATE"
        }
    """
    try:
        # Parse HH:MM
        hour, minute = map(int, current_time_str.split(':'))
        current_time = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        today_date = current_time.date()
        
        from datetime import time # Ensure time is imported or available. existing import?
        # Assuming table top imports are present.
        
        # Find market open (09:15)
        market_open = datetime.combine(today_date, time(9, 15))
        
        if current_time.tzinfo:
            # naive/aware fix if needed
            market_open = market_open.replace(tzinfo=current_time.tzinfo)
            
        minutes_since_open = (current_time - market_open).total_seconds() / 60
        
        # 1. Bias Decay (Phase 2 Fix)
        # Weight decays from 1.0 to 0.0 over 60 minutes
        bias_weight = max(0.0, 1.0 - (minutes_since_open / 60.0))
        if minutes_since_open > 60: bias_weight = 0.0      
        # Classify session phase per canonical spec
        if minutes_since_open <= 45:
            session_phase = "OPENING"
        elif minutes_since_open <= 240:  # Until 13:15
            session_phase = "MIDDAY"
        else:
            session_phase = "LATE"
        
        return {
            "minutes_since_open": int(minutes_since_open),
            "session_phase": session_phase,
            "bias_weight": round(bias_weight, 2),
            "next_event": "CLOSE" if session_phase == "CLOSING" else "NONE"
        }
    except:
        return {
            "minutes_since_open": 0,
            "session_phase": "UNKNOWN",
            "bias_weight": 1.0
        }

# ============================================================================
# CANONICAL SECTION 2: REGIME & MOMENTUM
# ============================================================================
def detect_rejection_pattern(bar, prev_bars=None):
    """
    Behavioral Rejection Signature (Canonical Phase-2.5)
    Requires: Wick > Body AND Close in extreme 30% AND Relative Volume expansion
    """
    h, l, o, c = bar['h'], bar['l'], bar['o'], bar['c']
    range_pts = h - l
    if range_pts <= 0: return "NONE"
    
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    
    # 1. Volume Expansion Check
    rel_vol = 1.0
    if prev_bars and len(prev_bars) >= 5:
        avg_vol = sum(b['volume'] for b in prev_bars[-5:]) / 5
        rel_vol = bar['volume'] / avg_vol if avg_vol > 0 else 1.0
    
    # 2. Rejection Logic (Short/Top Rejection)
    # Wick Ratio > 0.6 (Stricter Phase-2.5)
    wick_ratio_top = upper_wick / range_pts if range_pts > 0 else 0
    is_top_rejection = (wick_ratio_top > 0.6) and (c <= l + 0.4 * range_pts) and (rel_vol >= 1.0)
    
    # 3. Rejection Logic (Long/Bottom Rejection)
    wick_ratio_bottom = lower_wick / range_pts if range_pts > 0 else 0
    is_bottom_rejection = (wick_ratio_bottom > 0.6) and (c >= h - 0.4 * range_pts) and (rel_vol >= 1.0)
    
    if is_top_rejection: return "TOP_REJECTION"
    if is_bottom_rejection: return "BOTTOM_REJECTION"
    return "NONE"

def calculate_momentum_slope(bars_3):
    """
    Directional energy over last 3 bars.
    Returns slope (pts/bar) + consistency.
    """
    if len(bars_3) < 3: return 0.0, 0.0
    
    # Simple linear regression slope of Closes
    y = [b['c'] for b in bars_3]
    x = [0, 1, 2]
    # m = (n*sum(xy) - sum(x)sum(y)) / (n*sum(x^2) - (sum(x))^2)
    n = len(x)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(i*i for i in x)
    sum_xy = sum(x[i]*y[i] for i in range(n))
    
    denom = (n * sum_xx - sum_x**2)
    slope = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    
    # Consistency: all 3 bars in same direction?
    consistency = 1.0 if (y[2] > y[1] > y[0]) or (y[2] < y[1] < y[0]) else 0.5
    
    return round(slope, 2), consistency

def calculate_or_regime(bars_5min, or_range):
    """
    Classifies the Opening Auction into DISCOVERY, BALANCE, or FAILURE.
    """
    if not bars_5min or len(bars_5min) < 3: return "UNKNOWN"
    
    overlap_count = 0
    net_move = abs(bars_5min[-1]['c'] - bars_5min[0]['o'])
    
    for i in range(1, len(bars_5min)):
        b_curr = bars_5min[i]
        b_prev = bars_5min[i-1]
        
        # Range Overlap
        overlap = min(b_curr['h'], b_prev['h']) - max(b_curr['l'], b_prev['l'])
        if overlap > 0:
            overlap_count += 1

    overlap_ratio = overlap_count / len(bars_5min)
    
    # Thresholds
    # SYNERGY TUNING: If trending with conviction (>40% of OR range), it's DISCOVERY
    # even if overlap is high (e.g. steady grind without deep pullbacks)
    move_ratio = net_move / or_range if or_range > 0 else 0
    if move_ratio > 0.4:
        return "DISCOVERY"

    if overlap_ratio > 0.7 and net_move < 0.3 * or_range: return "BALANCE"
    
    return "DISCOVERY" # Default to discovery for active handling

def detect_v_reversal(bars_15min, current_price, em_low, em_high, atr):
    """
    Detects a V-reversal pattern (Sharp turn from extreme stretch).
    Matches 01-12 behavior.
    """
    if not bars_15min or len(bars_15min) < 3:
        return False
        
    last_3 = bars_15min[-3:]
    
    # 1. Extreme Stretch Check
    # Price should be near or below EM Low
    is_extreme = current_price < em_low + 0.3 * atr
    
    # 2. Rejection Behavior
    # Handled by caller or specialized function
    return is_extreme

def calculate_trend_efficiency(bars_5min, window=5):
    """
    Calculates Trend Efficiency Ratio (TER) to classify regime.
    TER = NetDisplacement / SumRanges
    
    Returns: (ter_value, regime)
    """
    if not bars_5min or len(bars_5min) < window:
        return 0.0, "ROTATION"
        
    recent_bars = bars_5min[-window:]
    
    # Net Displacement: Close[N] - Open[1]
    net_displacement = recent_bars[-1]['c'] - recent_bars[0]['o']
    
    # Sum of Ranges: Sum(High - Low)
    sum_ranges = sum((b['h'] - b['l']) for b in recent_bars)
    
    # Safety: Avoid division by zero
    ter = abs(net_displacement) / max(sum_ranges, 1e-6)
    ter = round(ter, 2)
    
    # --- REGIME MOMENTUM (Phase 2.7-Light) ---
    # RM = Rate of change in trend quality
    # Detects improving vs deteriorating trends
    regime_momentum = 0.0
    
    if len(recent_bars) >= 6:  # Need at least 6 bars (current 3 + previous 3)
        # Calculate TER for 3 bars ago
        bars_3ago = recent_bars[-6:-3]  # 3 bars before the current 3
        net_3ago = bars_3ago[-1]['c'] - bars_3ago[0]['o']
        sum_ranges_3ago = sum((b['h'] - b['l']) for b in bars_3ago)
        ter_3ago = abs(net_3ago) / max(sum_ranges_3ago, 1e-6)
        
        # RM = Current TER - Previous TER
        regime_momentum = round(ter - ter_3ago, 3)
    
    regime = "TRANSITION"
    if ter > 0.55: regime = "TREND"
    elif ter < 0.30: regime = "ROTATION"
    
    return ter, regime, regime_momentum

def calculate_effective_atr(bars_5min, current_atr, direction="NEUTRAL", window=20):
    """
    Calculates Directional Effective ATR.
    Uses rolling median of Bullish/Bearish candle ranges.
    Fallback to Global ATR if insufficient data.
    """
    if not bars_5min or len(bars_5min) < 10:
        return current_atr
        
    recent = bars_5min[-window:] if len(bars_5min) > window else bars_5min
    
    bull_ranges = []
    bear_ranges = []
    
    for b in recent:
        r = b['h'] - b['l']
        if b['c'] > b['o']: bull_ranges.append(r)
        elif b['c'] < b['o']: bear_ranges.append(r)
        
    import statistics
    
    eff_atr = current_atr
    
    if direction == "BULLISH" and len(bull_ranges) >= 3:
        eff_atr = statistics.median(bull_ranges)
    elif direction == "BEARISH" and len(bear_ranges) >= 3:
        eff_atr = statistics.median(bear_ranges)
        
    # Safety clamp: Don't deviate wildly from global ATR (0.5x to 2.0x)
    eff_atr = max(current_atr * 0.5, min(eff_atr, current_atr * 2.0))
    
    return round(eff_atr, 1)

def detect_bearish_exhaustion(last_bar, avg_range, rel_vol):
    """
    Detects Bearish Exhaustion Candle.
    Criteria: Upper Wick > 0.6 * Range, Close in bottom half, High Vol, Wide Range.
    """
    if not last_bar: return False
    
    b_range = last_bar['h'] - last_bar['l']
    if b_range == 0: return False
    
    upper_wick = last_bar['h'] - max(last_bar['c'], last_bar['o'])
    upper_ratio = upper_wick / b_range
    mid_point = (last_bar['h'] + last_bar['l']) / 2
    
    is_exhaustion = (
        upper_ratio > 0.6 and
        last_bar['c'] < mid_point and
        rel_vol > 1.3 and
        b_range > 1.2 * avg_range
    )
    
    return is_exhaustion
    # Last few bars should show long wicks or a hammer at the low
    rejection = detect_rejection_pattern(last_3[-1]) == "BOTTOM_REJECTION"
    
    # 3. Fast Recovery
    # Current bar close > previous bar body high
    recovery = last_3[-1]['c'] > last_3[-2]['h']
    
    if is_extreme and rejection and recovery:
        return True
        
    return False

# ============================================================================
# CANONICAL SECTION 3: HTF LOCATION CONTEXT
# ============================================================================
def calculate_location_context(current_price, support, pivot, resistance, or_range):
    """
    Absolute location classification - NO subjectivity.
    Canonical compliance: Section 3️⃣
    
    Returns:
        {
            "location": "NEAR_SUPPORT" | "NEAR_RESISTANCE" | "NEAR_PIVOT" | "MID_RANGE",
            "distance_to_support": float,
            "distance_to_resistance": float,
            "distance_to_pivot": float
        }
    """
    if not or_range or or_range == 0:
        return {
            "location": "UNKNOWN",
            "distance_to_support": 0,
            "distance_to_resistance": 0,
            "distance_to_pivot": 0
        }
    
    # Proximity checks per canonical spec
    dist_s = abs(current_price - support) if support > 0 else 999999
    dist_r = abs(current_price - resistance) if resistance > 0 else 999999
    dist_p = abs(current_price - pivot) if pivot > 0 else 999999
    
    near_support = dist_s <= 0.15 * or_range
    near_resistance = dist_r <= 0.15 * or_range
    near_pivot = dist_p <= 0.10 * or_range
    
    # Absolute Optimal Floor (Hard distance)
    is_optimal_support = dist_s < 5
    is_optimal_resistance = dist_r < 5
    
    # Prioritize alignment
    if is_optimal_resistance:
        location = "OPTIMAL_TOP"
    elif is_optimal_support:
        location = "OPTIMAL_BOTTOM"
    elif near_resistance:
        location = "NEAR_RESISTANCE"
    elif near_support:
        location = "NEAR_SUPPORT"
    elif near_pivot:
        location = "NEAR_PIVOT"
    else:
        location = "MID_RANGE"
    
    return {
        "location": location,
        "distance_to_support": round(current_price - support, 2),
        "distance_to_resistance": round(resistance - current_price, 2),
        "distance_to_pivot": round(current_price - pivot, 2)
    }


def calculate_vwap(bars):
    """
    Calculates VWAP from a list of bars (e.g. today_5min).
    VWAP = Sum(Volume * Typical Price) / Sum(Volume)
    """
    if not bars: return 0.0
    
    cum_pv = 0.0
    cum_vol = 0.0
    
    for b in bars:
        typ = (b['h'] + b['l'] + b['c']) / 3
        vol = b['volume']
        cum_pv += typ * vol
        cum_vol += vol
        
    return round(cum_pv / cum_vol, 2) if cum_vol > 0 else 0.0

def detect_two_bar_failure(bars):
    """
    Detects Two-Bar Reversal (Failure to maintain new extreme).
    """
    if not bars or len(bars) < 2: return False
    
    b1 = bars[-2]
    b2 = bars[-1]
    
    # Bullish Reversal (Red then Green)
    # B1 Red, B2 Green, B2 Low < B1 Low, B2 Close > B1 Close
    is_bullish_fail = (
        b1['c'] < b1['o'] and
        b2['l'] < b1['l'] and
        b2['c'] > b1['c']
    )
    
    # Bearish Reversal (Green then Red)
    # B1 Green, B2 Red, B2 High > B1 High, B2 Close < B1 Close
    is_bearish_fail = (
        b1['c'] > b1['o'] and
        b2['h'] > b1['h'] and
        b2['c'] < b1['c']
    )
    
    return is_bullish_fail or is_bearish_fail

def calculate_micro_context(bars_15min, current_price, support, resistance, pivot, atr_14, or_range=0, em_low=0, em_high=0, today_5min=None):
    """
    Analyzes 15-min bars to determine micro-structural context using deterministic mapping.
    - bars_15min: List of dicts with o, h, l, c, volume
    - atr_14: ATR value from 15-min bars
    - today_5min: 5-min bars for TER calculation (Phase-2 Geometry)
    """
    if not bars_15min or len(bars_15min) < 3:
        return {
            "behavior": "UNKNOWN",
            "micro_bias": "NEUTRAL",
            "rejection": False,
            "rejection_pattern": "NONE",
            "momentum_slope": 0.0,
            "momentum_consistency": 0.0,
            "has_energy": False,
            "v_reversal": False,
            "trend_efficiency": 0.0,
            "trend_regime": "ROTATION",
            "effective_atr": atr_14,
            "bearish_exhaustion": False,
            "is_grind": False,
            "vwap_rejection": False,
            "two_bar_failure": False
        }

    closes = [b['c'] for b in bars_15min]
    
    # helper for SMA
    def sma(data, window):
        if len(data) < window: return None
        return sum(data[-window:]) / window

    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    
    # 1. Swing Context
    # Find swing highs/lows (simplified fractal: high > prev_high & high > next_high)
    # Since we only have 'past' data up to last closed bar:
    # A swing high is confirmed if bar[i-1] is highest of i-2, i-1, i.
    def get_swings(bars):
        highs = []
        lows = []
        for i in range(2, len(bars) - 1):
            if bars[i-1]['h'] > bars[i-2]['h'] and bars[i-1]['h'] > bars[i]['h']:
                highs.append(bars[i-1]['h'])
            if bars[i-1]['l'] < bars[i-2]['l'] and bars[i-1]['l'] < bars[i]['l']:
                lows.append(bars[i-1]['l'])
        return highs, lows

    s_highs, s_lows = get_swings(bars_15min)
    last_sh = s_highs[-1] if len(s_highs) >= 1 else None
    prior_sh = s_highs[-2] if len(s_highs) >= 2 else None
    last_sl = s_lows[-1] if len(s_lows) >= 1 else None
    prior_sl = s_lows[-2] if len(s_lows) >= 2 else None

    swing_context = "RANGE_SWING"
    if ma20 and ma50:
        if current_price > ma20 > ma50 and last_sl and prior_sl and last_sl > prior_sl:
            swing_context = "BULLISH_SWING"
        elif current_price < ma20 < ma50 and last_sh and prior_sh and last_sh < prior_sh:
            swing_context = "BEARISH_SWING"

    # 2. Retracement Depth
    impulse_high = max(b['h'] for b in bars_15min[-10:])
    impulse_low = min(b['l'] for b in bars_15min[-10:])
    diff = impulse_high - impulse_low
    if diff > 0:
        if swing_context == "BULLISH_SWING":
            retrace_pct = (impulse_high - current_price) / diff
        elif swing_context == "BEARISH_SWING":
            retrace_pct = (current_price - impulse_low) / diff
        else:
            retrace_pct = 0.5
        
        if retrace_pct < 0.236: retracement_depth = "SHALLOW"
        elif retrace_pct <= 0.5: retracement_depth = "NORMAL"
        elif retrace_pct <= 0.618: retracement_depth = "DEEP"
        else: retracement_depth = "FULL"
    else:
        retracement_depth = "NORMAL"

    # 3. PRICE ACTION SIGNALS (New Canonical Primitives)
    # --------------------------------------------------
    stall_at_level = False
    failure_to_extend = False
    weak_follow_through = False
    rejection = False
    
    # New Metrics for Smart Flip
    last_body_ratio = 0.0
    velocity_increasing = False
    absorption = False
    net_progress_3 = 0.0
    
    last_bar = bars_15min[-1]
    last_range = last_bar['h'] - last_bar['l']
    last_body = abs(last_bar['c'] - last_bar['o'])
    if last_range > 0:
        last_body_ratio = round(last_body / last_range, 2)
    
    # Calculate Velocity (Range expansion in direction)
    if len(bars_15min) >= 3:
        range_now = bars_15min[-1]['h'] - bars_15min[-1]['l']
        range_prev = bars_15min[-2]['h'] - bars_15min[-2]['l']
        velocity_increasing = range_now > range_prev * 1.2
        
        # Net Progress (Close to Close of last 3 bars)
        net_progress_3 = bars_15min[-1]['c'] - bars_15min[-3]['c']

        # Absorption (High Volume + Low Progress)
        vol_avg = sum(b['volume'] for b in bars_15min[-4:-1]) / 3
        curr_vol = bars_15min[-1]['volume']
        if curr_vol > 1.5 * vol_avg and abs(net_progress_3) < 0.2 * or_range:
             absorption = True

    # 2. Structural Break Detector (Trend Override)
    # 2. Structural Break Detector (Trend Override)
    # Check for VALID break in last 6 bars (1.5 hours) - Persistent State
    structural_break = False
    break_direction = "NEUTRAL"
    
    # Analyze rolling 3-bar windows in last 6 bars
    # Need at least 3 bars
    if len(bars_15min) >= 3:
        # Scan windows: [..., -3], [..., -2], [..., -1]
        # Start looking from -6 (or len) up to -1
        lookback = min(len(bars_15min), 8) # Search last 2 hours max
        
        # Valid break candidate
        detected_break = None # (type, index, break_price)
        
        for i in range(len(bars_15min) - lookback + 2, len(bars_15min)):
            # Window ending at i (bars[i-2], bars[i-1], bars[i])
            window = [bars_15min[i-2], bars_15min[i-1], bars_15min[i]]
            
            # Check for Up Break
            is_up = all(b['c'] > b['o'] for b in window) and \
                    all(window[k]['c'] > window[k-1]['c'] for k in range(1, 3))
            
            # Check for Down Break
            is_down = all(b['c'] < b['o'] for b in window) and \
                      all(window[k]['c'] < window[k-1]['c'] for k in range(1, 3))
            
            # Check for Net Progress
            vol_proxy = or_range if or_range > 0 else 100.0
            move = window[2]['c'] - bars_15min[i-2]['open'] if 'open' in bars_15min[i-2] else window[2]['c'] - bars_15min[i-2]['o']
            
            if is_up or (move > 1.2 * vol_proxy):
                 detected_break = ('BULLISH', i, window[2]['c'])
            elif is_down or (move < -1.2 * vol_proxy):
                 detected_break = ('BEARISH', i, window[2]['c'])
                 
        # If break detected, check INVALIDATION (Reversal)
        if detected_break:
            b_type, b_idx, b_price = detected_break
            
            # Check price action AFTER the break
            # If current price reversed > 50% of break move? Or just strictly above/below breakdown?
            curr_price = bars_15min[-1]['c']
            
            if b_type == 'BEARISH':
                # Valid if price is NOT significantly above break price + buffer
                # Allow retest, but if it closes above break start... 
                # Simple Logic: If it's a Break, we are in Trend Mode unless we see a Structural Reversal (3 bars up).
                # Since we loop chronologically, a later Bullish break would overwrite detection.
                structural_break = True
                break_direction = 'BEARISH'
            elif b_type == 'BULLISH':
                structural_break = True
                break_direction = 'BULLISH'

    if or_range > 0:
        radius = 0.12 * or_range
        # A. Detect Stall at Support/Resistance
        last_3 = bars_15min[-3:]
        in_zone_sup = sum(1 for b in last_3 if abs(b['c'] - support) <= radius) >= 2
        in_zone_res = sum(1 for b in last_3 if abs(b['c'] - resistance) <= radius) >= 2
        
        # Price stall: max_move <= 0.25 * OR_RANGE
        prices_3 = [b['c'] for b in last_3]
        max_move_3 = max(prices_3) - min(prices_3)
        is_stalling = max_move_3 <= 0.25 * or_range
        stall_at_level = (in_zone_sup or in_zone_res) and is_stalling

        # B. Failure to Extend (Intent Failure)
        last_6 = bars_15min[-6:]
        ext_threshold = 0.18 * or_range
        ext_attempts = 0
        ext_success = 0
        for b in last_6:
            if b['l'] < support - ext_threshold or b['h'] > resistance + ext_threshold:
                ext_attempts += 1
                if b['c'] < support - ext_threshold or b['c'] > resistance + ext_threshold:
                    ext_success += 1
        failure_to_extend = (ext_attempts >= 2 and ext_success == 0)

        # C. Weak Follow-Through (Effort vs Result)
        effort = sum(abs(b['h'] - b['l']) for b in last_3)
        result = abs(bars_15min[-1]['c'] - bars_15min[-3]['c'])
        weak_follow_through = (effort >= 0.6 * or_range and result <= 0.2 * or_range)

        # Phase 2.5: Behavioral Rejection Pattern
        rej_pattern = detect_rejection_pattern(bars_15min[-1], bars_15min[:-1])
        rejection = rej_pattern != "NONE"
        
        # E. Momentum Slope
        m_slope, m_consistency = calculate_momentum_slope(bars_15min[-3:])

    # 4. Consolidate Price Behavior
    if stall_at_level:
        price_behavior = "STALL_AT_LEVEL"
    elif failure_to_extend:
        price_behavior = "FAILURE_TO_EXTEND"
    elif rejection:
        price_behavior = f"REJECTION_{rej_pattern}"
    else:
        # Fallback to breakout or range
        is_breakout = (last_range > 0 and (last_body / last_range) > 0.6)
        if is_breakout:
            price_behavior = "BREAKOUT"
        else:
            price_behavior = "IN_RANGE"

    # 4. Volume Behavior
    volume_behavior = "NORMAL"
    if len(bars_15min) >= 10:
        vol_avg = sum(b['volume'] for b in bars_15min[-10:]) / 10
        vol_ratio = bars_15min[-1]['volume'] / vol_avg if vol_avg > 0 else 1.0
        is_red = bars_15min[-1]['c'] < bars_15min[-1]['o']
        
        if vol_ratio > 1.5:
            volume_behavior = "EXPANDING_ON_RED" if is_red else "EXPANDING_ON_GREEN"
        elif vol_ratio < 0.7:
            volume_behavior = "CONTRACTING"

    # 5. Micro Bias
    micro_bias = "NEUTRAL"
    if swing_context == "BEARISH_SWING":
        if price_behavior in ["CONSOLIDATION_AT_SUPPORT", "REJECTION_TOP_REJECTION"] and "RED" in volume_behavior:
            micro_bias = "BEARISH_CONTINUATION"
        elif price_behavior == "REJECTION_BOTTOM_REJECTION" and volume_behavior == "CONTRACTING":
            micro_bias = "BEARISH_EXHAUSTION"
    elif swing_context == "BULLISH_SWING":
        if price_behavior in ["CONSOLIDATION_AT_RESISTANCE", "REJECTION_BOTTOM_REJECTION"] and "GREEN" in volume_behavior:
            micro_bias = "BULLISH_CONTINUATION"
        elif price_behavior == "REJECTION_TOP_REJECTION" and volume_behavior == "CONTRACTING":
            micro_bias = "BULLISH_EXHAUSTION"

    # 6. FAILURE_TO_ACCEPT (ITC Veto - Canonical)
    failure_to_accept = False
    impulse_detected = False
    i_move = 0.0
    if or_range > 0 and len(bars_15min) >= 15:
        window_15 = bars_15min[-15:]
        i_low = min(b['l'] for b in window_15)
        i_high = max(b['h'] for b in window_15)
        i_move = i_high - i_low
        
        # Gate: Impulse Requirement (0.4 * OR + Vol Expanding)
        if i_move >= 0.4 * or_range and "EXPANDING" in volume_behavior:
            up_count = sum(1 for b in window_15 if b['c'] > b['o'])
            down_count = sum(1 for b in window_15 if b['c'] < b['o'])
            
            direction = None
            if up_count / len(window_15) >= 0.65: direction = "BULLISH"
            elif down_count / len(window_15) >= 0.65: direction = "BEARISH"
            
            if direction:
                impulse_detected = True
                # Gate: Acceptance Check (last 5 bars)
                check_bars = bars_15min[-5:]
                if direction == "BULLISH":
                    acc_level = i_low + 0.6 * i_move
                    closes_above = sum(1 for b in check_bars if b['c'] >= acc_level)
                    deepest_pb = min(b['l'] for b in check_bars)
                    # Failure if no accept in 5 bars or structure violated
                    if closes_above == 0 or deepest_pb < i_low - 0.2 * or_range:
                        failure_to_accept = True
                else:
                    acc_level = i_high - 0.6 * i_move
                    closes_below = sum(1 for b in check_bars if b['c'] <= acc_level)
                    highest_pb = max(b['h'] for b in check_bars)
                    if closes_below == 0 or highest_pb > i_high + 0.2 * or_range:
                        failure_to_accept = True

    # 6. Confidence (PHASE-2: satisfied_conditions / total_conditions)
    # Define Conditions:
    # 1. Directional micro_bias (not NEUTRAL)
    # 2. Volume alignment (not CONTRACTING)
    # 3. Entry location quality (not MID_RANGE / IN_RANGE)
    # 4. Strength (Swing Context established)
    
    today_5min = today_5min or []
    
    total_cond = 4
    satisfied = 0
    if micro_bias != "NEUTRAL": satisfied += 1
    if volume_behavior not in ["CONTRACTING", "NORMAL"]: satisfied += 1
    if price_behavior not in ["IN_RANGE"]: satisfied += 1
    if swing_context != "RANGE_SWING": satisfied += 1
    
    confidence = round(satisfied / total_cond, 2)

    today_5min = today_5min or []
    total_cond = 4

    # 7. Phase-2 Geometry Extensions
    ter, trend_regime, regime_momentum = calculate_trend_efficiency(today_5min)

    # 7b. TREND_GRIND Detection
    # Logic: TrendEfficiency > 0.35 AND NetProgress > 0.6*ATR AND No Impulse/Expansion
    effective_atr = calculate_effective_atr(today_5min, atr_14, direction="NEUTRAL") # Default until direction
    
    is_grind = False
    if ter > 0.35:
        net_prog_abs = abs(net_progress_3)
        # Using effective_atr for threshold
        if net_prog_abs >= 0.6 * effective_atr:
            # Must NOT be Impulse or Expanding Vol (Slow Grind)
            if not impulse_detected and "EXPANDING" not in volume_behavior and retracement_depth != "DEEP":
                is_grind = True
                trend_regime = "TREND_GRIND"
    
    # Calculate Direction for Effective ATR (Refined)
    eff_direction = "NEUTRAL"
    if micro_bias == "BULLISH_CONTINUATION": eff_direction = "BULLISH"
    elif micro_bias == "BEARISH_CONTINUATION": eff_direction = "BEARISH"
    
    # Recalculate Eff ATR if direction known
    effective_atr = calculate_effective_atr(today_5min or bars_15min, atr_14, direction=eff_direction)
    
    # Bearish Exhaustion (for REMR)
    bearish_exhaustion = detect_bearish_exhaustion(
        last_bar=bars_15min[-1],
        avg_range=(atr_14 / 2), # Approx avg range
        rel_vol=bars_15min[-1]['volume'] / (sum(b['volume'] for b in bars_15min[-10:]) / 10 if len(bars_15min) >= 10 else 1)
    )

    # New REMR Validators
    vwap_val = calculate_vwap(today_5min)
    vwap_rejection = False
    if vwap_val > 0:
        # Close rejects VWAP? (Price approached VWAP and rejected)
        # Simplify: Close is away from VWAP? No, Rejection means touched and retreated.
        # Strict PROMPT definiton: "CloseRejectsVWAP == True"
        # We assume this means price action shows rejection at VWAP level.
        # Implementation: Wick touches VWAP, Close is away.
        last = bars_15min[-1]
        dist_vwap = abs(last['c'] - vwap_val)
        touched = (last['l'] <= vwap_val <= last['h'])
        vwap_rejection = touched and (dist_vwap > 0.1 * (last['h'] - last['l']))

    two_bar_fail = detect_two_bar_failure(bars_15min)

    return {
        "swing_context": swing_context,
        "retracement_depth": retracement_depth,
        "price_behavior": price_behavior,
        "volume_behavior": volume_behavior,
        "micro_bias": micro_bias,
        "confidence": confidence,
        "stall_at_level": stall_at_level,
        "failure_to_extend": failure_to_extend,
        "weak_follow_through": weak_follow_through,
        "rejection": rejection,
        "rejection_pattern": rej_pattern if 'rej_pattern' in locals() else "NONE",
        "failure_to_accept": failure_to_accept,
        "impulse_detected": impulse_detected,
        "impulse_move_pts": round(i_move, 2) if impulse_detected else 0.0,
        "last_body_ratio": last_body_ratio if 'last_body_ratio' in locals() else 0.0,
        "velocity_increasing": velocity_increasing if 'velocity_increasing' in locals() else False,
        "max_move_3": round(max_move_3, 1) if 'max_move_3' in locals() else 0.0,
        "absorption": absorption if 'absorption' in locals() else False,
        "net_progress_3": round(net_progress_3, 1) if 'net_progress_3' in locals() else 0.0,
        "structural_break": structural_break,
        "break_direction": break_direction,
        "momentum_slope": m_slope if 'm_slope' in locals() else 0.0,
        "momentum_consistency": m_consistency if 'm_consistency' in locals() else 0.0,
        "has_energy": impulse_detected or ("EXPANDING" in volume_behavior),
        "v_reversal": detect_v_reversal(bars_15min, current_price, em_low, em_high, atr_14),
        "trend_efficiency": ter,
        "trend_regime": trend_regime,
        "regime_momentum": regime_momentum,  # Phase 2.7-Light
        "effective_atr": effective_atr,
        "bearish_exhaustion": bearish_exhaustion,
        "is_grind": is_grind,
        "vwap_rejection": vwap_rejection,
        "two_bar_failure": two_bar_fail,
        "vwap": vwap_val
    }


def calculate_opening_range(today_5min):
    """
    Extracts the High and Low between 09:15 and 10:00 IST.
    """
    if not today_5min:
        return None
        
    or_bars = []
    for b in today_5min:
        # ts format from database.py: '%Y-%m-%d %H:%M:%S'
        try:
            time_str = b['ts'][11:16]
            if "09:15" <= time_str <= "10:00":
                or_bars.append(b)
        except:
            continue
            
    if not or_bars:
        return None
        
    or_high = max(b['h'] for b in or_bars)
    or_low = min(b['l'] for b in or_bars)
    or_range = or_high - or_low
    
    return {
        "or_high": round(or_high, 1),
        "or_low": round(or_low, 1),
        "or_range": round(or_range, 1)
    }

def calculate_expected_move_envelope(or_range, prior_day_range):
    """
    Calculates the volatility_of_day and the EM envelope.
    """
    if not or_range or not prior_day_range:
        return {
            "or_range": 0,
            "volatility_of_day": "NORMAL",
            "expected_move_low": 10,
            "expected_move_high": 40
        }
        
    # Volatility of the Day Detection
    if or_range >= 0.35 * prior_day_range:
        vol_of_day = "HIGH"
    elif or_range <= 0.20 * prior_day_range:
        vol_of_day = "LOW"
    else:
        vol_of_day = "NORMAL"
        
    return {
        "or_range": or_range,
        "volatility_of_day": vol_of_day,
        "expected_move_low": int(0.6 * or_range),
        "expected_move_high": int(1.2 * or_range)
    }

def calculate_economic_context(current_price, target_pts, selected_style=None):
    """
    Calculates the economic impact for a Nifty trade.
    Phase-2.5: Style-specific economic thresholds.
    """
    lot_size = 65 
    brokerage_per_lot = 60 # Approx ₹60 round trip for Nifty options
    
    expected_move = target_pts if target_pts else 0
    est_pnl = expected_move * lot_size * 0.7  # 0.7 delta
    net_expected_pnl = est_pnl - brokerage_per_lot
    
    # Style-specific significance using STYLE_ECONOMICS
    min_required_pnl = None
    if selected_style and selected_style in STYLE_ECONOMICS:
        min_required_pnl = STYLE_ECONOMICS[selected_style]["min_pnl"]
        if min_required_pnl == float("inf"):
            # LATE_SESSION_RISK_OFF - no new positions
            significance = "TRIVIAL"
        elif net_expected_pnl >= min_required_pnl:
            significance = "MEANINGFUL"
        else:
            significance = "TRIVIAL"
    else:
        # Generic fallback when no style selected
        if net_expected_pnl >= 1000:
            significance = "MEANINGFUL"
        elif net_expected_pnl >= 500:
            significance = "MARGINAL"
        else:
            significance = "TRIVIAL"
    
    return {
        "expected_move_pts": expected_move,
        "estimated_option_pnl_inr": int(est_pnl),
        "net_expected_pnl_inr": int(net_expected_pnl),
        "economic_significance": significance,
        "min_required_pnl": min_required_pnl
    }

def calculate_style_eligibility(current_time_str, micro_context, morning_plan, or_data, current_price, expected_move, today_5min=[], intraday_state="UNKNOWN"):
    """
    Determines exactly which trading styles are eligible based on time and structural facts.
    AUTHORITATIVE: Matches pseudocode specification exactly.
    
    Args:
        current_time_str: Time as "HH:MM"
        micro_context: Dict with swing_context, price_behavior, volume_behavior, etc.
        morning_plan: Dict with market_personality, boundary_levels, etc.
        or_data: Dict with OR high/low/range
        current_price: Current price (float)
        expected_move: Dict with or_range, volatility_of_day, expected_move_low/high
        today_5min: List of 5-min candles for regime classification
        intraday_state: "TREND_UP"|"TREND_DOWN"|"RANGE"|"COMPRESSION"|"OPENING_RANGE"
    """
    if not current_time_str or current_time_str == "N/A":
        return {}
        
    try:
        hr_min = int(current_time_str.replace(":", ""))
    except:
        return {}
        
    styles = {
        "OPENING_RANGE_EXPANSION": False,
        "RANGE_EXTREME_MEAN_REVERSION": False,
        "INTRADAY_TREND_CONTINUATION": False,
        "VOLATILITY_BREAK": False,
        "LATE_SESSION_RISK_OFF": False
    }
    
    # -------------------------------------------------------------------
    # PHASE 2.5: OPENING AUCTION REGIME
    # -------------------------------------------------------------------
    # Calculate OR Regime if we have enough 5-min data
    or_range = or_data.get('or_range') if or_data else expected_move.get('or_range', 0)
    or_regime = calculate_or_regime(today_5min, or_range)
    
    # -------------------------------------------------------------------
    # STATE MACHINE OVERRIDES (HIERARCHY ENFORCEMENT)
    # -------------------------------------------------------------------
    
    # 1. TREND MODE (ITC Dominance)
    if "TREND" in intraday_state:
        # User Rule: "Once ITC enabled: Disable REMR entirely."
        styles["INTRADAY_TREND_CONTINUATION"] = True
        styles["RANGE_EXTREME_MEAN_REVERSION"] = False
        styles["OPENING_RANGE_EXPANSION"] = False 
        styles["VOLATILITY_BREAK"] = False
        return styles

    # 2. RANGE / OPENING MODE
    # Extract helper facts
    behavior = micro_context.get('price_behavior', 'IN_RANGE')
    rejection = micro_context.get('rejection', False)
    rej_pattern = micro_context.get('rejection_pattern', "NONE")
    m_slope = micro_context.get('momentum_slope', 0.0)
    
    # STYLE 1: OPENING_RANGE_EXPANSION (ORE)
    # Only allowed in DISCOVERY or FAILURE (extension)
    if 920 <= hr_min <= 1030:
        if or_regime == "DISCOVERY" and behavior == "BREAKOUT":
            styles["OPENING_RANGE_EXPANSION"] = True

    # STYLE 2: RANGE_EXTREME_MEAN_REVERSION (REMR)
    # Behavioral Gate: If early (<10:00), strict rejection requirement
    if hr_min < 1000:
        if behavior.startswith("REJECTION") and rejection:
             styles["RANGE_EXTREME_MEAN_REVERSION"] = True
        else:
             styles["RANGE_EXTREME_MEAN_REVERSION"] = False
    else:
        # Mid-day REMR more permissive but still needs stall or rejection
        if behavior in ["STALL_AT_LEVEL", "FAILURE_TO_EXTEND"] or rejection:
            styles["RANGE_EXTREME_MEAN_REVERSION"] = True

    # STYLE 3: INTRADAY_TREND_CONTINUATION (ITC)
    # Allowed if State Machine detects TREND or if we have STABLE break or V-Reversal
    v_rev = micro_context.get('v_reversal', False)
    if intraday_state in ["TREND_UP", "TREND_DOWN"] or v_rev:
        styles["INTRADAY_TREND_CONTINUATION"] = True

    # 3. COMPRESSION MODE (VBD Dominance)
    if intraday_state == "COMPRESSION":
        styles["VOLATILITY_BREAK"] = True
        styles["RANGE_EXTREME_MEAN_REVERSION"] = False 
    
    # LATE SESSION GUARD
    if hr_min >= 1430:
        styles["LATE_SESSION_RISK_OFF"] = True
        for s in styles: 
            if s != "LATE_SESSION_RISK_OFF": styles[s] = False
        
    return styles
        
    return styles
    

def calculate_morning_context(daily_hist, current_price, support, resistance, pivot, vix, atr_14):
    """
    Implements deterministic mapping for Morning Call based on authoritative risk rules.
    """
    if not daily_hist:
        return {}

    # 1. Primary Bias
    # Use only last 3 days for bias determination
    recent_daily = daily_hist[:3] if len(daily_hist) >= 3 else daily_hist
    green_count = sum(1 for d in recent_daily if d['c'] > d['o'])
    red_count = sum(1 for d in recent_daily if d['c'] < d['o'])
    
    buffer = 20
    primary_bias = "NEUTRAL"
    if green_count >= 2 and current_price < resistance - buffer:
        primary_bias = "BULLISH"
    elif red_count >= 2 and current_price > support + buffer:
        primary_bias = "BEARISH"

    # 2. VIX Regime
    vix_regime = "NORMAL"
    if vix < 13: vix_regime = "COMPLACENT"
    elif vix > 18: vix_regime = "PANIC"

    # 3. Market Personality
    # IF prior day range > 1.2 × recent average range (5-day)
    market_personality = "CHOPPY"
    if len(daily_hist) >= 2:
        yesterday_range = daily_hist[0]['h'] - daily_hist[0]['l'] 
        prior_days = daily_hist[1:6] if len(daily_hist) > 1 else []
        if prior_days:
            avg_range = sum(d['h'] - d['l'] for d in prior_days) / len(prior_days)
            if yesterday_range > 1.2 * avg_range:
                market_personality = "TRENDING"

    # 4. Bias Strength (STRONG | FRAGILE)
    bias_strength = "FRAGILE"
    if primary_bias != "NEUTRAL":
        opposing_level = resistance if primary_bias == "BULLISH" else support
        dist = abs(current_price - opposing_level)
        trend_aligned = (green_count == 3 if primary_bias == "BULLISH" else red_count == 3)
        if trend_aligned and dist > 100:
            bias_strength = "STRONG"

    # 5. Expected Range (ATR * multiplier)
    base_range = (atr_14 * 1.2) if atr_14 else 150
    expected_range = base_range
    if vix_regime == "NORMAL": expected_range = base_range * 1.2
    elif vix_regime == "PANIC": expected_range = base_range * 1.5
    
    # 6. Invalidation Level
    invalidation_level = None
    if primary_bias == "BULLISH":
        invalidation_level = support - 20
    elif primary_bias == "BEARISH":
        invalidation_level = resistance + 20

    return {
        "primary_bias": primary_bias,
        "bias_strength": bias_strength,
        "vix_regime": vix_regime,
        "market_personality": market_personality,
        "expected_range_pts": int(expected_range),
        "invalidation_level": invalidation_level,
        "max_expected_move": int(expected_range)
    }

# ============================================================================
# CANONICAL SECTION 4: INTRADAY STATE MACHINE
# ============================================================================
def calculate_intraday_state(current_price, or_high, or_low, bars_15min, atr):
    """
    Determines the Behavioral State of the market.
    Follows 'Intraday Decision Constitution' rules.
    
    States:
    - OPENING_RANGE (First 45 mins - Handled by Caller mostly)
    - TREND_UP (Breakout above OR High)
    - TREND_DOWN (Breakdown below OR Low)
    - RANGE (Inside OR)
    - COMPRESSION (Tight range, pending break)
    """
    state = "RANGE"
    reason = "Inside Opening Range"
    
    # Safety
    if not bars_15min or not atr:
        return "UNKNOWN", "Insufficient Data"
        
    last_close = bars_15min[-1]['c']
    
    # Define Buffers (Noise Filter)
    # 0.2 ATR is roughly 10-15 points on Nifty
    buffer = 0.2 * atr
    
    # 1. Trend Detection (Breakout/Breakdown)
    if last_close > (or_high + buffer):
        state = "TREND_UP"
        reason = f"Breakout above OR High ({or_high:.1f}) + Buffer"
    elif last_close < (or_low - buffer):
        state = "TREND_DOWN"
        reason = f"Breakdown below OR Low ({or_low:.1f}) - Buffer"
        
    # 2. Compression Detection
    # If state is RANGE, check for tightness
    if state == "RANGE" and len(bars_15min) >= 3:
        # Check last 3 bars range
        recent_high = max(b['h'] for b in bars_15min[-3:])
        recent_low = min(b['l'] for b in bars_15min[-3:])
        recent_range = recent_high - recent_low
        
        if recent_range < 0.5 * atr:
             state = "COMPRESSION"
             reason = "Volatility Compression (< 0.5 ATR)"

    return state, reason
