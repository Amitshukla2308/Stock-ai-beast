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

    def _emit_telegram_event(self, event_type, payload, mode_tag="BACKTEST"):
        """
        Emits a structured JSON block for n8n to parse.
        Format: <<<TELEGRAM {event_type}>>> {json} <<<END>>>
        """
        import json
        try:
            # Inject Mode Tag
            payload['mode'] = mode_tag
            
            clean_payload = json.loads(json.dumps(payload, default=str))
            json_str = json.dumps(clean_payload)
            print(f"\n<<<TELEGRAM {event_type}>>> {json_str} <<<END>>>\n")
        except Exception as e:
            print(f"⚠️ Telegram Emit Error: {e}")
