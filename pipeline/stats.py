# pipeline/stats.py — Analytics module for performance analysis

import json
from typing import Dict, List
from collections import defaultdict


def analyze_peak_signals(log: dict) -> dict:
    """
    Analyze which peak detection signals perform best.

    Returns dict with:
    - by_signal: Performance breakdown by peak_signal type
    - summary: Overall statistics
    """
    try:
        shorts = log.get("shorts", [])

        # Filter to uploaded shorts only (skip rejections)
        uploaded = [s for s in shorts if s.get("status") == "uploaded"]

        if not uploaded:
            return {
                "error": "No uploaded shorts found in log",
                "total_entries": len(shorts),
                "uploaded": 0
            }

        # Group by peak_signal
        by_signal = defaultdict(lambda: {
            "count": 0,
            "total_views_24h": 0,
            "total_views_72h": 0,
            "total_views_7d": 0,
            "total_likes_24h": 0,
            "total_likes_72h": 0,
            "total_likes_7d": 0,
            "avg_clip_duration": 0,
            "avg_peak_position_pct": 0,
            "shorts": []
        })

        for short in uploaded:
            signal = short.get("peak_signal", "unknown")
            data = by_signal[signal]

            data["count"] += 1
            data["total_views_24h"] += short.get("snapshots", {}).get("24h", {}).get("views", 0)
            data["total_views_72h"] += short.get("snapshots", {}).get("72h", {}).get("views", 0)
            data["total_views_7d"] += short.get("snapshots", {}).get("7d", {}).get("views", 0)
            data["total_likes_24h"] += short.get("snapshots", {}).get("24h", {}).get("likes", 0)
            data["total_likes_72h"] += short.get("snapshots", {}).get("72h", {}).get("likes", 0)
            data["total_likes_7d"] += short.get("snapshots", {}).get("7d", {}).get("likes", 0)
            data["avg_clip_duration"] += short.get("clip_duration", 0)
            data["avg_peak_position_pct"] += short.get("peak_position_pct", 0)
            data["shorts"].append({
                "short_id": short.get("short_id"),
                "title": short.get("title", "")[:50],
                "views_24h": short.get("snapshots", {}).get("24h", {}).get("views", 0)
            })

        # Calculate averages
        for signal, data in by_signal.items():
            count = data["count"]
            if count > 0:
                data["avg_views_24h"] = round(data["total_views_24h"] / count, 1)
                data["avg_views_72h"] = round(data["total_views_72h"] / count, 1)
                data["avg_views_7d"] = round(data["total_views_7d"] / count, 1)
                data["avg_likes_24h"] = round(data["total_likes_24h"] / count, 1)
                data["avg_likes_72h"] = round(data["total_likes_72h"] / count, 1)
                data["avg_likes_7d"] = round(data["total_likes_7d"] / count, 1)
                data["avg_clip_duration"] = round(data["avg_clip_duration"] / count, 1)
                data["avg_peak_position_pct"] = round(data["avg_peak_position_pct"] / count, 1)

        # Summary stats
        total_uploaded = len(uploaded)
        total_views_7d = sum(s.get("snapshots", {}).get("7d", {}).get("views", 0) for s in uploaded)

        return {
            "summary": {
                "total_uploaded": total_uploaded,
                "total_views_7d": total_views_7d,
                "avg_views_per_short_7d": round(total_views_7d / total_uploaded, 1) if total_uploaded > 0 else 0
            },
            "by_signal": dict(by_signal),
            "signal_ranking": sorted(
                [(sig, data["avg_views_7d"]) for sig, data in by_signal.items()],
                key=lambda x: x[1],
                reverse=True
            )
        }
    except Exception as e:
        return {"error": f"Analysis failed: {e}"}


def analyze_hook_styles(log: dict) -> dict:
    """
    Analyze which hook styles perform best.

    Returns performance breakdown by hook_style (shocked/deadpan/hype/storyteller).
    """
    try:
        shorts = log.get("shorts", [])
        uploaded = [s for s in shorts if s.get("status") == "uploaded"]

        if not uploaded:
            return {"error": "No uploaded shorts found"}

        # Group by hook_style
        by_style = defaultdict(lambda: {
            "count": 0,
            "total_views_7d": 0,
            "total_likes_7d": 0,
            "avg_hook_length": 0
        })

        for short in uploaded:
            style = short.get("hook_style", "unknown")
            data = by_style[style]

            data["count"] += 1
            data["total_views_7d"] += short.get("snapshots", {}).get("7d", {}).get("views", 0)
            data["total_likes_7d"] += short.get("snapshots", {}).get("7d", {}).get("likes", 0)
            data["avg_hook_length"] += short.get("hook_word_count", 0)

        # Calculate averages
        for style, data in by_style.items():
            count = data["count"]
            if count > 0:
                data["avg_views_7d"] = round(data["total_views_7d"] / count, 1)
                data["avg_likes_7d"] = round(data["total_likes_7d"] / count, 1)
                data["avg_hook_length"] = round(data["avg_hook_length"] / count, 1)

        return {
            "by_style": dict(by_style),
            "style_ranking": sorted(
                [(style, data["avg_views_7d"]) for style, data in by_style.items()],
                key=lambda x: x[1],
                reverse=True
            )
        }
    except Exception as e:
        return {"error": f"Hook style analysis failed: {e}"}


def analyze_source_channels(log: dict) -> dict:
    """
    Analyze which source channels produce best-performing clips.

    Returns performance breakdown by source_channel_title.
    """
    try:
        shorts = log.get("shorts", [])
        uploaded = [s for s in shorts if s.get("status") == "uploaded"]

        if not uploaded:
            return {"error": "No uploaded shorts found"}

        by_channel = defaultdict(lambda: {
            "count": 0,
            "total_views_7d": 0,
            "total_likes_7d": 0
        })

        for short in uploaded:
            channel = short.get("source_channel_title", "unknown")
            data = by_channel[channel]

            data["count"] += 1
            data["total_views_7d"] += short.get("snapshots", {}).get("7d", {}).get("views", 0)
            data["total_likes_7d"] += short.get("snapshots", {}).get("7d", {}).get("likes", 0)

        # Calculate averages
        for channel, data in by_channel.items():
            count = data["count"]
            if count > 0:
                data["avg_views_7d"] = round(data["total_views_7d"] / count, 1)
                data["avg_likes_7d"] = round(data["total_likes_7d"] / count, 1)

        return {
            "by_channel": dict(by_channel),
            "channel_ranking": sorted(
                [(ch, data["avg_views_7d"]) for ch, data in by_channel.items()],
                key=lambda x: x[1],
                reverse=True
            )
        }
    except Exception as e:
        return {"error": f"Source channel analysis failed: {e}"}


if __name__ == "__main__":
    import pathlib
    log_path = pathlib.Path("data/performance_log.json")

    if not log_path.exists():
        print("Error: data/performance_log.json not found")
    else:
        with open(log_path) as f:
            log = json.load(f)

        print("=" * 60)
        print("PEAK SIGNAL ANALYSIS")
        print("=" * 60)
        signal_results = analyze_peak_signals(log)
        print(json.dumps(signal_results, indent=2))

        print("\n" + "=" * 60)
        print("HOOK STYLE ANALYSIS")
        print("=" * 60)
        style_results = analyze_hook_styles(log)
        print(json.dumps(style_results, indent=2))

        print("\n" + "=" * 60)
        print("SOURCE CHANNEL ANALYSIS")
        print("=" * 60)
        channel_results = analyze_source_channels(log)
        print(json.dumps(channel_results, indent=2))
