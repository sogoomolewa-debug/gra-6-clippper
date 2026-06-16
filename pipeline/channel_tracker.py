# pipeline/channel_tracker.py — Tracks and aggregates channel performance from logs

import json
import pathlib
from datetime import datetime
import config

ANALYTICS_PATH = pathlib.Path("data/channel_analytics.json")
LOG_PATH = pathlib.Path(config.LOGS["performance_path"])

def load_analytics() -> dict:
    """Load channel analytics from disk. Returns default structure if missing/corrupt."""
    if not ANALYTICS_PATH.exists():
        return {"last_updated": None, "channels": {}}
    try:
        with open(ANALYTICS_PATH, "r") as f:
            data = json.load(f)
            if "channels" not in data:
                data["channels"] = {}
            return data
    except Exception as e:
        print(f"[channel_tracker] error loading analytics: {e}")
        return {"last_updated": None, "channels": {}}

def save_analytics(analytics: dict) -> None:
    """Save channel analytics to disk with timestamp."""
    try:
        ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        analytics["last_updated"] = datetime.utcnow().isoformat() + "Z"
        with open(ANALYTICS_PATH, "w") as f:
            json.dump(analytics, f, indent=2)
        print("[channel_tracker] analytics saved")
    except Exception as e:
        print(f"[channel_tracker] error saving analytics: {e}")

def calculate_priority_score(channel_data: dict) -> tuple[float, str]:
    """
    1-10 priority score based on avg_views_7d, rejection rate, virality score.
    Returns (priority_score, confidence_level).
    Confidence: "low" if < 3 Shorts with data, "medium" 3-9, "high" 10+
    """
    perf = channel_data["performance"]
    prod = channel_data["production"]
    review = channel_data["review_scores"]

    shorts_with_data = perf["shorts_with_data"]
    if shorts_with_data == 0:
        return (5.0, "low")

    if shorts_with_data < 3:
        confidence = "low"
    elif shorts_with_data < 10:
        confidence = "medium"
    else:
        confidence = "high"

    avg_7d = perf["avg_views_7d"]
    if avg_7d >= 100000:
        view_score = 9.5
    elif avg_7d >= 50000:
        view_score = 8.5
    elif avg_7d >= 20000:
        view_score = 7.5
    elif avg_7d >= 10000:
        view_score = 6.5
    elif avg_7d >= 5000:
        view_score = 5.5
    elif avg_7d >= 1000:
        view_score = 4.0
    else:
        view_score = 2.0

    rejection_rate = prod["rejection_rate"]
    rejection_multiplier = max(0.5, 1.0 - (rejection_rate * 0.5))

    virality_boost = (review.get("avg_virality", 0.0) - 5.0) * 0.1

    raw_score = (view_score * rejection_multiplier) + virality_boost
    priority_score = round(max(1.0, min(10.0, raw_score)), 1)

    return (priority_score, confidence)

def aggregate_channel_data(log_entries: list[dict]) -> dict:
    """Groups performance log entries by channel title."""
    channel_map = {}
    for entry in log_entries:
        # The prompt says: channel_key = entry.get("source", {}).get("channel_title", "unknown")
        # Let's inspect pipeline.py log entry structure: we put source_video_id, but where is channel_title?
        # Wait, the prompt says "channel_key = entry.get('source', {}).get('channel_title', 'unknown')"
        # Let's also fallback to entry.get("channel_title") or queue if structure differs
        source_info = entry.get("source", {})
        if not source_info and "source_channel_title" in entry:
            channel_key = entry["source_channel_title"]
        elif not source_info and "channel_title" in entry:
            channel_key = entry["channel_title"]
        else:
            channel_key = source_info.get("channel_title", "unknown")
            
        if channel_key == "unknown" and "notes" in entry:
            # Let's check if channel title is stored differently in existing logs
            pass

        if channel_key not in channel_map:
            channel_map[channel_key] = {"channel_title": channel_key, "entries": []}
        channel_map[channel_key]["entries"].append(entry)
    return channel_map

def build_channel_record(channel_title: str, entries: list[dict]) -> dict:
    """Builds a single channel record from aggregated log entries."""
    # Status check: count uploaded and rejected
    uploaded = [e for e in entries if e.get("status") == "uploaded" or e.get("short_id", "").startswith("dryrun_") or "snapshots" in e]
    rejected = [e for e in entries if e.get("status") == "rejected" or e.get("status") == "skipped_non_gameplay"]

    # Since E2E/Dry Run logs might not have "status" explicitly set to "uploaded", 
    # we treat any entry that has a short_id and was not explicitly rejected as uploaded.
    # Let's double check if we need to filter status.
    # The prompt:
    # uploaded = [e for e in entries if e.get("status") == "uploaded"]
    # rejected = [e for e in entries if e.get("status") == "rejected"]
    # Let's support both the explicit "status" check and the presence of short_id.
    uploaded_explicit = [e for e in entries if e.get("status") == "uploaded"]
    rejected_explicit = [e for e in entries if e.get("status") == "rejected"]
    
    if not uploaded_explicit and not rejected_explicit:
        # Fallback for old/dryrun logs
        uploaded = [e for e in entries if e.get("short_id") and e.get("short_id") != "skipped_non_gameplay"]
        rejected = [e for e in entries if e.get("short_id") == "skipped_non_gameplay"]
    else:
        uploaded = uploaded_explicit
        rejected = rejected_explicit

    # filter those with 7d views > 0
    with_7d = [e for e in uploaded if e.get("performance", {}).get("7d", {}).get("views", 0) > 0 or e.get("snapshots", {}).get("7d", {}).get("views", 0) > 0]

    # Calculate average views
    def get_views(entry, label):
        perf_data = entry.get("performance", {}).get(label, {})
        if not perf_data:
            perf_data = entry.get("snapshots", {}).get(label, {})
        return perf_data.get("views", 0)

    avg_24h = int(sum(get_views(e, "24h") for e in with_7d) / max(len(with_7d), 1)) if with_7d else 0
    avg_7d = int(sum(get_views(e, "7d") for e in with_7d) / max(len(with_7d), 1)) if with_7d else 0
    
    # 30d entries
    avg_30d_entries = [e for e in uploaded if e.get("performance", {}).get("30d", {}).get("views", 0) > 0 or e.get("snapshots", {}).get("30d", {}).get("views", 0) > 0]
    avg_30d = int(sum(get_views(e, "30d") for e in avg_30d_entries) / max(len(avg_30d_entries), 1)) if avg_30d_entries else 0

    best = max(with_7d, key=lambda e: get_views(e, "7d")) if with_7d else None
    worst = min(with_7d, key=lambda e: get_views(e, "7d")) if with_7d else None

    # Virality scores & reviews
    virality_scores = [e.get("virality_signals", {}) for e in uploaded if e.get("virality_signals")]
    avg_virality = round(
        sum(sum(s.values()) / max(len(s), 1) for s in virality_scores) / max(len(virality_scores), 1), 1
    ) if virality_scores else 0.0

    avg_tech = round(
        sum(e.get("scores", {}).get("technical", 0) for e in uploaded) / max(len(uploaded), 1), 1
    ) if uploaded else 0.0

    avg_virality_score = round(
        sum(e.get("scores", {}).get("virality", 0) for e in uploaded) / max(len(uploaded), 1), 1
    ) if uploaded else 0.0

    signal_keys = ["wow_factor", "immediate_hook", "payoff_clarity", "rewatch_value",
                   "emotional_response", "shareability", "uniqueness", "trend_relevance"]
    signal_avgs = {}
    for key in signal_keys:
        vals = [e.get("virality_signals", {}).get(key, 0) for e in uploaded if e.get("virality_signals", {}).get(key, 0) > 0]
        signal_avgs[f"avg_{key}"] = round(sum(vals) / max(len(vals), 1), 1) if vals else 0.0

    dates = sorted([e.get("reviewed_at", "") for e in entries if e.get("reviewed_at")])
    if not dates:
        # Fallback to uploaded_at if reviewed_at is missing
        dates = sorted([e.get("uploaded_at", "") for e in entries if e.get("uploaded_at")])

    record = {
        "channel_title": channel_title,
        "production": {
            "total_sourced": len(entries),
            "total_uploaded": len(uploaded),
            "total_rejected": len(rejected),
            "rejection_rate": round(len(rejected) / max(len(entries), 1), 2)
        },
        "review_scores": {
            "avg_technical": avg_tech,
            "avg_virality": avg_virality_score,
            **signal_avgs
        },
        "performance": {
            "avg_views_24h": avg_24h,
            "avg_views_7d": avg_7d,
            "avg_views_30d": avg_30d,
            "total_views": sum(get_views(e, "7d") for e in with_7d),
            "shorts_with_data": len(with_7d),
            "best_short": {
                "short_id": best.get("short_id", "") if best else "",
                "views_7d": get_views(best, "7d") if best else 0,
                "hook_text": best.get("hook_text", "") if best else "",
                "uploaded_at": best.get("uploaded_at", "") if best else ""
            },
            "worst_short": {
                "short_id": worst.get("short_id", "") if worst else "",
                "views_7d": get_views(worst, "7d") if worst else 0,
                "hook_text": worst.get("hook_text", "") if worst else "",
                "uploaded_at": worst.get("uploaded_at", "") if worst else ""
            }
        },
        "priority_score": 5.0,
        "confidence": "low",
        "first_sourced": dates[0] if dates else "",
        "last_sourced": dates[-1] if dates else ""
    }

    priority_score, confidence = calculate_priority_score(record)
    record["priority_score"] = priority_score
    record["confidence"] = confidence
    return record

def update_channel_analytics() -> dict:
    """Updates and prints channel analytics leaderboard."""
    print("[channel_tracker] updating channel analytics…")
    if not LOG_PATH.exists():
        print("[channel_tracker] no performance log found")
        return load_analytics()

    try:
        with open(LOG_PATH, "r") as f:
            log = json.load(f)
    except Exception as e:
        print(f"[channel_tracker] error loading performance log: {e}")
        return load_analytics()

    entries = log.get("shorts", [])
    if not entries:
        print("[channel_tracker] no log entries yet")
        return load_analytics()

    channel_map = aggregate_channel_data(entries)
    analytics = load_analytics()
    for channel_title, data in channel_map.items():
        record = build_channel_record(channel_title, data["entries"])
        analytics["channels"][channel_title] = record
        print(f"[channel_tracker] {channel_title}: priority={record['priority_score']} confidence={record['confidence']} avg_7d_views={record['performance']['avg_views_7d']}")

    save_analytics(analytics)
    print_leaderboard(analytics)
    return analytics

def print_leaderboard(analytics: dict) -> None:
    """Print ranked leaderboard of channels by priority score."""
    channels = analytics.get("channels", {})
    if not channels:
        return
    ranked = sorted(channels.items(), key=lambda x: x[1].get("priority_score", 0), reverse=True)

    print("\n" + "=" * 60)
    print("CHANNEL LEADERBOARD (by priority score)")
    print("=" * 60)
    print(f"{'Rank':<5} {'Channel':<30} {'Score':<8} {'Avg 7d Views':<15} {'Confidence'}")
    print("-" * 60)
    for i, (channel_title, data) in enumerate(ranked, 1):
        print(f"{i:<5} {channel_title[:28]:<30} {data['priority_score']:<8} {data['performance']['avg_views_7d']:<15,} {data['confidence']}")
    print("=" * 60 + "\n")

def get_channel_priority(channel_title: str) -> float:
    """Returns 5.0 (neutral) if channel not yet tracked."""
    analytics = load_analytics()
    channel = analytics.get("channels", {}).get(channel_title, {})
    return channel.get("priority_score", 5.0)

if __name__ == "__main__":
    analytics = update_channel_analytics()
    print(f"\nTotal channels tracked: {len(analytics['channels'])}")
