# pipeline/editor.py — Download clip segment, compose 9:16 Short

import subprocess
import os
import pathlib
import tempfile
import shutil

import config


def download_clip(video_url: str, start_time: float, end_time: float, output_path: str) -> bool:
    """Download a specific segment of a YouTube video."""
    try:
        cmd = [
            "yt-dlp",
            "--download-sections", f"*{start_time:.2f}-{end_time:.2f}",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "--merge-output-format", "mp4",
            "-o", output_path,
            video_url
        ]
        print(f"[editor] downloading clip: {start_time:.1f}s → {end_time:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[editor] download error: {result.stderr.strip()[:500]}")
            return False
        print(f"[editor] downloaded clip: {output_path}")
        return True
    except subprocess.TimeoutExpired:
        print("[editor] download timed out")
        return False
    except Exception as e:
        print(f"[editor] download error: {e}")
        return False


def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[editor] ffprobe error: {result.stderr.strip()}")
            return float(config.CLIP["hook_duration_seconds"])
        duration = float(result.stdout.strip())
        print(f"[editor] audio duration: {duration:.2f}s")
        return duration
    except Exception as e:
        print(f"[editor] audio duration error: {e}")
        return float(config.CLIP["hook_duration_seconds"])


def crop_to_vertical(input_path: str, output_path: str) -> bool:
    """Crop video to 1080x1920 vertical format."""
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "scale=-2:1920,crop=1080:1920",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path
        ]
        print("[editor] cropping to vertical 1080x1920")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[editor] crop error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] crop error: {e}")
        return False


def trim_clip(input_path: str, start: float, duration: float, output_path: str) -> bool:
    """Trim a clip to a specific start time and duration."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration),
            "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path
        ]
        print(f"[editor] trimming: start={start:.1f}s duration={duration:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[editor] trim error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] trim error: {e}")
        return False


def apply_blur(input_path: str, output_path: str) -> bool:
    """Apply heavy blur to a video clip."""
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "boxblur=20:5",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path
        ]
        print("[editor] applying blur")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[editor] blur error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] blur error: {e}")
        return False


def replace_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """Replace video audio with hook audio."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-shortest",
            "-c:v", "copy", "-c:a", "aac",
            output_path
        ]
        print("[editor] replacing audio with hook voiceover")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[editor] audio replace error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] audio replace error: {e}")
        return False


def burn_caption(input_path: str, text: str, output_path: str) -> bool:
    """Burn caption text onto video."""
    try:
        # Escape special characters for ffmpeg drawtext
        escaped = text.replace("'", "\\'").replace(":", "\\:")
        drawtext_filter = (
            f"drawtext=text='{escaped}'"
            f":fontsize=55:fontcolor=white"
            f":x=(w-text_w)/2:y=h-180"
            f":box=1:boxcolor=black@0.6:boxborderw=12"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", drawtext_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            output_path
        ]
        print(f"[editor] burning caption: {text}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[editor] caption error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] caption error: {e}")
        return False


def concatenate_clips(clip1: str, clip2: str, output_path: str) -> bool:
    """Concatenate two video clips."""
    try:
        # Create temp concat list file
        tmp_list_path = pathlib.Path(tempfile.mktemp(suffix=".txt"))
        with open(tmp_list_path, "w") as f:
            # Escape path for ffmpeg concat demuxer
            f.write(f"file '{clip1}'\n")
            f.write(f"file '{clip2}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(tmp_list_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path
        ]
        print("[editor] concatenating clips")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Cleanup list file
        try:
            tmp_list_path.unlink()
        except Exception:
            pass

        if result.returncode != 0:
            print(f"[editor] concat error: {result.stderr.strip()[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[editor] concat error: {e}")
        return False


def build_short(video_url: str, start_time: float, end_time: float,
                hook_audio: str, hook_text: str, output_path: str) -> bool:
    """Build complete YouTube Short: blurred hook intro + clear reveal."""
    try:
        tmp_dir = pathlib.Path(tempfile.mkdtemp())
        print(f"[editor] building short in temp dir: {tmp_dir}")

        # STEP 1 — Download raw segment
        raw = tmp_dir / "raw.mp4"
        print("[editor] step 1/9: downloading raw segment")
        if not download_clip(video_url, start_time, end_time, str(raw)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 2 — Crop to vertical
        vertical = tmp_dir / "vertical.mp4"
        print("[editor] step 2/9: cropping to vertical")
        if not crop_to_vertical(str(raw), str(vertical)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 3 — Get hook audio duration
        hook_dur = get_audio_duration(hook_audio)
        reveal_start = hook_dur
        print(f"[editor] step 3/9: hook duration = {hook_dur:.2f}s")

        # STEP 4 — Trim hook section
        hook_vid = tmp_dir / "hook_vid.mp4"
        print("[editor] step 4/9: trimming hook section")
        if not trim_clip(str(vertical), 0, hook_dur, str(hook_vid)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 5 — Blur hook section
        hook_blurred = tmp_dir / "hook_blurred.mp4"
        print("[editor] step 5/9: blurring hook section")
        if not apply_blur(str(hook_vid), str(hook_blurred)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 6 — Replace hook section audio with TTS
        hook_with_audio = tmp_dir / "hook_audio.mp4"
        print("[editor] step 6/9: replacing audio with voiceover")
        if not replace_audio(str(hook_blurred), hook_audio, str(hook_with_audio)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 7 — Burn captions onto hook section
        hook_captioned = tmp_dir / "hook_captioned.mp4"
        print("[editor] step 7/9: burning captions")
        if not burn_caption(str(hook_with_audio), hook_text, str(hook_captioned)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 8 — Trim reveal section
        reveal_dur = (end_time - start_time) - hook_dur
        if reveal_dur <= 0:
             reveal_dur = 0.1 # Minimal duration
        reveal = tmp_dir / "reveal.mp4"
        print(f"[editor] step 8/9: trimming reveal ({reveal_dur:.1f}s)")
        if not trim_clip(str(vertical), reveal_start, reveal_dur, str(reveal)):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # STEP 9 — Concatenate hook + reveal
        print("[editor] step 9/9: concatenating final short")
        if not concatenate_clips(str(hook_captioned), str(reveal), output_path):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False

        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"[editor] short built: {output_path}")
        return True
    except Exception as e:
        print(f"[editor] build_short error: {e}")
        return False


if __name__ == "__main__":
    print("editor.py requires full pipeline context — test via pipeline.py")
