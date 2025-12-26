from datetime import datetime
from . import ledger

class PaperBroker:
    def __init__(self):
        self.state = ledger.load_ledger()
        print(f"📄 Paper Broker Initialized. Cash: {self.state['cash']}")

    def place_order(self, data):
        """
        Mimics Fyers place_order.
        data dict contains: symbol, qty, side (1=BUY, -1=SELL), type, etc.
        """
        symbol = data.get("symbol")
        qty = int(data.get("qty", 0))
        side = data.get("side") # 1 = BUY, -1 = SELL
        
        # For simulation, we need a price. 
        # In a real backtest, this comes from the current candle.
        # Here, we might need to fetch it or accept it as an arg.
        # Since the interface is fixed (data dict), we cheat and assume 'limitPrice' 
        # is filled with current price OR we just log it as executed at "MARKET" (0)
        # But for ledger tracking we need a value.
        
        # NOTE: In a proper system, the Broker is unaware of market price unless passed, 
        # or it looks it up. For this MVP, we will assume the caller puts the current market price 
        # in 'limitPrice' even for market orders, OR we just use a placeholder if 0.
        
        price = data.get("limitPrice", 0)
        if price == 0:
             # If price is 0 (Market Order), we ideally need the live price.
             # but we don't have access to the data feed here easily.
             # We will just print a warning and use a dummy or last known?
             # Let's assume the OMS logic *could* pass the current price in a custom field 
             # tailored for PaperBroker, or we just rely on later adjustment.
             # For now, let's just say we execute at 0 (Logic Placeholder).
             price = 0 
        
        action = "BUY" if side == 1 else "SELL"
        
        # 1. Validate Cash/Holdings
        if action == "BUY":
            cost = price * qty
            if cost > 0 and self.state["cash"] < cost:
                 return {"s": "error", "message": "Insufficient Funds"}
            self.state["cash"] -= cost
            
            # Update Position
            current_qty = self.state["positions"].get(symbol, 0)
            self.state["positions"][symbol] = current_qty + qty
            
        elif action == "SELL":
            current_qty = self.state["positions"].get(symbol, 0)
            if current_qty < qty:
                 return {"s": "error", "message": "Insufficient Holdings"}
            
            revenue = price * qty
            self.state["cash"] += revenue
            self.state["positions"][symbol] = current_qty - qty
            
            # Cleanup zero positions
            if self.state["positions"][symbol] == 0:
                del self.state["positions"][symbol]

        # 2. Log Trade
        ledger.log_trade(self.state, symbol, action, qty, price)
        ledger.save_ledger(self.state)
        
        return {
            "s": "ok", 
            "id": f"PAPER-{int(datetime.now().timestamp())}", 
            "message": f"Paper {action} Executed"
        }

    def history(self, data):
        """
        Pass-through or Mock History? 
        Paper Broker usually doesn't provide data history, it consumes it.
        But main_cxo calls fyers.history().
        If we replace fyers completely, we need this.
        However, the plan is to Separate Execution from Data.
        So this might not be called if we configure it right.
        Implementing a dummy just in case.
        """
        return {"s": "error", "message": "PaperBroker does not provide History API. Use Data Client."}
