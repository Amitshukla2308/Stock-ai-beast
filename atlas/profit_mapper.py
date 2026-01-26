"""
Project Atlas: Profit Mapper (Offline)
Purpose:
Map identified Clusters (Regimes) to Profitability Distributions.
Function: PnL(Cluster, Action) -> Distribution

Input: atlas/data/clustered_states.pkl
Output: atlas/profitability_map.json

Logic:
1. Load Clustered State Vectors.
2. Group by [ClusterID, Action, Style].
3. Calculate statistical edge per group (Win Rate, Mean PnL, RR, MAE/MFE).
4. Export as JSON for use by the Live Engine/LLM.
"""

import pandas as pd
import json
import os

class ProfitMapper:
    def __init__(self, data_path="atlas/data/clustered_states.pkl"):
        self.data_path = data_path
        self.output_path = "atlas/profitability_map.json"
        
    def run_mapping(self):
        """
        Calculates profitability stats per cluster.
        """
        if not os.path.exists(self.data_path):
            print(f"⚠️ Profit Mapper: File not found ({self.data_path}). Run ClusterEngine first.")
            return

        try:
            df = pd.read_pickle(self.data_path)
            print(f"✅ Loaded {len(df)} clustered states.")
            
            # Grouping stats
            # We want to know how each Style performed in each Cluster
            results = {}
            
            cluster_groups = df.groupby(['cluster_id', 'action', 'style'])
            
            for (cluster_id, action, style), group in cluster_groups:
                c_id = str(cluster_id)
                if c_id not in results: results[c_id] = {}
                
                # Logic to determine "Win"
                # For simplicity, PnL > 0 is a win
                wins = group[group['pnl_points'] > 0]
                win_rate = len(wins) / len(group) if len(group) > 0 else 0
                
                avg_pnl = group['pnl_points'].mean()
                avg_mae = group['mae'].mean()
                avg_mfe = group['mfe'].mean()
                
                # Expressiveness/Reliability metric
                # Simple score: WinRate * AvgPnL / (AvgMAE + 1)
                edge_score = (win_rate * avg_pnl) / (abs(avg_mae) + 1)
                
                key = f"{action}|{style}"
                results[c_id][key] = {
                    "win_rate": round(win_rate, 2),
                    "mean_pnl": round(avg_pnl, 2),
                    "mean_mae": round(avg_mae, 2),
                    "mean_mfe": round(avg_mfe, 2),
                    "sample_size": len(group),
                    "edge_score": round(edge_score, 4)
                }
            
            with open(self.output_path, 'w') as f:
                json.dump(results, f, indent=4)
                
            print(f"✅ Profitability map saved to {self.output_path}")
            return results
            
        except Exception as e:
            print(f"❌ Error during Profit Mapping: {e}")

if __name__ == "__main__":
    mapper = ProfitMapper()
    mapper.run_mapping()
