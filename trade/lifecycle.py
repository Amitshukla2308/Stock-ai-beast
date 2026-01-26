"""
Trade Engine v2.8: Lifecycle
State machine enforcement. Prevents illegal transitions.
No implicit close. No forgot to log. No silent corruption.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from trade.models import Trade, ExitEvent, TradeStatus, ExitReason
from trade.ledger import trade_ledger
from trade.store import trade_store
from config.config_loader import config

logger = logging.getLogger(__name__)


class TradeLifecycle:
    """
    State machine for trade lifecycle.
    CANDIDATE → PROPOSED → OPEN → ACTIVE → EXITED → CLOSED → ARCHIVED
    """
    
    def __init__(self, session_id: str, broker=None, is_simulation: bool = False):
        self.session_id = session_id
        self.trade_counter = 0
        self.broker = broker
        self.is_simulation = is_simulation
    
    def _generate_trade_id(self, timestamp: datetime) -> str:
        """Generate unique trade ID"""
        self.trade_counter += 1
        return f"{self.session_id}_{timestamp.strftime('%H%M%S')}_{self.trade_counter}"
    
    def propose_trade(self, decision: Dict[str, Any], context: Dict[str, Any], timestamp: datetime) -> Trade:
        """
        Create a proposed trade from decision and context.
        Does NOT open it yet.
        """
        trade = Trade(
            trade_id=self._generate_trade_id(timestamp),
            session_id=self.session_id,
            symbol=context.get('symbol', 'NSE:NIFTY50-INDEX'),
            style=decision.get('selected_style', 'UNKNOWN'),
            direction="CALL" if decision.get('action') == "BUY_CALL" else "PUT",
            entry_time=timestamp,
            entry_price=decision.get('entry_price', context.get('close', context.get('price', 0))),
            sl_price=decision.get('sl'),
            target_price=decision.get('target'),
            quantity=config.get('GLOBAL.NIFTY_LOT_SIZE', 65) * decision.get('size_factor', 1),
            confidence=decision.get('confidence', 0),
            regime=context.get('regime_id', 'UNKNOWN'),
            session_phase=context.get('session_phase', 'UNKNOWN'),
            trend_efficiency=context.get('trend_efficiency', 0),
            atr=context.get('atr', 0),
            or_range=context.get('or_range', 0),
            location=context.get('location_class', 'UNKNOWN'),
            reason=decision.get('reason', ''),
            status=TradeStatus.PROPOSED,
            metadata=decision.get('metadata', {}),
            physics_ctx={
                "velocity": context.get('velocity', 0.0),
                "entropy": context.get('entropy_price', 0.0),
                "accel": context.get('accel', 0.0),
                "ter": context.get('ter', 0.0)
            }
        )
        
        logger.info(f"[LIFECYCLE] ✨ Proposed: {trade.trade_id} | {trade.style} {trade.direction}")
        return trade
    
    def open_trade(self, trade: Trade) -> bool:
        """
        Open a proposed trade. Updates ledger and store.
        Returns False if trade cannot be opened (e.g., position exists).
        """
        if trade.status != TradeStatus.PROPOSED:
            logger.error(f"[LIFECYCLE] Cannot open: Trade {trade.trade_id} is not in PROPOSED state")
            return False
        
        # Check no existing position (Unless Atlas Probe or Counterfactual)
        is_atlas = trade.metadata.get('is_atlas_probe', False)
        is_ghost = trade.is_counterfactual
        
        if not is_atlas and not is_ghost and trade_ledger.has_open_position(trade.symbol):
            logger.warning(f"[LIFECYCLE] Cannot open: Position already exists for {trade.symbol}")
            return False
        
        # Open in ledger
        if not trade_ledger.open_trade(trade):
            return False
        
        # Persist to store (SKIP FOR ATLAS)
        is_atlas = trade.metadata.get('is_atlas_probe', False)
        
        if not is_atlas:
            trade_store.insert_trade(trade)
            # Log trade open (Standard)
            logger.info(f"""
[TRADE OPEN]
ID={trade.trade_id}
Style={trade.style}
Dir={trade.direction}
Entry={trade.entry_price}
SL={trade.sl_price}
TGT={trade.target_price}
Conf={trade.confidence}
Regime={trade.regime}
Reason="{trade.reason}"
""")
        else:
             # Log Atlas Probe Entry (Minimal)
             logger.debug(f"[ATLAS] 🧠 Probe OPEN: {trade.trade_id} | {trade.direction}")
             
        return True
    
    def close_trade(self, trade_id: str, exit_event: ExitEvent) -> Optional[Trade]:
        """
        Close an open trade. Updates ledger and store.
        Returns the closed Trade or None if failed.
        """
        # Close in ledger
        trade = trade_ledger.close_trade(trade_id, exit_event)
        if not trade:
            return None
        
        # Persist to store (SKIP FOR ATLAS)
        is_atlas = trade.metadata.get('is_atlas_probe', False)
        
        if not is_atlas:
            trade_store.close_trade(trade)
            
            # Fetch Balance Context
            balance = 0.0
            if self.broker:
                balance = self.broker.get_balance()
                
            # Rich Log trade close
            C_RESET = "\033[0m"
            C_GREEN = "\033[92m"
            C_RED = "\033[91m"
            C_YELLOW = "\033[93m"
            C_CYAN = "\033[96m"
            
            pnl_val = trade.pnl_rupees
            pnl_arrow = "▲" if pnl_val >= 0 else "▼"
            pnl_color = C_GREEN if pnl_val >= 0 else C_RED
            
            # Update Broker (Accountant)
            # v2.9.4 Reverted per User Request: Only update balance for REAL trades
            print(f"[DEBUG] Closing Trade {trade.trade_id}. Broker attached: {self.broker is not None}")
            print(f"[DEBUG] Is Counterfactual: {trade.is_counterfactual} | PnL Rupees: {pnl_val}")
            
            if self.broker and hasattr(self.broker, 'update_balance'):
                if not trade.is_counterfactual:
                    print(f"[DEBUG] Calling broker.update_balance with {pnl_val}")
                    self.broker.update_balance(pnl_val)
                else:
                    print(f"[DEBUG] Skipping balance update for Ghost trade")
                
            # Refetch updated balance
            if self.broker:
                balance = self.broker.get_balance()
                
            prev_bal = balance - pnl_val
            bal_pch = ((balance - prev_bal) / prev_bal * 100) if prev_bal != 0 else 0.0
            bal_arrow = "▲" if bal_pch >= 0 else "▼"
            bal_color = C_GREEN if bal_pch >= 0 else C_RED

            etd_str = f"{trade.etd:+.1f}" if trade.etd is not None else "N/A"
            etd_color = C_RED if (trade.etd and trade.etd > 0) else C_RESET

            # Shadow Comparison
            shadow_msg = ""
            if trade.shadow_pnl is not None:
                delta = trade.pnl_points - trade.shadow_pnl
                outcome = "System Wins" if delta >= 0 else "Brain Was Right"
                color = C_GREEN if delta >= 0 else C_RED
                shadow_msg = f"\nVS_BRAIN: {C_DIM}Brain:{trade.shadow_pnl:+.1f}{C_RESET} vs System:{trade.pnl_points:+.1f} | Delta={color}{delta:+.1f} ({outcome}){C_RESET}"

            if not trade.is_counterfactual:
                logger.info(f"""
[TRADE CLOSE]
ID={trade.trade_id}
Exit={trade.exit_price}
Reason={trade.exit_reason.value if trade.exit_reason else 'UNKNOWN'}
BarsHeld={trade.bars_held}
PnL={pnl_color}{trade.pnl_points:+.1f}pts ({pnl_arrow} ₹{trade.pnl_rupees:+.0f}){C_RESET}
MFE={trade.mfe:+.1f}
MAE={trade.mae:+.1f}
ETD={etd_color}{etd_str}{C_RESET}{shadow_msg}
Balance={C_YELLOW}₹{balance:,.0f}{C_RESET} ({bal_color}{bal_arrow} {bal_pch:+.2f}%{C_RESET})
""")
            else:
                logger.info(f"""
{C_CYAN}[GHOST CLOSED] (Counterfactual){C_RESET}
ID={trade.trade_id}
Exit={trade.exit_price}
Reason={trade.exit_reason.value if trade.exit_reason else 'UNKNOWN'}
PnL={pnl_color}{trade.pnl_points:+.1f}pts{C_RESET}
MFE={trade.mfe:+.1f}
""")
        else:
            # Log Atlas Probe Exit (Minimal)
            logger.debug(f"[ATLAS] 🏁 Probe CLOSE: {trade.trade_id} | PnL: {trade.pnl_points:.1f}")
        
        # ATLAS HOOK: If this was a probe, log the outcome row
        if "atlas_state" in trade.metadata:
#            from atlas.state_logger import atlas_logger
            atlas_logger.log_probe_outcome(trade)

        return trade
    
    def force_close_all(self, current_price: float, timestamp: datetime, reason: ExitReason = ExitReason.EOD) -> int:
        """
        Force close all open positions (e.g., at EOD).
        Returns count of closed trades.
        """
        closed_count = 0
        
        # Get list of open trades (copy to avoid modification during iteration)
        open_trades = list(trade_ledger.open_positions.values())
        
        for trade in open_trades:
            pnl_points = (current_price - trade.entry_price) if trade.direction == "CALL" else (trade.entry_price - current_price)
            
            # v2.9 Authoritative Math: Points * 65 * 0.55
            delta = config.get('GLOBAL.OPTIONS_DELTA', 0.55)
            lot_size = config.get('GLOBAL.NIFTY_LOT_SIZE', 65)
            pnl_rupees = pnl_points * delta * trade.quantity
            
            exit_event = ExitEvent(
                trade_id=trade.trade_id,
                exit_time=timestamp,
                exit_price=current_price,
                exit_reason=reason,
                pnl_points=pnl_points,
                pnl_rupees=pnl_rupees,
                bars_held=0  # Would need bar counter
            )
            
            if self.close_trade(trade.trade_id, exit_event):
                closed_count += 1
        
        return closed_count


# Factory function for new sessions
def create_lifecycle(session_id: str, broker=None, is_simulation: bool = False) -> TradeLifecycle:
    return TradeLifecycle(session_id, broker, is_simulation=is_simulation)
