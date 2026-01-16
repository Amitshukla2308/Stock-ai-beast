import os
import sys
import json
from datetime import datetime
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv

load_dotenv()

TOKEN_FILE = "fyers_token.json"
CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
SECRET_ID = os.getenv("FYERS_SECRET_ID")
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI")

class FyersAuth:
    @staticmethod
    def get_token_path():
        if os.path.exists(TOKEN_FILE):
            return TOKEN_FILE
        if os.path.exists(f"/app/{TOKEN_FILE}"):
            return f"/app/{TOKEN_FILE}"
        return TOKEN_FILE

    @staticmethod
    def validate_token():
        token_path = FyersAuth.get_token_path()
        if not os.path.exists(token_path):
            return None
        try:
            with open(token_path, "r") as f:
                data = json.load(f)
                access_token = data.get("access_token")
                timestamp = data.get("timestamp")
            if not access_token or not timestamp:
                return None
            token_time = datetime.fromisoformat(timestamp)
            now = datetime.now()
            if token_time.date() < now.date():
                return None
            today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if token_time < today_6am and now >= today_6am:
                return None
            return access_token
        except Exception as e:
            print(f"Token Read Error: {e}")
            return None

    @staticmethod
    def authenticate():
        print("\nAuth Init...")
        if not CLIENT_ID or not SECRET_ID or not REDIRECT_URI:
            print("Error: Missing Creds")
            return None
        session = fyersModel.SessionModel(
            client_id=CLIENT_ID,
            secret_key=SECRET_ID,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )
        url = session.generate_authcode()
        print(f"\nClick: {url}")
        redirect_url = input("\nPaste URL: ").strip()
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(redirect_url)
            auth_code = parse_qs(parsed.query).get("auth_code", [None])[0]
            if not auth_code:
                print("Error: No Code")
                return None
            session.set_token(auth_code)
            res = session.generate_token()
            if res.get("code") == 200:
                FyersAuth.save_token(res["access_token"])
                print("Login OK")
                return res["access_token"]
            else:
                print(f"Login Failed: {res}")
                return None
        except Exception as e:
            print(f"Auth Error: {e}")
            return None

    @staticmethod
    def save_token(access_token):
        with open(TOKEN_FILE, "w") as f:
            json.dump({"access_token": access_token, "timestamp": datetime.now().isoformat()}, f)
        print(f"Saved {TOKEN_FILE}")

def load_token():
    return FyersAuth.validate_token()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if FyersAuth.validate_token():
            print("Valid")
            sys.exit(0)
        else:
            print("Invalid")
            sys.exit(1)
    else:
        if not FyersAuth.validate_token():
            FyersAuth.authenticate()
        else:
            print("Already Valid")
