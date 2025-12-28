from abc import ABC, abstractmethod

class BaseMode(ABC):
    @abstractmethod
    def start(self):
        """Start the trading mode loop"""
        pass

    @abstractmethod
    def stop(self):
        """Stop the trading mode"""
        pass
        
    @abstractmethod
    def on_tick(self, tick):
        """Handle incoming market data"""
        pass
