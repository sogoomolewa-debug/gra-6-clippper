# pipeline/repost_monitor.py — Zero-view detection + auto-repost
# Checks recently uploaded shorts for 0 views after ~5 hours.
# If stuck at 0, deletes from YouTube and re-uploads the preserved video file.
# Max 1 repost attempt per video — never retries twice.

import json
import os
import pathlib
from datetime import datetime

import dotenv
dotenv.load_dotenv()

import config
from pipeline import uploader


REPOST_WINDOW_HOURS = 5       # check shorts older than this
REPOST_MAX_AGE_HOURS = 24     # don't repost shorts older than this
MAX_REPOSTS_PER_RUN = 1       # only repost one per run to avoid spam signals


def get_youtube_client():
    """Build authenticated YouTube client with upload + readonly scope."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
        if not oauth_json:
            print("[repost] error: YOUTUBE_OAUTH_JSON not set")
            return None

        data = json.loads(oauth_json)
        creds = Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly"
            ]
        )
        creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds)
        print("[repost] YouTube client authenticated")
        return youtube
    except Exception as e:
        print(f"[repost] auth error: {e}")
        return None


def fetch_view_count(youtube, video_id: str) -> int | None:
    """Fetch current view count for a video. Returns None if video not found."""
    try:
        response = youtube.videos().list(
            part="statistics",
            id=video_id
        ).execute()

        items = response.get("items", [])
        if not items:
            print(f"[repost] video {video_id} not found (maybe already deleted)")
            return None

        views = int(items[0]["statistics"].get("viewCount", 0))
        return views
    except Exception as e:
        print(f"[repost] error fetching views for {video_id}: {e}")
        return None


def delete_video(youtube, video_id: str) -> bool:
    """Delete a video from YouTube."""
    try:
        youtube.videos().delete(id=video_id).execute()
        print(f"[repost] ✅ deleted video {video_id}")
        return True
    except Exception as e:
        print(f"[repost] error deleting {video_id}: {e}")
        return False


def load_performance_log() -> dict:
    """Load performance log from disk."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        if not path.exists():
            return {"shorts": []}
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[repost] error loading log: {e}")
        return {"shorts": []}


def save_performance_log(log: dict) -> None:
    """Save performance log to disk."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[repost] log saved: {len(log.get('shorts', []))} entries")
    except Exception as e:
        print(f"[repost] error saving log: {e}")


def get_repost_candidates(log: dict) -> list:
    """Find uploaded shorts that are in the repost window and haven't been reposted yet."""
    candidates = []
    now = datetime.utcnow()

    for entry in log.get("shorts", []):
        # Only check actually uploaded shorts (not dry runs, skips, or errors)
        status = entry.get("status", "")
        short_id = entry.get("short_id", "")

        if status != "uploaded":
            continue
        if short_id.startswith("dryrun_"):
            continue

        # Skip if already reposted (max 1 attempt)
        if entry.get("repost_count", 0) >= 1:
            continue

        # Check age
        try:
            uploaded_at = entry.get("uploaded_at", "")
            uploaded_dt = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
            age_hours = (now.replace(tzinfo=uploaded_dt.tzinfo) - uploaded_dt).total_seconds() / 3600
        except Exception:
            continue

        # Must be in the repost window: old enough to check, not too old
        if age_hours < REPOST_WINDOW_HOURS:
            print(f"[repost] {short_id}: too young ({age_hours:.1f}h < {REPOST_WINDOW_HOURS}h), skipping")
            continue
        if age_hours > REPOST_MAX_AGE_HOURS:
            continue

        candidates.append((entry, age_hours))

    return candidates


def repost_video(youtube, entry: dict, log: dict) -> bool:
    """Delete a 0-view short and re-upload using the preserved video file.

    Returns True if re-upload succeeded.
    """
    try:
        old_short_id = entry["short_id"]
        video_file = entry.get("repost_video_path", "")

        if not video_file or not pathlib.Path(video_file).exists():
            print(f"[repost] ❌ no preserved video file for {old_short_id}")
            print(f"[repost]   expected at: {video_file}")
            # Mark as attempted so we don't retry
            entry["repost_count"] = entry.get("repost_count", 0) + 1
            entry["repost_notes"] = "no preserved video file found"
            return False

        # Step 1: Delete the old video
        if not delete_video(youtube, old_short_id):
            print(f"[repost] ❌ could not delete {old_short_id}, aborting repost")
            entry["repost_count"] = entry.get("repost_count", 0) + 1
            entry["repost_notes"] = "delete failed"
            return False

        # Step 2: Re-upload
        print(f"[repost] re-uploading {video_file}...")
        new_short_id = uploader.upload_short(
            file_path=video_file,
            title=entry.get("title", "GTA Moment #GTA6 #Shorts"),
            visual_description=entry.get("visual_description", ""),
            source_type=entry.get("source_type", "gta"),
            original_channel=entry.get("source_channel_title", ""),
            original_url=entry.get("source_url", "")
        )

        if not new_short_id:
            print(f"[repost] ❌ re-upload failed for {old_short_id}")
            entry["repost_count"] = entry.get("repost_count", 0) + 1
            entry["repost_notes"] = "re-upload failed"
            return False

        # Step 3: Update the log entry
        entry["repost_count"] = entry.get("repost_count", 0) + 1
        entry["original_short_id"] = old_short_id
        entry["short_id"] = new_short_id
        entry["short_url"] = f"https://youtube.com/shorts/{new_short_id}"
        entry["reposted_at"] = datetime.utcnow().isoformat() + "Z"
        entry["repost_notes"] = "auto-reposted due to 0 views"
        # Reset snapshots for the new upload
        entry["snapshots"] = {
            "24h": {"views": 0, "likes": 0, "comments": 0},
            "72h": {"views": 0, "likes": 0, "comments": 0},
            "7d": {"views": 0, "likes": 0, "comments": 0}
        }

        print(f"[repost] ✅ reposted: {old_short_id} → {new_short_id}")
        print(f"[repost]   new URL: https://youtube.com/shorts/{new_short_id}")
        return True

    except Exception as e:
        print(f"[repost] error during repost: {e}")
        entry["repost_count"] = entry.get("repost_count", 0) + 1
        entry["repost_notes"] = f"error: {e}"
        return False


def run() -> None:
    """Main entry point: check for 0-view shorts and repost if needed."""
    try:
        print("=" * 60)
        print(f"[repost] zero-view monitor starting: {datetime.utcnow().isoformat()}Z")
        print("=" * 60)

        youtube = get_youtube_client()
        if youtube is None:
            print("[repost] cannot proceed without YouTube client")
            return

        log = load_performance_log()
        candidates = get_repost_candidates(log)

        if not candidates:
            print("[repost] no shorts in repost window — nothing to check")
            save_performance_log(log)
            return

        print(f"[repost] found {len(candidates)} candidate(s) to check")
        reposts_done = 0

        for entry, age_hours in candidates:
            if reposts_done >= MAX_REPOSTS_PER_RUN:
                print(f"[repost] hit max reposts per run ({MAX_REPOSTS_PER_RUN}), stopping")
                break

            short_id = entry["short_id"]
            views = fetch_view_count(youtube, short_id)

            if views is None:
                print(f"[repost] {short_id}: could not fetch views, skipping")
                continue

            if views > 0:
                print(f"[repost] {short_id}: has {views} views after {age_hours:.1f}h — healthy ✅")
                continue

            # Zero views detected!
            print(f"[repost] ⚠ {short_id}: ZERO views after {age_hours:.1f}h — triggering repost")
            success = repost_video(youtube, entry, log)
            if success:
                reposts_done += 1

        save_performance_log(log)

        # Commit data files
        _commit_data_files()

        print(f"\n[repost] complete — {reposts_done} repost(s) performed")
        print("=" * 60)

    except Exception as e:
        print(f"[repost] fatal error: {e}")


def _commit_data_files() -> None:
    """Commit updated data files to git."""
    try:
        import subprocess

        if not pathlib.Path(".git").exists():
            return

        commands = [
            ["git", "config", "user.name", "pipeline-bot"],
            ["git", "config", "user.email", "bot@pipeline"],
            ["git", "add", "data/performance_log.json"],
        ]
        for cmd in commands:
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except Exception:
                pass

        try:
            diff = subprocess.run(
                ["git", "diff", "--staged", "--quiet"],
                capture_output=True, text=True, timeout=30
            )
            if diff.returncode != 0:
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                subprocess.run(
                    ["git", "commit", "-m", f"repost: {date_str}"],
                    capture_output=True, text=True, timeout=30
                )
                subprocess.run(
                    ["git", "push"],
                    capture_output=True, text=True, timeout=60
                )
                print("[repost] data files committed")
        except Exception:
            pass
    except Exception as e:
        print(f"[repost] git commit error: {e}")


if __name__ == "__main__":
    run()
