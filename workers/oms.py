def execute_order(broker_model, symbol: str, action: str, quantity: int, reason: str):
def execute_order(broker_model, symbol: str, action: str, quantity: int, reason: str, market_price: float = 0):
    """
    Executes the trade after all checks allow it.
    """
    print(f"⚡ [OMS] Executing {action} {quantity} x {symbol} @ ~{market_price}")
    print(f"   Reason: {reason}")
    
    try:
        if broker_model:
            # Fyers API Constants
            # Side: 1 = BUY, -1 = SELL
            side = 1 if action == "BUY" else -1
            
            # Type: 2 = Market Order (Simple for MVP)
            order_type = 2 
            
            # For Paper Trading, we might want to pass the market price as limitPrice 
            # so the mock broker knows what price to fill at.
            # Real Fyers API ignores limitPrice for Market Orders (Type 2).
            price_to_send = market_price if market_price > 0 else 0
            
            data = {
                "symbol": symbol,
                "qty": quantity,
                "type": order_type,
                "side": side,
                "productType": "INTRADAY", 
                "limitPrice": price_to_send, 
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
            }
            
            response = broker_model.place_order(data=data)
            print(f"✅ Order Sent. Response: {response}")
            
            if response.get("s") == "error":
                 print(f"❌ Broker Error: {response.get('message')}")
                 return {"status": "FAILED", "error": response.get('message')}
                 
            return {"status": "SUBMITTED", "response": response}
        else:
            print("⚠️ Paper Trade Logged.")
            
        return {"status": "FILLED", "price": 0, "msg": "Trade Executed"} 
        
    except Exception as e:
        print(f"❌ Order Failed: {e}")
        return {"status": "FAILED", "error": str(e)}
