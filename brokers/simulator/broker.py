from brokers.base_broker import BaseBroker
import logging

logger = logging.getLogger(__name__)

class SimBroker(BaseBroker):
    """
    Broker implementation for Historical Backtests.
    Handles virtual fills and balance tracking.
    """
    
    def __init__(self, initial_balance=30000, fyers_client=None):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.total_deposited = initial_balance
        self.wipeout_count = 0
        self.open_position = None
        self.margin_required = 10000 
        self.pts_to_rupees = 35.75   
        self.balance_history = []
        self.trade_count = 0
        self.fyers_client = fyers_client  # For real option pricing
        
    def execute_entry(self, symbol, side, quantity, price, sl, target, reason, timestamp=None):
        """
        v6.3 Mock Fidelity: Use Real Option Prices
        Entry uses index 'price' to select ATM strike, but fills at real option premium.
        """
        fill_price = price + 1.5  # Fallback to delta model
        option_symbol = None
        strike = None
        
        print(f"   [SimBroker] execute_entry called: {side} @ {price}, fyers_client={self.fyers_client is not None if hasattr(self, 'fyers_client') else False}")
        
        try:
            from brokers.simulator.option_utils import find_nearest_expiry_with_ltp
            
            # Deterministically find exact option instrument and price
            if self.fyers_client:
                 print(f"   [SimBroker] 🔎 Searching for nearest valid expiry for {side}...")
                 option_symbol, real_ltp, strike = find_nearest_expiry_with_ltp(self.fyers_client, price, side)
                 
                 if option_symbol and real_ltp:
                     fill_price = real_ltp + 1.0  # Add realistic slippage
                     print(f"   [SimBroker] 🎯 Deterministic Fill: {option_symbol} @ ₹{fill_price:.2f}")
                     logger.info(f"   [SimBroker] 💰 Real Fill: {option_symbol} @ ₹{fill_price:.2f}")
                 else:
                     print(f"   [SimBroker] ⚠️ Could not find valid expiry, falling back to delta model")
                     logger.warning(f"   [SimBroker] ⚠️ No valid expiry found, using delta model")
            else:
                print(f"   [SimBroker] No Fyers client available, using delta model")
                logger.debug(f"   [SimBroker] No Fyers client, using delta model")
                
        except Exception as e:
            print(f"   [SimBroker] Exception during option pricing: {e}")
            import traceback
            traceback.print_exc()
            logger.warning(f"   [SimBroker] Option pricing failed: {e}. Using fallback.")

        self.open_position = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'entry_price': fill_price,
            'sl': sl,
            'target': target,
            'reason': reason,
            'entry_time': timestamp,
            'option_symbol': option_symbol,  # Track the actual option
            'strike': strike
        }
        return {"status": "FILLED", "price": fill_price, "option_symbol": option_symbol}

    def execute_exit(self, symbol, side, quantity, price, reason, timestamp=None):
        if not self.open_position:
            return {"status": "FAILED", "error": "No open position to exit"}
        
        pos = self.open_position
        fill_price = price - 1.5 # Default index exit with slippage
        
        print(f"   [SimBroker] execute_exit called: {side} @ {price}, reason={reason}")
        
        # v6.3: Use real option price for exit if it was a real option entry
        is_premium_trade = pos['entry_price'] < 5000
        if is_premium_trade and self.fyers_client and pos.get('option_symbol'):
             try:
                 from brokers.simulator.option_utils import get_option_ltp
                 real_exit_ltp = get_option_ltp(self.fyers_client, pos['option_symbol'])
                 if real_exit_ltp and real_exit_ltp > 0:
                     fill_price = real_exit_ltp - 1.0 # Realistic slippage on exit
                     print(f"   [SimBroker] 🎯 Real Option Exit: {pos['option_symbol']} @ ₹{fill_price:.2f}")
             except Exception as e:
                 print(f"   [SimBroker] ⚠️ Failed to fetch option exit price: {e}")

        # Brokerage: fixed 20 rupees per trade (deducted at exit)
        brokerage = 20.0
        
        # PnL Calculation (Exit - Entry for CALL, Entry - Exit for PUT)
        pnl_pts = fill_price - pos['entry_price'] if pos['side'] == 'CALL' else pos['entry_price'] - fill_price
        
        # v6.3: Calculate Gross PnL (Option premium vs Index delta)
        if is_premium_trade:
             # Pure option math: (exit - entry) * quantity
             gross_pnl_rupees = pnl_pts * quantity
        else:
             # Index math: (exit - entry) * quantity * delta
             gross_pnl_rupees = pnl_pts * self.pts_to_rupees * (quantity / 65.0) 
        
        print(f"   [SimBroker] PnL Calc: {pnl_pts:+.2f} points | Gross PnL: ₹{gross_pnl_rupees:+.0f}")
        
        # Net PnL = Gross - Brokerage
        net_pnl_rupees = gross_pnl_rupees - brokerage
        
        self.balance += net_pnl_rupees
        self.trade_count += 1
        
        # Record history
        self.balance_history.append({
            'timestamp': timestamp,
            'balance': self.balance,
            'pnl_rupees': net_pnl_rupees,
            'brokerage': brokerage,
            'slippage_pts': 3.0 # Total for trade
        })
        
        if self.balance < self.margin_required:
            self.wipeout_count += 1
            injection = self.initial_balance - self.balance
            self.total_deposited += injection
            self.balance = self.initial_balance
            print(f"      💀 [SimBroker] WIPEOUT! Injected ₹{injection:.0f}")
            
        self.open_position = None
        return {"status": "FILLED", "price": fill_price, "pnl_pts": pnl_pts, "rupee_pnl": net_pnl_rupees}

    def get_summary(self):
        return {
            'initial_balance': self.initial_balance,
            'total_deposited': self.total_deposited,
            'current_balance': self.balance,
            'net_pnl_rupees': self.balance - self.total_deposited,
            'wipeout_count': self.wipeout_count,
            'trade_count': self.trade_count,
            'balance_history': self.balance_history
        }

    def get_positions(self):
        return [self.open_position] if self.open_position else []

    def get_balance(self):
        return self.balance

    def update_balance(self, amount: float):
        """
        External balance update (e.g. from TradeLifecycle).
        """
        self.balance += amount
        self.balance_history.append({
            'timestamp': None, # Timestamp usually handled by caller or context
            'balance': self.balance,
            'pnl_rupees': amount,
            'source': 'EXTERNAL_UPDATE'
        })
        
        if self.balance < self.margin_required:
            self.wipeout_count += 1
            injection = self.initial_balance - self.balance
            self.total_deposited += injection
            self.balance = self.initial_balance
            print(f"      💀 [SimBroker] WIPEOUT! Injected ₹{injection:.0f}")

    def process_tick(self, tick):
        pass
