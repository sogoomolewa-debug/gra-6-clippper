# Helper script to generate YOUTUBE_OAUTH_JSON
# Run this on your LOCAL MACHINE, not in the cloud CLI.

from google_auth_oauthlib.flow import InstalledAppFlow
import json
import os

# 1. Download your OAuth Desktop client JSON from Google Cloud Console
# 2. Rename it to 'client_secrets.json' and place it in this folder
CLIENT_SECRETS_FILE = "client_secrets.json" 

# We need the 'upload' scope to post videos
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]

def main():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"Error: {CLIENT_SECRETS_FILE} not found.")
        print("Please download your OAuth JSON from Google Cloud Console and rename it.")
        return

    # Use the console-based flow (no local server)
    # This will print a URL for the user to visit and ask for a code
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, 
        SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    print("\n" + "="*50)
    print("1. Go to this URL in your browser:")
    print(auth_url)
    print("\n2. Authorize the app and COPY the code provided.")
    print("="*50 + "\n")
    
    code = input("Enter the authorization code: ").strip()
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    oauth_data = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri
    }
    
    print("\n" + "="*50)
    print("YOUR YOUTUBE_OAUTH_JSON (Copy the line below):")
    print("="*50)
    print(json.dumps(oauth_data))
    print("="*50 + "\n")
    print("Paste this into your GitHub Secrets as YOUTUBE_OAUTH_JSON")

if __name__ == "__main__":
    main()
