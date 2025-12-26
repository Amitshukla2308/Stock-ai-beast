import json
import os
from datetime import datetime

LEDGER_FILE = "data/paper_ledger.json"

DEFAULT_STATE = {
    "cash": 100000.0,
    "positions": {}, # symbol -> quantity
    "trade_history": []
}

def load_ledger():
    if not os.path.exists(LEDGER_FILE):
        _ensure_data_dir()
        save_ledger(DEFAULT_STATE)
        return DEFAULT_STATE
    
    try:
        with open(LEDGER_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Ledger Load Error: {e}. Resetting.")
        return DEFAULT_STATE

def save_ledger(state):
    _ensure_data_dir()
    with open(LEDGER_FILE, "w") as f:
        json.dump(state, f, indent=2)

def log_trade(state, symbol, action, quantity, price):
    trade = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price
    }
    state["trade_history"].append(trade)
    return state

def _ensure_data_dir():
    os.makedirs(os.path.dirname(LEDGER_FILE), exist_ok=True)
