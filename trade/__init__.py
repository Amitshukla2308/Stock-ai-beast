"""
Trade Engine v2.8
The spine of the trading system. Single source of truth for all trade state.
"""
from trade.models import Trade, ExitEvent, DailySummary, TradeStatus, ExitReason
from trade.store import trade_store
from trade.ledger import trade_ledger
from trade.lifecycle import TradeLifecycle, create_lifecycle
from trade.exit_engine import exit_engine
from trade.eod import eod_processor
from trade.reporter import trade_reporter

__all__ = [
    'Trade', 'ExitEvent', 'DailySummary', 'TradeStatus', 'ExitReason',
    'trade_store', 'trade_ledger', 'TradeLifecycle', 'create_lifecycle',
    'exit_engine', 'eod_processor', 'trade_reporter'
]
