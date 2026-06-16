# test_e2e.py — End-to-end test of the editing pipeline with frame verification
#
# PURPOSE:
# Full end-to-end test using a cached MP4.
# Does NOT download anything. Does NOT call YouTube API or Modal.
# Tests: crop → blur → audio replace → captions → concatenate → verify output.
# Extracts total frames from output to confirm all bug fixes are correct.
#
# USAGE:
#   1. Place your cached MP4 at: cache/sample_clip.mp4
#   2. Generate a silent test hook:
#      python -c "
#      import struct, wave
#      w = wave.open('cache/test_hook.wav', 'w')
#      w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
#      w.writeframes(struct.pack('<' + 'h'*66150, *([0]*66150)))
#      w.close()
#      print('test_hook.wav created')
#      "
#   3. Run: python test_e2e.py

# Load env vars first
import pathlib
import os
import sys

# Ensure pipeline is importable
sys.path.insert(0, str(pathlib.Path(__file__).parent))

# Load .env variables manually
env_path = pathlib.Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip().strip('"').strip("'")

import subprocess
import json
import struct
import wave

# ── CONFIG ────────────────────────────────────────────────────────────────────

CACHED_VIDEO_PATH = "scratch/cached_analyzer_segment.mp4"  # 1280x720 120s cached clip
HOOK_AUDIO_PATH   = "scratch/test_hook.wav"                # Short WAV file
OUTPUT_PATH        = "scratch/test_output_short.mp4"


# ── VERIFICATION FUNCTIONS ────────────────────────────────────────────────────

def ffprobe_info(video_path: str) -> dict:
    """Extract full video info using ffprobe JSON output."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames,duration,codec_name"
            ":format=duration,size",
            "-of", "json",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[verify] ffprobe failed: {result.stderr}")
            return {}
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[verify] ffprobe error: {e}")
        return {}


def get_audio_info(video_path: str) -> dict:
    """Check audio stream exists and get info."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,bit_rate,sample_rate",
            "-of", "json",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return data.get("streams", [{}])[0] if data.get("streams") else {}
    except Exception as e:
        print(f"[verify] audio info error: {e}")
        return {}


def calculate_expected_frames(duration_sec: float, fps_str: str) -> int:
    """
    Calculate expected frame count from duration and fps string.
    fps_str format from ffprobe: "30000/1001" or "30/1"
    """
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)
        return int(duration_sec * fps)
    except Exception:
        return int(duration_sec * 30.0)


def verify_output(output_path: str) -> dict:
    """
    Run all verification checks on the output Short.
    Returns dict with all results and a pass/fail for each.
    """
    print("\n" + "=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)

    results = {}
    info = ffprobe_info(output_path)
    audio_info = get_audio_info(output_path)

    streams = info.get("streams", [{}])
    video_stream = streams[0] if streams else {}
    format_info = info.get("format", {})

    # 1 — Check file exists
    exists = pathlib.Path(output_path).exists()
    results["file_exists"] = exists
    print(f"{'✅' if exists else '❌'} File exists: {output_path}")

    if not exists:
        return results

    # 2 — Check dimensions (must be 1080x1920)
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    correct_dims = (width == 1080 and height == 1920)
    results["dimensions"] = f"{width}x{height}"
    results["dimensions_correct"] = correct_dims
    print(f"{'✅' if correct_dims else '❌'} Dimensions: {width}x{height} (expected 1080x1920)")

    # 3 — Check duration (must be 45-60 seconds)
    duration = float(format_info.get("duration", 0))
    duration_ok = 45.0 <= duration <= 60.0
    results["duration_sec"] = round(duration, 2)
    results["duration_ok"] = duration_ok
    print(f"{'✅' if duration_ok else '❌'} Duration: {duration:.2f}s (expected 45-60s)")

    # 4 — Check total frames
    fps_str = video_stream.get("r_frame_rate", "30/1")
    nb_frames_raw = video_stream.get("nb_frames", "0")

    if nb_frames_raw and nb_frames_raw != "N/A":
        actual_frames = int(nb_frames_raw)
    else:
        # ffprobe sometimes doesn't report nb_frames — count manually
        try:
            count_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-count_frames",
                "-show_entries", "stream=nb_read_frames",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output_path
            ]
            count_result = subprocess.run(count_cmd, capture_output=True, text=True)
            actual_frames = int(count_result.stdout.strip()) if count_result.stdout.strip().isdigit() else 0
        except Exception:
            actual_frames = 0

    expected_frames = calculate_expected_frames(duration, fps_str)
    # Allow 5% tolerance for encoding differences
    frames_ok = actual_frames > 0 and abs(actual_frames - expected_frames) < (expected_frames * 0.05)

    results["fps"] = fps_str
    results["total_frames_actual"] = actual_frames
    results["total_frames_expected"] = expected_frames
    results["frames_ok"] = frames_ok
    print(f"{'✅' if frames_ok else '❌'} Total frames: {actual_frames} actual | {expected_frames} expected @ {fps_str}fps")

    # 5 — Check no black frames in second half
    # Sample a frame from 75% through the video
    sample_time = duration * 0.75
    sample_path = str(pathlib.Path(output_path).parent / "frame_sample.jpg")
    try:
        sample_cmd = [
            "ffmpeg", "-y", "-ss", f"{sample_time:.1f}",
            "-i", output_path, "-frames:v", "1",
            "-f", "image2", sample_path
        ]
        subprocess.run(sample_cmd, capture_output=True)
    except Exception:
        pass
    sample_exists = pathlib.Path(sample_path).exists()
    sample_size = pathlib.Path(sample_path).stat().st_size if sample_exists else 0

    # A black frame compresses to very small file (< 5KB)
    # A real frame is typically 50KB+
    frame_has_content = sample_size > 5000
    results["frame_at_75pct_size_bytes"] = sample_size
    results["no_black_frames"] = frame_has_content
    print(f"{'✅' if frame_has_content else '❌'} Frame at 75% ({sample_time:.1f}s): {sample_size} bytes ({'has content' if frame_has_content else 'possibly black/still'})")
    if sample_exists:
        pathlib.Path(sample_path).unlink(missing_ok=True)

    # 6 — Check audio stream exists in output
    has_audio = bool(audio_info)
    results["has_audio"] = has_audio
    results["audio_codec"] = audio_info.get("codec_name", "none")
    print(f"{'✅' if has_audio else '❌'} Audio stream: {audio_info.get('codec_name', 'MISSING')}")

    # 7 — Check file size is reasonable (not empty, not corrupt)
    file_size = pathlib.Path(output_path).stat().st_size
    size_ok = file_size > 500_000  # More than 500KB
    results["file_size_bytes"] = file_size
    results["file_size_ok"] = size_ok
    print(f"{'✅' if size_ok else '❌'} File size: {file_size / 1_000_000:.2f} MB")

    # Summary
    all_passed = all([
        correct_dims, duration_ok, frames_ok,
        frame_has_content, has_audio, size_ok
    ])
    results["all_passed"] = all_passed
    print("\n" + "=" * 60)
    print(f"RESULT: {'✅ ALL CHECKS PASSED' if all_passed else '❌ SOME CHECKS FAILED'}")
    print("=" * 60 + "\n")

    return results


# ── MAIN TEST RUNNER ──────────────────────────────────────────────────────────

def generate_fallback_silent_wav(path: str, duration_sec: float = 3.0) -> None:
    """Generate a silent fallback WAV file."""
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        w = wave.open(str(p), 'w')
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        num_frames = int(22050 * duration_sec)
        w.writeframes(struct.pack('<' + 'h' * num_frames, *([0] * num_frames)))
        w.close()
        print(f"[test] created silent fallback WAV: {path}")
    except Exception as e:
        print(f"[test] error creating fallback WAV: {e}")


def run_e2e_test() -> None:
    """Run full end-to-end editing test with cached video."""
    print("=" * 60)
    print("GTA6 SHORTS PIPELINE — E2E TEST (WITH INTEGRATION)")
    print("=" * 60)

    # Validate cached video exists
    if not pathlib.Path(CACHED_VIDEO_PATH).exists():
        print(f"❌ Missing cached video: {CACHED_VIDEO_PATH}")
        sys.exit(1)

    # Ensure output directory exists
    pathlib.Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)

    from pipeline import clip_analyzer, voice, hook
    from pipeline.editor import build_short

    # 1. Get video duration
    video_duration = clip_analyzer.get_segment_duration(CACHED_VIDEO_PATH)
    print(f"[test] Cached video duration: {video_duration:.2f}s")

    # 2. Call Gemini 2.5 Flash to discover boundaries & description
    print("\n[test] 1. Discovering viral moment via Gemini 2.5 Flash...")
    peak_sec_local = 30.0
    comment_context = "the money glitch is insane"
    
    # Upload to Gemini File API, then analyze
    video_file = clip_analyzer.upload_to_gemini(CACHED_VIDEO_PATH)
    
    description_text = ""
    if video_file is None:
        print("[test] ⚠️ Gemini upload failed.")
        print("[test] Using fallback boundaries & description for E2E validation.")
        natural_start = 22.0
        natural_end = 74.0
        description_text = "A player shows an inventory screen with a huge amount of glitched money."
    else:
        try:
            res = clip_analyzer.analyze_with_gemini(
                video_file=video_file,
                peak_sec_local=peak_sec_local,
                segment_duration=video_duration,
                comment_context=comment_context
            )
            print("[test] ✓ Gemini analysis succeeded.")
            natural_start = res["natural_start"]
            natural_end = res["natural_end"]
            description_text = res.get("description", "")
            print(f"[test] Raw boundaries returned: {natural_start}s → {natural_end}s")
            print(f"[test] Description: {description_text}")
        except Exception as e:
            print(f"[test] ⚠️ Gemini analysis error: {e}")
            print("[test] Using fallback boundaries & description for E2E validation.")
            natural_start = 22.0
            natural_end = 74.0
            description_text = "A player shows an inventory screen with a huge amount of glitched money."
        finally:
            try:
                clip_analyzer.client.files.delete(name=video_file.name)
                print(f"[test] deleted Gemini file: {video_file.name}")
            except:
                pass

    # Clamp boundaries
    local_start, local_end = clip_analyzer.clamp_boundaries(
        natural_start,
        natural_end,
        peak_sec_local,
        video_duration
    )
    print(f"[test] Clamped boundaries: {local_start}s → {local_end}s ({local_end - local_start:.1f}s)")

    # 3. Generate hook dynamically via Groq
    print("\n[test] 2. Generating hook dynamically via Groq...")
    hook_text = hook.get_hook_with_fallback(
        video_title="GTA 6 Money Glitch Gameplay",
        visual_description=description_text,
        transcript_context="",
        timestamp_comments=[{"text": comment_context, "like_count": 100}]
    )
    print(f"[test] Generated hook: {hook_text}")

    # 4. Generate actual voice hook (or fallback to silent wav on failure)
    print("\n[test] 3. Generating voice hook...")
    pathlib.Path(HOOK_AUDIO_PATH).unlink(missing_ok=True)
    voice_success = voice.generate_voice(hook_text, HOOK_AUDIO_PATH)
    if not voice_success or not pathlib.Path(HOOK_AUDIO_PATH).exists():
        print("[test] ⚠️ Voice generation failed (likely billing/rate limit). Using fallback silent WAV.")
        generate_fallback_silent_wav(HOOK_AUDIO_PATH, duration_sec=3.0)
    else:
        print(f"[test] ✓ Voice generated successfully: {HOOK_AUDIO_PATH}")

    # 5. Run build_short with boundaries and generated/fallback hook audio
    print("\n[test] 4. Building Short...")
    success = build_short(
        video_url="",
        global_start=local_start,
        global_end=local_end,
        hook_audio=HOOK_AUDIO_PATH,
        hook_text=hook_text,
        output_path=OUTPUT_PATH,
        cached_video_path=CACHED_VIDEO_PATH,
        original_channel="Hazardous"
    )

    if not success:
        print("❌ build_short FAILED — check ffmpeg errors above")
        sys.exit(1)

    print("\n[test] build_short completed — running verification\n")

    # Verify output
    results = verify_output(OUTPUT_PATH)

    # Exit code
    sys.exit(0 if results.get("all_passed") else 1)


if __name__ == "__main__":
    run_e2e_test()
