from google_auth_oauthlib.flow import InstalledAppFlow
import json
import os

CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CODE = "4/1AdkVLPyDjXKFKp2T7UUQ8DaRTDtAYiKGDAgzX578d1IXEwmJKajzvAy4Dv4"

def main():
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, 
        SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    flow.fetch_token(code=CODE)
    creds = flow.credentials
    
    oauth_data = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri
    }
    
    print("\n--- YOUR YOUTUBE_OAUTH_JSON ---")
    print(json.dumps(oauth_data))
    print("-------------------------------\n")

if __name__ == "__main__":
    main()
