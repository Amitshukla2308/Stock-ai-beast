"""
v2.8 Confidence Engine
Calculates a numeric confidence score (0.0 - 1.0) for each eligible style.
Pure Math Layer. No decisions (Pass/Fail), only Scoring.
"""
from typing import Dict, List
from config.config_loader import config

class ConfidenceEngine:
    def calculate_confidence(self, eligible_styles: List[str], facts: Dict) -> Dict[str, float]:
        """
        Score each eligible style based on market facts.
        """
        scores = {}
        
        # Extract Key Facts
        ter = facts.get('trend_efficiency', 0.0)
        regime = facts.get('trend_regime', 'ROTATION')
        vix = facts.get('vix', 15.0)
        
        for style in eligible_styles:
            base_score = 0.5 # Neutral start
            
            # Extract Levels
            price = facts.get('price', 0.0)
            bc = facts.get('bc', 0.0)
            tc = facts.get('tc', 0.0)
            near_htf = facts.get('near_htf', False)
            
            # --- General Structural Boosts ---
            if near_htf:
                base_score += 0.1 # General proximity boost
            
            # --- ITC (Trend) Scoring ---
            if style == 'ITC':
                # Higher TER = Higher Confidence
                trend_boost = min(0.4, ter * 0.5)
                base_score += trend_boost
                
                # Regime Penalty
                if regime == 'ROTATION':
                    base_score -= 0.1
                
                # CPR Structural Boost: Trend is higher confidence outside CPR
                if tc > 0 and bc > 0:
                    if price > tc or price < bc:
                        base_score += 0.1
                    else:
                        base_score -= 0.1 # CPR Churn penalty
            
            # --- REMR (Reversion) Scoring ---
            elif style == 'REMR':
                # High TER = Bad for Reversion
                trend_penalty = min(0.4, ter * 0.5)
                base_score -= trend_penalty
                
                # Low VIX = Bad for Reversion (Grinding)
                if vix < 12.0:
                    base_score -= 0.1
                    
                # High VIX = Good for Reversion
                if vix > 20.0:
                    base_score += 0.1
                    
                # CPR Boundary Boost: Reversions from TC/BC are high quality
                if near_htf and (facts.get('near_tc') or facts.get('near_bc')):
                    base_score += 0.1
            scores[style] = max(0.0, min(1.0, base_score))
            
        return scores

# Global Instance
confidence_engine = ConfidenceEngine()
