import os
from brokers.base_broker import BaseBroker
from brokers.fyers.connector import get_fyers_model

class FyersBroker(BaseBroker):
    """
    Broker implementation for Fyers API (Live and Mock modes).
    """
    
    def __init__(self, client_id=None, token=None):
        self.client_id = client_id or os.getenv("FYERS_CLIENT_ID")
        self.fyers = None # Lazy init
        
    def _ensure_fyers(self):
        if not self.fyers:
            self.fyers = get_fyers_model()
            
    def execute_entry(self, symbol, side, quantity, price, sl, target, reason, timestamp=None):
        self._ensure_fyers()
        print(f"⚡ [FyersBroker] ENTRY: {side} {symbol} @ {price}")
        
        # Side: 1 = BUY, -1 = SELL
        # For entry: BUY CALL (side=1) or BUY PUT (side=1, but symbol is PE)
        # In Fyers, buying a PE is still a BUY order (side=1)
        fyers_side = 1
        
        data = {
            "symbol": symbol,
            "qty": quantity,
            "type": 2, # Market Order
            "side": fyers_side,
            "productType": "INTRADAY",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        
        try:
            response = self.fyers.place_order(data=data)
            if response.get("s") == "ok":
                return {"status": "FILLED", "order_id": response.get("id")}
            else:
                return {"status": "FAILED", "error": response.get("message")}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    def execute_exit(self, symbol, side, quantity, price, reason, timestamp=None):
        self._ensure_fyers()
        print(f"⚡ [FyersBroker] EXIT: {side} {symbol} @ {price}")
        
        # To exit a BUY position, we SELL (side=-1)
        fyers_side = -1
        
        data = {
            "symbol": symbol,
            "qty": quantity,
            "type": 2, # Market Order
            "side": fyers_side,
            "productType": "INTRADAY",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        
        try:
            response = self.fyers.place_order(data=data)
            if response.get("s") == "ok":
                return {"status": "FILLED", "order_id": response.get("id")}
            else:
                return {"status": "FAILED", "error": response.get("message")}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    def get_positions(self):
        self._ensure_fyers()
        try:
            resp = self.fyers.positions()
            if resp.get("s") == "ok":
                return resp.get("netPositions", [])
            return []
        except:
            return []

    def get_balance(self):
        self._ensure_fyers()
        try:
            resp = self.fyers.funds()
            if resp.get("s") == "ok":
                # Find available margin
                for fund in resp.get("fund_limit", []):
                    if fund.get("title") == "Equity":
                        return fund.get("equityAmount", 0)
            return 0
        except:
            return 0

    def process_tick(self, tick):
        # Live broker doesn't need to do anything on every tick for simulation
        pass
