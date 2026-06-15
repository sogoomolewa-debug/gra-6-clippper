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

import subprocess
import pathlib
import sys
import os
import json

# ── CONFIG ────────────────────────────────────────────────────────────────────
# SET THESE BEFORE RUNNING

CACHED_VIDEO_PATH = "scratch/cached_analyzer_segment.mp4"  # 1280x720 120s cached clip
HOOK_AUDIO_PATH   = "scratch/test_hook.wav"                # Short WAV file (3s)
HOOK_TEXT          = "Nobody saw this coming."              # Test caption text
OUTPUT_PATH        = "scratch/test_output_short.mp4"

# Simulate what clip_analyzer would return (global boundaries)
# Cached video is 120s — pick a 52s window inside it
GLOBAL_START       = 10.0    # Start of natural clip within cached video
GLOBAL_END         = 62.0    # End of natural clip (52 seconds)


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

    # 3 — Check duration (must be 45-57 seconds)
    duration = float(format_info.get("duration", 0))
    duration_ok = 45.0 <= duration <= 57.0
    results["duration_sec"] = round(duration, 2)
    results["duration_ok"] = duration_ok
    print(f"{'✅' if duration_ok else '❌'} Duration: {duration:.2f}s (expected 45-57s)")

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

def run_e2e_test() -> None:
    """Run full end-to-end editing test with cached video."""
    print("=" * 60)
    print("GTA6 SHORTS PIPELINE — E2E TEST")
    print("Using cached video — no downloads")
    print("=" * 60)

    # Validate inputs exist
    for path, name in [(CACHED_VIDEO_PATH, "cached video"), (HOOK_AUDIO_PATH, "hook audio")]:
        if not pathlib.Path(path).exists():
            print(f"❌ Missing {name}: {path}")
            print(f"   Place your cached MP4 at: {CACHED_VIDEO_PATH}")
            print(f"   Generate a test WAV:")
            print(f"   python -c \"import struct,wave; w=wave.open('{HOOK_AUDIO_PATH}','w'); "
                  f"w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); "
                  f"w.writeframes(struct.pack('<' + 'h'*66150, *([0]*66150))); w.close()\"")
            sys.exit(1)

    # Ensure output directory exists
    pathlib.Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)

    # Import editor
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from pipeline.editor import build_short

    print(f"\n[test] cached video: {CACHED_VIDEO_PATH}")
    print(f"[test] hook audio:   {HOOK_AUDIO_PATH}")
    print(f"[test] hook text:    {HOOK_TEXT}")
    print(f"[test] output:       {OUTPUT_PATH}")
    print(f"[test] clip window:  {GLOBAL_START}s → {GLOBAL_END}s ({GLOBAL_END - GLOBAL_START:.1f}s)")
    print()

    # Run build_short with cached video
    success = build_short(
        video_url="",                # Not used — cached_video_path overrides
        global_start=GLOBAL_START,
        global_end=GLOBAL_END,
        hook_audio=HOOK_AUDIO_PATH,
        hook_text=HOOK_TEXT,
        output_path=OUTPUT_PATH,
        cached_video_path=CACHED_VIDEO_PATH   # Use cache
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
