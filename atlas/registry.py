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
        self.fallback_stats = {}
        self._load_registry()

    def _load_registry(self):
        conf_path = os.path.join(self.artifact_dir, "confluence_map.json")
        stats_path = os.path.join(self.artifact_dir, "regime_stats.parquet")
        
        if not os.path.exists(conf_path):
            logger.error(f"[REGISTRY] ❌ Confluence Map not found: {conf_path}")
            return

        try:
            with open(conf_path, 'r') as f:
                data = json.load(f)
                self.long_edges = {(e['cluster_15m'], e['cluster_5m']): e for e in data.get('long_edges', [])}
                self.short_edges = {(e['cluster_15m'], e['cluster_5m']): e for e in data.get('short_edges', [])}
            
            if os.path.exists(stats_path):
                stats_df = pd.read_parquet(stats_path)
                self.fallback_stats = stats_df.set_index(['cluster_15m', 'cluster_5m'])['win_rate_long'].to_dict()
                logger.info(f"[REGISTRY] ✅ Loaded {len(self.fallback_stats)} Fallback stats.")
            
            logger.info(f"[REGISTRY] ✅ Loaded {len(self.long_edges)} Long and {len(self.short_edges)} Short edges.")
        except Exception as e:
            logger.error(f"[REGISTRY] ❌ Load Failed: {e}")

    def get_alpha_state(self, c15: int, c5: int, cutoff_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Retrieves stats for a cluster pair. 
        v4.0 Sovereign: Pure research-based lookup.
        """
        key = (int(c15), int(c5))

        # 1. Primary: High-Alpha Map (Research Bootstrap 2021-2024)
        if key in self.long_edges:
            edge = self.long_edges[key]
            return {
                "bias": "LONG",
                "win_rate": edge.get('win_rate_long', 0.0),
                "avg_mfe": edge.get('avg_mfe_long', 0.0),
                "avg_mae": edge.get('avg_mae_long', 0.0),
                "confluence_id": f"LONG_{c15}_{c5}",
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

        # 3. Tertiary: Dynamic RAG Fallback
        if cutoff_time:
            from data.database import retrieve_relevant_nuggets
            nuggets = retrieve_relevant_nuggets(tags=[f"{c15}:{c5}"], cutoff_time=cutoff_time, limit=10)
            if nuggets:
                wins = [n for n in nuggets if (n.get('call_pnl', 0) > 0 or n.get('put_pnl', 0) > 0)]
                wr = len(wins) / len(nuggets)
                mfe_mean = sum([n.get('mfe', 0.0) for n in nuggets]) / len(nuggets)
                mae_mean = sum([n.get('mae', 0.0) for n in nuggets]) / len(nuggets)
                
                return {
                    "bias": "LONG" if wr > 0.45 else "NONE",
                    "win_rate": wr,
                    "avg_mfe": mfe_mean, "avg_mae": mae_mean,
                    "confluence_id": f"RAG_{c15}_{c5}",
                    "is_fallback": True
                }

        return {
            "bias": "NONE",
            "win_rate": 0.0, "avg_mfe": 0.0, "avg_mae": 0.0,
            "confluence_id": f"NONE_{c15}_{c5}",
            "is_fallback": False
        }

