import os
import json
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv

load_dotenv()

# Config
# Note: When moving to a package, verify if .env loading still works from root
CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
SECRET_ID = os.getenv("FYERS_SECRET_ID")
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI")
# Store token in the root directory relative to execution
TOKEN_FILE = "fyers_token.json" 

def get_next_6am_expiry():
    """
    Calculates the timestamp for 6 AM on the next day.
    """
    now = datetime.now()
    next_day = now + timedelta(days=1)
    expiry_time = next_day.replace(hour=6, minute=0, second=0, microsecond=0)
    return expiry_time.timestamp()

def save_token(access_token):
    expiry = get_next_6am_expiry()
    data = {
        "access_token": access_token,
        "expiry": expiry,
        "expiry_readable": datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Token saved! Valid until: {data['expiry_readable']}")

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
        if datetime.now().timestamp() < data["expiry"]:
            return data["access_token"]
        return None
    except Exception:
        return None

def authenticate():
    token = load_token()
    if token:
        print("✅ Valid token found.")
        return token

    if not CLIENT_ID or not SECRET_ID:
        print("❌ Error: credentials not found in .env")
        return

    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_ID,
        redirect_uri=REDIRECT_URI,
        response_type="code"
    )

    generate_token_url = session.generate_authcode()
    print("\n🔐 Fyers Authentication Required")
    print(generate_token_url)
    try:
        webbrowser.open(generate_token_url)
    except:
        pass

    redirect_url = input("Paste the Redirect URL here: ").strip()
    try:
        parsed = urlparse(redirect_url)
        # Handle cases where full URL isn't pasted or has extra quotes
        if 'auth_code' not in redirect_url:
             # Maybe they just pasted the code? catch this case
             if len(redirect_url) > 50:
                 auth_code = redirect_url
             else:
                 print("❌ Invalid URL format.")
                 return
        else:
             auth_code = parse_qs(parsed.query)['auth_code'][0]
        
        print(f"🔍 Extracted Auth Code: {auth_code[:10]}...{auth_code[-10:]}")
        
        # Debug JWT expiry if possible
        try:
            import base64
            parts = auth_code.split('.')
            if len(parts) > 1:
                padding = len(parts[1]) % 4
                curr_ts = datetime.now().timestamp()
                payload = json.loads(base64.b64decode(parts[1] + "="*padding).decode('utf-8'))
                exp = payload.get('exp', 0)
                iat = payload.get('iat', 0)
                print(f"🕒 Token Issued: {datetime.fromtimestamp(iat)} | Expires: {datetime.fromtimestamp(exp)}")
                print(f"⏱️ Time remaining: {exp - curr_ts:.2f} seconds")
                if exp < curr_ts:
                    print("❌ CODE EXPIRED! Please generate a new one faster.")
                    return
        except Exception as e:
            print(f"⚠️ Could not decode JWT for debug: {e}")

    except Exception as e:
        print(f"❌ Failed to extract auth_code: {e}")
        return

    session.set_token(auth_code)
    response = session.generate_token()
    
    if response.get("code") == 200:
        access_token = response["access_token"]
        save_token(access_token)
        return access_token
    else:
        print(f"❌ Authentication Failed: {response}")
        return None

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # CLI Mode
        url_arg = sys.argv[1]
        print(f"🔗 Using URL from CLI: {url_arg[:20]}...")
        try:
            parsed = urlparse(url_arg)
            qs = parse_qs(parsed.query)
            if 'auth_code' in qs:
                auth_code = qs['auth_code'][0]
                session = fyersModel.SessionModel(
                    client_id=CLIENT_ID,
                    secret_key=SECRET_ID,
                    redirect_uri=REDIRECT_URI,
                    response_type="code"
                )
                session.set_token(auth_code)
                response = session.generate_token()
                if response.get("code") == 200:
                    save_token(response["access_token"])
                else:
                     print(f"❌ Authentication Failed: {response}")
            else:
                print("❌ No auth_code in URL")
        except Exception as e:
            print(f"❌ Error processing CLI URL: {e}")
    else:
        authenticate()
