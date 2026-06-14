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
            "-f", "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1][height<=1080]",
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


def build_short(
    video_url: str,
    global_start: float,        # From clip_analyzer — natural start in global time
    global_end: float,          # From clip_analyzer — natural end in global time
    hook_audio: str,
    hook_text: str,
    output_path: str
) -> bool:
    """Build complete YouTube Short: blurred hook intro + clear reveal."""
    try:
        tmp = pathlib.Path(tempfile.mkdtemp())
        clip_duration = global_end - global_start
        print(f"[editor] building short in temp dir: {tmp} (duration: {clip_duration:.1f}s)")

        # STEP 1 — Download the naturally-bounded clip
        raw = tmp / "raw.mp4"
        success = download_clip(video_url, global_start, global_end, str(raw))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 2 — Crop to 9:16 vertical
        vertical = tmp / "vertical.mp4"
        success = crop_to_vertical(str(raw), str(vertical))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 3 — Get hook audio duration
        hook_dur = get_audio_duration(hook_audio)

        # STEP 4 — Trim hook section (first hook_dur seconds)
        hook_vid = tmp / "hook_vid.mp4"
        success = trim_clip(str(vertical), 0, hook_dur, str(hook_vid))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 5 — Blur hook section
        hook_blurred = tmp / "hook_blurred.mp4"
        success = apply_blur(str(hook_vid), str(hook_blurred))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 6 — Replace hook audio with TTS voice
        hook_with_audio = tmp / "hook_with_audio.mp4"
        success = replace_audio(str(hook_blurred), hook_audio, str(hook_with_audio))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 7 — Burn captions onto hook section
        hook_captioned = tmp / "hook_captioned.mp4"
        success = burn_caption(str(hook_with_audio), hook_text, str(hook_captioned))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 8 — Trim reveal section (after hook_dur to end)
        reveal_dur = clip_duration - hook_dur
        reveal = tmp / "reveal.mp4"
        success = trim_clip(str(vertical), hook_dur, reveal_dur, str(reveal))
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # STEP 9 — Concatenate hook + reveal
        success = concatenate_clips(str(hook_captioned), str(reveal), output_path)
        if not success:
            shutil.rmtree(tmp, ignore_errors=True)
            return False

        # CLEANUP
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[editor] short built: {output_path} ({clip_duration:.1f}s)")
        return True

    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[editor] build_short error: {e}")
        return False


if __name__ == "__main__":
    print("editor.py requires full pipeline context — test via pipeline.py")
