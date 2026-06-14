# pipeline/clip_analyzer.py — Downloads clip segment and calls the Modal video analysis endpoint
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
        # Using 720p maximum height for faster upload and processing on Modal
        cmd = [
            "yt-dlp",
            "--download-sections", f"*{global_start:.2f}-{global_end:.2f}",
            "-f", "bestvideo[vcodec^=avc1][height<=720]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1][height<=720]",
            "--merge-output-format", "mp4",
            "-o", output_path
        ]
        if config.YOUTUBE_COOKIES_PATH and pathlib.Path(config.YOUTUBE_COOKIES_PATH).exists():
            cmd.extend(["--cookies", config.YOUTUBE_COOKIES_PATH])
        
        import shutil
        node_path = shutil.which("node")
        if node_path:
            cmd.extend(["--js-runtimes", f"node:{node_path}"])
            
        cmd.append(video_url)
        print(f"[analyzer] downloading segment: {global_start:.1f}s → {global_end:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[analyzer] download error: {result.stderr.strip()[:500]}")
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
    segment_duration: float
) -> dict:
    """Call Modal Qwen2.5-VL video understanding endpoint."""
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
        encoded = base64.b64encode(video_bytes).decode("utf-8")

        payload = {
            "video_b64": encoded,
            "peak_sec_local": peak_sec_local,
            "segment_duration": segment_duration
        }

        print(f"[analyzer] calling Modal endpoint at: {endpoint}")
        response = requests.post(endpoint, json=payload, timeout=180)
        if response.status_code != 200:
            print(f"[analyzer] endpoint returned status {response.status_code}: {response.text[:500]}")
            fallback["error"] = f"status {response.status_code}"
            return fallback

        return response.json()
    except Exception as e:
        print(f"[analyzer] endpoint call failed: {e}")
        fallback["error"] = str(e)
        return fallback

def analyze_clip(
    video_url: str,
    peak_sec_global: float,
    video_duration: float
) -> dict:
    """
    Downloads a video segment (peak-30s to peak+90s) and gets visual description and natural clip boundaries.
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    segment_path = str(tmp / "segment.mp4")

    # Download 30s before peak to 90s after — gives model full context
    segment_global_start = max(0.0, peak_sec_global - 30.0)
    segment_global_end = min(video_duration, peak_sec_global + 90.0)

    # Peak position within the downloaded segment
    peak_sec_local = peak_sec_global - segment_global_start

    success = download_segment(video_url, segment_global_start, segment_global_end, segment_path)

    if not success:
        print("[analyzer] segment download failed, using smart offset fallback")
        shutil.rmtree(str(tmp), ignore_errors=True)
        return {
            "description": "",
            "global_start": max(0.0, peak_sec_global - 8.0),
            "global_end": max(0.0, peak_sec_global - 8.0) + 52.0,
            "local_start": 0.0,
            "local_end": 52.0
        }

    actual_duration = get_segment_duration(segment_path)
    result = call_video_endpoint(segment_path, peak_sec_local, actual_duration)

    shutil.rmtree(str(tmp), ignore_errors=True)

    # Translate local boundaries back to global video time
    global_start = segment_global_start + result["natural_start"]
    global_end = segment_global_start + result["natural_end"]

    print(f"[analyzer] visual description: {result.get('description')}")
    print(f"[analyzer] natural boundaries: {global_start:.1f}s → {global_end:.1f}s (global)")

    return {
        "description": result.get("description", ""),
        "global_start": round(global_start, 1),
        "global_end": round(global_end, 1),
        "local_start": result.get("natural_start", 0.0),
        "local_end": result.get("natural_end", 52.0)
    }

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        url = sys.argv[1]
        peak = float(sys.argv[2])
        result = analyze_clip(url, peak, 600.0)
        print(result)
    else:
        print("Usage: python clip_analyzer.py <video_url> <peak_sec>")
