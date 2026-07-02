# scripts/diagnose_videos.py — Check YouTube video status metadata
# Run locally or via workflow_dispatch to inspect selfDeclaredMadeForKids
# and other status fields for uploaded Shorts.
#
# Usage:
#   export YOUTUBE_OAUTH_JSON='{"client_id":"...","client_secret":"...","refresh_token":"...","token_uri":"..."}'
#   python scripts/diagnose_videos.py [VIDEO_ID ...]
#
# If no IDs are passed, reads all real uploads from data/performance_log.json.

import json
import os
import sys
import pathlib

import google.oauth2.credentials
import google.auth.transport.requests
import googleapiclient.discovery


def get_youtube_client():
    """Build authenticated YouTube client with readonly scope."""
    oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
    if not oauth_json:
        print("[diagnose] YOUTUBE_OAUTH_JSON not set")
        sys.exit(1)

    data = json.loads(oauth_json)
    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.readonly"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


def diagnose_video(youtube, video_id: str) -> dict | None:
    """Fetch full status + snippet for a single video."""
    try:
        response = youtube.videos().list(
            part="status,snippet,statistics",
            id=video_id
        ).execute()

        items = response.get("items", [])
        if not items:
            print(f"  {video_id}: NOT FOUND (deleted or invalid ID)")
            return None

        item = items[0]
        status = item.get("status", {})
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})

        result = {
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "categoryId": snippet.get("categoryId", "MISSING"),
            "privacyStatus": status.get("privacyStatus", "MISSING"),
            "uploadStatus": status.get("uploadStatus", "MISSING"),
            "selfDeclaredMadeForKids": status.get("selfDeclaredMadeForKids", "MISSING"),
            "madeForKids": status.get("madeForKids", "MISSING"),
            "publicStatsViewable": status.get("publicStatsViewable", "MISSING"),
            "rejectionReason": status.get("rejectionReason", None),
            "failureReason": status.get("failureReason", None),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
        }

        # Flag mismatch between declared and effective
        declared = result["selfDeclaredMadeForKids"]
        effective = result["madeForKids"]
        if declared != "MISSING" and effective != "MISSING" and declared != effective:
            result["MFK_MISMATCH"] = True
        else:
            result["MFK_MISMATCH"] = False

        return result
    except Exception as e:
        print(f"  {video_id}: ERROR — {e}")
        return None


def get_video_ids_from_log() -> list[str]:
    """Extract real (non-dryrun) upload IDs from performance log."""
    log_path = pathlib.Path("data/performance_log.json")
    if not log_path.exists():
        print("[diagnose] data/performance_log.json not found")
        return []

    with open(log_path) as f:
        data = json.load(f)

    ids = []
    for entry in data.get("shorts", []):
        sid = entry.get("short_id", "")
        if sid and not sid.startswith("dryrun") and not sid.startswith("skipped") and not sid.startswith("mock"):
            if entry.get("status") == "uploaded":
                ids.append(sid)
    return ids


def main():
    video_ids = sys.argv[1:] if len(sys.argv) > 1 else get_video_ids_from_log()

    if not video_ids:
        print("[diagnose] no video IDs to check")
        sys.exit(1)

    print(f"[diagnose] checking {len(video_ids)} video(s)...")
    youtube = get_youtube_client()

    results = []
    for vid in video_ids:
        print(f"\n  Checking {vid}...")
        result = diagnose_video(youtube, vid)
        if result:
            results.append(result)

    # Print summary table
    print("\n" + "=" * 100)
    print(f"{'Video ID':<15} {'Views':>8} {'Privacy':>10} {'Upload':>12} {'Category':>10} "
          f"{'Declared MFK':>14} {'Effective MFK':>15} {'MISMATCH':>10}")
    print("=" * 100)

    for r in results:
        mismatch = "⚠ YES" if r["MFK_MISMATCH"] else "—"
        print(f"{r['video_id']:<15} {r['views']:>8} {r['privacyStatus']:>10} "
              f"{r['uploadStatus']:>12} {r['categoryId']:>10} "
              f"{str(r['selfDeclaredMadeForKids']):>14} "
              f"{str(r['madeForKids']):>15} {mismatch:>10}")

    # Flag any issues
    print()
    issues = [r for r in results if r["MFK_MISMATCH"] or r["rejectionReason"] or r["failureReason"]]
    if issues:
        print("⚠ ISSUES FOUND:")
        for r in issues:
            if r["MFK_MISMATCH"]:
                print(f"  {r['video_id']}: declared={r['selfDeclaredMadeForKids']} but effective={r['madeForKids']}")
            if r["rejectionReason"]:
                print(f"  {r['video_id']}: rejection reason = {r['rejectionReason']}")
            if r["failureReason"]:
                print(f"  {r['video_id']}: failure reason = {r['failureReason']}")
    else:
        print("✅ No madeForKids mismatches or rejection/failure reasons found.")

    zero_view = [r for r in results if r["views"] == 0]
    if zero_view:
        print(f"\n⚠ Videos with 0 views:")
        for r in zero_view:
            print(f"  {r['video_id']}: privacy={r['privacyStatus']}, upload={r['uploadStatus']}, "
                  f"madeForKids={r['madeForKids']}")


if __name__ == "__main__":
    main()
