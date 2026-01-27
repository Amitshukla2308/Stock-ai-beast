from brokers.base_broker import BaseBroker

class SimBroker(BaseBroker):
    """
    Broker implementation for Historical Backtests.
    Handles virtual fills and balance tracking.
    """
    
    def __init__(self, initial_balance=30000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.total_deposited = initial_balance
        self.wipeout_count = 0
        self.open_position = None
        self.margin_required = 10000 
        self.pts_to_rupees = 35.75   
        self.balance_history = []
        self.trade_count = 0
        
    def execute_entry(self, symbol, side, quantity, price, sl, target, reason, timestamp=None):
        # Slippage: 1.5 pts penalty on Entry (Buy)
        slippage = 1.5
        fill_price = price + slippage
        
        self.open_position = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'entry_price': fill_price,
            'sl': sl,
            'target': target,
            'reason': reason,
            'entry_time': timestamp
        }
        return {"status": "FILLED", "price": fill_price}

    def execute_exit(self, symbol, side, quantity, price, reason, timestamp=None):
        if not self.open_position:
            return {"status": "FAILED", "error": "No open position to exit"}
        
        pos = self.open_position
        
        # Slippage: 1.5 pts penalty on Exit (Sell)
        slippage = 1.5
        fill_price = price - slippage
        
        # Brokerage: fixed 20 rupees per trade (deducted at exit)
        brokerage = 20.0
        
        pnl_pts = fill_price - pos['entry_price'] if pos['side'] == 'CALL' else pos['entry_price'] - fill_price
        
        # Caluclate Gross PnL
        gross_pnl_rupees = pnl_pts * self.pts_to_rupees * (quantity / 65.0) 
        
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
