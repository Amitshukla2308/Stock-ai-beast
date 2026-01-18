import requests
from abc import ABC, abstractmethod
import time

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
        Includes rate limiting and 429 retry logic.
        """
        import json
        import time as time_module
        
        try:
            # Rate limiting: ensure minimum interval between messages
            current_time = time_module.time()
            time_since_last = current_time - BaseMode._last_telegram_time
            if time_since_last < BaseMode._min_telegram_interval:
                sleep_time = BaseMode._min_telegram_interval - time_since_last
                time_module.sleep(sleep_time)
            
            # Inject Mode Tag
            payload['mode'] = mode_tag
            payload['type'] = event_type
            payload['chatId'] = getattr(self, 'chat_id', None)
            
            clean_payload = json.loads(json.dumps(payload, default=str))
            json_str = json.dumps(clean_payload)
            
            # 1. Print to Stdout (Legacy/Fallback + Logging)
            # print(f"\n<<<TELEGRAM {event_type}>>> {json_str} <<<END>>>\n")
            
            # 2. Push to n8n Webhook with retry logic for 429
            webhook_url = "http://host.docker.internal:5678/webhook/telegram-push"
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    resp = requests.post(webhook_url, json=clean_payload, timeout=5)
                    BaseMode._last_telegram_time = time_module.time()
                    
                    if resp.status_code == 200:
                        break  # Success
                    elif resp.status_code == 429:
                        # Rate limited - parse retry_after from Telegram response
                        retry_after = 5  # Default 5 seconds
                        try:
                            error_data = resp.json()
                            if 'parameters' in error_data:
                                retry_after = error_data['parameters'].get('retry_after', 5)
                        except:
                            pass
                        print(f"⚠️ Telegram 429: Retry after {retry_after}s (attempt {attempt+1}/{max_retries})")
                        time_module.sleep(min(retry_after, 30))  # Cap at 30s
                    else:
                        print(f"⚠️ Webhook returned {resp.status_code}: {resp.text[:100]}")
                        break  # Don't retry on other errors
                        
                except Exception as w_err:
                    print(f"⚠️ Webhook Push Failed ({event_type}): {w_err}")
                    break
                    
        except Exception as e:
            print(f"⚠️ Telegram Emit Error ({event_type}): {e}")


