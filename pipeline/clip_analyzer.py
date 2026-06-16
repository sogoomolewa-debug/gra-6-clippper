# pipeline/clip_analyzer.py — Downloads clip segment and analyzes via Gemini 2.5 Flash
# BUG 1 FIX: Passes comment_context so Gemini focuses on comment-identified moment
# BUG 4 FIX: Clamps natural boundaries to config max_duration_seconds immediately after Gemini returns

from google import genai
from pydantic import BaseModel, Field
import os
import subprocess
import pathlib
import tempfile
import shutil
import time
import re
import sys

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


def upload_to_gemini(video_path: str) -> object | None:
    """Upload video segment to Gemini File API, wait for processing."""
    try:
        print("[analyzer] uploading segment to Gemini…")
        video_file = client.files.upload(file=video_path)
        waited = 0
        max_wait = 120
        while True:
            file_info = client.files.get(name=video_file.name)
            if file_info.state.name == "ACTIVE":
                break
            elif file_info.state.name == "FAILED":
                print("[analyzer] Gemini file processing failed")
                return None
            time.sleep(3)
            waited += 3
            if waited >= max_wait:
                print("[analyzer] Gemini processing timeout")
                return None
        print(f"[analyzer] Gemini file ready: {video_file.name}")
        return file_info
    except Exception as e:
        print(f"[analyzer] Gemini upload error: {e}")
        return None


class VideoAnalysis(BaseModel):
    is_gameplay: bool = Field(description="True if the video segment shows actual direct game graphics/gameplay. False if it is a talking head, reaction video (facecam dominant with minimal gameplay), commentary slides, or news/fandom rant.")
    description: str = Field(description="A single sentence describing the visual action at the peak timestamp.")
    natural_start: float = Field(description="The timestamp in seconds where the action peak's setup naturally begins.")
    natural_end: float = Field(description="The timestamp in seconds where the reaction to the action peak naturally ends.")


def analyze_with_gemini(
    video_file: object,
    peak_sec_local: float,
    segment_duration: float,
    comment_context: str
) -> dict:
    """
    Ask Gemini to verify gameplay, describe the video segment, and find natural clip boundaries in a single structured call.
    Returns: {"is_gameplay": bool, "description": str, "natural_start": float, "natural_end": float}
    """
    try:
        prompt = (
            f"This is a clip from a video related to Grand Theft Auto. "
            f"A viewer left this comment about what happens at {peak_sec_local:.0f} seconds: '{comment_context}'. "
            f"Perform the following analysis tasks:\n"
            f"1. Determine if this clip shows actual, direct in-game gameplay graphics of a GTA game being played (driving, shooting, missions, etc.). If it is a talking head (person's face), news/speculation slides, podcast, commentary show, or reaction video with minimal gameplay, set is_gameplay to false.\n"
            f"2. Describe in exactly ONE sentence what visually happens at {peak_sec_local:.0f} seconds.\n"
            f"3. Find where the peak action at {peak_sec_local:.0f} seconds naturally begins (setup) and naturally ends (reaction complete). "
            f"The window must be between 45 and 55 seconds long, and must include the peak at {peak_sec_local:.0f} seconds."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[video_file, prompt],
            config={
                "response_mime_type": "application/json",
                "response_schema": VideoAnalysis,
            }
        )

        import json
        data = json.loads(response.text)
        print(f"[analyzer] Gemini analysis result: {data}")

        return {
            "is_gameplay": data.get("is_gameplay", True),
            "description": data.get("description", ""),
            "natural_start": float(data.get("natural_start", max(0.0, peak_sec_local - 8.0))),
            "natural_end": float(data.get("natural_end", max(0.0, peak_sec_local - 8.0) + 52.0))
        }
    except Exception as e:
        print(f"[analyzer] Gemini analysis error: {e}")
        return {
            "is_gameplay": True,
            "description": "",
            "natural_start": max(0.0, peak_sec_local - 8.0),
            "natural_end": max(0.0, peak_sec_local - 8.0) + 52.0
        }


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
    and natural clip boundaries from Gemini 2.5 Flash.

    BUG 1 FIX: Passes comment_context so Gemini focuses on the right moment.
    BUG 4 FIX: Clamps boundaries via clamp_boundaries() immediately after Gemini returns.

    Returns:
    {
        "description": str,
        "global_start": float,    # Natural start in global video time
        "global_end": float,      # Natural end in global video time
    }
    """
    if timestamp_comments is None:
        timestamp_comments = []

    def fallback(reason: str) -> dict:
        print(f"[analyzer] {reason} — using smart offset fallback")
        fallback_start = max(0.0, peak_sec_global - 8.0)
        return {
            "is_gameplay": True,
            "description": "",
            "global_start": fallback_start,
            "global_end": fallback_start + float(config.CLIP["max_duration_seconds"])
        }

    try:
        # Build comment context string for Gemini — use highest-liked comment
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
            return fallback("download failed")

        actual_duration = get_segment_duration(segment_path)

        video_file = upload_to_gemini(segment_path)
        shutil.rmtree(str(tmp), ignore_errors=True)  # Delete local segment after upload

        if video_file is None:
            return fallback("Gemini upload failed")

        try:
            result = analyze_with_gemini(
                video_file, peak_sec_local, actual_duration, comment_context
            )
        except Exception as e:
            print(f"[analyzer] Gemini analysis error: {e}")
            result = {
                "description": "",
                "natural_start": max(0.0, peak_sec_local - 8.0),
                "natural_end": max(0.0, peak_sec_local - 8.0) + 52.0
            }
        finally:
            try:
                client.files.delete(name=video_file.name)
                print(f"[analyzer] deleted Gemini file: {video_file.name}")
            except:
                pass

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
            "is_gameplay": result.get("is_gameplay", True),
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


# Module-level Gemini setup
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        result = analyze_clip(sys.argv[1], float(sys.argv[2]), 600.0)
        print(result)
    else:
        print("Usage: python clip_analyzer.py <video_url> <peak_sec>")
