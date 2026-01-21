import os
import json
import time
import requests

_last_telegram_time = 0
_min_telegram_interval = 0.5

def emit_telegram_signal(event_type, payload, mode_tag="SYSTEM"):
    """
    Centralized utility to emit Telegram signals.
    1. Prints structured text to stdout (for terminal/n8n scraping).
    2. Sends a POST request to the n8n webhook (for real-time Telegram delivery).
    """
    global _last_telegram_time
    
    try:
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - _last_telegram_time
        if time_since_last < _min_telegram_interval:
            time.sleep(_min_telegram_interval - time_since_last)
            
        # Metadata
        payload['mode'] = mode_tag
        payload['type'] = event_type
        
        # Inject Chat ID from environment if missing
        if 'chatId' not in payload or not payload['chatId']:
            payload['chatId'] = os.getenv("TELEGRAM_CHAT_ID")
        
        # Ensure payload is JSON serializable
        clean_payload = json.loads(json.dumps(payload, default=str))
        json_str = json.dumps(clean_payload)
        
        # 1. Stdout Signal
        # Useful for local debugging and environments that scrape process logs
        print(f"\n<<<TELEGRAM {event_type}>>> {json_str} <<<END>>>\n")
        
        # 2. n8n Webhook
        webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "http://host.docker.internal:5678/webhook/telegram-push")
        try:
            requests.post(webhook_url, json=clean_payload, timeout=3)
            _last_telegram_time = time.time()
        except Exception:
            # Silently fail webhook - stdout is the fallback
            pass
            
    except Exception as e:
        # Don't crash the main execution if telemetry fails
        print(f"⚠️ Telegram Signal Error: {e}")
