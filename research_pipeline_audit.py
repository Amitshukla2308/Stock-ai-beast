
import logging
import json
from datetime import datetime, timedelta
import pandas as pd
from engine.research_engine import ResearchEngine
from data.database import fetch_context_data, get_connection, IST, UTC
from brain.llm_client import LLMClient

# Setup logging to console
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def run_audit(target_date_str="2026-01-16", symbol="NIFTY"):
    print(f"\n{'='*80}")
    print(f"🔍 RESEARCH PIPELINE AUDIT: {target_date_str} | {symbol}")
    print(f"{'='*80}\n")

    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    
    # 1. Fetch Morning Context
    print(f"--- 1. MORNING CONTEXT (09:15) ---")
    morning_ts = target_date.replace(hour=9, minute=15)
    context = fetch_context_data(morning_ts, symbol)
    
    print(f"Daily 3 Bars: {len(context.get('daily_3', []))}")
    print(f"Warmup 15-min Bars: {len(context.get('last_15min', []))}")
    print(f"VIX Spot: {context.get('vix_spot')}")
    
    # 2. Mock a Plan (like Morning Brief) or use fallbacks
    plan = {
        "primary_bias": "NEUTRAL",
        "reference_levels": {
            "pivot": 24000,
            "support": 23900,
            "resistance": 24100
        }
    }
    
    # 3. Simulate Ticks throughout the day
    engine = ResearchEngine(llm_client=LLMClient())
    
    # Use a separate read-only connection for ticks to avoid locks
    try:
        db_path = "data/trading_audit.db"
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        ticks_query = f"""
            SELECT timestamp, open, high, low, close, volume 
            FROM candles_1min 
            WHERE symbol LIKE '%{symbol}%' 
              AND date(timestamp) = '{target_date_str}'
            ORDER BY timestamp ASC
        """
        ticks_df = pd.read_sql_query(ticks_query, conn)
        conn.close()
    except Exception as e:
        print(f"❌ Read-Only Connection Failed: {e}. Falling back to standard.")
        conn = get_connection()
        ticks_query = f"""
            SELECT timestamp, open, high, low, close, volume 
            FROM candles_1min 
            WHERE symbol LIKE '%{symbol}%' 
              AND date(timestamp) = '{target_date_str}'
            ORDER BY timestamp ASC
        """
        ticks_df = pd.read_sql_query(ticks_query, conn)
        conn.close()
    
    if ticks_df.empty:
        print(f"❌ No ticks found for {target_date_str}")
        return

    print(f"Found {len(ticks_df)} 1-min ticks. Simulating 5-min aggregation...")

    today_bars = []
    
    # Pick a few specific times to audit: 09:30, 10:15, 12:00
    audit_times = ["09:30:00", "10:15:00", "12:00:00", "14:30:00"]
    
    for i, row in ticks_df.iterrows():
        ts_utc = datetime.fromisoformat(row['timestamp'])
        ts_ist = ts_utc.replace(tzinfo=UTC).astimezone(IST)
        ts_str = ts_ist.strftime('%H:%M:%S')
        
        # Simple 5-min aggregation mock (usually handled by BacktestMode)
        if i % 5 == 0:
            bar = {
                'ts': ts_ist.strftime('%Y-%m-%d %H:%M:%S'),
                'o': row['open'], 'h': row['high'], 'l': row['low'], 'c': row['close'], 'v': row['volume']
            }
            today_bars.append(bar)

        if ts_ist.strftime('%H:%M:%S') in audit_times:
            print(f"\n>>> AUDITING TICK: {ts_ist.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Construct the tick packet exactly as BacktestMode does
            tick_packet = {
                'timestamp': ts_ist,
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume'],
                'symbol': symbol,
                'time_str': ts_ist.strftime('%H:%M:%S'),
                'today_5min': today_bars,
                'last_15min': context.get('last_15min', []) + today_bars,
                'daily_3': context.get('daily_3', []),
                'vix': context.get('vix_spot', 15.0)
            }
            
            # Run through Research Engine
            # allow_llm=False to avoid unwanted API calls during logic audit
            try:
                result = engine.process_tick(tick_packet, plan, allow_llm=False)
                enrich = result.get('enrichment', {})
                
                print(f"   [ENRICH] ATR: {enrich.get('atr')} | Price: {enrich.get('price')}")
                print(f"   [ENRICH] OR Range: {enrich.get('or_range')} | Established: {enrich.get('or_established')}")
                print(f"   [ENRICH] TER: {enrich.get('trend_efficiency')} | Regime: {enrich.get('trend_regime')}")
                print(f"   [ENRICH] Loc: {enrich.get('location_class')} | RegimeMomentum: {enrich.get('regime_momentum')}")
                
                if enrich.get('atr') == 0 or enrich.get('atr') == 15.0:
                    print(f"   ⚠️ WARNING: ATR is {enrich.get('atr')} (Default/Zero)")
                if enrich.get('or_range') == 0 and ts_ist.hour >= 10:
                    print(f"   ⚠️ WARNING: OR Range is 0 after 10:00")
                
            except Exception as e:
                print(f"   ❌ Engine Error: {e}")

if __name__ == "__main__":
    import sqlite3
    import os
    # Copy DB to bypass locks
    try:
        if os.path.exists("data/trading.db"):
            import shutil
            shutil.copy2("data/trading.db", "data/trading_audit.db")
        
        db_path = "data/trading_audit.db"
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dates = conn.execute("SELECT DISTINCT date(timestamp) FROM candles_1min UNION SELECT DISTINCT date(timestamp) FROM candles_5min ORDER BY 1 DESC LIMIT 3").fetchall()
        conn.close()
        
        if dates:
            for d in dates:
                run_audit(d[0])
        else:
            print("❌ Database appears empty.")
    except Exception as e:
        import traceback
        print(f"❌ Initial Date Check Failed: {e}")
        traceback.print_exc()
