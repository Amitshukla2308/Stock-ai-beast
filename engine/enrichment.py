# engine/enrichment.py
import math

# Style-Specific Economic Minimums (Authoritative - Canonical Spec)
STYLE_ECONOMICS = {
    "OPENING_RANGE_EXPANSION": {"min_pnl": 1000, "max_hold_min": 45},
    "RANGE_EXTREME_MEAN_REVERSION": {"min_pnl": 500, "max_hold_min": 20},
    "INTRADAY_TREND_CONTINUATION": {"min_pnl": 1500, "max_hold_min": 60},
    "VOLATILITY_BREAK": {"min_pnl": 1800, "max_hold_min": 30},
    "LATE_SESSION_RISK_OFF": {"min_pnl": float("inf"), "max_hold_min": 0}
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
        
        # Calculate minutes since 09:15
        market_open_minutes = 9 * 60 + 15  # 555
        current_minutes = hour * 60 + minute
        minutes_since_open = current_minutes - market_open_minutes
        
        # Classify session phase per canonical spec
        if minutes_since_open <= 45:
            session_phase = "OPENING"
        elif minutes_since_open <= 240:  # Until 13:15
            session_phase = "MIDDAY"
        else:
            session_phase = "LATE"
        
        return {
            "minutes_since_open": minutes_since_open,
            "session_phase": session_phase
        }
    except:
        return {
            "minutes_since_open": 0,
            "session_phase": "UNKNOWN"
        }

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


def calculate_micro_context(bars_15min, current_price, support, resistance, pivot, atr_14, or_range=0):
    """
    Analyzes 15-min bars to determine micro-structural context using deterministic mapping.
    - bars_15min: List of dicts with o, h, l, c, volume
    - atr_14: ATR value from 15-min bars
    """
    if not bars_15min or len(bars_15min) < 2:
        return {}

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

        # D. Rejection (Canonical Logic)
        c_now = bars_15min[-1]['c']
        c_prev = bars_15min[-2]['c']
        rejection = (c_now < support and c_prev > support) or (c_now > resistance and c_prev < resistance) or \
                    (last_3[0]['l'] < support and last_3[-1]['c'] > support) or \
                    (last_3[0]['h'] > resistance and last_3[-1]['c'] < resistance)

    # 4. Consolidate Price Behavior
    if stall_at_level:
        price_behavior = "STALL_AT_LEVEL"
    elif failure_to_extend:
        price_behavior = "FAILURE_TO_EXTEND"
    elif rejection:
        price_behavior = "REJECTION"
    else:
        # Fallback to breakout or range
        last_bar = bars_15min[-1]
        last_body = abs(last_bar['c'] - last_bar['o'])
        last_range = last_bar['h'] - last_bar['l']
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
        if price_behavior in ["CONSOLIDATION_AT_SUPPORT", "REJECTION_AT_RESISTANCE"] and "RED" in volume_behavior:
            micro_bias = "BEARISH_CONTINUATION"
        elif price_behavior == "REJECTION_AT_SUPPORT" and volume_behavior == "CONTRACTING":
            micro_bias = "BEARISH_EXHAUSTION"
    elif swing_context == "BULLISH_SWING":
        if price_behavior in ["CONSOLIDATION_AT_RESISTANCE", "REJECTION_AT_SUPPORT"] and "GREEN" in volume_behavior:
            micro_bias = "BULLISH_CONTINUATION"
        elif price_behavior == "REJECTION_AT_RESISTANCE" and volume_behavior == "CONTRACTING":
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
    
    total_cond = 4
    satisfied = 0
    if micro_bias != "NEUTRAL": satisfied += 1
    if volume_behavior not in ["CONTRACTING", "NORMAL"]: satisfied += 1
    if price_behavior not in ["IN_RANGE"]: satisfied += 1
    if swing_context != "RANGE_SWING": satisfied += 1
    
    confidence = round(satisfied / total_cond, 2)

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
        "failure_to_accept": failure_to_accept,
        "impulse_detected": impulse_detected,
        "impulse_move_pts": round(i_move, 2) if impulse_detected else 0.0
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

def calculate_style_eligibility(current_time_str, micro_context, morning_plan, or_data, current_price, expected_move):
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
    
    # Extract helper facts
    swing = micro_context.get('swing_context', 'RANGE_SWING')
    behavior = micro_context.get('price_behavior', 'IN_RANGE')
    vol_behavior = micro_context.get('volume_behavior', 'NORMAL')
    retracement = micro_context.get('retracement_depth', 'UNCERTAIN')
    compression = micro_context.get('compression_ratio', 1.0)
    
    personality = morning_plan.get('market_personality', 'CHOPPY')
    boundaries = morning_plan.get('boundary_levels', {})
    support = boundaries.get('support_zone', 0)
    resistance = boundaries.get('resistance_zone', 0)
    pivot = boundaries.get('pivot_point', 0)
    
    # Expected Move envelope
    em_or_range = expected_move.get('or_range', 0)
    em_low = expected_move.get('expected_move_low', 0)
    em_high = expected_move.get('expected_move_high', 0)
    volatility_of_day = expected_move.get('volatility_of_day', 'NORMAL')
    
    # -------------------------------------------------------------------
    # STYLE 1: OPENING_RANGE_EXPANSION
    # Time: 09:20-10:00
    # Condition: BREAKOUT + (NORMAL or HIGH volatility) + or_range > 0
    # -------------------------------------------------------------------
    if (
        920 <= hr_min <= 1000
        and behavior == "BREAKOUT"
        and volatility_of_day in ("NORMAL", "HIGH")
        and em_or_range > 0
    ):
        styles["OPENING_RANGE_EXPANSION"] = True
    
    # -------------------------------------------------------------------
    # STYLE 2: RANGE_EXTREME_MEAN_REVERSION (ADVANCED FIX - JAN 14)
    # Market: CHOPPY
    # Scoring: Location + Failure to Extend + Stall + Rejection
    # Threshold: EM High >= 25 pts, REMR_Confidence >= 0.45
    # -------------------------------------------------------------------
    if personality == "CHOPPY" and em_high >= 25:
        # 1. Location Weight (0.50)
        proximity = 0.15 * em_or_range if em_or_range > 0 else 15
        in_location = abs(current_price - support) <= proximity or abs(current_price - resistance) <= proximity
        loc_score = 0.50 if in_location else 0.0
        
        # 2. Failure to Extend (0.30)
        failure_score = 0.30 if micro_context.get('failure_to_extend') else 0.0
        
        # 3. Micro Alignment (0.20) - Bias/Stall/Rejection alignment
        alignment = micro_context.get('stall_at_level') or micro_context.get('rejection') or micro_context.get('weak_follow_through')
        alignment_score = 0.20 if alignment else 0.0
        
        remr_confidence = loc_score + failure_score + alignment_score
        
        if remr_confidence >= 0.45:
            styles["RANGE_EXTREME_MEAN_REVERSION"] = True
            # Optional: Log the confidence if needed, for now just set eligibility
    
    # -------------------------------------------------------------------
    # STYLE 3: INTRADAY_TREND_CONTINUATION
    # Market: TRENDING
    # Veto: Failure to Accept (Binary Structural Veto)
    # Threshold: EM High >= 40 pts
    # -------------------------------------------------------------------
    valid_retracement = retracement in ("38.2", "50", "SHALLOW", "NORMAL")
    fta_veto = micro_context.get('failure_to_accept', False)
    impulse_ok = micro_context.get('impulse_detected', False)
    
    if (
        personality == "TRENDING"
        and swing in ("UP_SWING", "DOWN_SWING", "BULLISH_SWING", "BEARISH_SWING")
        and valid_retracement
        and vol_behavior in ("EXPANDING", "EXPANDING_ON_GREEN", "EXPANDING_ON_RED")
        and em_high >= 40
        and impulse_ok
        and not fta_veto
    ):
        styles["INTRADAY_TREND_CONTINUATION"] = True
    
    # -------------------------------------------------------------------
    # STYLE 4: VOLATILITY_BREAK
    # Compression: ratio <= 0.7
    # Behavior: BREAKOUT
    # Volume: EXPANDING
    # Volatility: HIGH
    # -------------------------------------------------------------------
    if (
        compression <= 0.7
        and behavior == "BREAKOUT"
        and vol_behavior in ("EXPANDING", "EXPANDING_ON_GREEN", "EXPANDING_ON_RED")
        and volatility_of_day == "HIGH"
    ):
        styles["VOLATILITY_BREAK"] = True
    
    # -------------------------------------------------------------------
    # STYLE 5: LATE_SESSION_RISK_OFF
    # Time: >= 14:30
    # Rule: NO NEW POSITIONS
    # -------------------------------------------------------------------
    if hr_min >= 1430:
        styles["LATE_SESSION_RISK_OFF"] = True
    
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
