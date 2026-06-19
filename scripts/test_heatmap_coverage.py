#!/usr/bin/env python3
"""Test what % of videos from whitelist channels have heatmap data."""

import sys
import os

sys.path.insert(0, '.')

from pipeline.heatmap import get_heatmap_data
from pipeline.search import get_top_videos


def test_heatmap_coverage():
    """Test heatmap availability across whitelist channels."""
    try:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            print("Error: YOUTUBE_API_KEY not set")
            return

        print("Fetching recent videos from whitelist channels...")
        videos = get_top_videos(api_key, "whitelist", limit=20)

        if not videos:
            print("No videos found from whitelist channels")
            return

        print(f"Testing heatmap availability for {len(videos)} videos...\n")

        results = {
            "has_heatmap": 0,
            "no_heatmap": 0,
            "by_channel": {},
            "details": []
        }

        for i, v in enumerate(videos, 1):
            channel = v["channel_title"]
            video_id = v["video_id"]
            title = v["title"][:50]

            if channel not in results["by_channel"]:
                results["by_channel"][channel] = {"has": 0, "no": 0}

            print(f"[{i}/{len(videos)}] Testing: {channel} - {title}")

            heatmap = get_heatmap_data(v["url"])

            if heatmap and len(heatmap) >= 10:
                results["has_heatmap"] += 1
                results["by_channel"][channel]["has"] += 1
                status = f"✓ HEATMAP ({len(heatmap)} segments)"
                print(f"  → {status}")
            else:
                results["no_heatmap"] += 1
                results["by_channel"][channel]["no"] += 1
                seg_count = len(heatmap) if heatmap else 0
                status = f"✗ NO HEATMAP ({seg_count} segments)"
                print(f"  → {status}")

            results["details"].append({
                "channel": channel,
                "video_id": video_id,
                "title": title,
                "has_heatmap": heatmap and len(heatmap) >= 10,
                "segment_count": len(heatmap) if heatmap else 0
            })

        # Summary
        total = results["has_heatmap"] + results["no_heatmap"]
        coverage_pct = (results["has_heatmap"] / total * 100) if total > 0 else 0

        print("\n" + "=" * 60)
        print("HEATMAP COVERAGE SUMMARY")
        print("=" * 60)
        print(f"Total videos tested: {total}")
        print(f"With heatmap (≥10 segments): {results['has_heatmap']} ({coverage_pct:.1f}%)")
        print(f"Without heatmap: {results['no_heatmap']} ({100 - coverage_pct:.1f}%)")

        print("\n" + "=" * 60)
        print("BY CHANNEL")
        print("=" * 60)

        for ch, stats in sorted(results["by_channel"].items()):
            ch_total = stats["has"] + stats["no"]
            ch_pct = (stats["has"] / ch_total * 100) if ch_total > 0 else 0
            print(f"{ch}: {stats['has']}/{ch_total} ({ch_pct:.0f}%)")

        # Analysis
        print("\n" + "=" * 60)
        print("ANALYSIS")
        print("=" * 60)

        if coverage_pct < 30:
            print("⚠️  LOW COVERAGE: Heatmap is unreliable as primary signal.")
            print("   Recommendation: Prioritize comment timestamps and audio energy.")
        elif coverage_pct < 60:
            print("⚠️  MODERATE COVERAGE: Heatmap works for some channels.")
            print("   Recommendation: Keep current fallback chain (heatmap → comments → audio).")
        else:
            print("✓ GOOD COVERAGE: Heatmap is viable primary signal.")

        # Check segment count distribution for videos without heatmap
        no_heatmap_details = [d for d in results["details"] if not d["has_heatmap"]]
        if no_heatmap_details:
            low_segments = [d for d in no_heatmap_details if d["segment_count"] > 0 and d["segment_count"] < 10]
            zero_segments = [d for d in no_heatmap_details if d["segment_count"] == 0]

            print(f"\nNo-heatmap breakdown:")
            print(f"  - Zero segments (no data): {len(zero_segments)}")
            print(f"  - Low segments (1-9, below threshold): {len(low_segments)}")

            if len(low_segments) > len(zero_segments):
                print("\n💡 INSIGHT: Many videos have heatmap data but <10 segments.")
                print("   Consider lowering threshold from ≥10 to ≥5 in pipeline.py line 182.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_heatmap_coverage()
