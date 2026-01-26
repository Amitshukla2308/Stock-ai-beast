"""
Super Nova v1: Training Engine
Orchestrates the Oracle Ghost Ground Truth generation and Latent State encoding.
Separated from BacktestMode to ensure strict isolation of learning logic.
"""
import logging
from datetime import datetime, timedelta
from typing import List

# Base
from engine.modes.backtest import BacktestMode
from trade.models import Trade, TradeStatus
from trade import trade_ledger
# Database persistence
from data.database import save_latent_state, save_oracle_truth

logger = logging.getLogger(__name__)

class TrainingEngine(BacktestMode):
    """
    Oracle-aware backtest engine for Super Nova v1 (Phase 3).
    - Encodes Market State -> Latent Vector (Phase 1).
    - Spawns Oracle Ghosts (Call/Put/Hold) -> Ground Truth (Phase 3).
    - Persists everything for Atlas v2 clustering.
    - DOES NOT EXECUTE REAL TRADES (Uses purely Ghost logic for data collection).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.oracle_ghosts: List[Trade] = []
        self.branch_outcomes = {} # hour_key -> {CALL_PNL, PUT_PNL, HOLD_PNL...}
        self.current_latent_vector = None
        
    def start(self):
        """Override start to set mode"""
        self.research_engine.mode = 'learn'
        logger.info(f"🎓 Starting SUPER NOVA TRAINING: {self.start_date.date()} to {self.end_date.date()}")
        super().start()

    def _on_tactical_tick(self, ts, tick, enrichment, decision):
        """
        [SUPER NOVA HOOK]
        Triggered every 15 mins (or schedule).
        1. Encode Latent State.
        2. Spawn Oracle Ghosts.
        """
        try:
            time_key = ts.strftime('%H:%M')
            
            # --- PHASE 1: LATENT ENCODER ---
            # Enrich context for Encoder
            encoder_context = {
                'symbol': self.symbol,
                'tte_mins': 375 - (ts.hour * 60 + ts.minute - 555), # Approx mins from 9:15
                'price': tick['close'],
                'vix_spot': enrichment.get('vix', 15.0),
                'velocity': enrichment.get('physics', {}).get('velocity', 0.0),
                'entropy': enrichment.get('physics', {}).get('entropy', 1.0),
                'trend_efficiency': enrichment.get('physics', {}).get('trend_efficiency', 0.0),
                'dist_pivot': enrichment.get('calc', {}).get('dist_pivot'),
                'dist_s1': enrichment.get('calc', {}).get('dist_s1'),
                'dist_r1': enrichment.get('calc', {}).get('dist_r1')
            }
            
            latent_vector = self.brain.get_market_latent_state(encoder_context)
            if latent_vector:
                self.current_latent_vector = latent_vector
                save_latent_state(ts, self.symbol, latent_vector)
                logger.info(f"      🧬 Latent Encoded: Trend={latent_vector.get('trend_strength')} | Risk={latent_vector.get('risk_state')}")
            
            # --- PHASE 3: ORACLE GHOSTS ---
            # Spawn Ghosts for Ground Truth
            self._spawn_oracle_ghost(ts, tick, enrichment, "CALL")
            self._spawn_oracle_ghost(ts, tick, enrichment, "PUT")
            
            # Monitor HOLD path
            if time_key not in self.branch_outcomes: self.branch_outcomes[time_key] = {}
            self.branch_outcomes[time_key]['HOLD_START_PRICE'] = tick.get('close')
            self.branch_outcomes[time_key]['entry_time'] = ts
            
            # Store latent reference for later joining
            self.branch_outcomes[time_key]['latent_ref'] = latent_vector

        except Exception as e:
            logger.error(f"      ❌ [TRAIN] Super Nova Hook Error at {ts}: {e}", exc_info=True)
        
    def _spawn_oracle_ghost(self, ts, tick, enrichment, direction):
        """Spawns a specialized ghost trade for contradictory outcome tracking"""
        # Use simple fixed geometry for Oracle Baseline (e.g. 100pt Target / 50pt SL)
        # This standardizes the "Outcome" definition.
        
        ghost_decision = {
            "action": f"BUY_{direction}",
            "selected_style": "ORACLE", 
            "confidence": 1.0,
            "reason": f"[ORACLE_{direction}]",
            "metadata": {
                "oracle_branch": direction
            }
        }
        
        # Create trade as Counterfactual
        ghost = self.lifecycle.propose_trade(ghost_decision, enrichment, ts)
        ghost.is_counterfactual = True
        
        # Fixed Oracle Geometry (Standardized)
        ghost.sl_price = ghost.entry_price - 50 if direction == "CALL" else ghost.entry_price + 50
        ghost.target_price = ghost.entry_price + 100 if direction == "CALL" else ghost.entry_price - 100
            
        self.oracle_ghosts.append(ghost)
        self.lifecycle.open_trade(ghost)
        
    def _on_day_ended(self, ts, last_close):
        """Final Audit: Calculate Oracle Outcomes"""
        current_price = last_close
        
        # 1. Close remaining ghosts
        for ghost in self.oracle_ghosts:
            # Force update metrics if still open
             if ghost.status != TradeStatus.CLOSED:
                  # Update MFE/MAE one last time
                  if ghost.direction == "CALL":
                      ghost.mfe = max(ghost.mfe or 0, current_price - ghost.entry_price)
                      ghost.mae = max(ghost.mae or 0, ghost.entry_price - current_price)
                  else:
                      ghost.mfe = max(ghost.mfe or 0, ghost.entry_price - current_price)
                      ghost.mae = max(ghost.mae or 0, current_price - ghost.entry_price)

             # Aggregate into time_key bucket
             hour_key = ghost.entry_time.strftime('%H:%M')
             branch = ghost.metadata['oracle_branch'] # CALL or PUT
             
             if hour_key not in self.branch_outcomes: self.branch_outcomes[hour_key] = {}
             outcomes = self.branch_outcomes[hour_key]
             
             # Store metrics
             outcomes[f"{branch.lower()}_mfe"] = ghost.mfe
             outcomes[f"{branch.lower()}_mae"] = ghost.mae
             
             # Calculate Edge Survival (Did it hit SL immediately?)
             # Simple heuristic: Survival = MAE < 20pts in first 5 mins? 
             # For now, just store raw MFE/MAE. Dataset Builder defines survival.

        # 2. Persist Outcomes
        for time_key, data in self.branch_outcomes.items():
            if 'entry_time' not in data: continue
            
            # HOLD PnL
            start_price = data.get('HOLD_START_PRICE', 0)
            hold_pnl = current_price - start_price
            
            # Construct Outcome Record
            outcome_record = {
                'call_mfe': data.get('call_mfe', 0.0),
                'call_mae': data.get('call_mae', 0.0),
                'put_mfe': data.get('put_mfe', 0.0),
                'put_mae': data.get('put_mae', 0.0),
                'hold_pnl': hold_pnl,
                # Placeholders for now, logic can be refined in Dataset Builder
                'edge_survival_5': 1 if data.get('call_mae', 999) < 20 or data.get('put_mae', 999) < 20 else 0,
                'edge_survival_10': 1 
            }
            
            save_oracle_truth(data['entry_time'], self.symbol, outcome_record)
        
        # Legacy EOD calls (optional, but good for logs)
        super()._on_day_ended(ts, last_close)
        
        # Cleanup
        self.oracle_ghosts = []
        self.branch_outcomes = {}
