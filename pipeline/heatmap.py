# pipeline/heatmap.py — Find the most-rewatched segment timestamp

import subprocess
import json
import sys

import config


def get_heatmap_data(video_url: str) -> list[dict] | None:
    """Get heatmap data from yt-dlp for a video."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", video_url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"[heatmap] yt-dlp error: {result.stderr.strip()}")
            return None
        data = json.loads(result.stdout)
        heatmap = data.get("heatmap")
        if heatmap:
            print(f"[heatmap] got {len(heatmap)} heatmap segments")
        else:
            print("[heatmap] no heatmap data in video metadata")
        return heatmap
    except subprocess.TimeoutExpired:
        print("[heatmap] yt-dlp timed out")
        return None
    except Exception as e:
        print(f"[heatmap] error getting heatmap: {e}")
        return None


def get_video_duration(video_url: str) -> float:
    """Get video duration via yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", video_url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"[heatmap] duration fetch error: {result.stderr.strip()}")
            return 300.0
        data = json.loads(result.stdout)
        duration = float(data.get("duration", 300))
        print(f"[heatmap] video duration: {duration:.1f}s")
        return duration
    except Exception as e:
        print(f"[heatmap] error getting duration: {e}")
        return 300.0


def find_peak_window(heatmap: list[dict], window_duration: float = 52.0) -> tuple[float, float]:
    """Find the window with highest heatmap intensity using sliding window."""
    try:
        if not heatmap:
            return (0.0, window_duration)

        max_end = max(seg.get("end_time", 0) for seg in heatmap)
        if max_end <= window_duration:
            return (0.0, min(window_duration, max_end))

        best_start = 0.0
        best_intensity = -1.0
        step = 0.5
        current = 0.0

        while current + window_duration <= max_end:
            window_start = current
            window_end = current + window_duration
            total_intensity = 0.0

            for seg in heatmap:
                seg_start = seg.get("start_time", 0)
                seg_end = seg.get("end_time", 0)
                seg_value = seg.get("value", 0)

                # Calculate overlap
                overlap_start = max(window_start, seg_start)
                overlap_end = min(window_end, seg_end)

                if overlap_end > overlap_start:
                    seg_duration = seg_end - seg_start
                    if seg_duration > 0:
                        overlap_fraction = (overlap_end - overlap_start) / seg_duration
                        total_intensity += seg_value * overlap_fraction

            if total_intensity > best_intensity:
                best_intensity = total_intensity
                best_start = current

            current += step

        # Clamp end so it doesn't exceed last segment
        best_end = min(best_start + window_duration, max_end)
        return (best_start, best_end)
    except Exception as e:
        print(f"[heatmap] error in find_peak_window: {e}")
        return (0.0, window_duration)


def get_fallback_timestamps(video_url: str, window_duration: float = 52.0) -> tuple[float, float]:
    """Fallback: pick a segment at 30% into the video."""
    try:
        duration = get_video_duration(video_url)
        start = duration * 0.3
        end = min(start + window_duration, duration - 5)
        print(f"[heatmap] fallback timestamps: {start:.1f}s → {end:.1f}s")
        return (start, end)
    except Exception as e:
        print(f"[heatmap] fallback error: {e}")
        return (90.0, 90.0 + window_duration)


def get_clip_timestamps(video_url: str) -> tuple[float, float]:
    """Get the best clip timestamps for a video."""
    try:
        heatmap = get_heatmap_data(video_url)
        window = config.CLIP["max_duration_seconds"] - 3

        if heatmap and len(heatmap) >= 10:
            result = find_peak_window(heatmap, window)
            print(f"[heatmap] peak found via heatmap: {result[0]:.1f}s → {result[1]:.1f}s")
            return result
        else:
            print("[heatmap] no heatmap data, using fallback")
            return get_fallback_timestamps(video_url, window)
    except Exception as e:
        print(f"[heatmap] error getting clip timestamps: {e}")
        return (90.0, 142.0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.heatmap <video_url>")
    else:
        url = sys.argv[1]
        start, end = get_clip_timestamps(url)
        print(f"Clip: {start:.1f}s → {end:.1f}s (duration: {end - start:.1f}s)")
