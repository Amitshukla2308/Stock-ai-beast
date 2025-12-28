import os
import hashlib
import requests
import json
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
SECRET_KEY = os.getenv("FYERS_SECRET_ID")
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI")

def get_hash(client_id, secret_key):
    # Fyers V3 AppIdHash = SHA256(client_id + ":" + secret_key)
    # Important: Ensure client_id is the App ID (e.g., XVZ12345), but typically it is passed as XVZ12345-100
    # Let's try hashing exactly as the SDK does
    data_string = f"{client_id}:{secret_key}"
    return hashlib.sha256(data_string.encode('utf-8')).hexdigest()

def manual_login(auth_code):
    app_id_hash = get_hash(CLIENT_ID, SECRET_KEY)
    
    url = "https://api-t1.fyers.in/api/v3/validate-authcode"
    
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash,
        "code": auth_code,
        # redirect_uri is technically not required in the body for validate-authcode in some versions, 
        # but let's send it if needed? The docs say:
        # { "grant_type": "authorization_code", "appIdHash": "...", "code": "..." }
        # Let's try strictly what is required.
    }
    
    print(f"\n🚀 Sending Manual Request to {url}")
    print(f"AppHash used: {app_id_hash}")
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        data = response.json()
        if data.get('s') == 'ok':
            print("✅ SUCCESS! Access Token Generated.")
            # Save it
            with open("fyers_token.json", "w") as f:
                # Mock expiry for now
                import time
                token_data = {
                    "access_token": data['access_token'],
                    "expiry": time.time() + 86400 # 24h
                }
                json.dump(token_data, f)
            print("Saved to fyers_token.json")
        else:
            print("❌ FAILED.")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    import sys
    url_arg = input("Paste Redirect URL: ").strip() if len(sys.argv) < 2 else sys.argv[1]
    
    if 'auth_code' in url_arg:
        try:
            parsed = urlparse(url_arg)
            qs = parse_qs(parsed.query)
            code = qs['auth_code'][0]
            manual_login(code)
        except Exception as e:
            print(f"Error parsing URL: {e}")
    else:
        # Maybe raw code?
        manual_login(url_arg)
