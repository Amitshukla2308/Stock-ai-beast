import os
import json
import time
from datetime import datetime, timedelta
import hashlib
import requests
from dotenv import load_dotenv

def get_ist_now():
    # Returns IST aware datetime (UTC+5:30)
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


# Load environment variables
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(PROJ_ROOT, ".env")

import sys

# Logging Helper for n8n compatibility
def log(msg):
    # Print to stderr so stdout is reserved for the Result URL/JSON
    print(msg, file=sys.stderr)

# Load environment variables
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(PROJ_ROOT, ".env")

log(f"📂 Project Root: {PROJ_ROOT}")

if os.path.exists(DOTENV_PATH):
    # Fix for BOM in .env file (\ufeffFYERS_CLIENT_ID)
    from io import StringIO
    with open(DOTENV_PATH, "r", encoding="utf-8-sig") as f:
        env_content = f.read()
    load_dotenv(stream=StringIO(env_content), override=False)
    log("✅ .env file loaded (BOM stripped).")
else:
    log("⚠️ .env file NOT found at expected path.")

TOKEN_FILE = os.path.join(PROJ_ROOT, "fyers_token.json")

def get_env_var(name, prompt_msg):
    val = os.getenv(name)
    if not val:
        val = input(f"{prompt_msg}: ").strip()
    return val

def validate_token_file():
    """Checks if the token file exists and matches the 6 AM freshness rule."""
    if not os.path.exists(TOKEN_FILE):
        return None

    try:
        # Handle potential BOM from PowerShell created files
        try:
             with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
             with open(TOKEN_FILE, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
        
        # 6 AM RULE
        gen_str = data.get('generated_at')
        if not gen_str: return None
        
        gen_time = datetime.fromisoformat(str(gen_str))
        now = get_ist_now()
        
        if now.hour >= 6:
            session_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        else:
            session_start = (now - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            
        if gen_time < session_start:
            log(f"⚠️ Token from previous session (Generated {gen_time.strftime('%Y-%m-%d %H:%M')}). Expired.")
            return None
            
        return data.get('access_token')

    except Exception as e:
        log(f"⚠️ Error reading token file: {e}")
        return None

def validate_live_session(token):
    """
    Validates the token against the Fyers API (e.g., fetch profile).
    Returns True if valid, False otherwise.
    """
    if not token: return False
    
    try:
        client_id = os.getenv("FYERS_CLIENT_ID")
        headers = {"Authorization": f"{client_id}:{token}"}
        # Lightweight call: Get Profile
        resp = requests.get("https://api-t1.fyers.in/api/v3/profile", headers=headers, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("s") == "ok":
                log("✅ Fyers API Session Confirmed via Profile Check.")
                return True
        
        log(f"❌ Token validation failed (Code: {resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        log(f"⚠️ Network error during token check: {e}")
        return False

def authenticate_fyers(headless_url=None, generate_url_only=False):
    """
    Interactive or Headless flow to get Fyers Access Token.
    Args:
        headless_url (str): The redirect URL passed via CLI/n8n.
        generate_url_only (bool): If True, just print auth URL and exit.
    Returns:
        access_token (str)
    """
    # 0. Generate URL Mode
    if generate_url_only:
        client_id = get_env_var("FYERS_CLIENT_ID", "Enter Fyers Client ID")
        redirect_uri = "https://trade.fyers.in/api-login/redirect-url"
        from urllib.parse import quote_plus
        encoded_redirect = quote_plus(redirect_uri)
        auth_url = (
            f"https://api-t1.fyers.in/api/v3/generate-authcode?"
            f"client_id={client_id}&redirect_uri={encoded_redirect}&"
            f"response_type=code&state=None"
        )
        print(auth_url)
        return None

    # 1. Check for existing valid token (Skip if forcing update via headless)
    if not headless_url:
        existing_token = validate_token_file()
        if existing_token:
            # Re-read to get expiry for display
            try:
                 with open(TOKEN_FILE, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                 expiry_ts = data.get('expiry', 0)
                 expiry_str = datetime.fromtimestamp(expiry_ts).strftime('%Y-%m-%d %H:%M')
            except:
                 expiry_str = "Unknown"
                 
            log(f"✅ Found valid Fyers access token (Expires: {expiry_str})") 
            return existing_token

    log("\n🔐 Fyers Authentication Initiated...")
    
    # 2. Get Credentials
    client_id = get_env_var("FYERS_CLIENT_ID", "Enter Fyers Client ID")
    secret_id = get_env_var("FYERS_SECRET_ID", "Enter Fyers Secret ID")
    redirect_uri = "https://trade.fyers.in/api-login/redirect-url"
    
    # 3. Generate Auth URL (Only needed if NOT headless)
    if not headless_url:
        grant_type = "authorization_code"
        response_type = "code"
        state = "None"
        
        from urllib.parse import quote_plus
        encoded_redirect = quote_plus(redirect_uri)
        
        auth_url = (
            f"https://api-t1.fyers.in/api/v3/generate-authcode?"
            f"client_id={client_id}&redirect_uri={encoded_redirect}&"
            f"response_type={response_type}&state={state}"
        )
        
        print("\n👉 ACTION REQUIRED:")
        print(f"1. Open this URL in your browser:\n{auth_url}\n")
        print("2. Login and you will be redirected to a page.")
        print(f"3. Copy the FULL URL of that redirected page and paste it below.", file=sys.stderr)
        
        full_url = input("\n🔗 Paste Redirected URL here: ").strip()
    else:
        log(f"🤖 Headless Mode: Using provided URL/Code")
        full_url = headless_url
    
    # 4. Extract Auth Code
    auth_code = ""
    if "auth_code=" in full_url:
        import re
        match = re.search(r'auth_code=([^&]+)', full_url)
        if match:
            auth_code = match.group(1)
    else:
        auth_code = full_url
        
    if not auth_code:
        raise ValueError("Could not extract auth_code from input.")

    log("\n🔄 Exchanging auth code for access token...")

    # 5. Generate SHA256 Hash (AppIdHash)
    # Format: SHA256(client_id:secret_id)
    app_id_hash_str = f"{client_id}:{secret_id}"
    app_id_hash = hashlib.sha256(app_id_hash_str.encode('utf-8')).hexdigest()
    
    # 6. Validate Auth Code via API
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash,
        "code": auth_code,
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    resp = requests.post("https://api-t1.fyers.in/api/v3/validate-authcode", json=payload, headers=headers)
    
    if resp.status_code != 200:
        print(f"❌ API Error: {resp.text}")
        raise Exception("Authentication Failed")
        
    resp_json = resp.json()
    
    if resp_json.get("s") == "ok":
        access_token = resp_json.get("access_token")
        
        # Calculate strict expiry (Next Day 6 AM)
        now = get_ist_now()
        if now.hour >= 6:
            expiry_dt = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        else:
            expiry_dt = now.replace(hour=6, minute=0, second=0, microsecond=0)
        
        expiry_ts = int(expiry_dt.timestamp())
        
        token_data = {
            "access_token": access_token,
            "expiry": expiry_ts,
            "generated_at": str(now)
        }
        
        # 7. Save to File
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f, indent=4)
            
        print("✅ Token successfully saved to fyers_token.json!")
        return access_token
    else:
        log(f"❌ Auth Failed: {resp_json.get('message')}")
        raise Exception(f"Auth Failed: {resp_json}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fyers Auth Utility")
    parser.add_argument("--url", type=str, help="Redirect URL with auth_code (Headless Mode)")
    parser.add_argument("--generate-url", action="store_true", help="Print Auth URL and exit")
    parser.add_argument("--check-token", action="store_true", help="Check for valid token, print status or generate URL")
    args = parser.parse_args()

    try:
        # New smart check mode for n8n
        if args.check_token:
            existing_token = validate_token_file()
            if existing_token:
                # Token is valid - inform user
                try:
                    with open(TOKEN_FILE, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                    gen_time = datetime.fromisoformat(str(data['generated_at']))
                    expiry_ts = data.get('expiry', 0)
                    expiry_dt = datetime.fromtimestamp(expiry_ts)
                    
                    print(f"✅ Active Fyers Session")
                    print(f"📅 Generated: {gen_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"⏰ Expires: {expiry_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"\nNo need to login again. Your token is valid until 6 AM tomorrow.")
                except Exception as e:
                    print(f"Token exists but couldn't read details: {e}")
            else:
                # No valid token - generate URL
                authenticate_fyers(generate_url_only=True)
        else:
            # Original modes
            authenticate_fyers(headless_url=args.url, generate_url_only=args.generate_url)
    except KeyboardInterrupt:
        print("\n🚫 Auth Cancelled.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import sys
        sys.exit(1)

