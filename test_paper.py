
import sys
import os

# Adjust path so we can import brokers.paper
sys.path.append(os.getcwd())

from brokers.paper.connector import PaperBroker

def test_paper_broker():
    print("Testing Paper Broker...")
    broker = PaperBroker()
    
    # Check Initial State
    initial_cash = broker.state['cash']
    print(f"Initial Cash: {initial_cash}")
    
    # Place Buy Order
    order = {
        "symbol": "NSE:TEST-EQ",
        "qty": 10,
        "side": 1, 
        "limitPrice": 100
    }
    resp = broker.place_order(order)
    print(f"Buy Response: {resp}")
    
    assert broker.state['cash'] == initial_cash - 1000
    assert broker.state['positions']["NSE:TEST-EQ"] == 10
    
    print("✅ Buy Logic Verified")
    
    # Place Sell Order
    order_sell = {
        "symbol": "NSE:TEST-EQ",
        "qty": 5,
        "side": -1,
        "limitPrice": 110
    }
    resp = broker.place_order(order_sell)
    print(f"Sell Response: {resp}")

    expected_cash = initial_cash - 1000 + 550
    assert broker.state['cash'] == expected_cash
    assert broker.state['positions']["NSE:TEST-EQ"] == 5
    
    print("✅ Sell Logic Verified")
    print("✅ Paper Broker Test Passed")

if __name__ == "__main__":
    test_paper_broker()
