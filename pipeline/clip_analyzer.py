# pipeline/clip_analyzer.py — Downloads clip segment and calls the Modal video analysis endpoint
# BUG 1 FIX: Passes comment_context to Modal so Qwen focuses on comment-identified moment
# BUG 4 FIX: Clamps natural boundaries to config max_duration_seconds immediately after Qwen returns

import base64
import os
import subprocess
import pathlib
import tempfile
import requests
import sys
import shutil

import config


def download_segment(
    video_url: str,
    global_start: float,
    global_end: float,
    output_path: str
) -> bool:
    """Download a video segment around the peak timestamp using yt-dlp."""
    try:
        cmd = [
            "yt-dlp",
            "--download-sections", f"*{global_start:.2f}-{global_end:.2f}",
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "--merge-output-format", "mp4",
            "-o", output_path
        ]
        cookies_path = getattr(config, "YOUTUBE_COOKIES_PATH", "")
        if cookies_path and pathlib.Path(cookies_path).exists():
            cmd.extend(["--cookies", cookies_path])

        import shutil as sh
        node_path = sh.which("node")
        if node_path:
            cmd.extend(["--js-runtimes", f"node:{node_path}"])

        cmd.append(video_url)
        print(f"[analyzer] downloading segment: {global_start:.1f}s → {global_end:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[analyzer] download error: {result.stderr.strip()[-500:]}")
            return False
        print(f"[analyzer] downloaded segment: {output_path}")
        return True
    except subprocess.TimeoutExpired:
        print("[analyzer] download timed out")
        return False
    except Exception as e:
        print(f"[analyzer] download error: {e}")
        return False


def get_segment_duration(video_path: str) -> float:
    """Get the duration of the downloaded video segment via ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
        return 120.0
    except Exception as e:
        print(f"[analyzer] duration check error: {e}")
        return 120.0


def call_video_endpoint(
    video_path: str,
    peak_sec_local: float,
    segment_duration: float,
    comment_context: str
) -> dict:
    """Call Modal Qwen2.5-VL video understanding endpoint with comment context."""
    fallback = {
        "description": "",
        "natural_start": max(0.0, peak_sec_local - 8.0),
        "natural_end": max(0.0, peak_sec_local - 8.0) + 52.0,
        "error": "endpoint failed"
    }
    try:
        endpoint = os.environ.get("MODAL_VIDEO_ENDPOINT", "")
        if not endpoint:
            print("[analyzer] error: MODAL_VIDEO_ENDPOINT env var not set")
            fallback["error"] = "MODAL_VIDEO_ENDPOINT not set"
            return fallback

        # Read video file as bytes and base64 encode
        path = pathlib.Path(video_path)
        if not path.exists():
            print(f"[analyzer] video file not found: {video_path}")
            return fallback

        video_bytes = path.read_bytes()
        video_b64 = base64.b64encode(video_bytes).decode("utf-8")

        payload = {
            "video_b64": video_b64,
            "peak_sec_local": peak_sec_local,
            "segment_duration": segment_duration,
            "comment_context": comment_context
        }

        print(f"[analyzer] calling Modal endpoint at: {endpoint}")
        print(f"[analyzer] comment context: {comment_context[:80]}...")
        response = requests.post(endpoint, json=payload, timeout=180)
        if response.status_code != 200:
            print(f"[analyzer] endpoint error {response.status_code}: {response.text[:500]}")
            fallback["error"] = f"status {response.status_code}"
            return fallback

        return response.json()
    except Exception as e:
        print(f"[analyzer] endpoint call failed: {e}")
        fallback["error"] = str(e)
        return fallback


def clamp_boundaries(
    natural_start: float,
    natural_end: float,
    peak_sec_local: float,
    segment_duration: float
) -> tuple[float, float]:
    """
    Enforces clip duration constraints.
    Peak moment must be inside the final window.

    BUG 4 FIX: Qwen sometimes returns 95s windows — this clamps to config max.
    """
    max_dur = float(config.CLIP["max_duration_seconds"])
    min_dur = 45.0

    duration = natural_end - natural_start

    # Too long — trim end first, keep natural start
    if duration > max_dur:
        natural_end = natural_start + max_dur
        print(f"[analyzer] clamped long clip: {duration:.1f}s → {max_dur:.1f}s")

    # Too short — extend end
    if (natural_end - natural_start) < min_dur:
        natural_end = natural_start + min_dur
        print(f"[analyzer] extended short clip to {min_dur:.1f}s")

    # Verify peak is inside window — if not, re-center around peak
    if not (natural_start <= peak_sec_local <= natural_end):
        natural_start = max(0.0, peak_sec_local - 8.0)
        natural_end = natural_start + max_dur
        print(f"[analyzer] re-centered around peak: {natural_start:.1f}s → {natural_end:.1f}s")

    # Clamp to segment bounds
    natural_end = min(natural_end, segment_duration)
    natural_start = max(0.0, natural_start)

    return (round(natural_start, 1), round(natural_end, 1))


def analyze_clip(
    video_url: str,
    peak_sec_global: float,
    video_duration: float,
    timestamp_comments: list[dict] | None = None
) -> dict:
    """
    Downloads a video segment (peak-30s to peak+90s) and gets visual description
    and natural clip boundaries from Qwen2.5-VL via Modal.

    BUG 1 FIX: Passes comment_context so Qwen focuses on the right moment.
    BUG 4 FIX: Clamps boundaries via clamp_boundaries() immediately after Qwen returns.

    Returns:
    {
        "description": str,
        "global_start": float,    # Natural start in global video time
        "global_end": float,      # Natural end in global video time
    }
    """
    if timestamp_comments is None:
        timestamp_comments = []

    try:
        # Build comment context string for Qwen — use highest-liked comment
        comment_context = "an interesting gameplay moment"
        if timestamp_comments:
            top_comments = sorted(
                timestamp_comments,
                key=lambda c: c.get("like_count", 0),
                reverse=True
            )
            if top_comments and top_comments[0].get("text"):
                comment_context = top_comments[0]["text"]

        tmp = pathlib.Path(tempfile.mkdtemp())
        segment_path = str(tmp / "segment.mp4")

        # Buffer: 30s before peak to 90s after — gives model full context
        segment_global_start = max(0.0, peak_sec_global - 30.0)
        segment_global_end = min(video_duration, peak_sec_global + 90.0)

        # Peak position within the downloaded segment
        peak_sec_local = peak_sec_global - segment_global_start

        success = download_segment(video_url, segment_global_start, segment_global_end, segment_path)

        if not success:
            shutil.rmtree(str(tmp), ignore_errors=True)
            print("[analyzer] download failed — using smart offset fallback")
            fallback_start = max(0.0, peak_sec_global - 8.0)
            return {
                "description": "",
                "global_start": fallback_start,
                "global_end": fallback_start + float(config.CLIP["max_duration_seconds"])
            }

        actual_duration = get_segment_duration(segment_path)
        result = call_video_endpoint(segment_path, peak_sec_local, actual_duration, comment_context)

        shutil.rmtree(str(tmp), ignore_errors=True)

        # BUG 4 FIX: Clamp local boundaries immediately
        local_start, local_end = clamp_boundaries(
            result["natural_start"],
            result["natural_end"],
            peak_sec_local,
            actual_duration
        )

        # Translate to global time
        global_start = round(segment_global_start + local_start, 1)
        global_end = round(segment_global_start + local_end, 1)

        print(f"[analyzer] description: {result['description']}")
        print(f"[analyzer] global boundaries: {global_start}s → {global_end}s ({global_end - global_start:.1f}s)")

        return {
            "description": result.get("description", ""),
            "global_start": global_start,
            "global_end": global_end
        }

    except Exception as e:
        print(f"[analyzer] analyze_clip error: {e}")
        fallback_start = max(0.0, peak_sec_global - 8.0)
        return {
            "description": "",
            "global_start": fallback_start,
            "global_end": fallback_start + float(config.CLIP["max_duration_seconds"])
        }


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        result = analyze_clip(sys.argv[1], float(sys.argv[2]), 600.0)
        print(result)
    else:
        print("Usage: python clip_analyzer.py <video_url> <peak_sec>")
