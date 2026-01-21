import os
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv

load_dotenv()

def get_fyers_model():
    """
    Authenticate with Fyers using the persistent token system.
    """
    client_id = os.getenv("FYERS_CLIENT_ID")
    if not client_id:
        raise ValueError("FYERS_CLIENT_ID not found in .env")
        
    # Use the UNIFIED robust engine auth module
    from engine.auth_fyers import validate_token_file
    access_token = validate_token_file()
    
    if not access_token:
        # Check environment variable as fallback (for CI or specialized setups)
        access_token = os.getenv("FYERS_ACCESS_TOKEN")
        
    if not access_token:
        # This is where we should ideally raise or trigger login
        # For compatibility with legacy code, we still raise the error
        # But prefill will now catch this and trigger interactive login
        raise ValueError("No valid Fyers token found. Run 'python engine/auth_fyers.py' or check Telegram.")
        
    fyers = fyersModel.FyersModel(client_id=client_id, token=access_token, is_async=False, log_path="")
    return fyers
