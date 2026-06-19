#!/usr/bin/env python3
"""Analyze peak signal performance from performance log."""

import sys
import json
import pathlib

sys.path.insert(0, '.')

from pipeline.stats import analyze_peak_signals, analyze_hook_styles, analyze_source_channels


def main():
    log_path = pathlib.Path("data/performance_log.json")

    if not log_path.exists():
        print("Error: data/performance_log.json not found")
        return

    with open(log_path) as f:
        log = json.load(f)

    total_shorts = len(log.get("shorts", []))
    uploaded = [s for s in log.get("shorts", []) if s.get("status") == "uploaded"]

    print("=" * 60)
    print("PERFORMANCE ANALYTICS")
    print("=" * 60)
    print(f"Total entries: {total_shorts}")
    print(f"Uploaded shorts: {len(uploaded)}")
    print()

    # Peak signal analysis
    print("=" * 60)
    print("PEAK SIGNAL ANALYSIS")
    print("=" * 60)
    signal_results = analyze_peak_signals(log)

    if "error" in signal_results:
        print(f"Error: {signal_results['error']}")
        if "total_entries" in signal_results:
            print(f"Total entries: {signal_results['total_entries']}")
            print(f"Uploaded: {signal_results.get('uploaded', 0)}")
    else:
        summary = signal_results["summary"]
        print(f"Total uploaded: {summary['total_uploaded']}")
        print(f"Total views (7d): {summary['total_views_7d']}")
        print(f"Avg views per short (7d): {summary['avg_views_per_short_7d']}")
        print()

        print("By Signal:")
        for signal, avg_views in signal_results["signal_ranking"]:
            data = signal_results["by_signal"][signal]
            print(f"  {signal}:")
            print(f"    Count: {data['count']}")
            print(f"    Avg views (24h/72h/7d): {data['avg_views_24h']}/{data['avg_views_72h']}/{data['avg_views_7d']}")
            print(f"    Avg likes (7d): {data['avg_likes_7d']}")
            print(f"    Avg clip duration: {data['avg_clip_duration']}s")
            print(f"    Avg peak position: {data['avg_peak_position_pct']:.1f}%")
            print()

    # Hook style analysis
    print("=" * 60)
    print("HOOK STYLE ANALYSIS")
    print("=" * 60)
    style_results = analyze_hook_styles(log)

    if "error" in style_results:
        print(f"Note: {style_results['error']}")
        print("(Hook style tracking added in this update — no historical data)")
    else:
        for style, avg_views in style_results["style_ranking"]:
            data = style_results["by_style"][style]
            print(f"  {style}:")
            print(f"    Count: {data['count']}")
            print(f"    Avg views (7d): {data['avg_views_7d']}")
            print(f"    Avg hook length: {data['avg_hook_length']} words")
            print()

    # Source channel analysis
    print("=" * 60)
    print("SOURCE CHANNEL ANALYSIS")
    print("=" * 60)
    channel_results = analyze_source_channels(log)

    if "error" in channel_results:
        print(f"Error: {channel_results['error']}")
    else:
        for channel, avg_views in channel_results["channel_ranking"]:
            data = channel_results["by_channel"][channel]
            print(f"  {channel}:")
            print(f"    Shorts created: {data['count']}")
            print(f"    Avg views (7d): {data['avg_views_7d']}")
            print(f"    Avg likes (7d): {data['avg_likes_7d']}")
            print()


if __name__ == "__main__":
    main()
