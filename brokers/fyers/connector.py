import os
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv
from . import auth

load_dotenv()

def get_fyers_model():
    """
    Authenticate with Fyers using the persistent token system.
    """
    client_id = os.getenv("FYERS_CLIENT_ID")
    if not client_id:
        raise ValueError("FYERS_CLIENT_ID not found in .env")
        
    # Load from the ROBUST engine auth module
    from engine.auth_fyers import validate_token_file
    access_token = validate_token_file()
    
    if not access_token:
        # Fallback
        access_token = os.getenv("FYERS_ACCESS_TOKEN")
        if not access_token:
            raise ValueError("No valid token. Please run 'python -m engine.auth_fyers --url ...' to login.")
        
    fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
    return fyers
