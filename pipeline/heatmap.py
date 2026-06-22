# pipeline/heatmap.py — Find the most-rewatched segment timestamp and handle comment scoring
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import List, Dict, Tuple, Optional

import config
from pipeline import ytdlp


def get_video_metadata(video_url: str) -> dict:
    """Get video duration and heatmap data in a single yt-dlp call.

    Returns: {"duration": float, "heatmap": list|None}
    """
    try:
        cmd = ytdlp.command() + ["--dump-json", "--no-download"]
        if config.YOUTUBE_COOKIES_PATH and pathlib.Path(config.YOUTUBE_COOKIES_PATH).exists():
            cmd.extend(["--cookies", config.YOUTUBE_COOKIES_PATH])
        import shutil
        node_path = shutil.which("node")
        if node_path:
            cmd.extend(["--js-runtimes", f"node:{node_path}"])
        cmd.append(video_url)
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"[heatmap] yt-dlp error: {result.stderr.strip()}")
            return {"duration": 300.0, "heatmap": None}
        data = json.loads(result.stdout)
        duration = float(data.get("duration", 300))
        heatmap = data.get("heatmap")
        if heatmap:
            print(f"[heatmap] got {len(heatmap)} heatmap segments, duration: {duration:.1f}s")
        else:
            print(f"[heatmap] no heatmap data, duration: {duration:.1f}s")
        return {"duration": duration, "heatmap": heatmap}
    except subprocess.TimeoutExpired:
        print("[heatmap] yt-dlp timed out")
        return {"duration": 300.0, "heatmap": None}
    except Exception as e:
        print(f"[heatmap] error getting metadata: {e}")
        return {"duration": 300.0, "heatmap": None}


def find_peak_window(heatmap: List[dict], window_duration: float) -> Tuple[float, float]:
    """Find the window with highest heatmap intensity using sliding window.

    Args:
        heatmap: List of heatmap segments with start_time, end_time, value
        window_duration: Window size in seconds (should match config.CLIP["max_duration_seconds"] - 3)
    """
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


def _window_intensity(heatmap: List[dict], window_start: float, window_end: float) -> float:
    """Calculate total heatmap intensity for a given window."""
    total = 0.0
    for seg in heatmap:
        seg_start = seg.get("start_time", 0)
        seg_end = seg.get("end_time", 0)
        seg_value = seg.get("value", 0)
        overlap_start = max(window_start, seg_start)
        overlap_end = min(window_end, seg_end)
        if overlap_end > overlap_start:
            seg_duration = seg_end - seg_start
            if seg_duration > 0:
                overlap_fraction = (overlap_end - overlap_start) / seg_duration
                total += seg_value * overlap_fraction
    return total


def find_top_peaks(heatmap: List[dict], window_duration: float, n: int = 3) -> List[Tuple[float, float]]:
    """Find the top N non-overlapping peak windows sorted by intensity.

    Returns list of (start, end) tuples, highest intensity first.
    """
    try:
        if not heatmap:
            return []

        max_end = max(seg.get("end_time", 0) for seg in heatmap)
        if max_end <= window_duration:
            return [(0.0, min(window_duration, max_end))]

        # Collect all windows with their intensities
        step = 0.5
        current = 0.0
        windows = []

        while current + window_duration <= max_end:
            intensity = _window_intensity(heatmap, current, current + window_duration)
            windows.append((current, current + window_duration, intensity))
            current += step

        # Sort by intensity descending
        windows.sort(key=lambda w: w[2], reverse=True)

        # Pick top N non-overlapping windows
        peaks = []
        for start, end, intensity in windows:
            if len(peaks) >= n:
                break
            # Check overlap with already-selected peaks
            overlaps = False
            for ps, pe in peaks:
                if start < pe and end > ps:
                    overlaps = True
                    break
            if not overlaps:
                peaks.append((start, end))

        print(f"[heatmap] found {len(peaks)} non-overlapping peaks")
        for i, (s, e) in enumerate(peaks):
            intensity = _window_intensity(heatmap, s, e)
            print(f"[heatmap]   peak {i+1}: {s:.1f}s → {e:.1f}s (intensity: {intensity:.2f})")
        return peaks
    except Exception as e:
        print(f"[heatmap] error in find_top_peaks: {e}")
        return []


def get_fallback_timestamps(video_url: str, window_duration: float = 52.0) -> Tuple[float, float]:
    """Fallback: pick a segment at 30% into the video."""
    try:
        metadata = get_video_metadata(video_url)
        duration = metadata["duration"]
        start = duration * 0.3
        end = min(start + window_duration, duration - 5)
        print(f"[heatmap] fallback timestamps: {start:.1f}s → {end:.1f}s")
        return (start, end)
    except Exception as e:
        print(f"[heatmap] fallback error: {e}")
        return (90.0, 90.0 + window_duration)


def get_clip_timestamps(video_url: str) -> Tuple[float, float]:
    """Get the best clip timestamps for a video."""
    try:
        metadata = get_video_metadata(video_url)
        heatmap = metadata["heatmap"]
        window = config.CLIP["max_duration_seconds"] - 3

        if heatmap and len(heatmap) >= 10:
            result = find_peak_window(heatmap, window)
            print(f"[heatmap] peak found via heatmap: {result[0]:.1f}s → {result[1]:.1f}s")
            return result
        else:
            print("[heatmap] no heatmap data, using fallback")
            duration = metadata["duration"]
            start = duration * 0.3
            end = min(start + window, duration - 5)
            return (start, end)
    except Exception as e:
        print(f"[heatmap] error getting clip timestamps: {e}")
        return (90.0, 142.0)


def extract_and_score_timestamps(comments: List[dict], video_duration: int) -> Dict[int, float]:
    """Extract timestamps from comments and score them based on mentions and likes."""
    try:
        scores = {}
        # Pattern to match timestamps: e.g. 1:23, 12:34, 1:23:45
        pattern = re.compile(r'\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b')

        for comment in comments:
            text = comment.get("text", "")
            like_count = comment.get("like_count", 0)
            weight = 1.0 + float(like_count)

            # Find all timestamps in this comment
            matches = pattern.findall(text)
            seen_secs = set()
            for match in matches:
                try:
                    hours = int(match[0]) if match[0] else 0
                    minutes = int(match[1])
                    seconds = int(match[2])
                    sec = hours * 3600 + minutes * 60 + seconds
                    if 0 <= sec < video_duration:
                        seen_secs.add(sec)
                except Exception:
                    continue

            for sec in seen_secs:
                scores[sec] = scores.get(sec, 0.0) + weight

        # Smooth scores with a small window (e.g., +/- 2 seconds) to group nearby mentions
        smoothed_scores = {}
        for sec, score in scores.items():
            for offset in range(-2, 3):
                target_sec = sec + offset
                if 0 <= target_sec < video_duration:
                    factor = 1.0 - (abs(offset) * 0.2)
                    smoothed_scores[target_sec] = smoothed_scores.get(target_sec, 0.0) + (score * factor)

        return smoothed_scores
    except Exception as e:
        print(f"[heatmap] error in extract_and_score_timestamps: {e}")
        return {}


def get_best_comment_timestamp(clusters: Dict[int, float]) -> Optional[int]:
    """Get the highest scoring timestamp from clusters."""
    try:
        if not clusters:
            return None
        best_sec = max(clusters, key=clusters.get)
        if clusters[best_sec] > 0.0:
            return best_sec
        return None
    except Exception as e:
        print(f"[heatmap] error in get_best_comment_timestamp: {e}")
        return None


def get_timestamp_comments(comments: List[dict], peak_sec: int) -> List[dict]:
    """Find comments that mention timestamps near the peak_sec."""
    try:
        pattern = re.compile(r'\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b')
        relevant_comments = []

        for comment in comments:
            text = comment.get("text", "")
            matches = pattern.findall(text)
            is_relevant = False
            for match in matches:
                try:
                    hours = int(match[0]) if match[0] else 0
                    minutes = int(match[1])
                    seconds = int(match[2])
                    sec = hours * 3600 + minutes * 60 + seconds
                    if abs(sec - peak_sec) <= 5:
                        is_relevant = True
                        break
                except Exception:
                    continue
            if is_relevant:
                relevant_comments.append(comment)

        # Sort relevant comments by like_count desc
        relevant_comments.sort(key=lambda x: x.get("like_count", 0), reverse=True)
        return relevant_comments
    except Exception as e:
        print(f"[heatmap] error in get_timestamp_comments: {e}")
        return []


def analyze_comments_for_moment(comments: List[dict]) -> dict:
    """Use Groq to analyze comments and extract what viewers found most exciting.

    Called when heatmap and timestamp signals are both absent.
    Returns: {"moment_description": str, "position_hint": str, "confidence": float}
    """
    try:
        import groq

        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            print("[heatmap] GROQ_API_KEY not set, skipping comment analysis")
            return {"moment_description": "", "position_hint": "unknown", "confidence": 0.0}

        # Format top 30 comments by likes
        top_comments = sorted(comments, key=lambda c: c.get("like_count", 0), reverse=True)[:30]
        if not top_comments:
            return {"moment_description": "", "position_hint": "unknown", "confidence": 0.0}

        formatted = ""
        for i, c in enumerate(top_comments):
            text = c.get("text", "").strip().replace("\n", " ")[:150]
            likes = c.get("like_count", 0)
            formatted += f"{i+1}. \"{text}\" ({likes} likes)\n"

        system_prompt = (
            "You analyze YouTube comments from GTA gameplay videos to identify "
            "what specific moment viewers found most exciting, funny, or memorable."
        )

        user_prompt = (
            "Analyze these comments and identify the MOST EXCITING moment viewers are reacting to.\n\n"
            f"Comments:\n{formatted}\n"
            "Rules:\n"
            "- Focus on comments describing physical actions (crashes, stunts, ragdoll, explosions, glitches)\n"
            "- Ignore generic reactions ('lol', 'bruh', emoji-only, subscriber begging)\n"
            "- If viewers describe a specific moment, extract WHAT happened\n"
            "- If viewers hint at WHEN (near the end, early, at the start, around the middle), extract that\n"
            "- If comments are all generic with no specific moment, set confidence to 0.0\n\n"
            "Respond ONLY with JSON:\n"
            "{\n"
            "  \"moment_description\": \"one sentence describing what viewers found most exciting\",\n"
            "  \"position_hint\": \"early\" | \"middle\" | \"late\" | \"unknown\",\n"
            "  \"confidence\": 0.0 to 1.0\n"
            "}"
        )

        client = groq.Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=150,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)
        print(f"[heatmap] Groq comment analysis: {result}")
        return {
            "moment_description": str(result.get("moment_description", "")),
            "position_hint": str(result.get("position_hint", "unknown")),
            "confidence": float(result.get("confidence", 0.0))
        }
    except Exception as e:
        print(f"[heatmap] error in analyze_comments_for_moment: {e}")
        return {"moment_description": "", "position_hint": "unknown", "confidence": 0.0}


def get_position_segments(
    duration: float,
    position_hint: str,
    segment_window: float = 120.0
) -> List[Tuple[float, float]]:
    """Return 2-3 segment windows biased toward the position hint.

    Each segment is (start, end) in global video time.
    """
    try:
        if duration <= segment_window:
            return [(0.0, duration)]

        if position_hint == "early":
            # Focus on first 40% of video
            positions = [0.10, 0.25, 0.40]
        elif position_hint == "late":
            # Focus on last 40% of video
            positions = [0.60, 0.75, 0.90]
        elif position_hint == "middle":
            # Focus on middle
            positions = [0.35, 0.50, 0.65]
        else:
            # Unknown — spread evenly
            positions = [0.25, 0.50, 0.75]

        segments = []
        for pct in positions:
            center = duration * pct
            start = max(0.0, center - segment_window / 2)
            end = min(duration, start + segment_window)
            # Re-adjust start if end got clamped
            start = max(0.0, end - segment_window)
            segments.append((round(start, 1), round(end, 1)))

        # Deduplicate overlapping segments
        deduped = [segments[0]]
        for seg in segments[1:]:
            prev = deduped[-1]
            # If more than 50% overlap, skip
            overlap = max(0, min(prev[1], seg[1]) - max(prev[0], seg[0]))
            if overlap < segment_window * 0.5:
                deduped.append(seg)

        print(f"[heatmap] position segments (hint={position_hint}): {deduped}")
        return deduped
    except Exception as e:
        print(f"[heatmap] error in get_position_segments: {e}")
        return [(duration * 0.3, min(duration * 0.3 + segment_window, duration))]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.heatmap <video_url>")
    else:
        url = sys.argv[1]
        start, end = get_clip_timestamps(url)
        print(f"Clip: {start:.1f}s → {end:.1f}s (duration: {end - start:.1f}s)")
