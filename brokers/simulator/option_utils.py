"""
Mock Mode Option Pricing Utilities
Provides real-time option instrument selection and pricing for SimBroker.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

def get_atm_strike(spot_price: float, strike_interval: int = 50) -> int:
    """
    Round spot price to nearest ATM strike.
    
    Args:
        spot_price: Current NIFTY spot price
        strike_interval: Strike interval (50 for NIFTY)
    
    Returns:
        Nearest strike price
    """
    return round(spot_price / strike_interval) * strike_interval


def construct_option_symbol(strike: int, side: str, date_obj: datetime) -> str:
    """Constructs symbol for a specific date object."""
    option_type = 'CE' if side == 'CALL' else 'PE'
    yy = date_obj.strftime('%y')
    
    month_val = date_obj.month
    if month_val <= 9: m = str(month_val)
    elif month_val == 10: m = 'O'
    elif month_val == 11: m = 'N'
    else: m = 'D'
    
    dd = date_obj.strftime('%d')
    return f"NSE:NIFTY{yy}{m}{dd}{strike}{option_type}"


def find_nearest_expiry_with_ltp(fyers_client, spot_price: float, side: str) -> Tuple[Optional[str], Optional[float], Optional[int]]:
    """
    Deterministically find the nearest expiry by checking the next 7 days.
    """
    strike = get_atm_strike(spot_price)
    now = datetime.now(IST)
    
    # Tuesday is 1, Wednesday is 2... 
    # NIFTY is Tuesday now (v6.3 Compliance)
    potential_dates = []
    for i in range(8):
        check_date = now + timedelta(days=i)
        # Traditionally we check Tuesday(1), but we check all for robustness 
        # (Handles holidays shifting expiry to previous day)
        potential_dates.append(check_date)
    
    # Generate symbols for the next week
    symbol_map = {} # symbol -> (date, strike)
    for dt in potential_dates:
        sym = construct_option_symbol(strike, side, dt)
        symbol_map[sym] = (dt, strike)
    
    symbols_to_check = ",".join(symbol_map.keys())
    
    try:
        response = fyers_client.quotes({"symbols": symbols_to_check})
        if response and response.get('s') == 'ok' and 'd' in response:
            # Fyers returns d as a list of quotes
            quotes = response['d']
            
            # Sort quotes by date to find the NEAREST one
            valid_quotes = []
            for q in quotes:
                sym = q.get('n')
                ltp = q.get('v', {}).get('lp', 0)
                if ltp and ltp > 0:
                    dt, st = symbol_map[sym]
                    valid_quotes.append({
                        'symbol': sym,
                        'ltp': float(ltp),
                        'strike': st,
                        'date': dt
                    })
            
            if valid_quotes:
                # Get the one with the minimum date (nearest expiry)
                valid_quotes.sort(key=lambda x: x['date'])
                nearest = valid_quotes[0]
                logger.info(f"   [Expiry] 🎯 Found Nearest Expiry: {nearest['symbol']} (Date: {nearest['date'].strftime('%Y-%m-%d')})")
                return nearest['symbol'], nearest['ltp'], nearest['strike']
                
    except Exception as e:
        logger.error(f"   [Expiry] ❌ Batch check failed: {e}")
        
    return None, None, None

def get_option_ltp(fyers_client, option_symbol: str) -> Optional[float]:
    """
    Fetch live LTP for an option instrument from Fyers.
    """
    try:
        data = {"symbols": option_symbol}
        response = fyers_client.quotes(data)
        
        if response and response.get('s') == 'ok' and 'd' in response:
            quotes = response['d']
            if quotes:
                ltp = quotes[0].get('v', {}).get('lp', 0)
                return float(ltp) if ltp > 0 else None
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch option LTP for {option_symbol}: {e}")
        return None
