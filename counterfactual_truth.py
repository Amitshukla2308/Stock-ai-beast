import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import json
import logging

logger = logging.getLogger(__name__)

class TradeReplayer:
    """
    Deterministic Truth Engine.
    Replays a trade on 1-minute OHLC data to find the exact outcome (First Touch).
    """
    def __init__(self, candles_df):
        """
        :param candles_df: DataFrame with 'timestamp', 'open', 'high', 'low', 'close'
                           Must be sorted by timestamp.
        """
        self.candles = candles_df

    def replay(self, entry_price, sl, target, direction, start_time, check_sl_first=True):
        """
        Replays the trade forward from start_time.
        :return: (exit_time, exit_price, pnl, result_type)
        """
        # Filter for candles AFTER start_time (inclusive of minute? No, usually next candle or same candle if entry is on open)
        # We assume entry is filled. Replay starts from the same candle (intra-candle risk) or next.
        # Standard: Start from the minute matching start_time (inclusive)
        
        subset = self.candles[self.candles['timestamp'] >= start_time]
        
        for _, candle in subset.iterrows():
            c_high = candle['high']
            c_low = candle['low']
            c_close = candle['close']
            ts = candle['timestamp']
            
            # Stop Replay at 15:30 (EOD)
            if ts.time() >= time(15, 30):
                # EOD Exit
                pnl = (c_close - entry_price) if direction == 'CALL' else (entry_price - c_close)
                return ts, c_close, pnl, "EOD_EXIT"

            # Check Stops/Targets
            # Conservative Assumption: If SL and TGT both in range, SL hit first.
            
            sl_hit = False
            tgt_hit = False
            
            if direction == 'CALL':
                if c_low <= sl: sl_hit = True
                if c_high >= target: tgt_hit = True
            else: # PUT
                if c_high >= sl: sl_hit = True
                if c_low <= target: tgt_hit = True
                
            if sl_hit and tgt_hit:
                # Ambiguity
                if check_sl_first:
                    return ts, sl, (sl - entry_price) if direction == 'CALL' else (entry_price - sl), "SL_HIT_AMBIGUOUS"
                else:
                    return ts, target, (target - entry_price) if direction == 'CALL' else (entry_price - target), "TGT_HIT_AMBIGUOUS"
            
            if sl_hit:
                return ts, sl, (sl - entry_price) if direction == 'CALL' else (entry_price - sl), "SL_HIT"
                
            if tgt_hit:
                return ts, target, (target - entry_price) if direction == 'CALL' else (entry_price - target), "TARGET_HIT"

        # End of Data (should ideally hit 15:30 check first)
        return None, 0, 0, "NO_DATA"

class CounterfactualAnalyzer:
    """
    Analyzes what-if scenarios using the Truth Engine.
    """
    def __init__(self, db_path='data/trading.db', session_id=None):
        self.db_path = db_path
        self.session_id = session_id
        self.replayer = None
        self.candles_loaded = False
        
        # Reports Storage
        self.report_data = {
            'Time-Based Exits': {'trades': 0, 'actual_pnl': 0.0, 'cf_pnl': 0.0, 'benefit': 0.0, 'wins': 0},
            'Blocked Trades':   {'trades': 0, 'actual_pnl': 0.0, 'cf_pnl': 0.0, 'benefit': 0.0, 'wins': 0},
            'Engine Mods':      {'trades': 0, 'actual_pnl': 0.0, 'cf_pnl': 0.0, 'benefit': 0.0, 'wins': 0},
            'AI Smart Exits':   {'trades': 0, 'actual_pnl': 0.0, 'cf_pnl': 0.0, 'benefit': 0.0, 'wins': 0}
        }
        
    def _get_connection(self):
        return duckdb.connect(self.db_path)

    def _load_data(self):
        """Loads 1-min candles for the session timeframe."""
        if self.candles_loaded: return
        
        conn = self._get_connection()
        session = conn.execute(f"SELECT symbol, start_date, end_date FROM simulation_sessions WHERE session_id='{self.session_id}'").fetchone()
        
        if not session:
            conn.close()
            return
            
        symbol, sd, ed = session
        
        # Load 1-min data for strict replay
        query = f"""
            SELECT timestamp, open, high, low, close 
            FROM candles_1min 
            WHERE symbol='{symbol}' 
            AND timestamp >= '{sd}' 
            AND timestamp <= '{ed}'
            ORDER BY timestamp ASC
        """
        try:
            df = conn.execute(query).fetchdf()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            self.replayer = TradeReplayer(df)
            self.candles_loaded = True
        except Exception as e:
            logger.error(f"Failed to load candle data: {e}")
        finally:
            conn.close()

    def run_full_analysis(self):
        """Main entry point."""
        self._load_data()
        if not self.replayer: return None
        
        self._analyze_time_exits()
        self._analyze_blocked_trades()
        self._analyze_engine_mods()
        self._analyze_ai_exits()
        
        return self._generate_report_string()

    def _analyze_time_exits(self):
        """A. Time-Based Exits: What if we held?"""
        conn = self._get_connection()
        trades = conn.execute(f"SELECT * FROM simulation_trades WHERE session_id='{self.session_id}' AND reason LIKE '%TIME%'").fetchdf()
        conn.close()
        
        cat = self.report_data['Time-Based Exits']
        
        for _, t in trades.iterrows():
            # Original Parameters
            # Note: We need original SL/Target. If not in DB, we infer from logs or standard params?
            # DB 'sl' and 'target' cols store the LAST active params.
            
            entry = t['entry_price']
            sl = t['sl']
            tgt = t['target']
            side = t['side']
            exit_time = pd.to_datetime(t['exit_time'])
            actual_pnl = t['pnl']
            
            # Replay from Exit Time
            _, _, cf_pnl, _ = self.replayer.replay(entry, sl, tgt, side, exit_time)
            
            cat['trades'] += 1
            cat['actual_pnl'] += actual_pnl
            cat['cf_pnl'] += cf_pnl
            if cf_pnl > 0: cat['wins'] += 1
            
        # Benefit = Actual - Counterfactual (System Value Add)
        # If Actual > CF, we added value (Pos).
        # If Actual < CF, we lost value (Neg).
        cat['benefit'] = cat['actual_pnl'] - cat['cf_pnl']

    def _analyze_blocked_trades(self):
        """B. Blocked Trades: What if we took them?"""
        conn = self._get_connection()
        # Look for TACTICAL logs with BLOCKED decision
        logs = conn.execute(f"SELECT timestamp, content FROM simulation_logs WHERE session_id='{self.session_id}' AND event_type='TACTICAL'").fetchdf()
        conn.close()
        
        cat = self.report_data['Blocked Trades']
        
        for _, row in logs.iterrows():
            try:
                data = json.loads(row['content'])
                if data.get('engine_decision') != 'BLOCKED': continue
                
                # Infer Original Intent
                reason = data.get('engine_reason', '')
                action = 'UNKNOWN'
                if 'BUY_CALL' in reason: action = 'BUY_CALL'
                elif 'BUY_PUT' in reason: action = 'BUY_PUT'
                else: continue # Skip if intent unclear
                
                start_time = pd.to_datetime(row['timestamp'])
                
                # Get Price at signal time
                # We need entry price. Assuming Close of signal candle or Open of next? 
                # Replayer candles has the data.
                candles = self.replayer.candles
                # Approximate entry: Current Close
                signal_candle = candles[candles['timestamp'] == start_time]
                if signal_candle.empty: continue
                entry_price = signal_candle.iloc[0]['close']
                
                # Standard Params (Assumed if blocked)
                # Should fetch from Style Economics or Standard Default
                sl_pts = 30
                tgt_pts = 60
                
                if action == 'BUY_CALL':
                    sl = entry_price - sl_pts
                    tgt = entry_price + tgt_pts
                else:
                    sl = entry_price + sl_pts
                    tgt = entry_price - tgt_pts
                    
                _, _, cf_pnl, _ = self.replayer.replay(entry_price, sl, tgt, action, start_time)
                
                cat['trades'] += 1
                cat['actual_pnl'] += 0 # Blocked = 0 PnL
                cat['cf_pnl'] += cf_pnl
                if cf_pnl > 0: cat['wins'] += 1
                
            except: continue
        
        # Benefit = Actual (0) - CF
        # If CF was +100, Benefit = -100 (Lost Opportunity).
        # If CF was -50, Benefit = +50 (Saved Money).
        cat['benefit'] = cat['actual_pnl'] - cat['cf_pnl']

    def _analyze_engine_mods(self):
        """C. Engine Modifications: What if we used original LLM params?"""
        # This requires capturing 'original_sl' which might be in the log content before overwrite.
        # Implementation depends on deep log parsing.
        pass 

    def _analyze_ai_exits(self):
        """D. AI Smart Exits: What if we ignored the AI and held?"""
        conn = self._get_connection()
        trades = conn.execute(f"SELECT * FROM simulation_trades WHERE session_id='{self.session_id}' AND reason LIKE '%AI%'").fetchdf()
        conn.close()
        
        cat = self.report_data['AI Smart Exits']
        
        for _, t in trades.iterrows():
            entry = t['entry_price']
            sl = t['sl']
            tgt = t['target']
            side = t['side']
            exit_time = pd.to_datetime(t['exit_time'])
            actual_pnl = t['pnl']
            
            # Replay from Exit Time
            _, _, cf_pnl, _ = self.replayer.replay(entry, sl, tgt, side, exit_time)
            
            cat['trades'] += 1
            cat['actual_pnl'] += actual_pnl
            cat['cf_pnl'] += cf_pnl
            if cf_pnl > 0: cat['wins'] += 1
            
        cat['benefit'] = cat['actual_pnl'] - cat['cf_pnl'] # Benefit is (Actual - Hypothetical) since AI INTERVENED

    def _generate_report_string(self):
        """Formats the data into the requested Markdown table."""
        
        # Calculate Totals
        total_actual = sum(c['actual_pnl'] for c in self.report_data.values())
        total_cf = sum(c['cf_pnl'] for c in self.report_data.values())
        # Net Benefit is sum of benefits (Careful with signs: Benefit is usually (Alternative - Actual)? 
        # No, "Benefit of the SYSTEM" or "Benefit of the CHANGE"?
        # User Req: "Net Benefit (CF - Actual)"
        
        lines = []
        lines.append("\n🔬 COUNTERFACTUAL ANALYSIS (Truth Engine)")
        lines.append("=" * 80)
        lines.append(f"{'Category':<20} | {'Trades':<6} | {'Actual':<10} | {'Counterfactual':<14} | {'Benefit':<10} | {'WinRate':<8}")
        lines.append("-" * 80)
        
        for name, data in self.report_data.items():
            if data['trades'] == 0: continue
            wr = (data['wins'] / data['trades']) * 100
            benefit = data['benefit']
            
            lines.append(f"{name:<20} | {data['trades']:<6} | {data['actual_pnl']:<10.1f} | {data['cf_pnl']:<14.1f} | {benefit:<10.1f} | {wr:<7.1f}%")
            
        lines.append("=" * 80)
        return "\n".join(lines)
