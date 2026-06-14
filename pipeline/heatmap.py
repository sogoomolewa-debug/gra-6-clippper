# pipeline/heatmap.py — Find the most-rewatched segment timestamp and handle audio peaks / comment scoring
import json
import pathlib
import re
import subprocess
import sys
from typing import List, Dict, Tuple, Optional

import config


def get_heatmap_data(video_url: str) -> Optional[List[dict]]:
    """Get heatmap data from yt-dlp for a video."""
    try:
        cmd = ["yt-dlp", "--dump-json", "--no-download"]
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
        cmd = ["yt-dlp", "--dump-json", "--no-download"]
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
            print(f"[heatmap] duration fetch error: {result.stderr.strip()}")
            return 300.0
        data = json.loads(result.stdout)
        duration = float(data.get("duration", 300))
        print(f"[heatmap] video duration: {duration:.1f}s")
        return duration
    except Exception as e:
        print(f"[heatmap] error getting duration: {e}")
        return 300.0


def find_peak_window(heatmap: List[dict], window_duration: float = 52.0) -> Tuple[float, float]:
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


def get_fallback_timestamps(video_url: str, window_duration: float = 52.0) -> Tuple[float, float]:
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


def get_clip_timestamps(video_url: str) -> Tuple[float, float]:
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


def download_audio_only(video_url: str, output_path: str) -> bool:
    """Download audio-only from YouTube using yt-dlp."""
    try:
        cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio/best[height<=360]",
            "-x",
            "--audio-format", "mp3",
            "-o", output_path
        ]
        if config.YOUTUBE_COOKIES_PATH and pathlib.Path(config.YOUTUBE_COOKIES_PATH).exists():
            cmd.extend(["--cookies", config.YOUTUBE_COOKIES_PATH])
        import shutil
        node_path = shutil.which("node")
        if node_path:
            cmd.extend(["--js-runtimes", f"node:{node_path}"])
        cmd.append(video_url)
        print(f"[heatmap] downloading audio-only: {video_url}")
        pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"[heatmap] download_audio_only error: {result.stderr.strip()[:500]}")
            return False

        out_file = pathlib.Path(output_path)
        if not out_file.exists():
            # Check if suffix was added
            actual_file = out_file.with_name(out_file.name + ".mp3")
            if actual_file.exists():
                actual_file.rename(out_file)
            else:
                # Find file starting with the same stem
                parent = out_file.parent
                candidates = list(parent.glob(out_file.stem + "*"))
                if candidates:
                    candidates[0].rename(out_file)

        if out_file.exists():
            print(f"[heatmap] audio-only downloaded: {output_path}")
            return True
        print(f"[heatmap] error: output file {output_path} not found after download")
        return False
    except Exception as e:
        print(f"[heatmap] error in download_audio_only: {e}")
        return False


def audio_energy_peak(audio_path: str, window_duration: float = 52.0) -> Tuple[float, float]:
    """Find the start and end time of the peak audio energy segment using librosa."""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=8000, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)

        if duration <= window_duration:
            return (0.0, duration)

        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

        dt = times[1] - times[0] if len(times) > 1 else 0.064
        window_frames = int(window_duration / dt)

        if window_frames >= len(rms):
            return (0.0, duration)

        sliding_energy = np.convolve(rms, np.ones(window_frames), mode='valid')
        peak_idx = np.argmax(sliding_energy)

        start_time = float(times[peak_idx])
        end_time = min(start_time + window_duration, duration)

        print(f"[heatmap] audio peak found: {start_time:.1f}s → {end_time:.1f}s")
        return (start_time, end_time)
    except Exception as e:
        print(f"[heatmap] error in audio_energy_peak: {e}")
        # Fallback to 30%
        try:
            import librosa
            duration = librosa.get_duration(path=audio_path)
        except Exception:
            duration = 300.0
        start = duration * 0.3
        return (start, min(start + window_duration, duration))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.heatmap <video_url>")
    else:
        url = sys.argv[1]
        start, end = get_clip_timestamps(url)
        print(f"Clip: {start:.1f}s → {end:.1f}s (duration: {end - start:.1f}s)")
