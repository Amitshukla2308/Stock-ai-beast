"""
v2.8 Core: Orchestrator
The Central Nervous System.
Wires together Enrichment, Signals, Eligibility, Risk, and Execution.
"""
import logging
from enrichment.momentum import momentum_tracker
from executor.execute import Executor

logger = logging.getLogger(__name__)

class Orchestrator:
    """
    The Causal Graph Driver.
    Tick -> Enrichment -> Signals -> Eligibility -> Confidence -> LLM -> Risk -> Executor
    """
    
    def __init__(self, executor: Executor):
        self.executor = executor
        
    def process_tick(self, tick: dict):
        """
        Drive the linear pipeline on every tick.
        """
        # 1. Enrichment: Update Global Facts (Momentum)
        momentum_tracker.update(tick)
        
        # 2. Execution Management (SL/Target Checks)
        # Delegated to Executor (The Authority)
        self.executor.manage_active_position(tick)

    def get_ledger(self):
        return self.executor.trade_ledger
