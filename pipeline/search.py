# pipeline/search.py — Search YouTube for eligible videos across content tiers

import os
from datetime import datetime, timedelta

import isodate

import config
from pipeline.channel_tracker import get_channel_priority


def passes_title_blacklist(title: str, description: str = "") -> bool:
    """Return True if the title/description is clean (no blacklisted phrases).
    This is Gate 1 — runs before any download or API call to save quota.
    
    Title-only keywords: wrong-game names that often appear in GTA video
    descriptions for SEO but don't mean the video is wrong-game content.
    Full-text keywords: content format indicators that are bad regardless."""
    try:
        title_lower = title.lower()
        full_lower = (title + " " + description).lower()
        
        # These only block if in the TITLE — they appear in GTA descriptions for SEO
        TITLE_ONLY_BLACKLIST = [
            # Wrong-game names — appear in GTA descriptions for SEO
            "fortnite", "minecraft", "roblox", "call of duty", "cod",
            "red dead", "rdr", "cyberpunk", "saints row",
            "simulator", "android gameplay", "mobile game", "mobile gameplay",
            "car simulator", "truck simulator", "bus simulator",
            "real racing", "asphalt", "need for speed", "nfs",
            "beamng", "beam ng", "euro truck",
            # Generic words — block in title, not description
            "news", "update", "updates",
            "leak", "leaks", "leaked",
        ]
        for phrase in TITLE_ONLY_BLACKLIST:
            if phrase in title_lower:
                print(f"[search] title blacklist hit: '{phrase}' in title '{title[:60]}'")
                return False
        
        # These block if found ANYWHERE (title or description)
        for phrase in config.TITLE_BLACKLIST:
            if phrase in TITLE_ONLY_BLACKLIST:
                continue  # already checked above against title only
            if phrase in full_lower:
                print(f"[search] title blacklist hit: '{phrase}' in '{title[:60]}'")
                return False
        return True
    except Exception as e:
        print(f"[search] title blacklist error: {e}")
        return True  # fail-open to avoid blocking good content




def build_youtube(api_key: str):
    """Build YouTube Data API v3 client."""
    try:
        from googleapiclient.discovery import build
        return build("youtube", "v3", developerKey=api_key)
    except Exception as e:
        print(f"[search] error building YouTube client: {e}")
        return None


def search_recent_videos(youtube, queries: list, published_after: datetime, max_results: int = 10) -> list[str]:
    """Search YouTube for recent videos matching queries. Returns deduplicated video IDs."""
    try:
        all_ids = []
        seen = set()
        for query in queries:
            try:
                print(f"[search] querying: {query}")
                response = youtube.search().list(
                    part="id",
                    type="video",
                    q=query,
                    publishedAfter=published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    videoDuration="medium",
                    order="viewCount",
                    maxResults=max_results
                ).execute()
                for item in response.get("items", []):
                    vid = item["id"].get("videoId")
                    if vid and vid not in seen:
                        seen.add(vid)
                        all_ids.append(vid)
            except Exception as e:
                print(f"[search] error on query '{query}': {e}")
                continue
        print(f"[search] found {len(all_ids)} unique video IDs across {len(queries)} queries")
        return all_ids
    except Exception as e:
        print(f"[search] error in search_recent_videos: {e}")
        return []


def get_video_details(youtube, video_ids: list[str]) -> list[dict]:
    """Fetch detailed info for video IDs in batches of 50."""
    try:
        results = []
        channel_ids_map = {}  # channel_id -> list of result indices

        # Process in batches of 50
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            try:
                response = youtube.videos().list(
                    part="statistics,contentDetails,snippet",
                    id=",".join(chunk)
                ).execute()
                for item in response.get("items", []):
                    try:
                        snippet = item["snippet"]
                        stats = item["statistics"]
                        content = item["contentDetails"]
                        duration_seconds = int(isodate.parse_duration(content["duration"]).total_seconds())
                        channel_title = snippet.get("channelTitle", "Unknown")
                        video = {
                            "video_id": item["id"],
                            "url": f"https://youtube.com/watch?v={item['id']}",
                            "title": snippet.get("title", ""),
                            "description": snippet.get("description", ""),
                            "category_id": snippet.get("categoryId", ""),
                            "channel_id": snippet.get("channelId", ""),
                            "channel_title": channel_title,
                            "channel_url": f"https://youtube.com/@{channel_title.replace(' ', '')}",
                            "view_count": int(stats.get("viewCount", 0)),
                            "like_count": int(stats.get("likeCount", 0)),
                            "duration_seconds": duration_seconds,
                            "published_at": snippet.get("publishedAt", ""),
                            "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                            "subscriber_count": 0  # Will be filled in below
                        }
                        idx = len(results)
                        results.append(video)
                        cid = video["channel_id"]
                        if cid not in channel_ids_map:
                            channel_ids_map[cid] = []
                        channel_ids_map[cid].append(idx)
                    except Exception as e:
                        print(f"[search] error parsing video item: {e}")
                        continue
            except Exception as e:
                print(f"[search] error fetching video details chunk: {e}")
                continue

        # Fetch subscriber counts for all channels
        all_channel_ids = list(channel_ids_map.keys())
        for i in range(0, len(all_channel_ids), 50):
            chunk = all_channel_ids[i:i + 50]
            try:
                ch_response = youtube.channels().list(
                    part="statistics",
                    id=",".join(chunk)
                ).execute()
                for ch_item in ch_response.get("items", []):
                    cid = ch_item["id"]
                    sub_count = int(ch_item.get("statistics", {}).get("subscriberCount", 0))
                    for idx in channel_ids_map.get(cid, []):
                        results[idx]["subscriber_count"] = sub_count
            except Exception as e:
                print(f"[search] error fetching channel stats: {e}")
                continue

        print(f"[search] fetched details for {len(results)} videos")
        return results
    except Exception as e:
        print(f"[search] error in get_video_details: {e}")
        return []


def is_eligible(video: dict, tier: dict, source_type: str = "whitelist") -> bool:
    """Check if video meets all eligibility criteria for the given tier."""
    try:
        # Gate 1: Title blacklist (free, no API cost)
        if not passes_title_blacklist(video.get("title", ""), video.get("description", "")):
            print(f"[search] blocked video {video.get('video_id')} by title blacklist")
            return False

        # Block Rockstar Games official channels to avoid copying original source directly
        ch_title = video.get("channel_title", "").lower()
        if "rockstar games" in ch_title or "rockstargames" in ch_title:
            print(f"[search] blocked video {video.get('video_id')} from Rockstar Games channel: {video.get('channel_title')}")
            return False

        # Block blacklisted channels (known non-gameplay or problematic)
        channel_bl = getattr(config, "CHANNEL_BLACKLIST", [])
        if video.get("channel_title", "") in channel_bl:
            print(f"[search] blocked video {video.get('video_id')} from blacklisted channel: {video.get('channel_title')}")
            return False

        # Restrict to Gaming Category (ID: 20)
        cat_id = video.get("category_id", "")
        if cat_id != "20":
            print(f"[search] blocked video {video.get('video_id')} due to non-gaming category: {cat_id}")
            return False

        # Block negative keywords in title and description
        blacklist = ["rant", "essay", "podcast", "review", "opinion", "thoughts", "news", "drama", "speculation", "vlog", "rambles", "reaction", "reacts", "stream highlight", "let's talk", "face reveal", "real talk"]
        title_desc_lower = (video.get("title", "") + " " + video.get("description", "")).lower()
        for word in blacklist:
            if word in title_desc_lower:
                print(f"[search] blocked video {video.get('video_id')} due to blacklist word '{word}' in title/description")
                return False

        # Ensure it contains positive GTA keywords (for whitelist/gta tiers)
        gta_keywords = ["gta", "grand theft auto", "los santos", "vice city", "liberty city", "san andreas", "grove street", "niko bellic", "bellic", "trevor", "michael", "franklin", "lester", "rockstar"]
        has_gta = any(kw in title_desc_lower for kw in gta_keywords)
        if not has_gta:
            print(f"[search] blocked video {video.get('video_id')} due to missing GTA keywords in title/description")
            return False

        # For discovery candidates, require GTA keywords in the TITLE specifically
        # (not just description — many non-GTA games stuff GTA keywords in descriptions for SEO)
        if source_type == "candidate":
            title_lower = video.get("title", "").lower()
            has_gta_in_title = any(kw in title_lower for kw in gta_keywords)
            if not has_gta_in_title:
                print(f"[search] blocked discovery video {video.get('video_id')} — GTA keyword only in description, not title")
                return False

        published_at = video.get("published_at", "")
        # Remove 'Z' for fromisoformat and ensure it's UTC
        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_hours = (datetime.utcnow().replace(tzinfo=published_dt.tzinfo) - published_dt).total_seconds() / 3600

        if age_hours > tier["max_age_hours"]:
            return False
        if video["view_count"] < tier["min_views"]:
            return False
        if video["duration_seconds"] < config.ELIGIBILITY["min_duration_seconds"]:
            return False
        if video["duration_seconds"] > config.ELIGIBILITY["max_duration_seconds"]:
            return False
        if video.get("subscriber_count", 0) < tier["min_channel_subscribers"]:
            return False
        if video["view_count"] > 0:
            like_ratio = video["like_count"] / video["view_count"]
            if like_ratio < config.ELIGIBILITY["min_like_ratio"]:
                return False
        return True
    except Exception as e:
        print(f"[search] eligibility check error: {e}")
        return False


def score_video(video: dict) -> float:
    """Score a video based on views, recency, and engagement, and apply channel priority boost."""
    try:
        published_at = video.get("published_at", "")
        # Remove Z and tzinfo for local-agnostic comparison matching the new score_video signature
        published_dt = datetime.fromisoformat(published_at.replace("Z", ""))
        age_hours = (datetime.utcnow() - published_dt).total_seconds() / 3600
        recency_weight = 1.0 if age_hours < 12 else 0.7 if age_hours < 24 else 0.4

        like_ratio = video["like_count"] / max(video["view_count"], 1) if video.get("like_count") else 0
        base_score = (video["view_count"] * recency_weight) + (like_ratio * 50000)

        # Channel priority multiplier — high-performing channels surface higher
        channel_priority = get_channel_priority(video.get("channel_title", ""))
        channel_multiplier = 0.7 + (channel_priority / 10.0) * 0.8

        # priority=1 -> 0.78x, priority=5 -> 1.1x, priority=10 -> 1.5x
        final_score = round(base_score * channel_multiplier, 1)
        print(f"[search] {video['channel_title'][:20]}: base={base_score:.0f} x channel_mult={channel_multiplier:.2f} = {final_score:.0f}")
        return final_score
    except Exception as e:
        print(f"[search] scoring error: {e}")
        return 0.0


def get_top_videos(api_key: str, tier_name: str, limit: int = 5) -> list[dict]:
    """Get top eligible videos (either via global search or whitelist channels)."""
    try:
        youtube = build_youtube(api_key)
        if youtube is None:
            return []

        mode = "whitelist" if tier_name == "whitelist" else "search"
        if mode == "whitelist":
            print("[search] whitelist mode active, sourcing from curated channels")
            whitelist_channels = config.SOURCING.get("whitelist_channels", [])
            video_ids = []
            for ch in whitelist_channels:
                try:
                    ch_id = ch["id"]
                    # Replace 'UC' with 'UU' to get the uploads playlist ID
                    playlist_id = "UU" + ch_id[2:]
                    print(f"[search] fetching latest uploads for channel '{ch['name']}' (playlist: {playlist_id})")
                    
                    response = youtube.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=playlist_id,
                        maxResults=5
                    ).execute()
                    
                    for item in response.get("items", []):
                        snippet = item.get("snippet", {})
                        title = snippet.get("title", "")
                        description = snippet.get("description", "")
                        
                        # Pre-API Title Blacklist Check (free gate)
                        if not passes_title_blacklist(title, description):
                            print(f"[search] pre-API blacklisted '{title}' from channel {ch['name']}")
                            continue

                        # Pre-API Positive Keyword Check
                        text_lower = (title + " " + description).lower()
                        gta_keywords = ["gta", "grand theft auto", "los santos", "vice city", "liberty city", "san andreas", "grove street", "niko bellic", "bellic", "trevor", "michael", "franklin", "lester", "rockstar"]
                        has_gta = any(kw in text_lower for kw in gta_keywords)
                        if not has_gta:
                            print(f"[search] pre-API skipped non-GTA video '{title}' from channel {ch['name']}")
                            continue

                        vid = item["contentDetails"].get("videoId")
                        if vid and vid not in video_ids:
                            video_ids.append(vid)
                except Exception as e:
                    print(f"[search] error fetching uploads for channel {ch.get('name')}: {e}")
                    continue
            
            if not video_ids:
                print("[search] no videos found in whitelisted channels")
                return []
                
            details = get_video_details(youtube, video_ids)
            
            # Relaxed eligibility for whitelist
            tier = {
                "max_age_hours": config.SOURCING.get("max_age_hours", 168),
                "min_views": config.SOURCING.get("min_views", 2000),
                "min_channel_subscribers": 0,
            }
            
            eligible = [v for v in details if is_eligible(v, tier)]
            
            # Apply priority multipliers
            priority_map = {ch["id"]: ch.get("priority", 1.0) for ch in config.SOURCING.get("whitelist_channels", [])}
            for v in eligible:
                base_score = score_video(v)
                priority_multiplier = priority_map.get(v["channel_id"], 1.0)
                v["score"] = base_score * priority_multiplier
                
            eligible.sort(key=lambda x: x["score"], reverse=True)
            top = eligible[:limit]
            print(f"[search] whitelist mode found={len(eligible)} eligible, returning top {len(top)}")
            return top

        # Else: Fallback to global keyword search
        tier = None
        for t in config.CONTENT_TIERS:
            if t["name"] == tier_name:
                tier = t
                break
        if tier is None:
            print(f"[search] error: tier '{tier_name}' not found")
            return []

        published_after = datetime.utcnow() - timedelta(hours=tier["max_age_hours"])
        video_ids = search_recent_videos(youtube, tier["queries"], published_after)
        if not video_ids:
            print(f"[search] no videos found for tier {tier_name}")
            return []

        details = get_video_details(youtube, video_ids)
        eligible = [v for v in details if is_eligible(v, tier)]

        for v in eligible:
            v["score"] = score_video(v)

        eligible.sort(key=lambda x: x["score"], reverse=True)
        top = eligible[:limit]

        print(f"[search] tier={tier_name} found={len(eligible)} eligible, returning top {len(top)}")
        return top
    except Exception as e:
        print(f"[search] error in get_top_videos: {e}")
        return []


def search_discovery_videos(api_key: str, current_whitelist_ids: list[str], channel_blacklist: list[str]) -> list[dict]:
    """Search for candidate videos from channels not yet in the whitelist or blacklist.
    Returns video dicts with source_type='candidate' for pipeline tracking."""
    try:
        youtube = build_youtube(api_key)
        if youtube is None:
            return []

        discovery_cfg = getattr(config, "DISCOVERY", {})
        queries = discovery_cfg.get("queries", [])
        max_per_query = discovery_cfg.get("max_results_per_query", 5)
        min_views = discovery_cfg.get("min_views", 50000)

        # Build set of known channel IDs for fast lookup
        known_ids = set(current_whitelist_ids)

        # Normalise blacklist names to lowercase for comparison
        bl_lower = {name.lower() for name in channel_blacklist}

        candidate_ids = []
        seen_videos = set()

        for query in queries:
            try:
                print(f"[search] discovery query: {query}")
                response = youtube.search().list(
                    part="snippet",
                    type="video",
                    q=query,
                    videoDuration="medium",
                    order="viewCount",
                    maxResults=max_per_query
                ).execute()
                for item in response.get("items", []):
                    vid = item["id"].get("videoId")
                    snippet = item.get("snippet", {})
                    channel_id = snippet.get("channelId", "")
                    channel_title = snippet.get("channelTitle", "")
                    title = snippet.get("title", "")
                    description = snippet.get("description", "")

                    if not vid or vid in seen_videos:
                        continue
                    # Skip known whitelist channels
                    if channel_id in known_ids:
                        continue
                    # Skip blacklisted channels
                    if channel_title.lower() in bl_lower:
                        print(f"[search] discovery skipped blacklisted channel: {channel_title}")
                        continue
                    # Apply title blacklist
                    if not passes_title_blacklist(title, description):
                        continue

                    seen_videos.add(vid)
                    candidate_ids.append(vid)
            except Exception as e:
                print(f"[search] discovery query error '{query}': {e}")
                continue

        if not candidate_ids:
            print("[search] discovery found no candidate videos")
            return []

        # Fetch full details
        details = get_video_details(youtube, candidate_ids)

        # Build a dummy tier for discovery eligibility
        discovery_tier = {
            "max_age_hours": discovery_cfg.get("max_age_hours", 336),
            "min_views": min_views,
            "min_channel_subscribers": 0
        }

        # Filter: minimum views, apply title blacklist again on full data
        candidates = []
        for v in details:
            if v.get("channel_id") in known_ids:
                continue
            if v.get("channel_title", "").lower() in bl_lower:
                continue
            if not is_eligible(v, discovery_tier, source_type="candidate"):
                continue
            v["source_type"] = "candidate"
            v["score"] = score_video(v)
            candidates.append(v)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        print(f"[search] discovery found {len(candidates)} candidate videos")
        return candidates
    except Exception as e:
        print(f"[search] discovery error: {e}")
        return []


def fetch_comments(video_id: str, api_key: str) -> list[dict]:
    """Fetch top comment threads for a video using YouTube Data API."""
    try:
        from googleapiclient.discovery import build
        youtube = build_youtube(api_key)
        if not youtube:
            return []

        print(f"[search] fetching comments for video: {video_id}")
        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            textFormat="plainText",
            maxResults=100
        ).execute()

        comments = []
        for item in response.get("items", []):
            try:
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "text": snippet.get("textDisplay", ""),
                    "like_count": int(snippet.get("likeCount", 0)),
                    "published_at": snippet.get("publishedAt", "")
                })
            except Exception:
                continue
        print(f"[search] fetched {len(comments)} comments for {video_id}")
        return comments
    except Exception as e:
        print(f"[search] error fetching comments: {e}")
        return []


if __name__ == "__main__":
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        print("[search] YOUTUBE_API_KEY not set")
    else:
        results = get_top_videos(api_key, tier_name="gta6")
        for v in results:
            print(f"  {v['title']} | views={v['view_count']} | score={v['score']:.0f}")
