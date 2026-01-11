import os
import re

FILE_PATH = "engine/auth_fyers.py"

def patch_auth_fyers_fix():
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        return

    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. FIX TIMEZONE (Use IST Awareness)
    # We'll inject a helper and use it.
    
    helper_code = """
def get_ist_now():
    # Returns IST aware datetime (UTC+5:30)
    return datetime.utcnow() + timedelta(hours=5, minutes=30)
"""
    
    # Insert helper after imports
    if "def get_ist_now():" not in content:
        content = content.replace("from dotenv import load_dotenv", "from dotenv import load_dotenv\n" + helper_code)

    # Replace datetime.now() with get_ist_now() in relevant places
    # Be careful not to replace it everywhere if unnecessary, but consistency is good.
    # Specifically in validate_token_file andauthenticate_fyers
    
    # We will regex replace checks
    # Old: now = datetime.now()
    # New: now = get_ist_now()
    
    content = content.replace("now = datetime.now()", "now = get_ist_now()")
    
    # 2. FIX HEADER in validate_live_session
    # Old: headers = {"Authorization": f"Bearer {token}"}
    # New: headers = {"Authorization": f"{client_id}:{token}"}
    # But we need client_id. It's in env.
    
    # Logic update:
    # client_id = os.getenv("FYERS_CLIENT_ID")
    # headers = {"Authorization": f"{client_id}:{token}"}
    
    # Regex match the header line
    # Match: headers = {"Authorization": f"Bearer {token}"}
    # Replace with logic fetching ID
    
    pattern = r'headers\s*=\s*\{"Authorization":\s*f"Bearer\s*\{token\}"\}'
    replacement = r'client_id = os.getenv("FYERS_CLIENT_ID")\n        headers = {"Authorization": f"{client_id}:{token}"}'
    
    new_content = re.sub(pattern, replacement, content)
    
    if content == new_content:
        print("⚠️ Parsing 'Bearer' header failed (Maybe already patched or different format?)")
        # Try finding the line loosely
        if 'f"Bearer {token}"' in content:
             new_content = content.replace('f"Bearer {token}"', 'f"{os.getenv(\'FYERS_CLIENT_ID\')}:{token}"')
             print("✅ Used fallback replacement for Header")

    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("💾 Patched auth_fyers.py (IST Logic + Auth Header Fix)")

if __name__ == "__main__":
    try:
        patch_auth_fyers_fix()
    except Exception as e:
        print(f"❌ Error: {e}")
