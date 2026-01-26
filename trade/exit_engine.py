"""
Trade Engine v2.8: Exit Engine
This is where exits ACTUALLY happen. Runs every candle.
SL/TGT/Time/Invalidation logic lives here. Not in backtest.py. Not in executor.
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from trade.models import Trade, ExitEvent, ExitReason
from trade.ledger import trade_ledger
from config.config_loader import config
from engine.comm import emit_telegram_signal

logger = logging.getLogger(__name__)


class ExitEngine:
    """
    Checks for exit conditions on every candle.
    Returns exit events to be processed by lifecycle.
    """
    
    def __init__(self):
        self.bar_counters: Dict[str, int] = {}  # trade_id -> bars since entry
    
    def check_exits(self, tick: Dict[str, Any], intelligence_context: Optional[Dict[str, Any]] = None) -> List[ExitEvent]:
        """
        Main entry point. Called every candle.
        Returns list of exit events.
        
        Args:
            tick: generic tick dict
            intelligence_context: Dict containing 'regime', 'd2_prob', etc. (SPEC-002)
        """
        exit_events = []
        
        timestamp = tick.get('timestamp')
        current_price = tick.get('close', 0)
        candle_high = tick.get('high', current_price)
        candle_low = tick.get('low', current_price)
        candle_open = tick.get('open', current_price)
        
        # Iterate over open positions
        for symbol, trade in list(trade_ledger.open_positions.items()):
            # Skip same-candle checks
            if trade.entry_time == timestamp:
                continue
            
            # Increment bar counter
            self.bar_counters[trade.trade_id] = self.bar_counters.get(trade.trade_id, 0) + 1
            bars_held = self.bar_counters[trade.trade_id]
            trade.bars_held = bars_held # Sync to trade object
            
            # Update MFE/MAE tracking
            trade_ledger.update_price_extremes(trade.trade_id, candle_high)
            trade_ledger.update_price_extremes(trade.trade_id, candle_low)
            
            # Recalculate basic PnL/MFE for Logic
            pnl_curr = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
            high = trade_ledger.daily_high_prices.get(trade.trade_id, trade.entry_price)
            low = trade_ledger.daily_low_prices.get(trade.trade_id, trade.entry_price)
            
            if trade.direction == "CALL":
                mfe = high - trade.entry_price
            else:
                mfe = trade.entry_price - low
            
            trade.mfe = mfe # Sync for accuracy
                
            # --- SPEC-002 EDGE DEATH TRACKING ---
            if intelligence_context:
                is_alive = self._check_edge_alive(trade, intelligence_context, pnl_curr)
                if not is_alive and trade.pnl_edge_death is None:
                    # Capture Edge Death Event
                    trade.pnl_edge_death = pnl_curr
                    trade.edge_death_bar = bars_held
                    logger.debug(f"💀 Edge Died for {trade.trade_id} @ Bar {bars_held} | PnL {pnl_curr:.1f}")
                    emit_telegram_signal("EDGE_DEATH", {
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "pnl": f"{pnl_curr:.1f}",
                        "reason": "Edge Validity Check Failed"
                    })
                    
            # Check exit conditions
            exit_event = self._check_trade_exit(
                trade, timestamp, current_price, candle_high, candle_low, candle_open, bars_held,
                intelligence_context
            )
            
            if exit_event:
                exit_events.append(exit_event)
                # Clean up bar counter
                self.bar_counters.pop(trade.trade_id, None)
                
                # Notify Exit Trigger
                emit_telegram_signal("EXIT_TRIGGER", {
                    "trade_id": trade.trade_id,
                    "symbol": trade.symbol,
                    "reason": exit_event.exit_reason.value,
                    "price": exit_event.exit_price,
                    "pnl": f"{exit_event.pnl_points:.1f}",
                    "etd": f"{exit_event.etd:.1f}",
                    "bars": bars_held
                })
            else:
                # TRADE UPDATE: Log status while active
                delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
                unrealized_rupees = pnl_curr * delta * trade.quantity
                mae = (trade.entry_price - low) if trade.direction == "CALL" else (high - trade.entry_price)
                
                # Color logic
                C_RESET = "\033[0m"
                C_PNL = "\033[92m" if pnl_curr >= 0 else "\033[91m" # Green/Red
                C_HEADER = "\033[96m" # Cyan
                C_DATA = "\033[93m" # Yellow
                C_DIM = "\033[90m"
                
                edge_status = f"{C_PNL}ALIVE{C_RESET}" if (trade.pnl_edge_death is None) else f"{C_DIM}DEAD{C_RESET}"
                
                log_msg = f"{C_HEADER}[UNREALIZED_PNL]{C_RESET} Bars={C_DATA}{bars_held}{C_RESET} | PnL={C_PNL}{pnl_curr:+.1f}pts (₹{unrealized_rupees:+.0f}){C_RESET} | MFE={mfe:+.1f} | Edge:{edge_status} | Close={current_price:.1f}"
                logger.info(log_msg)
                
                # Telegram Heartbeat
                emit_telegram_signal("TRADE_MONITOR", {
                    "trade_id": trade.trade_id,
                    "symbol": trade.symbol,
                    "bars": bars_held,
                    "pnl": f"{pnl_curr:.1f}",
                    "mfe": f"{mfe:.1f}",
                    "edge": "ALIVE" if trade.pnl_edge_death is None else "DEAD"
                })
        
        return exit_events
    
    def _check_edge_alive(self, trade: Trade, context: Dict[str, Any], current_pnl: float) -> bool:
        """
        Evaluate if the Alpha Edge is still valid. (SPEC-002)
        Delegates to shared logic.
        """
        from enrichment.edge_logic import check_edge_is_alive
        
        # Extract Params
        current_regime = int(context.get('regime_id', -1))
        d2_prob = context.get('d2_prob', 0.0)
        try:
             entry_regime = int(trade.regime)
        except:
             entry_regime = -1
             
        return check_edge_is_alive(
            entry_regime=entry_regime,
            current_regime=current_regime,
            bars_held=trade.bars_held,
            current_pnl=current_pnl,
            d2_prob=d2_prob,
            trade_style=trade.style
        )

    def _check_trade_exit(
        self, 
        trade: Trade, 
        timestamp: datetime,
        current_price: float,
        candle_high: float,
        candle_low: float,
        candle_open: float,
        bars_held: int,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ExitEvent]:
        
        exit_price = None
        exit_reason = None
        
        sl = trade.sl_price
        target = trade.target_price
        
        pnl_curr = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
        
        # --- 1. SL Logic (Hard Stop) --- (HIGHEST PRIORITY)
        # Check standard SL first
        if trade.direction == "CALL":
            if sl is not None and candle_low <= sl:
                exit_price = sl if candle_open > sl else candle_open
                exit_reason = ExitReason.SL
        else: # PUT
            if sl is not None and candle_high >= sl:
                exit_price = sl if candle_open < sl else candle_open
                exit_reason = ExitReason.SL
                
        if exit_price is not None:
             return self._finalize_exit(trade, exit_price, exit_reason, timestamp, bars_held)

        # --- 2. SOVEREIGN EDGE AUTHORITY (Architectural Law) ---
        # Highest priority after catastrophic safety stop (SL).
        if context:
            is_alive = self._check_edge_alive(trade, context, pnl_curr)
            if not is_alive:
                # HARD EXIT: Physics has failed.
                return self._finalize_exit(trade, current_price, ExitReason.EDGE_DEATH, timestamp, bars_held)

        # --- 3. RISK MANAGEMENT PROTECTIONS (Secondary) ---
        if context:
            regime = int(context.get('regime_id', -1))
            try: entry_regime = int(trade.regime)
            except: entry_regime = -1
            
            # RULE A: Time-Based Alpha Decay
            # If bars > 12 (1 hour) and PnL < 0.6 * MFE (stagnating)
            expected_life = 12
            if bars_held > expected_life:
                pnl_ratio_threshold = 0.6
                if trade.mfe > 20 and pnl_curr < (trade.mfe * pnl_ratio_threshold):
                     return self._finalize_exit(trade, current_price, ExitReason.TIME, timestamp, bars_held)

            # RULE B: Regime Invalidation (Backup)
            if entry_regime in [9, 11] and bars_held > 2:
                 allowed_next = [9, 11, 5]
                 if regime not in allowed_next and regime != entry_regime:
                     return self._finalize_exit(trade, current_price, ExitReason.INVALIDATION, timestamp, bars_held)

        # RULE C: MFE-Based Giveback Guard (Trailing)
        mfe = trade.mfe
        lock_ratio = 0.0
        if mfe >= 70: lock_ratio = 0.75
        elif mfe >= 40: lock_ratio = 0.65
            
        if lock_ratio > 0:
            stop_price_offset = mfe * lock_ratio
            trailing_stop = (trade.entry_price + stop_price_offset) if trade.direction == "CALL" else (trade.entry_price - stop_price_offset)
            
            if (trade.direction == "CALL" and current_price < trailing_stop) or (trade.direction == "PUT" and current_price > trailing_stop):
                 return self._finalize_exit(trade, trailing_stop, ExitReason.SL, timestamp, bars_held)

        # --- 4. OPTIONAL TARGETS (Non-Alpha Only) ---
        # Rule of v2.9.3: Alpha trades (9, 11) run until edge dies or safety stop hits.
        try: entry_regime = int(trade.regime)
        except: entry_regime = -1
        
        if entry_regime not in [9, 11]:
            if trade.direction == "CALL":
                if target is not None and candle_high >= target:
                    return self._finalize_exit(trade, target, ExitReason.TGT, timestamp, bars_held)
            else:
                if target is not None and candle_low <= target:
                    return self._finalize_exit(trade, target, ExitReason.TGT, timestamp, bars_held)

        return None
    
    def _finalize_exit(self, trade, exit_price, exit_reason, timestamp, bars_held):
        """Helper to compute final metrics and return ExitEvent"""
        
        pnl_points = (exit_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - exit_price)
        
        # v2.9 Authoritative Math: Points * 65 * 0.55
        delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
        lot_size = config.get('GLOBAL.NIFTY_LOT_SIZE', 65)
        # We use trade.quantity which already accounts for lot_size * factors
        pnl_rupees = pnl_points * delta * trade.quantity
        
        trade.exit_price = exit_price # Finalize in trade object too? 
        # (Ideally Lifecycle handles this, but we calculate ETD here)
        
        # Calculate ETD (Exit Timing Deviation)
        # ETD = PnL_at_edge_death - PnL_at_exit
        etd = 0.0
        if trade.pnl_edge_death is not None:
            etd = trade.pnl_edge_death - pnl_points
            
        # Update trade object immediately for consistency
        trade.etd = etd
        
        return ExitEvent(
            trade_id=trade.trade_id,
            exit_time=timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_points=pnl_points,
            pnl_rupees=pnl_rupees,
            bars_held=bars_held,
            mfe=trade.mfe,
            mae=trade.mae,
            pnl_edge_death=trade.pnl_edge_death,
            etd=trade.etd
        )

    def reset(self):
        """Reset for new session"""
        self.bar_counters.clear()


# Global instance
exit_engine = ExitEngine()
