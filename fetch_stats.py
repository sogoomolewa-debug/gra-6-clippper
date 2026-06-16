# fetch_stats.py — Weekly job: fetch YouTube stats for uploaded Shorts

import json
import os
from datetime import datetime
import pathlib

import config
from pipeline import channel_tracker



def get_youtube_client():
    """Build authenticated YouTube client with read-only scope."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
        if not oauth_json:
            print("[stats] error: YOUTUBE_OAUTH_JSON not set")
            return None

        data = json.loads(oauth_json)
        creds = Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.readonly"]
        )
        creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds)
        print("[stats] YouTube client authenticated")
        return youtube
    except Exception as e:
        print(f"[stats] auth error: {e}")
        return None


def fetch_video_stats(youtube, video_id: str) -> dict | None:
    """Fetch view, like, and comment counts for a video."""
    try:
        response = youtube.videos().list(
            part="statistics",
            id=video_id
        ).execute()

        items = response.get("items", [])
        if not items:
            print(f"[stats] no data found for {video_id}")
            return None

        stats = items[0]["statistics"]
        result = {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0))
        }
        return result
    except Exception as e:
        print(f"[stats] error fetching stats for {video_id}: {e}")
        return None


def needs_snapshot(entry: dict, label: str, hours: int) -> bool:
    """Check if a snapshot needs to be fetched for the given interval."""
    try:
        snapshots = entry.get("snapshots", {})
        if label not in snapshots:
            return True
        if snapshots[label].get("views", 0) != 0:
            return False  # Already fetched

        uploaded_at = entry.get("uploaded_at", "")
        # Handle ISO format with 'Z'
        uploaded_dt = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
        age_hours = (datetime.utcnow().replace(tzinfo=uploaded_dt.tzinfo) - uploaded_dt).total_seconds() / 3600
        return age_hours >= hours
    except Exception as e:
        print(f"[stats] needs_snapshot error: {e}")
        return False


def load_log() -> dict:
    """Load performance log."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        if not path.exists():
            return {"shorts": []}
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[stats] error loading log: {e}")
        return {"shorts": []}


def save_log(log: dict) -> None:
    """Save performance log."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[stats] log saved: {len(log.get('shorts', []))} entries")
    except Exception as e:
        print(f"[stats] error saving log: {e}")


def run() -> None:
    """Fetch stats for all Shorts that need snapshots."""
    try:
        youtube = get_youtube_client()
        if youtube is None:
            print("[stats] cannot proceed without YouTube client")
            return

        log = load_log()
        updates = 0

        for entry in log.get("shorts", []):
            for hours, label in config.LOGS["snapshot_intervals"]:
                if needs_snapshot(entry, label, hours):
                    stats = fetch_video_stats(youtube, entry["short_id"])
                    if stats:
                        entry["snapshots"][label] = stats
                        updates += 1
                        print(f"[stats] {entry['short_id']} @ {label}: {stats}")

        save_log(log)
        print("[stats] refreshing channel analytics...")
        channel_tracker.update_channel_analytics()
        print(f"[stats] complete — {updates} snapshots updated")
    except Exception as e:
        print(f"[stats] error: {e}")


if __name__ == "__main__":
    run()
