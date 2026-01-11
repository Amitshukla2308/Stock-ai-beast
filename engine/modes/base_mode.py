import requests
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
        Emits a structured JSON block for n8n to parse AND Pushes to Webhook for Real-Time updates.
        """
        import json
        import requests
        
        try:
            # Inject Mode Tag
            payload['mode'] = mode_tag
            payload['type'] = event_type # Explicit Type for Webhook
            payload['chatId'] = getattr(self, 'chat_id', None)
            
            clean_payload = json.loads(json.dumps(payload, default=str))
            json_str = json.dumps(clean_payload)
            
            # 1. Print to Stdout (Legacy/Fallback + Logging)
            print(f"\n<<<TELEGRAM {event_type}>>> {json_str} <<<END>>>\n")
            
            # 2. Push to n8n Webhook (Real-Time)
            # URL: http://n8n:5678/webhook/telegram-push inside Docker network
            webhook_url = "http://host.docker.internal:5678/webhook/telegram-push"
            try:
                requests.post(webhook_url, json=clean_payload, timeout=2)
            except Exception as w_err:
                print(f"⚠️ Webhook Push Failed: {w_err}")
                
        except Exception as e:
            print(f"⚠️ Telegram Emit Error: {e}")
