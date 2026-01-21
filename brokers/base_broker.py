from abc import ABC, abstractmethod

class BaseBroker(ABC):
    """
    Abstract interface for all broker implementations (Live, Mock, Simulator).
    Ensures logical parity across all trading modes.
    """
    
    @abstractmethod
    def execute_entry(self, symbol, side, quantity, price, sl, target, reason, timestamp=None):
        """Execute a buy/entry order."""
        pass
        
    @abstractmethod
    def execute_exit(self, symbol, side, quantity, price, reason, timestamp=None):
        """Execute a sell/exit order."""
        pass
        
    @abstractmethod
    def get_positions(self):
        """Retrieve current open positions."""
        pass
        
    @abstractmethod
    def get_balance(self):
        """Retrieve current account balance."""
        pass

    @abstractmethod
    def process_tick(self, tick):
        """Allow broker to update internal state (e.g. simulation) on every tick."""
        pass
