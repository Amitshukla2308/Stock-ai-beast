import requests
from abc import ABC, abstractmethod
import time
from engine.comm import emit_telegram_signal

class BaseMode(ABC):
    # Class-level rate limiting
    _last_telegram_time = 0
    _min_telegram_interval = 0.5  # Minimum 500ms between messages
    
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

    def _emit_telegram_event(self, event_type, payload, mode_tag="BACKTEST"):
        """
        Emits a structured JSON block for n8n to parse AND Pushes to Webhook for Real-Time updates.
        Delegates to centralized emit_telegram_signal.
        """
        # Add metadata specific to Mode instances
        if hasattr(self, 'chat_id') and self.chat_id:
             payload['chatId'] = self.chat_id
             
        emit_telegram_signal(event_type, payload, mode_tag=mode_tag)


