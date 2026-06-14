# pipeline/transcript.py — Download auto-captions and extract text around peak timestamp

import subprocess
import json
import os
import re
import tempfile
import shutil
import pathlib
import sys

import config


def download_transcript(video_url: str, output_dir: str) -> str | None:
    """Download auto-generated subtitles in json3 format."""
    try:
        output_template = str(pathlib.Path(output_dir) / "%(id)s.%(ext)s")

        # Try English first
        cmd = ["yt-dlp", "--write-auto-sub", "--skip-download",
               "--sub-format", "json3", "--sub-lang", "en",
               "-o", output_template]
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

        # If failed, try en-US
        if result.returncode != 0:
            print(f"[transcript] en failed, trying en-US: {result.stderr.strip()}")
            cmd = ["yt-dlp", "--write-auto-sub", "--skip-download",
                   "--sub-format", "json3", "--sub-lang", "en-US",
                   "-o", output_template]
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
            print(f"[transcript] download failed: {result.stderr.strip()}")
            return None

        # Find the .json3 file
        out_dir = pathlib.Path(output_dir)
        json3_files = list(out_dir.glob("*.json3"))
        if not json3_files:
            print("[transcript] no .json3 file found after download")
            return None

        path = str(json3_files[0])
        print(f"[transcript] downloaded: {path}")
        return path
    except subprocess.TimeoutExpired:
        print("[transcript] yt-dlp timed out")
        return None
    except Exception as e:
        print(f"[transcript] download error: {e}")
        return None


def parse_json3_transcript(file_path: str) -> list[dict]:
    """Parse json3 subtitle file into list of {start_ms, end_ms, text}."""
    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        entries = []
        for event in data.get("events", []):
            start_ms = event.get("tStartMs", 0)
            duration_ms = event.get("dDurationMs", 0)
            end_ms = start_ms + duration_ms

            segs = event.get("segs", [])
            if not segs:
                continue

            text_parts = []
            for seg in segs:
                utf8 = seg.get("utf8", "")
                if utf8:
                    text_parts.append(utf8)

            text = " ".join(text_parts)
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', text).strip()

            if not text or text == "\n":
                continue

            entries.append({
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text
            })

        entries.sort(key=lambda x: x["start_ms"])
        print(f"[transcript] parsed {len(entries)} caption entries")
        return entries
    except Exception as e:
        print(f"[transcript] parse error: {e}")
        return []


def extract_context(transcript: list[dict], target_start_sec: float, window_sec: float = 30.0) -> str:
    """Extract transcript text around a target timestamp."""
    try:
        target_ms = target_start_sec * 1000
        window_ms = window_sec * 1000

        relevant = []
        for entry in transcript:
            if entry["start_ms"] >= (target_ms - window_ms) and entry["start_ms"] <= (target_ms + window_ms):
                relevant.append(entry["text"])

        context = " ".join(relevant)
        # Collapse multiple spaces
        context = re.sub(r'\s+', ' ', context).strip()
        return context
    except Exception as e:
        print(f"[transcript] context extraction error: {e}")
        return ""


def get_video_context(video_url: str, peak_start: float) -> str:
    """Download transcript and extract context around peak timestamp."""
    try:
        tmp = tempfile.mkdtemp()
        path = download_transcript(video_url, tmp)

        if path is None:
            shutil.rmtree(tmp, ignore_errors=True)
            print("[transcript] no transcript available")
            return ""

        transcript = parse_json3_transcript(path)
        context = extract_context(transcript, peak_start)

        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[transcript] extracted {len(context)} chars around {peak_start:.1f}s")
        return context
    except Exception as e:
        print(f"[transcript] error getting context: {e}")
        return ""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m pipeline.transcript <video_url> <timestamp_seconds>")
    else:
        url = sys.argv[1]
        ts = float(sys.argv[2])
        ctx = get_video_context(url, ts)
        print(f"Context ({len(ctx)} chars):\n{ctx[:500]}")
