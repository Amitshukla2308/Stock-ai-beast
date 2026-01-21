"""
Trade Engine v2.8: Models
Pure dataclasses with no logic. The canonical data structures for trades.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class TradeStatus(Enum):
    """Trade lifecycle states"""
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(Enum):
    """Why a trade was closed"""
    SL = "SL"
    TGT = "TGT"
    TIME = "TIME"
    EOD = "EOD"
    INVALIDATION = "INVALIDATION"
    MANUAL = "MANUAL"


@dataclass
class Trade:
    """
    Complete trade record with full entry context.
    This is THE truth for what happened.
    """
    # Identity
    trade_id: str
    session_id: str
    symbol: str
    
    # Direction
    style: str  # REMR, ITC, VBD, etc.
    direction: str  # CALL or PUT
    
    # Entry
    entry_time: datetime
    entry_price: float
    sl_price: Optional[float] = None
    target_price: Optional[float] = None
    quantity: int = 50
    
    # Context at Entry
    confidence: float = 0.0
    regime: str = "UNKNOWN"
    session_phase: str = "UNKNOWN"
    trend_efficiency: float = 0.0
    atr: float = 0.0
    or_range: float = 0.0
    location: str = "UNKNOWN"
    reason: str = ""
    
    # State
    status: TradeStatus = TradeStatus.PROPOSED
    
    # Exit (populated on close)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    bars_held: int = 0
    
    # Performance (populated on close)
    pnl_points: float = 0.0
    pnl_rupees: float = 0.0
    mfe: float = 0.0  # Max Favorable Excursion
    mae: float = 0.0  # Max Adverse Excursion
    
    # Meta
    config_hash: str = ""
    system_version: str = "v2.8"


@dataclass
class ExitEvent:
    """Captures the moment a trade exits"""
    trade_id: str
    exit_time: datetime
    exit_price: float
    exit_reason: ExitReason
    pnl_points: float
    pnl_rupees: float
    bars_held: int = 0
    mfe: float = 0.0
    mae: float = 0.0


@dataclass
class DailySummary:
    """End-of-day statistics"""
    date: str
    session_id: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_points: float = 0.0
    total_pnl_rupees: float = 0.0
    best_style: str = ""
    worst_style: str = ""
    max_drawdown: float = 0.0
    trend_efficiency: float = 0.0  # Daily trend quality
    or_range: float = 0.0         # Opening range size
    participation_score: float = 0.0 # participation_rate for the day
