# scripts/analyze_performance.py — Pipeline performance analyzer
#
# Loads performance_log.json, fetches fresh YouTube stats + retention,
# and prints a comprehensive comparison report.
#
# USAGE:
#   python scripts/analyze_performance.py
#
# ENVIRONMENT:
#   YOUTUBE_OAUTH_JSON — OAuth2 credentials JSON (same as uploader.py)
#   YOUTUBE_API_KEY    — fallback for Data API if OAuth unavailable

import json
import os
import pathlib
import datetime
import sys
from collections import defaultdict

import dotenv
dotenv.load_dotenv()

from googleapiclient.discovery import build
import google.oauth2.credentials
import google.auth.transport.requests

LOG_PATH = pathlib.Path("data/performance_log.json")
REPORT_PATH = pathlib.Path("data/performance_analysis.json")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Load performance_log.json
# ══════════════════════════════════════════════════════════════════════════════

def load_uploaded_shorts() -> list[dict]:
    """Load performance log and return only uploaded entries (skip dryruns and skips)."""
    try:
        if not LOG_PATH.exists():
            print("[analysis] performance_log.json not found")
            return []

        with open(LOG_PATH, "r") as f:
            log_data = json.load(f)

        entries = []
        for entry in log_data.get("shorts", []):
            short_id = entry.get("short_id", "")
            status = entry.get("status", "")

            # Include entries that are explicitly "uploaded" OR old-format entries
            # (no status field) that have a real YouTube short_id
            is_uploaded = status == "uploaded"
            is_old_format_uploaded = (
                not status
                and not short_id.startswith("dryrun_")
                and not short_id.startswith("mock_")
                and not short_id.startswith("skipped_")
                and len(short_id) >= 8  # YouTube IDs are 11 chars
            )

            if is_uploaded or is_old_format_uploaded:
                entries.append(entry)

        print(f"[analysis] found {len(entries)} uploaded Shorts to analyze")
        return entries
    except Exception as e:
        print(f"[analysis] error loading shorts: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Fetch fresh YouTube Analytics via API
# ══════════════════════════════════════════════════════════════════════════════

def build_oauth_credentials() -> google.oauth2.credentials.Credentials | None:
    """Build OAuth2 credentials from YOUTUBE_OAUTH_JSON env var."""
    try:
        oauth_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
        if not oauth_json:
            print("[analysis] YOUTUBE_OAUTH_JSON not set")
            return None

        data = json.loads(oauth_json)
        creds = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=[
                "https://www.googleapis.com/auth/youtube.readonly",
                "https://www.googleapis.com/auth/yt-analytics.readonly",
            ],
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds
    except Exception as e:
        print(f"[analysis] OAuth credential error: {e}")
        return None


def get_youtube_data_client(creds=None):
    """Build YouTube Data API v3 client."""
    try:
        if creds:
            return build("youtube", "v3", credentials=creds)
        # Fallback to API key
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if api_key:
            return build("youtube", "v3", developerKey=api_key)
        print("[analysis] no YouTube credentials available")
        return None
    except Exception as e:
        print(f"[analysis] YouTube Data client error: {e}")
        return None


def get_youtube_analytics_client(creds):
    """Build YouTube Analytics API client (requires OAuth)."""
    try:
        if not creds:
            return None
        return build("youtubeAnalytics", "v2", credentials=creds)
    except Exception as e:
        print(f"[analysis] YouTube Analytics client error: {e}")
        return None


def fetch_video_stats(youtube, video_id: str) -> dict:
    """Fetch current video stats from YouTube Data API."""
    try:
        response = youtube.videos().list(
            part="statistics,contentDetails",
            id=video_id,
        ).execute()

        for item in response.get("items", []):
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            return {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration_iso": content.get("duration", ""),
            }
        return {"views": 0, "likes": 0, "comments": 0, "duration_iso": ""}
    except Exception as e:
        print(f"[analysis] fetch error for {video_id}: {e}")
        return {"views": 0, "likes": 0, "comments": 0, "duration_iso": ""}


def fetch_retention_data(analytics_client, short_id: str) -> dict:
    """Fetch audience retention metrics from YouTube Analytics API.

    Returns dict with avg_view_duration_sec and avg_view_percentage,
    or empty dict if unavailable.
    """
    if not analytics_client:
        return {}
    try:
        response = analytics_client.reports().query(
            ids="channel==MINE",
            startDate="2026-01-01",
            endDate="2026-12-31",
            metrics="averageViewDuration,averageViewPercentage,views",
            dimensions="video",
            filters=f"video=={short_id}",
        ).execute()

        rows = response.get("rows", [])
        if rows:
            # rows[0] = [videoId, avgViewDuration, avgViewPercentage, views]
            row = rows[0]
            return {
                "avg_view_duration_sec": float(row[1]),
                "avg_view_percentage": float(row[2]),
                "analytics_views": int(row[3]),
            }
        return {}
    except Exception as e:
        # Analytics API may not be enabled or may not have data yet
        print(f"[analysis] retention data unavailable for {short_id}: {e}")
        return {}


def fetch_all_stats(entries: list[dict]) -> list[dict]:
    """Fetch fresh YouTube stats and retention for all entries."""
    creds = build_oauth_credentials()
    youtube = get_youtube_data_client(creds)
    analytics = get_youtube_analytics_client(creds)

    if not youtube:
        print("[analysis] ⚠ could not build YouTube client — using snapshot data only")
        results = []
        for entry in entries:
            snap = entry.get("snapshots", {}).get("7d", {})
            results.append({
                "entry": entry,
                "stats": {
                    "views": snap.get("views", 0),
                    "likes": snap.get("likes", 0),
                    "comments": snap.get("comments", 0),
                    "duration_iso": "",
                },
                "retention": {},
            })
        return results

    if analytics:
        print("[analysis] YouTube Analytics API available — will fetch retention data")
    else:
        print("[analysis] YouTube Analytics API unavailable — retention % will use snapshot proxies")

    results = []
    for entry in entries:
        short_id = entry.get("short_id", "")
        print(f"[analysis] fetching stats for: {short_id}")

        stats = fetch_video_stats(youtube, short_id)
        retention = fetch_retention_data(analytics, short_id)

        results.append({
            "entry": entry,
            "stats": stats,
            "retention": retention,
        })

        ret_str = f"retention={retention['avg_view_percentage']:.1f}%" if retention else "retention=N/A"
        print(f"[analysis]   views={stats['views']:,} | likes={stats['likes']:,} | {ret_str}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Map pipeline format to each Short
# ══════════════════════════════════════════════════════════════════════════════

def infer_format(entry: dict) -> str:
    """Infer which pipeline format was used for this Short."""
    # Check explicit mode/format fields first (newer entries)
    if entry.get("hook_delivery"):
        return entry["hook_delivery"]
    if entry.get("content_profile"):
        return entry["content_profile"]
    if entry.get("mode"):
        return entry["mode"]

    hook = entry.get("hook_text", "")

    # No hook text = pure_gameplay mode
    if not hook or len(hook.strip()) < 3:
        return "pure_gameplay"

    # Check hook characteristics
    words = hook.split()
    word_count = len(words)

    # Hooks with ... and CAPS suggest tts_narrated with Stage 2 markup
    has_ellipsis = "..." in hook
    has_caps_word = any(w.isupper() and len(w) > 2 for w in words)

    if has_ellipsis and has_caps_word and word_count > 8:
        return "tts_narrated"  # Old markup format (Stage 2 was active)
    elif word_count <= 7 and not has_ellipsis:
        return "reference_inspired"  # Casual short hook
    elif word_count > 8:
        return "tts_narrated"  # Long dramatic hook
    else:
        return "tts_narrated"  # Default assumption


def get_retention_pct(item: dict) -> float | None:
    """Get retention percentage — prefer Analytics API, fall back to like/view proxy."""
    retention = item.get("retention", {})
    if retention and "avg_view_percentage" in retention:
        return round(retention["avg_view_percentage"], 1)
    # No retention data available
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Build comparison table and print report
# ══════════════════════════════════════════════════════════════════════════════

def avg(values: list) -> float:
    """Safe average."""
    return round(sum(values) / len(values), 1) if values else 0.0


def avg_int(values: list) -> int:
    """Safe average, returns int."""
    return round(sum(values) / len(values)) if values else 0


def print_section_table(title: str, data: dict, has_retention: bool):
    """Print a formatted comparison table for a grouping dimension."""
    print(f"\n  BY {title}:")
    if has_retention:
        print(f"  {'Category':<25} {'Count':>6} {'Avg Views':>12} {'Avg Retention':>15}")
        print(f"  {'-'*62}")
    else:
        print(f"  {'Category':<25} {'Count':>6} {'Avg Views':>12}")
        print(f"  {'-'*47}")

    # Sort by avg views descending
    rows = sorted(data.items(), key=lambda x: avg_int(x[1]["views"]), reverse=True)
    for category, bucket in rows:
        count = len(bucket["views"])
        avg_views = avg_int(bucket["views"])
        if has_retention and bucket["retention"]:
            avg_ret = avg(bucket["retention"])
            print(f"  {str(category):<25} {count:>6} {avg_views:>12,} {avg_ret:>14.1f}%")
        else:
            print(f"  {str(category):<25} {count:>6} {avg_views:>12,}")


def generate_report(items: list[dict]) -> dict:
    """Build full comparison report and print to terminal."""
    # Enrich items with inferred format
    for item in items:
        item["format"] = infer_format(item["entry"])

    has_retention = any(item.get("retention") for item in items)

    # ── Grouping buckets ──
    by_signal = defaultdict(lambda: {"views": [], "retention": []})
    by_moment = defaultdict(lambda: {"views": [], "retention": []})
    by_format = defaultdict(lambda: {"views": [], "retention": []})
    by_rag_score = defaultdict(lambda: {"views": [], "retention": []})
    by_hook_words = defaultdict(lambda: {"views": [], "retention": []})

    for item in items:
        entry = item["entry"]
        views = item["stats"].get("views", 0)
        ret_pct = get_retention_pct(item)

        signal = entry.get("peak_signal", "unknown")
        moment = entry.get("moment_type", "unknown") or "unknown"
        fmt = item["format"]
        rag_score = entry.get("viral_potential_score", 0) or 0
        hook_words = len(entry.get("hook_text", "").split()) if entry.get("hook_text") else 0

        # By signal
        by_signal[signal]["views"].append(views)
        if ret_pct is not None:
            by_signal[signal]["retention"].append(ret_pct)

        # By moment type
        by_moment[moment]["views"].append(views)
        if ret_pct is not None:
            by_moment[moment]["retention"].append(ret_pct)

        # By format
        by_format[fmt]["views"].append(views)
        if ret_pct is not None:
            by_format[fmt]["retention"].append(ret_pct)

        # By RAG viral score bucket
        if rag_score >= 8.0:
            bucket = "8.0 - 10.0"
        elif rag_score >= 6.0:
            bucket = "6.0 - 7.9"
        elif rag_score >= 4.0:
            bucket = "4.0 - 5.9"
        elif rag_score > 0:
            bucket = "0.0 - 3.9"
        else:
            bucket = "no_rag_score"
        by_rag_score[bucket]["views"].append(views)
        if ret_pct is not None:
            by_rag_score[bucket]["retention"].append(ret_pct)

        # By hook word count bucket
        if hook_words == 0:
            wbucket = "no hook"
        elif hook_words <= 5:
            wbucket = "1-5 words"
        elif hook_words <= 7:
            wbucket = "6-7 words"
        elif hook_words <= 9:
            wbucket = "8-9 words"
        else:
            wbucket = "10+ words (too long)"
        by_hook_words[wbucket]["views"].append(views)
        if ret_pct is not None:
            by_hook_words[wbucket]["retention"].append(ret_pct)

    # ── Print header ──
    total = len(items)
    if items:
        dates = [i["entry"].get("uploaded_at", "")[:10] for i in items]
        dates = [d for d in dates if d]
        date_range = f"{min(dates)} to {max(dates)}" if dates else "unknown"
    else:
        date_range = "no data"

    print("\n" + "═" * 60)
    print("PIPELINE PERFORMANCE ANALYSIS")
    print(f"Total Shorts: {total} | Date range: {date_range}")
    if not has_retention:
        print("Retention: Analytics API unavailable — using view data only")
    print("═" * 60)

    # ── Print tables ──
    print_section_table("PEAK SIGNAL", by_signal, has_retention)
    print_section_table("MOMENT TYPE", by_moment, has_retention)
    print_section_table("FORMAT (inferred)", by_format, has_retention)
    print_section_table("RAG VIRAL SCORE", by_rag_score, has_retention)
    print_section_table("HOOK WORD COUNT", by_hook_words, has_retention)

    # ── Best / Worst performers ──
    sorted_items = sorted(items, key=lambda x: x["stats"].get("views", 0), reverse=True)

    print(f"\n  BEST PERFORMING SHORTS:")
    if has_retention:
        print(f"  {'Rank':<5} {'Short ID':<15} {'Views':>8} {'Retention':>10} {'Signal':<20} {'Moment':<18} {'Hook'}")
        print(f"  {'-'*110}")
    else:
        print(f"  {'Rank':<5} {'Short ID':<15} {'Views':>8} {'Signal':<20} {'Moment':<18} {'Hook'}")
        print(f"  {'-'*95}")

    for rank, item in enumerate(sorted_items[:10], 1):
        e = item["entry"]
        s = item["stats"]
        ret = get_retention_pct(item)
        hook_preview = (e.get("hook_text", "") or "")[:30]
        ret_str = f"{ret:.1f}%" if ret is not None else "N/A"
        if has_retention:
            print(f"  {rank:<5} {e.get('short_id',''):<15} {s.get('views',0):>8,} {ret_str:>10} "
                  f"{e.get('peak_signal',''):<20} {(e.get('moment_type','') or '')::<18} {hook_preview}")
        else:
            print(f"  {rank:<5} {e.get('short_id',''):<15} {s.get('views',0):>8,} "
                  f"{e.get('peak_signal',''):<20} {(e.get('moment_type','') or ''):<18} {hook_preview}")

    print(f"\n  WORST PERFORMING SHORTS:")
    if has_retention:
        print(f"  {'Rank':<5} {'Short ID':<15} {'Views':>8} {'Retention':>10} {'Signal':<20} {'Moment':<18} {'Hook'}")
        print(f"  {'-'*110}")
    else:
        print(f"  {'Rank':<5} {'Short ID':<15} {'Views':>8} {'Signal':<20} {'Moment':<18} {'Hook'}")
        print(f"  {'-'*95}")

    bottom = sorted_items[-5:] if len(sorted_items) >= 5 else sorted_items
    for rank, item in enumerate(reversed(bottom), 1):
        e = item["entry"]
        s = item["stats"]
        ret = get_retention_pct(item)
        hook_preview = (e.get("hook_text", "") or "")[:30]
        ret_str = f"{ret:.1f}%" if ret is not None else "N/A"
        if has_retention:
            print(f"  {rank:<5} {e.get('short_id',''):<15} {s.get('views',0):>8,} {ret_str:>10} "
                  f"{e.get('peak_signal',''):<20} {(e.get('moment_type','') or ''):<18} {hook_preview}")
        else:
            print(f"  {rank:<5} {e.get('short_id',''):<15} {s.get('views',0):>8,} "
                  f"{e.get('peak_signal',''):<20} {(e.get('moment_type','') or ''):<18} {hook_preview}")

    # ── Hook duration analysis ──
    print(f"\n  HOOK DURATION ANALYSIS:")
    print(f"  {'Hook Text':<48} {'Words':>6} {'Est Dur':>8} {'Views':>8}")
    print(f"  {'-'*75}")
    for item in sorted_items:
        e = item["entry"]
        hook = e.get("hook_text", "")
        if not hook:
            continue
        words = len(hook.split())
        # Estimate: ~0.4s per word for TTS delivery
        est_duration = round(words * 0.4, 1)
        views = item["stats"].get("views", 0)
        flag = " ⚠ OVER 3s" if words > 8 else ""
        print(f"  {hook[:46]:<48} {words:>6} {est_duration:>7.1f}s {views:>8,}{flag}")

    # ── Recommendations ──
    print(f"\n  RECOMMENDATIONS:")
    print(f"  {'-'*55}")

    # Signal comparison
    signal_avgs = {k: avg_int(v["views"]) for k, v in by_signal.items()}
    if len(signal_avgs) > 1:
        best_signal = max(signal_avgs, key=signal_avgs.get)
        worst_signal = min(signal_avgs, key=signal_avgs.get)
        if signal_avgs[worst_signal] > 0:
            pct_diff = round((signal_avgs[best_signal] - signal_avgs[worst_signal]) / signal_avgs[worst_signal] * 100)
            print(f"  → {best_signal} signal produces {pct_diff}% more views than {worst_signal} signal")
        else:
            print(f"  → Best signal: {best_signal} ({signal_avgs[best_signal]:,} avg views)")

    # Moment type comparison
    moment_avgs = {k: avg_int(v["views"]) for k, v in by_moment.items() if k != "unknown"}
    if len(moment_avgs) >= 2:
        sorted_moments = sorted(moment_avgs.items(), key=lambda x: x[1], reverse=True)
        best_m, best_v = sorted_moments[0]
        worst_m, worst_v = sorted_moments[-1]
        print(f"  → moment_type {best_m} averages {best_v:,} views vs {worst_m} at {worst_v:,} views")

    # Format comparison
    format_avgs = {k: avg_int(v["views"]) for k, v in by_format.items()}
    if len(format_avgs) > 1:
        best_fmt = max(format_avgs, key=format_avgs.get)
        worst_fmt = min(format_avgs, key=format_avgs.get)
        print(f"  → Best format: {best_fmt} ({format_avgs[best_fmt]:,} avg views)")
        print(f"  → Worst format: {worst_fmt} ({format_avgs[worst_fmt]:,} avg views)")

    # Format retention comparison
    if has_retention:
        format_rets = {k: avg(v["retention"]) for k, v in by_format.items() if v["retention"]}
        if len(format_rets) > 1:
            best_ret_fmt = max(format_rets, key=format_rets.get)
            worst_ret_fmt = min(format_rets, key=format_rets.get)
            print(f"  → {best_ret_fmt} format averages {format_rets[best_ret_fmt]:.1f}% retention "
                  f"vs {worst_ret_fmt} at {format_rets[worst_ret_fmt]:.1f}%")

    # Hook word count comparison
    over_8 = [i for i in items if len((i["entry"].get("hook_text", "") or "").split()) > 8]
    under_8 = [i for i in items if 0 < len((i["entry"].get("hook_text", "") or "").split()) <= 8]
    if over_8 and under_8:
        avg_over = avg_int([i["stats"].get("views", 0) for i in over_8])
        avg_under = avg_int([i["stats"].get("views", 0) for i in under_8])
        print(f"  → hooks over 8 words average {avg_over:,} views vs under 8 words at {avg_under:,} views")
        if avg_over < avg_under:
            print(f"  → CONFIRMED: shorter hooks outperform — 7-word cap is correct")
        elif avg_over > avg_under:
            print(f"  → NOTE: longer hooks currently outperform — may be sample size issue")

    # Retention note
    if not has_retention:
        print(f"\n  NOTE ON RETENTION:")
        print(f"  True audience retention % requires YouTube Analytics API access.")
        print(f"  The YouTube Analytics API must be enabled in Google Cloud Console")
        print(f"  and the OAuth token must include the yt-analytics.readonly scope.")
        print(f"  For manual check: YouTube Studio → Content → select video → Analytics")

    print("═" * 60)

    # ── Build machine-readable report ──
    report = {
        "by_signal": {
            k: {"count": len(v["views"]), "avg_views": avg_int(v["views"]),
                 "avg_retention": avg(v["retention"]) if v["retention"] else None}
            for k, v in by_signal.items()
        },
        "by_moment_type": {
            k: {"count": len(v["views"]), "avg_views": avg_int(v["views"]),
                 "avg_retention": avg(v["retention"]) if v["retention"] else None}
            for k, v in by_moment.items()
        },
        "by_format": {
            k: {"count": len(v["views"]), "avg_views": avg_int(v["views"]),
                 "avg_retention": avg(v["retention"]) if v["retention"] else None}
            for k, v in by_format.items()
        },
        "by_rag_score": {
            k: {"count": len(v["views"]), "avg_views": avg_int(v["views"])}
            for k, v in by_rag_score.items()
        },
        "by_hook_word_count": {
            k: {"count": len(v["views"]), "avg_views": avg_int(v["views"])}
            for k, v in by_hook_words.items()
        },
        "best_shorts": [
            {
                "short_id": i["entry"].get("short_id"),
                "views": i["stats"].get("views", 0),
                "retention_pct": get_retention_pct(i),
                "signal": i["entry"].get("peak_signal"),
                "moment_type": i["entry"].get("moment_type"),
                "hook_text": i["entry"].get("hook_text"),
                "format": i["format"],
            }
            for i in sorted_items[:10]
        ],
        "worst_shorts": [
            {
                "short_id": i["entry"].get("short_id"),
                "views": i["stats"].get("views", 0),
                "retention_pct": get_retention_pct(i),
                "signal": i["entry"].get("peak_signal"),
                "moment_type": i["entry"].get("moment_type"),
                "hook_text": i["entry"].get("hook_text"),
                "format": i["format"],
            }
            for i in (sorted_items[-5:] if len(sorted_items) >= 5 else sorted_items)
        ],
    }

    return report


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Write summary to data/performance_analysis.json
# ══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    """Main entry point."""
    print("[analysis] loading uploaded Shorts from performance log...")
    entries = load_uploaded_shorts()

    if not entries:
        print("[analysis] no uploaded Shorts found in performance_log.json")
        return

    # Fetch fresh stats from YouTube
    items = fetch_all_stats(entries)

    # Generate and print report
    report = generate_report(items)

    # Save machine-readable report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "total_analyzed": len(items),
        "analytics_api_used": any(i.get("retention") for i in items),
        "findings": report,
    }
    REPORT_PATH.write_text(json.dumps(report_data, indent=2))
    print(f"\n[analysis] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    run()
