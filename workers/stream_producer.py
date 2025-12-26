import os
import time
import json
import redis
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fyers_apiv3.FyersWebsocket import data_ws
from brokers.fyers.auth import load_token
from data.database import get_connection, get_fyers_symbol

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_KEY = "market_feed"
import pytz
IST = pytz.timezone('Asia/Kolkata')

class StreamProducer:
    def __init__(self, mode="LIVE", days=1, symbol="BANKNIFTY"):
        self.mode = mode
        self.days = days
        self.symbol = symbol
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)
        self.running = True

    def start(self):
        print(f"🚀 Starting Stream Producer Mode: {self.mode} (Days: {self.days})")
        if self.mode == "MOCK":
            self._run_mock_adversarial()
        else:
            self._run_fyers_socket()

    def _publish(self, tick):
        """Push tick to Redis Stream"""
        # ID=* means auto-generate ID
        self.r.xadd(STREAM_KEY, tick)
        # print(f"   -> Pub: {tick['ltp']}")

    def _run_fyers_socket(self):
        """Real Fyers Feed"""
        access_token = load_token()
        if not access_token:
            print("❌ No valid Fyers token. Run: python -m brokers.fyers.auth")
            return
        symbol = get_fyers_symbol(self.symbol)

        def on_message(message):
            if 'symbol' in message and message['symbol'] == symbol:
                self._publish({
                    'timestamp': str(datetime.now(IST)),
                    'symbol': message['symbol'],
                    'ltp': str(message.get('ltp')),
                    'open': str(message.get('open_price')),
                    'high': str(message.get('high_price')),
                    'low': str(message.get('low_price'))
                })

        fyers = data_ws.FyersDataSocket(
            access_token=access_token,
            log_path="logs",
            litemode=True,
            write_to_file=False,
            reconnect=True,
            on_message=on_message
        )
        fyers.connect()

    def _run_mock_adversarial(self):
        """
        Adversarial Replay:
        Splits a 5-min candle into micro-movements.
        Sequence: Open -> Wick (Adversarial) -> Consolidate -> Close
        """
        print("   🎭 Loaded Adversarial Mock Logic")
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        utc = pytz.timezone('UTC')

    def _run_mock_adversarial(self):
        """
        Adversarial Replay:
        Splits a 5-min candle into micro-movements.
        Sequence: Open -> Wick (Adversarial) -> Consolidate -> Close
        """
        print("   🎭 Loaded Adversarial Mock Logic")
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        utc = pytz.timezone('UTC')

        conn = get_connection()
        
        # 1. Get the last available timestamp in DB
        last_ts = conn.execute("SELECT MAX(timestamp) FROM candles_5min").fetchone()[0]
        if not last_ts:
            print("   ❌ No data in database!")
            return

        # 2. Calculate Start timestamp (Last TS - N Days)
        # We want full days, so let's normalize to midnight? 
        # Or just subtract 24h * Days. simple subtraction is robust enough for mock.
        start_ts = last_ts - timedelta(days=self.days)
        
        print(f"   📅 Replay Range: {start_ts} -> {last_ts} ({self.days} Days)")
        
        # 3. Fetch Candles in Range (Forward Chronological)
        full_symbol = get_fyers_symbol(self.symbol)
        query = "SELECT timestamp, open, high, low, close FROM candles_5min WHERE symbol = ? AND timestamp > ? ORDER BY timestamp ASC"
        rows = conn.execute(query, (full_symbol, start_ts)).fetchall()
        conn.close()
        
        if not rows:
            print(f"   ❌ No candles found for {full_symbol} in calculated range.")
            return

        print(f"   ✅ Loaded {len(rows)} candles for {full_symbol} replay.")

        symbol = full_symbol
        
        # Iterate Forward
        for ts, o, h, l, c in rows:
            if not self.running: break
            
            # Convert timestamp to IST if naive or UTC
            if ts.tzinfo is None:
                ts = utc.localize(ts)
            
            ts_ist = ts.astimezone(ist)
            
            print(f"   🕯️ Simulating Candle {ts_ist.strftime('%Y-%m-%d %H:%M:%S')} (O:{o} H:{h} L:{l} C:{c})")
            
            # Micro-ticks generation
            # 1. Open
            self._publish({'timestamp': str(ts_ist), 'symbol': symbol, 'ltp': str(o), 'open': str(o), 'high': str(h), 'low': str(l)})
            time.sleep(0.5)

            # 2. Adversarial Wick logic
            is_green = c > o
            
            if is_green:
                # Dip to Low first
                points = [
                     o - (o-l)*0.3, # 30% down
                     l,             # Touch Low
                     o + (c-o)*0.5, # Recover
                     c              # Close
                ]
            else:
                 # Pop to High first
                 points = [
                     o + (h-o)*0.3, # 30% up
                     h,             # Touch High
                     o - (o-c)*0.5, # Drop
                     c              # Close
                 ]

            for p in points:
                 tick = {
                     'timestamp': str(ts_ist), 
                     'symbol': symbol, 
                     'ltp': str(round(p, 2)),
                     'open': str(o),
                     'high': str(h),
                     'low': str(l)
                 }
                 self._publish(tick)
                 time.sleep(0.5) # Fast replay

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Run in Adversarial Mock Mode")
    parser.add_argument("--days", type=int, default=1, help="Number of days to simulate in Mock mode")
    parser.add_argument("--symbol", type=str, default="BANKNIFTY", help="Symbol to stream")
    args = parser.parse_args()
    
    producer = StreamProducer(mode="MOCK" if args.mock else "LIVE", days=args.days, symbol=args.symbol)
    producer.start()
