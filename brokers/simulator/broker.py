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
        self.open_position = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'entry_price': price,
            'sl': sl,
            'target': target,
            'reason': reason,
            'entry_time': timestamp
        }
        return {"status": "FILLED", "price": price}

    def execute_exit(self, symbol, side, quantity, price, reason, timestamp=None):
        if not self.open_position:
            return {"status": "FAILED", "error": "No open position to exit"}
        
        pos = self.open_position
        pnl_pts = price - pos['entry_price'] if pos['side'] == 'CALL' else pos['entry_price'] - price
        rupee_pnl = pnl_pts * self.pts_to_rupees * (quantity / 65.0) 
        
        self.balance += rupee_pnl
        self.trade_count += 1
        
        # Record history
        self.balance_history.append({
            'timestamp': timestamp,
            'balance': self.balance,
            'pnl_rupees': rupee_pnl
        })
        
        if self.balance < self.margin_required:
            self.wipeout_count += 1
            injection = self.initial_balance - self.balance
            self.total_deposited += injection
            self.balance = self.initial_balance
            print(f"      💀 [SimBroker] WIPEOUT! Injected ₹{injection:.0f}")
            
        self.open_position = None
        return {"status": "FILLED", "price": price, "pnl_pts": pnl_pts, "rupee_pnl": rupee_pnl}

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

    def process_tick(self, tick):
        pass
