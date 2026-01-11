import os
import re

FILE_PATH = "engine/modes/backtest.py"

def patch_backtest_summary():
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        return

    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Target: The block logging OVERALL PERFORMANCE
    # logger.info(f"\n📈 OVERALL PERFORMANCE:")
    # ...
    # logger.info("="*80 + "\n")
    
    # We want to capture variables: total_pnl, max_dd, win_rate, total_trades
    # And Balance Monitor stats if available.
    # And Nuggets.
    
    # We will inject code BEFORE "conn.close()" (Line 232 in previous view)
    
    inject_code = """
            # TELEGRAM NOTIFICATION (Final Summary)
            summary_payload = {
                "total_pnl": total_pnl,
                "max_dd": abs(max_dd),
                "win_rate": win_rate,
                "total_trades": total_trades,
                "nuggets": nuggets if nuggets else []
            }
            
            if self.balance_monitor:
                bal = self.balance_monitor.get_summary()
                summary_payload['balance'] = {
                    "initial": bal['initial_balance'],
                    "final": bal['current_balance'],
                    "net_pnl": bal['net_pnl_rupees'],
                    "wipeouts": bal['wipeout_count']
                }
                
            self._emit_telegram_event("SUMMARY", summary_payload, mode_tag="BACKTEST")
"""

    if 'self._emit_telegram_event("SUMMARY"' in content:
        print("⚠️ Summary event already emits.")
        return

    # Find insertion point: Before conn.close() at the end of the reporting block
    # Context:
    #             logger.info("="*80 + "\n")
    #             conn.close()
    
    pattern = r'logger\.info\("=" \* 80 \+ "\\n"\)\s*conn\.close\(\)'
    replacement = 'logger.info("="*80 + "\\n")' + inject_code + '            conn.close()'
    
    new_content = re.sub(pattern, replacement, content)
    
    if new_content == content:
        # Try alternate pattern spacing
        pattern = r'logger\.info\("="\*80 \+ "\\n"\)\s*conn\.close\(\)'
        new_content = re.sub(pattern, replacement, content)
        
    if new_content != content:
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("💾 Patched backtest.py with SUMMARY event")
    else:
        print("❌ Could not find insertion point for Summary event")

if __name__ == "__main__":
    patch_backtest_summary()
