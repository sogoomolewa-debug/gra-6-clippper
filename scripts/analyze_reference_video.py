#!/usr/bin/env python3
"""Analyze a reference Short for pacing, audio, speech, captions, and style.

The script intentionally writes reports outside the repo by default:

    python3 scripts/analyze_reference_video.py path/to/reference.mp4
    python3 scripts/analyze_reference_video.py reference.mp4 --transcript "ngl I jumped"

Requires ffmpeg and ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def require_tool(name: str) -> None:
    if not shutil.which(name):
        raise SystemExit(f"error: {name} is required but was not found on PATH")


def ffprobe_json(path: Path) -> dict[str, Any]:
    result = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels",
        "-of",
        "json",
        str(path),
    ])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    return json.loads(result.stdout)


def parse_fraction(value: str) -> float:
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            return float(num) / float(den)
        except ZeroDivisionError:
            return 0.0
    return float(value or 0)


def collect_audio_metrics(path: Path) -> dict[str, Any]:
    silence = run([
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "silencedetect=noise=-35dB:d=0.12",
        "-f",
        "null",
        "-",
    ])
    volume = run([
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ])
    ebur = run([
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "ebur128=framelog=verbose",
        "-f",
        "null",
        "-",
    ])

    silence_events: list[dict[str, float | str]] = []
    current_start: float | None = None
    for line in silence.stderr.splitlines():
        if "silence_start:" in line:
            match = re.search(r"silence_start:\s*([0-9.]+)", line)
            if match:
                current_start = float(match.group(1))
                silence_events.append({"type": "start", "time": current_start})
        elif "silence_end:" in line:
            match = re.search(r"silence_end:\s*([0-9.]+).*silence_duration:\s*([0-9.]+)", line)
            if match:
                silence_events.append({
                    "type": "end",
                    "time": float(match.group(1)),
                    "duration": float(match.group(2)),
                    "start": current_start if current_start is not None else "",
                })
                current_start = None

    mean_volume = None
    max_volume = None
    for line in volume.stderr.splitlines():
        if "mean_volume:" in line:
            mean_volume = line.split("mean_volume:", 1)[1].strip()
        elif "max_volume:" in line:
            max_volume = line.split("max_volume:", 1)[1].strip()

    integrated_loudness = None
    loudness_range = None
    for line in ebur.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            integrated_loudness = line.split("I:", 1)[1].strip()
        elif "LRA:" in line and "LU" in line:
            loudness_range = line.split("LRA:", 1)[1].strip()

    return {
        "mean_volume": mean_volume,
        "max_volume": max_volume,
        "integrated_loudness": integrated_loudness,
        "loudness_range": loudness_range,
        "silence_events": silence_events,
        "silence_event_count": len(silence_events),
    }


def extract_frames(path: Path, out_dir: Path, fps: float) -> dict[str, Any]:
    frames_dir = out_dir / "frames_1fps"
    scenes_dir = out_dir / "scene_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)

    every_second = run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(path),
        "-vf",
        "fps=1",
        str(frames_dir / "frame_%03d.jpg"),
    ])
    scene_cut = run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(path),
        "-vf",
        "select='gt(scene,0.25)',showinfo",
        "-vsync",
        "vfr",
        str(scenes_dir / "scene_%03d.jpg"),
    ])

    scene_times = []
    for line in scene_cut.stderr.splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if match:
            scene_times.append(float(match.group(1)))

    return {
        "fps": fps,
        "sampled_frames": len(list(frames_dir.glob("*.jpg"))),
        "scene_frames": len(list(scenes_dir.glob("*.jpg"))),
        "scene_times": scene_times,
        "frames_dir": str(frames_dir),
        "scene_frames_dir": str(scenes_dir),
        "frame_extraction_ok": every_second.returncode == 0,
    }


def speech_metrics(transcript: str, duration: float, speech_start: float | None = None, speech_end: float | None = None) -> dict[str, Any]:
    speech_duration = duration
    if speech_start is not None and speech_end is not None and speech_end > speech_start:
        speech_duration = speech_end - speech_start
    words = re.findall(r"[A-Za-z0-9']+", transcript)
    pause_markers = transcript.count("...") + transcript.count("--") + transcript.count(" - ")
    sentence_like_units = [s.strip() for s in re.split(r"[.!?]+", transcript) if s.strip()]
    return {
        "transcript": transcript,
        "speech_start": speech_start,
        "speech_end": speech_end,
        "speech_duration_seconds": round(speech_duration, 3),
        "word_count": len(words),
        "estimated_words_per_second": round(len(words) / speech_duration, 2) if speech_duration > 0 else 0,
        "estimated_words_per_minute": round((len(words) / speech_duration) * 60, 1) if speech_duration > 0 else 0,
        "pause_marker_count": pause_markers,
        "sentence_or_fragment_count": len(sentence_like_units),
        "avg_words_per_fragment": round(len(words) / max(len(sentence_like_units), 1), 1),
    }


def build_report(data: dict[str, Any]) -> str:
    meta = data["metadata"]
    audio = data["audio"]
    frames = data["frames"]
    speech = data["speech"]
    duration = meta["duration_seconds"]

    lines = [
        "# Reference Video Analysis",
        "",
        "## Media",
        f"- Duration: {duration:.2f}s",
        f"- Resolution: {meta['width']}x{meta['height']}",
        f"- FPS: {meta['fps']:.2f}",
        f"- File size: {meta['size_bytes']} bytes",
        f"- Bitrate: {meta.get('bit_rate', 'unknown')}",
        "",
        "## Visual Pacing",
        f"- 1 FPS sample frames: {frames['sampled_frames']} in `{frames['frames_dir']}`",
        f"- Detected scene frames: {frames['scene_frames']} in `{frames['scene_frames_dir']}`",
        f"- Scene cut timestamps: {', '.join(f'{t:.2f}s' for t in frames['scene_times'][:20]) or 'none detected'}",
        "",
        "## Audio",
        f"- Mean volume: {audio['mean_volume'] or 'unknown'}",
        f"- Max volume: {audio['max_volume'] or 'unknown'}",
        f"- Integrated Loudness (LUFS): {audio.get('integrated_loudness') or 'unknown'}",
        f"- Loudness Range (LRA): {audio.get('loudness_range') or 'unknown'}",
        f"- Silence events: {audio['silence_event_count']}",
        "",
        "## Speech",
    ]

    if speech["transcript"]:
        lines.extend([
            f"- Transcript: {speech['transcript']}",
            f"- Speech window: {speech['speech_start']}s to {speech['speech_end']}s",
            f"- Speech duration: {speech['speech_duration_seconds']}s",
            f"- Word count: {speech['word_count']}",
            f"- Estimated WPS: {speech['estimated_words_per_second']}",
            f"- Estimated WPM: {speech['estimated_words_per_minute']}",
            f"- Pause markers: {speech['pause_marker_count']}",
            f"- Avg words per fragment: {speech['avg_words_per_fragment']}",
        ])
    else:
        lines.extend([
            "- Transcript: not provided.",
            "- Add `--transcript \"spoken words here\"` to calculate speech pacing.",
        ])

    lines.extend([
        "",
        "## Pipeline Recommendations",
        "- Match hook length to the speech metrics instead of a fixed visual duration.",
        "- For reference-style clips, prefer 5-7 word setup phrases with one prominent word captioned at a time.",
        "- Use scene cut timestamps to choose whether the reveal should start immediately or after a short setup.",
        "- Compare sampled frames against pipeline output for caption size, placement, and screen occupancy.",
        "- Use silence events and mean/max volume to tune TTS loudness, pause gaps, and reveal audio transition.",
    ])

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a reference Shorts-style MP4.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--transcript", default="", help="Optional manual transcript of spoken words.")
    parser.add_argument("--speech-start", type=float, default=None, help="Optional speech start timestamp in seconds.")
    parser.add_argument("--speech-end", type=float, default=None, help="Optional speech end timestamp in seconds.")
    args = parser.parse_args()

    require_tool("ffmpeg")
    require_tool("ffprobe")

    video = args.video
    if not video.exists():
        raise SystemExit(f"error: file not found: {video}")

    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="reference_analysis_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    probe = ffprobe_json(video)
    video_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = probe.get("format", {})
    duration = float(fmt.get("duration") or 0)
    fps = parse_fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0")

    data = {
        "source": str(video),
        "metadata": {
            "duration_seconds": duration,
            "width": int(video_stream.get("width") or 0),
            "height": int(video_stream.get("height") or 0),
            "fps": fps,
            "size_bytes": int(fmt.get("size") or 0),
            "bit_rate": fmt.get("bit_rate"),
        },
        "audio": collect_audio_metrics(video),
        "frames": extract_frames(video, out_dir, fps),
        "speech": speech_metrics(args.transcript, duration, args.speech_start, args.speech_end),
    }

    json_path = out_dir / "analysis.json"
    md_path = out_dir / "analysis.md"
    json_path.write_text(json.dumps(data, indent=2))
    md_path.write_text(build_report(data))

    print(f"analysis_json={json_path}")
    print(f"analysis_markdown={md_path}")
    print(f"frames_dir={data['frames']['frames_dir']}")
    print(f"scene_frames_dir={data['frames']['scene_frames_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
