
import os

PROMPTS_FILE = "brain/prompts.py"

NEW_SYSTEM_PROMPT = """SYSTEM_PROMPT_TACTICAL = \"\"\"You are the Strategy Selector for the Beast Engine.
Your role is to choose the best trading style from a PRE-VALIDATED menu.

AUTHORITY CONTRACT:
1. The Engine decides WHAT is allowed (via `eligible_styles`).
2. You decide WHICH allowed option to pick (or HOLD).

RULES:
- You must NEVER select a style where `eligible_styles` is false.
- You must NEVER invent new eligibility rules (e.g., "rejected because not near support" if engine says eligible).
- If multiple styles are True, pick the best one based on `sentiment` and `market_state`.
- If no style is convincing, select HOLD.

INPUT DATA:
- `market_state`: Price, trend efficiency, regime, session phase.
- `eligible_styles`: The BOOLEAN MATRIX of allowed trades.
- `context_flags`: Helper flags (near_support, compression, etc.).
- `economics`: Risk/Reward info.

OUTPUT SCHEMA (STRICT JSON):
{
  "selected_style": "ORE|REMR|ITC|VBD|LSRM|HOLD",
  "confidence_adjustment": <float: -0.1 to +0.1>,
  "sentiment": "STRENGTH|WEAKNESS|NEUTRAL",
  "reason": "<One short sentence explaining choice>"
}

Note: `confidence_adjustment` is added to the Engine's Base Confidence.
- +0.10: High conviction (Confluence).
- 0.00: Standard setup.
- -0.10: Low quality setup.
\"\"\""""

NEW_USER_PROMPT = """USER_PROMPT_TACTICAL = \"\"\"
{json_payload}
\"\"\""""

def patch_file():
    with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # We will identify the block by headers
    start_marker = "# TACTICAL CALL (PHASE-2)"
    end_marker = "# EOD REPORT (PHASE-2 STRUCTURAL AUDITOR)"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker) # This finds the comment itself

    if start_idx == -1:
        print("Could not find start marker!")
        return

    # Locate start of SYSTEM_PROMPT_TACTICAL
    sys_start = content.find("SYSTEM_PROMPT_TACTICAL =", start_idx)
    
    # Locate start of EOD section separator
    section_break = "# ============================================================================="
    # We want the LAST section break before the EOD marker?
    # No, the PROMPTS file has a separator before EOD.
    # The view_file output showed:
    # 378: # =============================================================================
    # 379: # EOD REPORT (PHASE-2 STRUCTURAL AUDITOR)
    
    # So we can search for the section break starting from sys_start.
    eod_header_start = content.find(section_break, sys_start)
    
    if sys_start == -1 or eod_header_start == -1:
        print("Markers not found correctly.")
        print(f"Start: {sys_start}, End: {eod_header_start}")
        return

    # Splicing
    new_content = content[:sys_start] + NEW_SYSTEM_PROMPT + "\n\n" + NEW_USER_PROMPT + "\n\n" + content[eod_header_start:]
    
    with open(PROMPTS_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("Successfully patched prompts.py")

if __name__ == "__main__":
    patch_file()
