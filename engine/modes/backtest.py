"""
v2.9 Backtest Mode (Dimensional Engine)
Thin wrapper driving the 64D Atlas Strategy.
- Standard 5m/15m Tick Loop.
- Uses `DimensionalEngine` for all signals.
- Implements Transition Engine (Adaptive Exit) directly in the loop.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import pytz

from engine.modes.base_mode import BaseMode
from engine.journal import Journal
from brokers.simulator.broker import SimBroker

# v4.0 Engine
from engine.research_engine import ResearchEngine

# v2.8 Modules
from adapters.data_adapter import data_adapter
from config.config_loader import config
from atlas.state_logger import atlas_logger

# v2.8 Trade Engine
from trade import (
    trade_ledger, exit_engine, eod_processor, trade_reporter,
    create_lifecycle, ExitReason, ExitEvent
)
from trade.models import Trade, TradeStatus 

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)

# --- SCHEDULE CONSTANTS ---
TACTICAL_START_TIME = time(9, 15) # Start immediately
TACTICAL_END_TIME = time(15, 30)
EOD_TIME = time(15, 30)

class BacktestMode(BaseMode):
    def __init__(self, start_date, end_date, symbol="NIFTY", resolution="5", initial_balance=30000, chat_id=None, use_gpu: bool = False):
        self.chat_id = chat_id
        self.start_date = start_date
        self.end_date = end_date
        self.symbol = symbol
        self.resolution = resolution
        self.session_id = f"BACKTEST_ATLAS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 1. Infrastructure
        self.broker = SimBroker(initial_balance=initial_balance)
        self.journal = Journal(session_id=self.session_id)
        
        # Override trace_logger session_id for this session
        # 2. Research Engine (v4.0 Brain)
        self.use_gpu = use_gpu
        self.engine = ResearchEngine(use_gpu=use_gpu)
        
        # 3. Trade Engine (v2.8)
        self.lifecycle = create_lifecycle(self.session_id, self.broker, is_simulation=True)
        
        # 4. Daily State
        self.running = False
        self.today_bars = []
        self.daily_summaries = []
        self.daily_context = {} 
        self.equity_curve = [] # Time Series Tracker

        # Blackwell Persistence Cache (v4.4.2)
        self._batch_signals = None # Will store dict of timestamp -> regime info
        
    def start(self):
        """Run the Historical Backtest"""
        logger.info(f"📊 Starting Atlas Backtest: {self.start_date.date()} to {self.end_date.date()} (Session: {self.session_id})")
        
        # v4.4.2 Blackwell Persistence: Prime the entire range if using GPU
        if self.use_gpu:
            self._precompute_batch_features()

        self.journal.register_session(
            symbol=self.symbol,
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d')
        )
        
        self.running = True
        try:
            self._run_simulation()
        finally:
            # -------------------------------------------------------------
            # v6.2-SOVEREIGN EOD REPORTING
            # -------------------------------------------------------------
            
            # 1. Flush Logs
            atlas_logger.flush()

            # 2. Generate Session Report (PDF/Text)
            trade_reporter.generate_session_report(
                self.session_id, 
                self.daily_summaries,
                llm_client=None
            )
            
            # 3. Plot Equity Curve
            try:
                from tests.plot_equity import plot_equity_curve
                plot_equity_curve(self.session_id)
            except ImportError:
                pass
                
            logger.info(f"[BACKTEST] 🏁 Session {self.session_id} Complete.")

    def stop(self):
        self.running = False
        logger.info("🛑 Backtest Stopped")
        atlas_logger.flush()

    def _on_day_ended(self, ts, last_close):
        """Standard EOD Hook."""
        summary = eod_processor.end_of_day(
            self.lifecycle, last_close, ts,
            llm_client=None, # No LLM summary
            morning_plan={"primary_bias": "ATLAS", "reference_levels": {}},
            symbol=self.symbol,
            today_bars=self.today_bars
        )
        return summary

    def _resample_to_15m(self, df_5m):
        """Resample 5m DataFrame to 15m (Parent)"""
        if df_5m.empty: return pd.DataFrame()
        
        df = df_5m.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        
        agg_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
        
        # Check if we have context info to preserve? 
        # For now just OHLCV is needed for calculators
        
        df_15 = df.resample('15min').agg(agg_dict).dropna()
        df_15 = df_15.reset_index()
        return df_15

    def _precompute_batch_features(self):
        """
        Blackwell Persistence: Calculates ALL features for the entire session on GPU.
        Eliminates 93k PCIe transfers in the backtest loop.
        """
        logger.info("🧪 [BLACKWELL] Priming VRAM for session persistence...")
        
        # 1. Fetch entire historical range (+ warmup)
        warmup_start = self.start_date - timedelta(days=10) # Safe buffer for 200 bars
        # Extend end_date to include the full last day
        query_end = self.end_date + timedelta(days=1)
        
        from data.database import get_connection, get_fyers_symbol, IST
        conn = get_connection("trading.db")
        full_symbol = get_fyers_symbol(self.symbol)
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume 
            FROM candles_5min 
            WHERE symbol = '{full_symbol}' 
              AND timestamp BETWEEN '{warmup_start}' AND '{query_end}'
            ORDER BY timestamp ASC
        """
        logger.info(f"   [BLACKWELL] Querying range: {warmup_start} to {query_end}")
        df_all = pd.read_sql_query(query, conn)
        conn.close()
        
        if df_all.empty: return
        
        df_all['timestamp'] = pd.to_datetime(df_all['timestamp'], format='ISO8601', utc=True).dt.tz_convert(IST)
        
        # v6.3.8: Prune duplicates that may exist due to mixed timestamp formats in DB tail
        initial_len = len(df_all)
        df_all = df_all.drop_duplicates(subset=['timestamp'], keep='last')
        if len(df_all) < initial_len:
            logger.info(f"   [BLACKWELL] Pruned {initial_len - len(df_all)} duplicate bars from database.")
        
        from engine.features.calculators_gpu import AtlasFeaturesGPU
        from engine.features.physics_engine import PhysicsEngine
        
        # 2. Physics & Features (Bulk GPU)
        logger.info(f"   - Calculating Physics Context for {len(df_all)} bars...")
        df_5m_64d = AtlasFeaturesGPU.calculate_all(PhysicsEngine.add_context(df_all))
        
        # 15m Resample for Parent
        df_all_v = df_all.set_index('timestamp')
        df_15m = df_all_v.resample('15min').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna().reset_index()
        
        logger.info(f"   - Calculating Parent Context ({len(df_15m)} bars)...")
        df_15m_64d = AtlasFeaturesGPU.calculate_all(PhysicsEngine.add_context(df_15m))
        
        # 3. Regime Identification (Bulk GPU)
        # Use existing engine instance to avoid redundant 5-second model load
        regime_engine = self.engine.regime
        logger.info("   - Running Vectorized Cluster Projection (Bulk Identification)...")
        regime_labels = regime_engine.identify_clusters_batch(df_5m_64d, df_15m_64d)
        
        # 4. Persistence Map (Dictionary for O(1) lookup during sim)
        # Store as dict: timestamp -> {c15, c5, features}
        # We also want the raw feature dict for trace/monitoring
        logger.info("   - Building Persistence Map...")
        
        # Merge regimes into 5m features
        df_final = pd.merge(df_5m_64d, regime_labels, on='timestamp', how='left').fillna(0)
        
        # Convert to high-speed lookup (STRING KEYS for Safety)
        df_final['ts_key'] = df_final['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        self._batch_signals = df_final.set_index('ts_key').to_dict('index')
        logger.info(f"🚀 [BLACKWELL] Persistence Engine Ready. Cached {len(self._batch_signals)} signals.")

    def on_tick(self, message):
        """
        Handles a single tick (5-min candle).
        1. Build DataFrames.
        2. Call DimensionalEngine.
        3. Execute Trades.
        """
        ts = message['timestamp']
        ts_str = ts.strftime('%H:%M:%S')
        
        # Accumulate Bar
        bar = {
            'ts': ts.strftime('%Y-%m-%d %H:%M:%S'),
            'o': message['open'], 'h': message['high'], 'l': message['low'], 'c': message['close'], 'v': message['volume']
        }
        self.today_bars.append(bar)
        
        # Check if in trade for UPnL logging
        current_trade = trade_ledger.get_open_position()
        
        # 1. Blackwell Persistence Check (v4.4.2)
        # Use String Keys to bypass Timezone Object Hell
        ts_key = ts.strftime('%Y-%m-%d %H:%M:%S')
        
        if self._batch_signals and ts_key in self._batch_signals:
            df_5m, df_15m = None, None # Skip heavy DF building
            cached = self._batch_signals[ts_key]
            # Form standard analysis result to bypass ResearchEngine compute
            analysis = {
                'regime_id': f"{int(cached['c15'])}:{int(cached['c5'])}",
                'features_5m': cached, # Contains all X01-X64
                'decision': None, # RiskGuard must be called in real-time (path dependent)
                'timestamp': ts
            }
            
            # Identify Clusters (Extracted for RiskGuard)
            c15, c5 = int(cached['c15']), int(cached['c5'])
            regime_id = analysis['regime_id']
            
            # Registry Lookup
            alpha_state = self.engine.registry.get_alpha_state(c15, c5, cutoff_time=ts)
            
            # RiskGuard Decision (MUST be sequential)
            # Ensure daily counters are reset if day changed (Backtest Specific Patch)
            self.engine.update_daily_state(ts)
            
            decision = self.engine.risk_guard.validate_alpha(
                alpha_state, message['close'], current_time=ts,
                daily_trade_count=self.engine.daily_count,
                consecutive_losses=self.engine.daily_losses
            )
            
            analysis['decision'] = decision
            wr = alpha_state.get('win_rate', 0.0)
            res_color = "\033[92m" if decision['action'] != "HOLD" else "\033[0m"
            analysis['log_str'] = f"[ATLAS-GPU] 🧠 {ts_str} | Price: {message['close']:,.2f} | Regime: {regime_id} | WR: {wr:.2f} | Action: {res_color}{decision['action']}\033[0m"
            analysis['alpha_state'] = alpha_state
            
        else:
            # Fallback to standard flow (CPU or Live data)
            # 1. Prepare DataFrames for Engine
            # Retrieve historical context (list of dicts)
            hist_5min = self.daily_context.get('last_5min', [])
            
            # Today's bars (Normalize keys to match hist_5min)
            from data.database import IST
            today_bars_std = []
            for b in self.today_bars:
                dt = pd.to_datetime(b['ts'])
                if dt.tzinfo is None:
                    dt = dt.tz_localize('Asia/Kolkata') # Assume IST for backtest local strings
                today_bars_std.append({
                    'timestamp': dt,
                    'open': b['o'], 'high': b['h'], 'low': b['l'], 'close': b['c'], 'volume': b['v']
                })

            # Combine: History + Today (Full Series)
            full_data = hist_5min + today_bars_std
            
            df_5m = pd.DataFrame(full_data)
            df_5m = df_5m.drop_duplicates('timestamp').sort_values('timestamp')
            
            # Resample for Parent (15m Hierarchy)
            df_15m = self._resample_to_15m(df_5m)

            try:
                analysis = self.engine.process_tick(df_5m, df_15m, silent=True)
            except Exception as e:
                logger.error(f"   [ATLAS] ❌ Inference Error: {e}")
                return

        decision = analysis.get('decision', {})
        signal = decision.get('action', 'HOLD')
        regime_id = analysis.get('regime_id', 'UNKNOWN')
        log_str = analysis.get('log_str', '')

        # 3. UNIFIED LOGGING (Continuous Time Series)
        # Add Balance Always
        cur_bal = self.broker.get_balance()
        
        # Calculate UPnL for Open Equity
        upnl_rupees = 0.0
        upnl_pts = 0.0
        
        if current_trade:
             # Calculate UPnL
             price = message['close']
             upnl_pts = (price - current_trade.entry_price) if current_trade.direction == "CALL" else (current_trade.entry_price - price)
             
             # Calculate Rupee Value (using delta/multiplier check, or standard lot)
             # Config checks
             delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
             multiplier = current_trade.quantity * delta
             upnl_rupees = upnl_pts * multiplier

             color = "\033[92m" if upnl_pts >= 0 else "\033[91m"
             # Append UPnL to the engine's log_str
             log_str += f" | {color}UPnL: {upnl_pts:+.1f}\033[0m"
        
        # log_str += f" | Bal: {cur_bal:,.0f}" # Balance is closed equity
        # logger.info(f"[TRACE-LINEAR] {ts.strftime('%Y-%m-%d')} | {log_str}")
        
        # --- EQUITY CURVE RECORDER (User Request) ---
        total_equity = cur_bal + upnl_rupees
        self.equity_curve.append({
            'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'), # Use string for CSV or object? Object better for DataFrame
            'equity': total_equity,
            'balance': cur_bal,
            'upnl': upnl_rupees
        })
        
        # 4. TRADE MANAGEMENT (Transition Engine)
        if current_trade:
            trade = current_trade
            trade.duration_bars = getattr(trade, 'duration_bars', 0) + 1 # v4.3 Time Decay Tracker
            
            # MFE/MAE Tracking (v4.0 Performance Fix)
            trade_ledger.update_price_extremes(trade.trade_id, message['close'])
            trade_ledger.update_price_extremes(trade.trade_id, message['high'])
            trade_ledger.update_price_extremes(trade.trade_id, message['low'])

            # Live Update of MFE/MAE on Trade Object (Critical for Stale Exit)
            high = trade_ledger.daily_high_prices.get(trade.trade_id, trade.entry_price)
            low = trade_ledger.daily_low_prices.get(trade.trade_id, trade.entry_price)
            
            if trade.direction == "CALL":
                trade.mfe = high - trade.entry_price
                trade.mae = trade.entry_price - low
            else:
                trade.mfe = trade.entry_price - low
                trade.mae = high - trade.entry_price

            # Multiplier Constants
            delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
            multiplier = trade.quantity * delta

            # Break-Even Trail Logic (User Request Check)
            be_cfg = config.get('RISK_RULES.break_even_trail', {})
            if be_cfg.get('enabled', False):
                trigger = be_cfg.get('trigger_mfe', 25.0)
                offset = be_cfg.get('offset', 0.0)
                
                # If current MFE exceeds trigger, move SL to Entry + Offset
                if trade.mfe >= trigger:
                    new_sl = trade.entry_price + offset if trade.direction == "CALL" else trade.entry_price - offset
                    
                    # Logic to ensure we don't relax the stop (only tighten)
                    if trade.direction == "CALL":
                        if new_sl > trade.sl_price:
                            trade.sl_price = new_sl
                            # logger.info(f"   [RISK] 🛡️ BE Triggered (MFE {trade.mfe:.1f} > {trigger}). SL -> {new_sl}")
                    else:
                        if new_sl < trade.sl_price:
                            trade.sl_price = new_sl
                            
            # 4. DETERMINISTIC SAFETY (SL/Target Check) - Priority v4.4
            exit_price = None
            exit_reason = None

            if trade.direction == "CALL":
                 if message['low'] <= trade.sl_price:
                      exit_price = trade.sl_price
                      exit_reason = ExitReason.SL
                 elif message['high'] >= trade.target_price:
                      exit_price = trade.target_price
                      exit_reason = ExitReason.TGT
            else: # PUT
                 if message['high'] >= trade.sl_price:
                      exit_price = trade.sl_price
                      exit_reason = ExitReason.SL
                 elif message['low'] <= trade.target_price:
                      exit_price = trade.target_price
                      exit_reason = ExitReason.TGT

            if exit_price:
                pts = (exit_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - exit_price)
                pnl_rupees = pts * multiplier
                exit_v = ExitEvent(
                    trade_id=trade.trade_id, exit_time=ts, exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_points=pts, pnl_rupees=pnl_rupees, bars_held=trade.duration_bars, mfe=trade.mfe, mae=trade.mae
                )
                self.lifecycle.close_trade(trade.trade_id, exit_v)
                
                if pts < 0: self.engine.daily_losses += 1
                else: self.engine.daily_losses = 0
                return

            # 5. ADAPTIVE EXIT (Transition Monitor: Regime Decay / Trap)
            monitor = self.engine.process_in_trade_tick(df_5m, df_15m, trade, pre_computed_result=analysis, current_price=message['close'])
            if monitor.get('in_trade_action') == "EXIT":
                pts = (message['close'] - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - message['close'])
                pnl_rupees = pts * multiplier
                
                # v4.4 Differentiate Exit Reasons
                reason_str = monitor.get('reason', "")
                exit_reason = ExitReason.INVALIDATION
                if "Stale" in reason_str:
                    exit_reason = ExitReason.STALE
                elif "Jitter" in reason_str:
                    exit_reason = ExitReason.JITTER
                
                exit_event = ExitEvent(
                    trade_id=trade.trade_id, exit_time=ts, exit_price=message['close'],
                    exit_reason=exit_reason,
                    pnl_points=pts, pnl_rupees=pnl_rupees, bars_held=trade.duration_bars, mfe=trade.mfe, mae=trade.mae
                )
                self.lifecycle.close_trade(trade.trade_id, exit_event)
                
                # v4.4 Churn Brake Tracking
                if pts < 0:
                    self.engine.daily_losses += 1
                else:
                    self.engine.daily_losses = 0
                return

            # SL/Target Check (Deterministic)
            pts = 0.0
            exit_price = None
            exit_reason = None

            if trade.direction == "CALL":
                 if message['low'] <= trade.sl_price:
                     exit_price = trade.sl_price
                     exit_reason = ExitReason.SL
                 elif message['high'] >= trade.target_price:
                     exit_price = trade.target_price
                     exit_reason = ExitReason.TGT
            else: # PUT
                 if message['high'] >= trade.sl_price:
                     exit_price = trade.sl_price
                     exit_reason = ExitReason.SL
                 elif message['low'] <= trade.target_price:
                     exit_price = trade.target_price
                     exit_reason = ExitReason.TGT


        
        else:
            # 4. ENTRY LOGIC
            if signal in ["BUY_CALL", "BUY_PUT"]:
                # Single Trade Constraint (Authoritative Gate)
                if trade_ledger.has_open_position(self.symbol):
                    return

                # Unified Context Extraction (v4.6)
                ctx = self.engine.get_trade_context(analysis, self.symbol, message['close'], mode="BACKTEST")
                
                # Propose + Open sequence (State Machine)
                trade = self.lifecycle.propose_trade(decision, ctx, ts)
                trade.metadata['is_fallback'] = decision.get('is_fallback', False)
                self.lifecycle.open_trade(trade)
                self.engine.daily_count += 1  # v4.3 Daily Limit Tracker
            
            elif signal == "HOLD" and any(k in decision.get('reason', "") for k in ["Risk", "Brake", "Sterilization", "Darwinian", "Probation"]):
                # v4.4 Tracking Counterfactuals (Blocked signals)
                # If it's a HOLD due to risk, but we have a bias (BUY_CALL/PUT) in alpha_state
                alpha_bias = analysis.get('alpha_state', {}).get('bias', 'NONE')
                if alpha_bias in ["LONG", "SHORT"]:
                    ghost_action = "BUY_CALL" if alpha_bias == "LONG" else "BUY_PUT"
                    ghost_decision = decision.copy()
                    ghost_decision['action'] = ghost_action
                    
                    # Unified Context Extraction (v4.6)
                    ctx = self.engine.get_trade_context(analysis, self.symbol, message['close'], mode="BACKTEST")
                    
                    # Propose as Counterfactual
                    trade = self.lifecycle.propose_trade(ghost_decision, ctx, ts)
                    trade.is_counterfactual = True
                    trade.block_reason = decision.get('reason')
                    # We 'Open' and 'Close' it immediately in simulation logic? 
                    # No, we just need the record for the report. 
                    # Actually, to get 'Counterfactual PnL', we'd need to track its lifecycle.
                    # For now, just recording the rejection count and reason is the priority.
                    self.lifecycle.open_trade(trade)

    def _run_simulation(self):
        current_date = self.start_date
        
        # Reset entire ledger only once at session start
        trade_ledger.reset()
        
        while current_date <= self.end_date and self.running:
            day_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"🌞 Simulating Day: {day_str} | Current Balance: ₹{self.broker.get_balance():,.0f}")
            
            # 1. Fetch Data
            ticks = data_adapter.fetch_data_for_day(current_date, self.symbol, self.resolution)
            if ticks.empty:
                logger.info("   ⚠️ No data. Skipping.")
                current_date += timedelta(days=1)
                continue
                
            # 2. Daily Context (Warmup History - strictly pre-market)
            from data.database import fetch_context_data
            # Force midnight normalization to prevent lookahead if current_date has time
            warmup_cutoff = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
            self.daily_context = fetch_context_data(warmup_cutoff, self.symbol, resolution=self.resolution)
            
            self.today_bars = []
            # trade_ledger.reset() -- REMOVED: Preserve trades across days for session report
            
            last_close = 0
            eod_done = False
            
            for i, row in ticks.iterrows():
                if not self.running: break
                
                ts = row['timestamp']
                last_close = row['close']
                
                tick_msg = {
                    'timestamp': ts,
                    'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'], 'volume': row['volume']
                }
                
                if ts.time() >= EOD_TIME:
                     summary = self._on_day_ended(ts, last_close)
                     if summary: self.daily_summaries.append(summary)
                     eod_done = True
                     break
                     
                self.on_tick(tick_msg)
                
            if not eod_done and not ticks.empty:
                 summary = self._on_day_ended(ticks.iloc[-1]['timestamp'], last_close)
                 if summary: self.daily_summaries.append(summary)
            
            current_date += timedelta(days=1)




