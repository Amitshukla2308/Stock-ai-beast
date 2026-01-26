"""
v2.8 Traceability: Trace Logger
Ensures every trade decision is auditable.
Logs the "Why" for every "No".
"""
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class TraceLogger:
    def __init__(self, session_id: str = "SESSION"):
        self.session_id = session_id

    def log_decision_chain(self, tick, style, eligibility, risk, confidence, decision):
        """
        Log the full decision chain for a specific style evaluation.
        Structure:
          [TRACE] STYLE=REMR | ELIG=True | RISK=Pass | CONF=0.82 | ACTION=BUY_CALL
        If blocked, explain why.
        """
        from data.database import get_connection
        timestamp = tick.get('timestamp')
        if hasattr(timestamp, 'strftime'):
            ts_str = timestamp.strftime('%H:%M:%S')
            ts_db = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            ts_str = str(timestamp)[11:19]
            ts_db = str(timestamp)
            
        # status flags
        is_eligible = eligibility.get(style, False)
        pass_risk = risk.get('action') != 'HOLD'
        
        final_action = decision.get('action', 'HOLD')
        reason = decision.get('reason', 'N/A')
        score = decision.get('confidence', 0.0)
        
        # Build Log String
        log_msg = (
            f" [TRACE] {ts_str} | {style} | "
            f"Elig:{'✅' if is_eligible else '❌'} | "
            f"Risk:{'✅' if pass_risk else '⛔'} | "
            f"Conf:{score:.2f} | "
            f"Final:{final_action} ({reason})"
        )
        
        logger.info(log_msg)
        
        # Persist to DB for EOD Audit
        payload = {
            "style": style,
            "eligible": is_eligible,
            "risk_pass": pass_risk,
            "confidence": score,
            "action": final_action,
            "reason": reason,
            "engine_decision": "BLOCKED" if final_action == "HOLD" and is_eligible else "PROCEEDED",
            "engine_reason": reason if final_action == "HOLD" else "N/A"
        }
        
        try:
            conn = get_connection()
            conn.execute("""
                INSERT INTO simulation_logs (session_id, timestamp, event_type, content)
                VALUES (?, ?, ?, ?)
            """, (self.session_id, ts_db, 'TACTICAL', json.dumps(payload)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to persist trace log: {e}")

    def flush(self):
        """No-op for back compatibility"""
        pass


# Global Instance (Backtest/Live modes should override session_id)
trace_logger = TraceLogger()
