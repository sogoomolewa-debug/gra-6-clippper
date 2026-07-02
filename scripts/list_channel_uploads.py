# scripts/list_channel_uploads.py — List all uploads from the authenticated channel
# Fetches directly from YouTube API, not from performance_log.json
#
# Usage:
#   export YOUTUBE_OAUTH_JSON='...'
#   python scripts/list_channel_uploads.py

import json
import os
import sys

import google.oauth2.credentials
import google.auth.transport.requests
import googleapiclient.discovery


def get_youtube_client():
    """Build authenticated YouTube client."""
    oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
    if not oauth_json:
        print("[list] YOUTUBE_OAUTH_JSON not set")
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


def main():
    youtube = get_youtube_client()

    # Step 1: Get the channel's uploads playlist
    channels_resp = youtube.channels().list(
        part="contentDetails,snippet",
        mine=True
    ).execute()

    items = channels_resp.get("items", [])
    if not items:
        print("[list] ERROR: no channel found for authenticated user")
        sys.exit(1)

    channel = items[0]
    channel_title = channel["snippet"]["title"]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"[list] Channel: {channel_title}")
    print(f"[list] Uploads playlist: {uploads_playlist}")

    # Step 2: List all videos in the uploads playlist
    video_ids = []
    next_page = None

    while True:
        pl_resp = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page
        ).execute()

        for item in pl_resp.get("items", []):
            vid = item["contentDetails"]["videoId"]
            title = item["snippet"]["title"]
            published = item["snippet"].get("publishedAt", "?")
            video_ids.append(vid)
            print(f"  found: {vid} | {published[:16]} | {title[:60]}")

        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    print(f"\n[list] Total uploads: {len(video_ids)}")

    if not video_ids:
        return

    # Step 3: Fetch full status + stats for all videos (in batches of 50)
    all_results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        vids_resp = youtube.videos().list(
            part="status,statistics,snippet",
            id=",".join(batch)
        ).execute()

        for item in vids_resp.get("items", []):
            vid = item["id"]
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            stats = item.get("statistics", {})

            all_results.append({
                "video_id": vid,
                "title": snippet.get("title", ""),
                "published": snippet.get("publishedAt", "?")[:16],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "privacy": status.get("privacyStatus", "?"),
                "upload_status": status.get("uploadStatus", "?"),
                "category": snippet.get("categoryId", "?"),
                "declared_mfk": status.get("selfDeclaredMadeForKids", "MISSING"),
                "effective_mfk": status.get("madeForKids", "MISSING"),
            })

    # Step 4: Print summary
    print(f"\n{'=' * 120}")
    print(f"{'Video ID':<15} {'Published':<18} {'Views':>7} {'Likes':>6} {'Privacy':>9} "
          f"{'Status':>10} {'Cat':>4} {'Decl MFK':>10} {'Eff MFK':>9} {'Title'}")
    print("=" * 120)

    for r in sorted(all_results, key=lambda x: x["published"]):
        print(f"{r['video_id']:<15} {r['published']:<18} {r['views']:>7} {r['likes']:>6} "
              f"{r['privacy']:>9} {r['upload_status']:>10} {r['category']:>4} "
              f"{str(r['declared_mfk']):>10} {str(r['effective_mfk']):>9} "
              f"{r['title'][:40]}")

    # Flag 0-view videos
    zero_view = [r for r in all_results if r["views"] == 0]
    if zero_view:
        print(f"\n⚠ ZERO-VIEW VIDEOS ({len(zero_view)}):")
        for r in zero_view:
            print(f"  {r['video_id']} | {r['published']} | privacy={r['privacy']} | "
                  f"upload_status={r['upload_status']} | mfk={r['effective_mfk']} | {r['title'][:50]}")


if __name__ == "__main__":
    main()
