from datetime import datetime, timedelta

def select_option_contract(side, spot_price, expiry_offset=0):
    """
    Select Bank Nifty option contract based on side and current spot
    
    Args:
        side: 'CALL' or 'PUT'
        spot_price: Current Bank Nifty index price
        expiry_offset: 0 = current week, 1 = next week, etc.
    
    Returns:
        symbol: NSE option symbol (e.g., "NSE:BANKNIFTY25DEC59000CE")
    """
    # Bank Nifty strikes are in 100-point increments
    base_strike = round(spot_price / 100) * 100
    
    # Choose slightly OTM for better premium/risk
    if side == 'CALL':
        strike = base_strike + 100  # 1 strike OTM
    else:  # PUT
        strike = base_strike - 100
    
    # Calculate nearest weekly expiry (Wednesday)
    today = datetime.now()
    days_to_wednesday = (2 - today.weekday()) % 7  # Wednesday = 2
    if days_to_wednesday == 0 and today.hour >= 15:  # After 3:30 PM Wednesday
        days_to_wednesday = 7  # Move to next week
    
    expiry = today + timedelta(days=days_to_wednesday + expiry_offset * 7)
    
    # Format: BANKNIFTY25DEC59000CE
    year_str = expiry.strftime('%y')
    month_str = expiry.strftime('%b').upper()
    day_str = expiry.strftime('%d')
    
    contract_type = "CE" if side == 'CALL' else "PE"
    
    # NSE format with zero-padded day
    symbol = f"NSE:BANKNIFTY{day_str}{month_str}{year_str}{strike}{contract_type}"
    
    print(f"   📋 Selected Contract: {symbol} (Spot: {spot_price:.0f})")
    return symbol
