# scripts/fix_stuck_videos.py — Fix selfDeclaredMadeForKids on stuck videos
# Uses videos.update to explicitly set selfDeclaredMadeForKids=false,
# then re-reads via videos.list to confirm.
#
# Usage:
#   export YOUTUBE_OAUTH_JSON='{"client_id":"...","client_secret":"...","refresh_token":"...","token_uri":"..."}'
#   python scripts/fix_stuck_videos.py VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3
#
# Requires youtube.force-ssl or youtube scope (NOT youtube.upload — that's insert only).

import json
import os
import sys

import google.oauth2.credentials
import google.auth.transport.requests
import googleapiclient.discovery


def get_youtube_client():
    """Build authenticated YouTube client with full youtube scope."""
    oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
    if not oauth_json:
        print("[fix] YOUTUBE_OAUTH_JSON not set")
        sys.exit(1)

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


def read_video_status(youtube, video_id: str) -> dict | None:
    """Read current status for a video."""
    try:
        response = youtube.videos().list(
            part="status,snippet,statistics",
            id=video_id
        ).execute()

        items = response.get("items", [])
        if not items:
            return None

        item = items[0]
        return {
            "video_id": video_id,
            "title": item.get("snippet", {}).get("title", ""),
            "categoryId": item.get("snippet", {}).get("categoryId", "?"),
            "privacyStatus": item.get("status", {}).get("privacyStatus", "?"),
            "selfDeclaredMadeForKids": item.get("status", {}).get("selfDeclaredMadeForKids", "MISSING"),
            "madeForKids": item.get("status", {}).get("madeForKids", "MISSING"),
            "views": int(item.get("statistics", {}).get("viewCount", 0)),
        }
    except Exception as e:
        print(f"  [fix] error reading {video_id}: {e}")
        return None


def fix_video(youtube, video_id: str) -> bool:
    """Update a video's status to explicitly declare not-made-for-kids."""
    try:
        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "selfDeclaredMadeForKids": False,
                    "privacyStatus": "public",
                    "embeddable": True
                }
            }
        ).execute()
        print(f"  [fix] ✅ updated {video_id}: selfDeclaredMadeForKids=False")
        return True
    except Exception as e:
        print(f"  [fix] ❌ failed to update {video_id}: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_stuck_videos.py VIDEO_ID_1 [VIDEO_ID_2 ...]")
        print("\nIf you don't know which IDs are stuck, run diagnose_videos.py first.")
        sys.exit(1)

    video_ids = sys.argv[1:]
    print(f"[fix] targeting {len(video_ids)} video(s): {', '.join(video_ids)}")

    youtube = get_youtube_client()

    results = []

    for vid in video_ids:
        print(f"\n{'─' * 60}")
        print(f"  Video: {vid}")

        # Read BEFORE state
        before = read_video_status(youtube, vid)
        if before is None:
            print(f"  ⚠ Video not found — skipping")
            results.append({"video_id": vid, "action": "NOT FOUND"})
            continue

        print(f"  BEFORE: declared={before['selfDeclaredMadeForKids']}, "
              f"effective={before['madeForKids']}, views={before['views']}")

        # Apply fix
        success = fix_video(youtube, vid)
        if not success:
            results.append({
                "video_id": vid,
                "before_declared": before["selfDeclaredMadeForKids"],
                "before_effective": before["madeForKids"],
                "action": "UPDATE FAILED",
            })
            continue

        # Read AFTER state
        after = read_video_status(youtube, vid)
        if after is None:
            print(f"  ⚠ Could not re-read video after update")
            results.append({
                "video_id": vid,
                "before_declared": before["selfDeclaredMadeForKids"],
                "before_effective": before["madeForKids"],
                "action": "UPDATED (verify manually)",
            })
            continue

        print(f"  AFTER:  declared={after['selfDeclaredMadeForKids']}, "
              f"effective={after['madeForKids']}, views={after['views']}")

        results.append({
            "video_id": vid,
            "before_declared": before["selfDeclaredMadeForKids"],
            "before_effective": before["madeForKids"],
            "action": "FIXED",
            "after_declared": after["selfDeclaredMadeForKids"],
            "after_effective": after["madeForKids"],
        })

    # Summary table
    print(f"\n{'=' * 90}")
    print(f"{'Video ID':<15} {'Before Declared':>16} {'Before Effective':>17} "
          f"{'Action':>12} {'After Declared':>15} {'After Effective':>16}")
    print("=" * 90)

    for r in results:
        print(f"{r['video_id']:<15} "
              f"{str(r.get('before_declared', '?')):>16} "
              f"{str(r.get('before_effective', '?')):>17} "
              f"{r.get('action', '?'):>12} "
              f"{str(r.get('after_declared', '—')):>15} "
              f"{str(r.get('after_effective', '—')):>16}")

    print()
    fixed = [r for r in results if r.get("action") == "FIXED"]
    failed = [r for r in results if "FAIL" in r.get("action", "")]
    print(f"✅ Fixed: {len(fixed)} | ❌ Failed: {len(failed)} | Total: {len(results)}")


if __name__ == "__main__":
    main()
