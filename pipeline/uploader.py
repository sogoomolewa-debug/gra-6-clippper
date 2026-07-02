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
        tags = config.get_hashtags(source_type)

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


def generate_engagement_comment(visual_description: str, moment_type: str = "") -> str:
    """Generate a casual first comment to boost engagement.

    Uses Groq to create a comment that sounds like a viewer reaction,
    not a creator. Designed to prime rewatching and comment section activity.
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            print("[upload] no GROQ_API_KEY — using fallback comment")
            return "nah that ending got me 💀"

        import requests
        prompt = (
            "Write ONE short casual YouTube comment (under 10 words) about this GTA clip. "
            "Sound like a real viewer who just watched it, not the creator. "
            "Use exactly 1 emoji at the end. "
            "Reference the specific action — don't be generic. "
            "Goal: make other viewers want to rewatch the clip. "
            "Do NOT use quotes. Output ONLY the comment text.\n\n"
            f"Visual description: {visual_description}\n"
            f"Moment type: {moment_type}"
        )

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 30,
                "temperature": 0.9
            },
            timeout=15
        )

        if response.status_code == 200:
            comment = response.json()["choices"][0]["message"]["content"].strip()
            comment = comment.strip('"').strip("'")
            print(f"[upload] engagement comment: {comment}")
            return comment
        else:
            print(f"[upload] comment generation failed: HTTP {response.status_code}")
            return "nah that ending got me 💀"
    except Exception as e:
        print(f"[upload] comment generation error: {e}")
        return "nah that ending got me 💀"


def get_youtube_client_for_comments():
    """Build YouTube client with comment posting scope (youtube.force-ssl).

    Separate from the upload client to avoid breaking uploads if comment
    scope isn't authorized. Returns None on any auth failure.
    """
    try:
        oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
        if not oauth_json:
            return None

        data = json.loads(oauth_json)
        creds = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    except Exception as e:
        print(f"[upload] comment auth error: {e}")
        return None


def post_first_comment(video_id: str, comment_text: str) -> bool:
    """Post a strategic first comment on the uploaded Short.

    Non-fatal — if this fails for any reason (scope, quota, network),
    the upload is unaffected. Logs the error and returns False.
    """
    try:
        youtube = get_youtube_client_for_comments()
        if youtube is None:
            print("[upload] skipping comment — no comment-scoped client")
            return False

        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    }
                }
            }
        ).execute()
        print(f"[upload] ✅ first comment posted: '{comment_text}'")
        return True
    except Exception as e:
        print(f"[upload] comment post error (non-fatal): {e}")
        return False


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
                "tags": config.get_upload_tags(),
                "categoryId": config.UPLOAD["category_id"],
                "defaultLanguage": "en",
                "defaultAudioLanguage": "en"
            },
            "status": {
                "privacyStatus": config.UPLOAD["privacy_status"],
                "selfDeclaredMadeForKids": False,  # COPPA: must always be explicit boolean
                "madeForKids": False
            }
        }

        # ── PRE-FLIGHT ASSERTION ──────────────────────────────────────
        # Fail loudly (crash the GitHub Action) if COPPA field is wrong.
        _status = body.get("status", {})
        assert "selfDeclaredMadeForKids" in _status, (
            "[upload] FATAL: selfDeclaredMadeForKids missing from upload payload"
        )
        assert isinstance(_status["selfDeclaredMadeForKids"], bool), (
            f"[upload] FATAL: selfDeclaredMadeForKids must be bool, got {type(_status['selfDeclaredMadeForKids'])}"
        )
        assert _status["selfDeclaredMadeForKids"] is False, (
            "[upload] FATAL: selfDeclaredMadeForKids must be False for gaming content"
        )
        assert body["snippet"].get("categoryId") == "20", (
            f"[upload] FATAL: categoryId must be '20' (Gaming), got {body['snippet'].get('categoryId')}"
        )
        print(f"[upload] pre-flight OK: categoryId=20, selfDeclaredMadeForKids=False")

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
