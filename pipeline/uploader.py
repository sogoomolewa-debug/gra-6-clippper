# pipeline/uploader.py — Upload Short to YouTube via OAuth2

import json
import os
import pathlib
import time

import googleapiclient.discovery
import googleapiclient.http
import google.oauth2.credentials
import google.auth.transport.requests

import config


def get_youtube_client():
    """Build authenticated YouTube client."""
    try:
        oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
        if not oauth_json:
            print("[upload] error: YOUTUBE_OAUTH_JSON not set")
            return None

        data = json.loads(oauth_json)
        creds = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
        print("[upload] YouTube client authenticated")
        return youtube
    except Exception as e:
        print(f"[upload] auth error: {e}")
        return None


def generate_title(video_title: str) -> str:
    """Generate a punchy title with hashtags."""
    try:
        words = video_title.split()[:7]
        title = " ".join(words) + " #GTA6 #Shorts"
        if len(title) > 100:
            title = title[:97] + "..."
        return title
    except Exception as e:
        print(f"[upload] title generation error: {e}")
        return "GTA 6 Amazing Moment #GTA6 #Shorts"


def generate_description(
    visual_description: str,
    source_type: str,
    original_channel: str,
    original_url: str
) -> str:
    """Generate description with visual SEO hook, creator credit, and engagement CTA."""
    try:
        # Determine hashtags based on game version
        if source_type == "gta6":
            tags = "#GTA6 #GTAVI #GrandTheftAuto #Gaming #Shorts"
        else:
            tags = "#GTA5 #GTAV #GrandTheftAuto #Gaming #Shorts"

        description = (
            f"{visual_description}\n\n"
            f"🎥 Original Video: {original_url}\n"
            f"👤 Sourced from: @{original_channel}\n\n"
            f"Subscribe to BYNDUO for more epic GTA stunts! What stunt should we try next? 👇\n\n"
            f"{tags}"
        )
        return description
    except Exception as e:
        print(f"[upload] description generation error: {e}")
        return "#GTA6 #Shorts"


def upload_short(
    file_path: str,
    title: str,
    visual_description: str,
    source_type: str,
    original_channel: str,
    original_url: str
) -> str | None:
    """Upload video to YouTube as a Short."""
    try:
        youtube = get_youtube_client()
        if youtube is None:
            return None

        body = {
            "snippet": {
                "title": title,
                "description": generate_description(visual_description, source_type, original_channel, original_url),
                "tags": config.UPLOAD["tags"],
                "categoryId": config.UPLOAD["category_id"],
                "defaultLanguage": "en",
                "defaultAudioLanguage": "en"
            },
            "status": {
                "privacyStatus": config.UPLOAD["privacy_status"],
                "selfDeclaredMadeForKids": False
            }
        }


        media = googleapiclient.http.MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=5 * 1024 * 1024
        )

        print(f"[upload] starting upload: {file_path}")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        retries = 0
        max_retries = 3

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"[upload] {int(status.progress() * 100)}% complete")
            except Exception as e:
                if retries < max_retries:
                    retries += 1
                    print(f"[upload] transient error, retry {retries}/{max_retries}: {e}")
                    time.sleep(5)
                else:
                    print(f"[upload] fatal upload error: {e}")
                    return None

        video_id = response.get("id")
        if video_id:
            print(f"[upload] ✅ successfully uploaded: https://youtube.com/shorts/{video_id}")
            return video_id
        else:
            print("[upload] error: no video ID in response")
            return None

    except Exception as e:
        print(f"[upload] upload_short error: {e}")
        return None


if __name__ == "__main__":
    print("uploader.py requires OAuth credentials — configure secrets first")
