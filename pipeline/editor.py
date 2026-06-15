# pipeline/editor.py — Download clip segment, compose 9:16 Short
# BUG 2 FIX: Reveal starts at global_start (natural boundary) — full context after blur
# BUG 3 FIX: Reveal has its own vertical master — original game audio guaranteed
# BUG 5 FIX: crop_to_vertical uses force_original_aspect_ratio=increase for any resolution
#
# RULE: vertical.mp4 is NEVER passed to replace_audio, apply_blur, or burn_caption.
#       It is read-only. Every operation creates a new named output file.

import subprocess
import os
import pathlib
import tempfile
import shutil

import config


def run_ffmpeg(cmd: list[str], step_name: str) -> bool:
    """Run an ffmpeg/ffprobe command, check returncode, print stderr on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[editor] {step_name} failed:")
            print(result.stderr[-500:])
            return False
        print(f"[editor] {step_name} ✓")
        return True
    except subprocess.TimeoutExpired:
        print(f"[editor] {step_name} timed out")
        return False
    except Exception as e:
        print(f"[editor] {step_name} error: {e}")
        return False


def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio/video file using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[editor] ffprobe error: {result.stderr.strip()[-500:]}")
            return float(config.CLIP["hook_duration_seconds"])
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"[editor] audio duration error: {e}")
        return float(config.CLIP["hook_duration_seconds"])


def download_clip(
    video_url: str,
    start_time: float,
    end_time: float,
    output_path: str
) -> bool:
    """Download a specific segment of a YouTube video."""
    try:
        cmd = [
            "yt-dlp",
            "--download-sections", f"*{start_time:.2f}-{end_time:.2f}",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
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
        print(f"[editor] downloading clip: {start_time:.1f}s → {end_time:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[editor] download error: {result.stderr.strip()[-500:]}")
            return False
        print(f"[editor] clip downloaded: {start_time:.1f}s → {end_time:.1f}s")
        return True
    except subprocess.TimeoutExpired:
        print("[editor] download timed out")
        return False
    except Exception as e:
        print(f"[editor] download error: {e}")
        return False


def crop_to_vertical(input_path: str, output_path: str) -> bool:
    """
    Converts ANY input resolution to exactly 1080x1920 (9:16 portrait).

    BUG 5 FIX: force_original_aspect_ratio=increase ensures no black bars.
    Works for landscape (1920x1080), portrait (1080x1920), square, any resolution.
    """
    filter_chain = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", filter_chain,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    return run_ffmpeg(cmd, "crop_to_vertical")


def trim_clip(
    input_path: str,
    start_sec: float,
    duration_sec: float,
    output_path: str
) -> bool:
    """Trim a clip to a specific start time and duration."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{duration_sec:.3f}",
        "-i", input_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        output_path
    ]
    return run_ffmpeg(cmd, f"trim [{start_sec:.1f}s → {start_sec + duration_sec:.1f}s]")


def apply_blur(input_path: str, output_path: str) -> bool:
    """Apply heavy blur to a video clip."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "gblur=sigma=20:steps=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    return run_ffmpeg(cmd, "apply_blur")


def replace_audio(
    video_path: str,
    audio_path: str,
    output_path: str
) -> bool:
    """Replace video audio with TTS audio. Video stream copied, audio from TTS file."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",       # Video from video_path
        "-map", "1:a:0",       # Audio from audio_path (TTS)
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-shortest",            # End when shorter stream ends
        output_path
    ]
    return run_ffmpeg(cmd, "replace_audio")


def wrap_text_by_chars(text: str, max_chars: int = 18) -> str:
    """Wrap text into multiple lines by character count, splitting at word boundaries."""
    try:
        words = text.split()
        lines = []
        current_line = []
        current_len = 0
        for word in words:
            if current_len + len(word) + (1 if current_line else 0) > max_chars:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_len = len(word)
            else:
                current_line.append(word)
                current_len += len(word) + (1 if len(current_line) > 1 else 0)
        if current_line:
            lines.append(" ".join(current_line))
        return "\n".join(lines)
    except Exception as e:
        print(f"[editor] text wrap error: {e}")
        return text


def burn_caption(
    input_path: str,
    text: str,
    output_path: str
) -> bool:
    """Burn caption text onto video."""
    try:
        font_path = config.CLIP.get("font_path", "assets/Oswald-Bold.ttf")
        font_path_abs = str(pathlib.Path(font_path).absolute())
        
        fontsize = config.CLIP.get("font_size_hook", 90)
        outline_w = config.CLIP.get("caption_outline_width", 6)
        outline_color = config.CLIP.get("caption_outline_color", "black")
        shadow_x = config.CLIP.get("caption_shadow_x", 3)
        shadow_y = config.CLIP.get("caption_shadow_y", 3)
        shadow_color = config.CLIP.get("caption_shadow_color", "black")
        hook_caps = config.CLIP.get("hook_caps", True)
        
        if hook_caps:
            text = text.upper()
            
        wrapped_text = wrap_text_by_chars(text, max_chars=18)
        
        # Escape special characters for ffmpeg drawtext
        escaped = wrapped_text.replace("'", "\\'").replace(":", "\\:")
        
        drawtext = (
            f"drawtext=text='{escaped}':"
            f"fontfile='{font_path_abs}':"
            f"fontsize={fontsize}:"
            f"fontcolor=white:"
            f"borderw={outline_w}:"
            f"bordercolor={outline_color}:"
            f"shadowx={shadow_x}:"
            f"shadowy={shadow_y}:"
            f"shadowcolor={shadow_color}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"line_spacing=15"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", drawtext,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            output_path
        ]
        return run_ffmpeg(cmd, "burn_caption")
    except Exception as e:
        print(f"[editor] burn_caption error: {e}")
        return False


def concatenate_clips(
    clip1_path: str,
    clip2_path: str,
    output_path: str
) -> bool:
    """Concatenate hook section and reveal section into final Short."""
    try:
        tmp_list = pathlib.Path(output_path).parent / "concat_list.txt"
        tmp_list.write_text(f"file '{clip1_path}'\nfile '{clip2_path}'\n")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(tmp_list),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            output_path
        ]
        result = run_ffmpeg(cmd, "concatenate")
        tmp_list.unlink(missing_ok=True)
        return result
    except Exception as e:
        print(f"[editor] concatenate error: {e}")
        return False


def build_short(
    video_url: str,
    global_start: float,         # Natural start from clip_analyzer
    global_end: float,           # Natural end from clip_analyzer
    hook_audio: str,
    hook_text: str,
    output_path: str,
    cached_video_path: str = ""  # If set, skip download and use this file
) -> bool:
    """
    OPTION B — Separate backdrop approach (matches reference creator format).

    Two completely separate video sources:

    - BACKDROP: any footage used only as blurred background during hook speech
      nobody sees it clearly — it is fully blurred
    - REVEAL: the actual clip starting EXACTLY at global_start (natural boundary)
      viewer sees clean action from the very beginning after blur lifts

    Final structure:
    [0s - hook_dur]  Blurred backdrop + TTS hook voice + burned captions
    [hook_dur - end] Actual clip from global_start — clean, original audio

    BUG 2 FIX: Reveal starts at global_start (natural boundary) — full context
    BUG 3 FIX: Reveal is its own vertical master — original audio guaranteed
    BUG 5 FIX: crop_to_vertical uses force_original_aspect_ratio=increase
    """
    try:
        tmp = pathlib.Path(tempfile.mkdtemp())
        hook_dur = get_audio_duration(hook_audio)
        print(f"[editor] hook duration: {hook_dur:.2f}s")

        # ── PART 1: BACKDROP (blurred background for hook speech) ──────────────

        backdrop_raw = tmp / "backdrop_raw.mp4"

        if cached_video_path and pathlib.Path(cached_video_path).exists():
            # Use cached file as backdrop source — no download needed
            import shutil as sh
            sh.copy2(cached_video_path, str(backdrop_raw))
            print(f"[editor] using cached video as backdrop: {cached_video_path}")
        else:
            # Download first few seconds of video as backdrop
            # Any footage works — it will be fully blurred
            backdrop_end = min(hook_dur + 5.0, global_start)
            if not download_clip(video_url, 0.0, backdrop_end, str(backdrop_raw)):
                shutil.rmtree(str(tmp), ignore_errors=True)
                return False

        # Trim backdrop raw to exact hook duration first
        backdrop_trimmed_raw = tmp / "backdrop_trimmed_raw.mp4"
        if not trim_clip(str(backdrop_raw), 0.0, hook_dur, str(backdrop_trimmed_raw)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        # Crop backdrop to vertical
        backdrop_vertical = tmp / "backdrop_vertical.mp4"
        if not crop_to_vertical(str(backdrop_trimmed_raw), str(backdrop_vertical)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        # Blur backdrop video
        backdrop_blurred = tmp / "backdrop_blurred.mp4"
        if not apply_blur(str(backdrop_vertical), str(backdrop_blurred)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        # Replace backdrop audio with TTS hook voice
        backdrop_tts = tmp / "backdrop_tts.mp4"
        if not replace_audio(str(backdrop_blurred), hook_audio, str(backdrop_tts)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        # Burn captions onto backdrop
        hook_final = tmp / "hook_final.mp4"
        if not burn_caption(str(backdrop_tts), hook_text, str(hook_final)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        print("[editor] hook section built ✓")

        # ── PART 2: REVEAL (actual clip — starts at natural boundary) ──────────

        reveal_raw = tmp / "reveal_raw.mp4"

        # Dynamically calculate the maximum allowed reveal duration so that the total
        # combined duration (hook + reveal) does not exceed 59.0 seconds.
        max_total_dur = 59.0
        allowed_reveal_dur = max_total_dur - hook_dur
        reveal_dur = min(global_end - global_start, allowed_reveal_dur)
        print(f"[editor] allowed reveal duration to stay under {max_total_dur}s: {allowed_reveal_dur:.2f}s (using {reveal_dur:.2f}s)")

        if cached_video_path and pathlib.Path(cached_video_path).exists():
            # Cached file IS the actual clip — use directly
            import shutil as sh
            sh.copy2(cached_video_path, str(reveal_raw))
            print(f"[editor] using cached video as reveal: {cached_video_path}")
        else:
            # Download actual clip from global_start — clean natural boundary
            # BUG 2 FIX: starts at global_start so viewer gets full context
            if not download_clip(video_url, global_start, global_start + reveal_dur, str(reveal_raw)):
                shutil.rmtree(str(tmp), ignore_errors=True)
                return False

        # Trim reveal to the correct window before cropping
        reveal_trimmed_raw = tmp / "reveal_trimmed_raw.mp4"
        if cached_video_path and pathlib.Path(cached_video_path).exists():
            if not trim_clip(str(reveal_raw), global_start, reveal_dur, str(reveal_trimmed_raw)):
                shutil.rmtree(str(tmp), ignore_errors=True)
                return False
        else:
            # Downloaded segment is already the correct window starting at 0.0
            import shutil as sh
            sh.copy2(str(reveal_raw), str(reveal_trimmed_raw))

        # Crop reveal to vertical — this is the reveal master, never modify it
        # BUG 3 FIX: reveal_vertical has its own original audio, never touched
        reveal_vertical = tmp / "reveal_vertical.mp4"
        if not crop_to_vertical(str(reveal_trimmed_raw), str(reveal_vertical)):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        reveal_duration = get_audio_duration(str(reveal_vertical))
        print(f"[editor] reveal duration: {reveal_duration:.2f}s | original audio intact ✓")

        # ── PART 3: CONCATENATE ────────────────────────────────────────────────

        # hook_final:      blurred backdrop + TTS voice + captions
        # reveal_vertical: clean clip from global_start + original game audio
        if not concatenate_clips(str(hook_final), str(reveal_vertical), output_path):
            shutil.rmtree(str(tmp), ignore_errors=True)
            return False

        # ── CLEANUP ────────────────────────────────────────────────────────────

        shutil.rmtree(str(tmp), ignore_errors=True)
        total = hook_dur + reveal_duration
        print(f"[editor] ✅ short built: {output_path} ({total:.1f}s total)")
        return True

    except Exception as e:
        print(f"[editor] build_short error: {e}")
        try:
            shutil.rmtree(str(tmp), ignore_errors=True)
        except Exception:
            pass
        return False


if __name__ == "__main__":
    print("Run test_e2e.py to test editor with cached video")
