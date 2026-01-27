"""
v4.0 Registry: The Confluence Map Gateway
Handles high-alpha cluster lookup and win-rate validation.
"""
import os
import json
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class Registry:
    def __init__(self, artifact_dir: str = "atlas/models"):
        self.artifact_dir = artifact_dir
        self.long_edges = {}
        self.short_edges = {}
        self.live_learning_map = {} # v6.0: Stores EOD updates during backtest
        self._load_registry()
        self._seed_from_bootstrap() # v6.2: Pre-populate with historical edge

    def _load_registry(self):
        conf_path = os.path.join(self.artifact_dir, "confluence_map.json")
        stats_path = os.path.join(self.artifact_dir, "regime_stats.parquet")
        
        if not os.path.exists(conf_path):
            logger.error(f"[REGISTRY] ❌ Confluence Map not found: {conf_path}")
            return

        try:
            with open(conf_path, 'r') as f:
                data = json.load(f)
                # Map keys as (c15, c5)
                self.long_edges = {(e['cluster_15m'], e['cluster_5m']): e for e in data.get('long_edges', [])}
                self.short_edges = {(e['cluster_15m'], e['cluster_5m']): e for e in data.get('short_edges', [])}
            
            # Fallback Stats
            if os.path.exists(stats_path):
                stats_df = pd.read_parquet(stats_path)
                # Store as (c15, c5) -> win_rate_long
                self.fallback_stats = stats_df.set_index(['cluster_15m', 'cluster_5m'])['win_rate_long'].to_dict()
                logger.info(f"[REGISTRY] ✅ Loaded {len(self.fallback_stats)} Fallback cluster stats.")
            else:
                self.fallback_stats = {}
                
            logger.info(f"[REGISTRY] ✅ Loaded {len(self.long_edges)} Long and {len(self.short_edges)} Short high-alpha edges.")
        except Exception as e:
            logger.error(f"[REGISTRY] ❌ Load Failed: {e}")

    def get_alpha_state(self, c15: int, c5: int, cutoff_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Retrieves stats for a cluster pair with Temporal Guarding (v6.0).
        """
        key = (int(c15), int(c5))
        is_live_period = cutoff_time and cutoff_time.year >= 2025

        # 1. v6.0: Check Live Learning Map first (Rolling Experience)
        if is_live_period and key in self.live_learning_map:
            edge = self.live_learning_map[key]
            tier = edge.get('tier', 2)
            
            return {
                "bias": edge['bias'],
                "win_rate": edge['win_rate'],
                "avg_mfe": edge.get('avg_mfe', 0.0),
                "avg_mae": edge.get('avg_mae', 0.0),
                "confluence_id": f"T{tier}_{c15}_{c5}",
                "is_fallback": False,
                "tier": tier,
                "expectancy": edge.get('expectancy', 0.0)
            }

        # 2. Primary: High-Alpha Map (Research Bootstrap 2021-2024)
        # In v6.0, we ONLY use this if we haven't learned enough in the live period yet
        # OR if we are in the pre-2025 bootstrap phase.
        if not is_live_period:
            if key in self.long_edges:
                edge = self.long_edges[key]
                return {
                    "bias": "LONG",
                    "win_rate": edge.get('win_rate_long', 0.0),
                    "avg_mfe": edge.get('avg_mfe_long', 0.0),
                    "avg_mae": edge.get('avg_mae_long', 0.0),
                    "confluence_id": f"BOOT_{c15}_{c5}",
                    "is_fallback": False
                }
            
            if key in self.short_edges:
                edge = self.short_edges[key]
                return {
                    "bias": "SHORT",
                    "win_rate": edge.get('win_rate_short', 0.0),
                    "avg_mfe": edge.get('avg_mfe_short', 0.0),
                    "avg_mae": edge.get('avg_mae_short', 0.0),
                    "confluence_id": f"BOOT_{c15}_{c5}",
                    "is_fallback": False
                }
        
        if key in self.short_edges:
            edge = self.short_edges[key]
            return {
                "bias": "SHORT",
                "win_rate": edge.get('win_rate_short', 0.0),
                "avg_mfe": edge.get('avg_mfe_short', 0.0),
                "avg_mae": edge.get('avg_mae_short', 0.0),
                "confluence_id": f"SHORT_{c15}_{c5}",
                "is_fallback": False
            }

        # 2. Secondary: Static Stat Fallback
        if key in self.fallback_stats:
             wr = self.fallback_stats[key]
             return {
                 "bias": "LONG" if wr > 0.45 else "NONE",
                 "win_rate": wr,
                 "avg_mfe": 0.0, "avg_mae": 0.0,
                 "confluence_id": f"STAT_{c15}_{c5}",
                 "is_fallback": True
             }

        # 3. Tertiary: Dynamic RAG Fallback (The True Anti-Cheat)
        # If we have a cutoff_time, we can ask the DB "What do we know about this regime so far?"
        if cutoff_time:
            from data.database import retrieve_relevant_nuggets
            # Query for the specific regime string (e.g. "6:29")
            nuggets = retrieve_relevant_nuggets(tags=[f"{c15}:{c5}"], cutoff_time=cutoff_time, limit=10)
            if nuggets:
                wins = [n for n in nuggets if (n.get('call_pnl', 0) > 0 or n.get('put_pnl', 0) > 0)]
                wr = len(wins) / len(nuggets)
                return {
                    "bias": "LONG" if wr > 0.45 else "NONE", # Adaptive Bias
                    "win_rate": wr,
                    "avg_mfe": 0.0, "avg_mae": 0.0,
                    "confluence_id": f"RAG_{c15}_{c5}",
                    "is_fallback": True,
                    "metadata": {"source": "temporal_rag", "sample_size": len(nuggets)}
                }

        return {
            "bias": "NONE",
            "win_rate": 0.0, "avg_mfe": 0.0, "avg_mae": 0.0,
            "confluence_id": f"NONE_{c15}_{c5}",
            "is_fallback": False
        }

    def _seed_from_bootstrap(self):
        """
        v6.2 Darwinian Legacy: Seeds the learning map with 4-year historical expertise.
        Injects Golden, Standard, and Blocked regimes from research.
        """
        from config.config_loader import config
        amp_cfg = config.get("ALPHA_AMPLIFICATION", {})
        block_cfg = config.get("FORENSIC_BLOCKS", {})
        steril_cfg = config.get("REGIME_STERILIZATION", {})

        # 1. Golden Regimes (Tier 1)
        for r_id in amp_cfg.get("golden_regimes", []):
            try:
                c15, c5 = map(int, r_id.split(':'))
                self.live_learning_map[(c15, c5)] = {
                    'bias': 'LONG', 'win_rate': 0.62, 'expectancy': 2.5,
                    'tier': 1, 'count': 20, 'net_pnl': 15000 # v6.2: Increased Inertia
                }
            except Exception: continue

        # 2. Toxic Regimes (Tier 4)
        toxic_list = set(block_cfg.get("regimes", [])) | set(steril_cfg.get("block_list", []))
        for r_id in toxic_list:
            try:
                c15, c5 = map(int, r_id.split(':'))
                self.live_learning_map[(c15, c5)] = {
                    'bias': 'NONE', 'win_rate': 0.30, 'expectancy': -20.0,
                    'tier': 4, 'count': 20, 'net_pnl': -15000 
                }
            except Exception: continue
            
        logger.info(f"[REGISTRY] 🏁 v6.2 Seeded {len(self.live_learning_map)} regimes from Expert Legacy.")

    def _assign_historical_tier(self, key: tuple, edge: dict, bias: str):
        """Helper to categorize historical expertise into Darwinian Tiers. (Deprecated in v6.2)"""
        pass

    def update_walk_forward_map(self, session_all_trades: pd.DataFrame):
        """
        v6.0: Updates the internal learning map based on simulation history.
        Called by BacktestMode at EOD.
        """
        if session_all_trades.empty: return
        
        # Group by regime to calculate current session stats
        stats = session_all_trades.groupby('regime').agg({
            'pnl_rupees': 'sum',
            'pnl_points': 'mean',
            'trade_id': 'count',
            'quantity': 'first' # To detect current sizing
        }).rename(columns={'trade_id': 'count', 'pnl_points': 'expectancy'})

        # Binary win calculation
        wins = session_all_trades[session_all_trades['pnl_points'] > 0].groupby('regime')['trade_id'].count()
        
        for regime_id, row in stats.iterrows():
            try:
                c15, c5 = map(int, regime_id.split(':'))
                key = (c15, c5)
                
                # v6.2: Accumulate upon bootstrap seeds if they exist
                historical = self.live_learning_map.get(key, {'count': 0, 'net_pnl': 0, 'win_rate': 0.5})
                
                session_count = row['count']
                total_count = historical['count'] + session_count
                
                # Weighting: New Win Rate is a weighted average
                session_wr = wins.get(regime_id, 0) / session_count if session_count > 0 else 0.0
                total_wr = ((historical['win_rate'] * historical['count']) + (session_wr * session_count)) / total_count
                
                total_pnl = historical['net_pnl'] + row['pnl_rupees']
                expectancy = row['expectancy'] # Just use current session expectancy for momentum?
                                               # Or average? Let's use average for stability.
                total_expectancy = (total_pnl / total_count / 35.75) if total_count > 0 else 0 # Points approx

                # --- v6.1/6.2 Darwinian Tier Classification ---
                tier = 2 # Default: Standard
                
                # Tier 1: Golden (Robust over Bootstrap + 2025)
                if total_count >= 10 and total_wr >= 0.58 and total_expectancy >= 1.5:
                    tier = 1
                
                # Tier 4: Blocked (Toxic Failure)
                elif total_count >= 5 and (total_wr < 0.38 or total_expectancy < -10.0):
                    tier = 4
                
                # Tier 3: Probation (Underperforming)
                elif total_count >= 3 and (total_wr < 0.52 or total_expectancy < 0.0):
                    tier = 3
                
                self.live_learning_map[key] = {
                    'bias': 'LONG' if total_expectancy > 0 else 'SHORT',
                    'win_rate': total_wr,
                    'expectancy': total_expectancy,
                    'tier': tier,
                    'count': total_count,
                    'net_pnl': total_pnl
                }
            except Exception: continue

        logger.info(f"[REGISTRY] 🧠 v6.1 Darwinism Updated: {len(self.live_learning_map)} regimes categorized.")
