import subprocess
import json
import pathlib
import tempfile
import shutil
import time
import os
import sys

from google import genai
import whisper
import yt_dlp

CHANNEL_HANDLE = "HecticSG"
CHANNEL_SHORTS_URL = "https://www.youtube.com/@HecticSG/shorts"
MIN_VIEW_COUNT = 5_000_000
OUTPUT_PATH = pathlib.Path("data/reference_hooks.json")
COOKIES_PATH = pathlib.Path(os.environ.get("YOUTUBE_COOKIES_PATH", "www.youtube.com_cookies.txt"))
MAX_RETRIES = 2

GEMINI_ANALYSIS_PROMPT = """
You are analyzing a viral YouTube Short by creator HecticSG to build
a hook style reference library. Watch the entire video carefully.

Extract the following with MAXIMUM ACCURACY and DEPTH.
Every field matters — this data trains an AI to mirror his style.
Return ONLY valid JSON. No markdown, no explanation.

{
  "hook": {
    "text": "EXACT verbatim words spoken in first 3 seconds. Transcribe precisely.",
    "duration_sec": 0.0,
    "word_count": 0,
    "emphasis_words": ["words he stresses or says louder"],
    "first_word": "first word spoken",
    "last_word": "last word spoken",
    "ends_with_punctuation": "none|period|ellipsis|em_dash|question|exclamation",
    "hook_pattern": "reaction_fragment|direct_address|open_statement|implied_question|exclamation_incomplete|observation_incomplete",
    "sentence_complete": false,
    "why_incomplete": "precise explanation of why the hook feels unfinished or open"
  },

  "delivery": {
    "pace": "slow|medium|fast",
    "words_per_second": 0.0,
    "energy_level": "deadpan|low|medium|high|frantic",
    "tone": "shocked|amused|disbelief|casual|urgent|reverent|horrified|impressed",
    "intonation_pattern": "rising|falling|flat|rising_then_suspended|falling_then_rise|suspended",
    "intonation_final_word": "rising|falling|flat|suspended",
    "micro_pause_before_key_word": true,
    "voice_characteristics": "detailed description of what makes his delivery distinctive in THIS specific clip — not generic, describe exactly what you hear",
    "sounds_scripted": false,
    "naturalness_reason": "why this specific delivery sounds natural or scripted"
  },

  "visual": {
    "game": "name of the game shown",
    "hook_visual": "precise description of what viewer sees during hook section",
    "hook_visual_is_blurred": true,
    "reveal_visual": "precise frame-by-frame description of the viral moment",
    "moment_type": "ragdoll|impossible_survival|physics_glitch|npc_behavior|stunt_success|stunt_fail|collision|impossible_height|speed_impact|chain_reaction|character_interaction|environmental_reaction|combo_kill|other",
    "moment_subject": "who or what the viral moment focuses on",
    "moment_outcome": "exactly what happens — the result that makes this viral",
    "peak_frame_description": "description of the single most visually striking frame",
    "does_reveal_resolve": false,
    "why_unresolved": "what visual question is left open at the end of the clip",
    "cut_timing": "does the clip cut at peak tension or after resolution"
  },

  "psychology": {
    "primary_trigger": "cognitive_dissonance|absurdity|impossibility|anticipation|schadenfreude|awe|humor|surprise|horror|satisfaction",
    "secondary_trigger": "same options or none",
    "viewer_question_created": "exact question this hook plants in the viewer's mind — be precise",
    "why_viewer_replays": "specific psychological reason this clip compels rewatching",
    "what_makes_it_viral": "one precise sentence on the exact psychological mechanism at work",
    "loop_mechanism": "what specific visual or audio element creates the rewatch compulsion",
    "hook_to_reveal_payoff": "how well the hook promise matches the reveal delivery — describe the payoff"
  },

  "clippability": {
    "is_clippable": true,
    "score": 8,
    "score_reasoning": "detailed explanation of the score",
    "what_makes_it_work": "precise list of elements that make this clippable",
    "what_would_break_it": "what single change would kill the viral potential",
    "transferable_to_gta": true,
    "gta_equivalent_moment": "describe the specific GTA VI moment that would be equivalent and trigger the same emotion",
    "gta_hook_translation": "how his exact hook would be adapted for a GTA VI version of this moment"
  },

  "rag_retrieval_tags": [
    "list of 5-10 specific tags for retrieval matching — use moment_type, primary_trigger, hook_pattern, game_mechanic involved"
  ]
}
"""

GEMINI_RETRY_PROMPT_TEMPLATE = """
You previously analyzed this Short and determined it was not clippable.
Your reason was: "{previous_reason}"

Watch the video again with fresh eyes. This time:
1. Look for ANY moment in the video — not just the one HecticSG chose
   to highlight — that could work as a viral clip
2. Is there a 10-14 second window anywhere in this video that contains
   a genuinely shocking, funny, or impossible-looking moment?
3. If yes, change is_clippable to true and describe that moment
4. If no, confirm is_clippable as false with a more detailed reason

Return the same JSON schema. Be thorough — do not dismiss content
without genuinely looking for alternative moments.
"""


def get_shorts_urls(cookies_path: pathlib.Path) -> list[dict]:
    """
    Fetch all Shorts URLs from HecticSG's channel using yt-dlp.
    Returns list of {url, video_id, view_count, title}.
    Filters to MIN_VIEW_COUNT only.
    """
    cmd = [
        sys.executable,
        "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(view_count)s\t%(title)s",
        "--no-warnings"
    ]
    if cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])
    
    node_path = shutil.which("node")
    if node_path:
        cmd.extend(["--js-runtimes", f"node:{node_path}"])
        
    cmd.append(CHANNEL_SHORTS_URL)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"[scraper] yt-dlp error: {result.stderr[-500:]}")
        return []

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        video_id = parts[0].strip()
        try:
            view_count = int(parts[1].strip())
        except:
            continue
        title = parts[2].strip() if len(parts) > 2 else ""

        if view_count >= MIN_VIEW_COUNT:
            entries.append({
                "video_id": video_id,
                "url": f"https://www.youtube.com/shorts/{video_id}",
                "view_count": view_count,
                "title": title
            })

    entries.sort(key=lambda x: x["view_count"], reverse=True)
    print(f"[scraper] found {len(entries)} Shorts above {MIN_VIEW_COUNT:,} views")
    return entries


def download_short(url: str, output_path: str, cookies_path: pathlib.Path) -> bool:
    """Download a single Short as mp4 to output_path."""
    cmd = [
        sys.executable,
        "-m", "yt_dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "-o", output_path
    ]
    if cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])

    node_path = shutil.which("node")
    if node_path:
        cmd.extend(["--js-runtimes", f"node:{node_path}"])

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"[scraper] download failed: {result.stderr[-300:]}")
        return False
    return pathlib.Path(output_path).exists()


def extract_audio(video_path: str, audio_path: str) -> bool:
    """Extract audio from video as 16kHz mono WAV for Whisper."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1",
        "-f", "wav", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0


def transcribe_hook(audio_path: str, model) -> dict:
    """
    Run Whisper with word-level timestamps on audio.
    Returns hook timing data for first 3 seconds only.
    """
    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        task="transcribe"
    )

    words_in_hook = []
    full_hook_text = []
    pause_positions = []
    prev_end = 0.0

    for segment in result["segments"]:
        for word_info in segment.get("words", []):
            word_start = word_info["start"]
            word_end = word_info["end"]
            word_text = word_info["word"].strip()

            if word_start > 3.5:  # First 3.5 seconds covers hook
                break

            # Detect pauses between words
            if prev_end > 0 and (word_start - prev_end) > 0.15:
                pause_positions.append({
                    "position_sec": round(prev_end, 3),
                    "duration_ms": round((word_start - prev_end) * 1000)
                })

            words_in_hook.append({
                "word": word_text,
                "start": round(word_start, 3),
                "end": round(word_end, 3)
            })
            full_hook_text.append(word_text)
            prev_end = word_end

    hook_text = " ".join(full_hook_text).strip()
    hook_duration = words_in_hook[-1]["end"] if words_in_hook else 0.0

    return {
        "whisper_hook_text": hook_text,
        "words_with_timing": words_in_hook,
        "pause_positions": pause_positions,
        "hook_duration_sec": round(hook_duration, 2),
        "word_count": len(words_in_hook)
    }


def upload_to_gemini(video_path: str, client) -> object | None:
    """Upload video to Gemini File API, wait for ACTIVE state."""
    print(f"[scraper] uploading to Gemini: {video_path}")
    video_file = client.files.upload(file=video_path)
    waited = 0
    while True:
        file_info = client.files.get(name=video_file.name)
        if file_info.state.name == "ACTIVE":
            break
        elif file_info.state.name == "FAILED":
            print("[scraper] Gemini upload failed")
            return None
        time.sleep(3)
        waited += 3
        if waited > 120:
            print("[scraper] Gemini upload timeout")
            return None
    print(f"[scraper] Gemini file ready: {video_file.name}")
    return file_info


def analyze_with_gemini(
    video_file: object,
    client,
    whisper_data: dict,
    retry_reason: str = ""
) -> dict | None:
    """
    Send video to Gemini for deep analysis.
    If retry_reason provided, uses focused retry prompt.
    Returns parsed JSON dict or None on failure.
    """
    prompt = GEMINI_ANALYSIS_PROMPT
    if retry_reason:
        prompt = GEMINI_RETRY_PROMPT_TEMPLATE.format(previous_reason=retry_reason)

    # Add Whisper data to prompt for accuracy
    whisper_context = (
        f"\n\nWHISPER TRANSCRIPTION DATA (use this for hook.text accuracy):\n"
        f"Hook text: \"{whisper_data['whisper_hook_text']}\"\n"
        f"Word timings: {json.dumps(whisper_data['words_with_timing'])}\n"
        f"Pauses detected: {json.dumps(whisper_data['pause_positions'])}\n"
        f"Hook duration: {whisper_data['hook_duration_sec']}s\n"
        f"Use this Whisper data to fill hook.text, hook.words_with_timing, "
        f"hook.pause_positions, hook.duration_sec, hook.word_count accurately.\n"
    )

    full_prompt = prompt + whisper_context

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[video_file, full_prompt],
                config={"response_mime_type": "application/json"}
            )
            raw = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            return data
        except Exception as e:
            print(f"[scraper] Gemini attempt {attempt+1} failed: {e}")
            time.sleep(5)
    return None


def load_existing_library() -> dict:
    """Load existing reference_hooks.json to skip already-processed videos."""
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text())
        except:
            pass
    return {"entries": [], "metadata": {"total": 0, "last_updated": ""}}


def save_library(library: dict) -> None:
    """Save library to data/reference_hooks.json."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    library["metadata"]["total"] = len(library["entries"])
    library["metadata"]["last_updated"] = datetime.utcnow().isoformat() + "Z"
    OUTPUT_PATH.write_text(json.dumps(library, indent=2))
    print(f"[scraper] saved {library['metadata']['total']} entries")


def process_video(
    entry: dict,
    client,
    whisper_model,
    cookies_path: pathlib.Path
) -> dict | None:
    """
    Full processing pipeline for a single Short.
    Downloads, transcribes, analyzes, retries if needed.
    Deletes all local files after analysis.
    Returns complete reference entry or None on failure.
    """
    video_id = entry["video_id"]
    url = entry["url"]
    tmp = pathlib.Path(tempfile.mkdtemp())
    video_path = str(tmp / f"{video_id}.mp4")
    audio_path = str(tmp / f"{video_id}.wav")

    try:
        # Download
        print(f"\n[scraper] processing: {entry['title']} ({entry['view_count']:,} views)")
        if not download_short(url, video_path, cookies_path):
            return None

        # Extract audio for Whisper
        if not extract_audio(video_path, audio_path):
            print("[scraper] audio extraction failed")
            return None

        # Whisper transcription
        print("[scraper] running Whisper transcription...")
        whisper_data = transcribe_hook(audio_path, whisper_model)
        print(f"[scraper] Whisper hook: \"{whisper_data['whisper_hook_text']}\"")

        # Upload to Gemini
        video_file = upload_to_gemini(video_path, client)
        if video_file is None:
            return None

        try:
            # First Gemini analysis pass
            analysis = analyze_with_gemini(video_file, client, whisper_data)
            if analysis is None:
                print("[scraper] Gemini analysis failed")
                return None

            # Check clippability — retry if not clippable
            if not analysis.get("clippability", {}).get("is_clippable", True):
                reason = analysis.get("clippability", {}).get("score_reasoning", "no reason given")
                print(f"[scraper] not clippable ({reason}) — retrying...")
                retry_analysis = analyze_with_gemini(
                    video_file, client, whisper_data,
                    retry_reason=reason
                )
                if retry_analysis:
                    analysis = retry_analysis

            # Build final entry
            final_entry = {
                "video_id": video_id,
                "url": url,
                "title": entry["title"],
                "view_count": entry["view_count"],
                "status": "clippable" if analysis.get("clippability", {}).get("is_clippable", False) else "unclippable_confirmed",
                **analysis
            }

            # Merge Whisper timing data into hook section for accuracy
            if "hook" in final_entry:
                final_entry["hook"]["words_with_timing"] = whisper_data["words_with_timing"]
                final_entry["hook"]["pause_positions"] = whisper_data["pause_positions"]
                final_entry["hook"]["duration_sec"] = whisper_data["hook_duration_sec"]
                final_entry["hook"]["word_count"] = whisper_data["word_count"]
                # Whisper text is more accurate than Gemini for exact words
                if whisper_data["whisper_hook_text"]:
                    final_entry["hook"]["text"] = whisper_data["whisper_hook_text"]

            return final_entry

        finally:
            # Always delete Gemini file
            try:
                client.files.delete(name=video_file.name)
                print(f"[scraper] deleted Gemini file: {video_file.name}")
            except:
                pass

    except Exception as e:
        print(f"[scraper] process_video error: {e}")
        return None
    finally:
        # Always delete local files
        shutil.rmtree(str(tmp), ignore_errors=True)


def run_scraper() -> None:
    """Main scraper orchestrator."""
    print("=" * 60)
    print("HecticSG Reference Hook Scraper")
    print(f"Target: {MIN_VIEW_COUNT:,}+ view Shorts only")
    print("=" * 60)

    # Setup Gemini
    if "GEMINI_API_KEY" not in os.environ:
        print("[scraper] ERROR: GEMINI_API_KEY environment variable not set")
        return
        
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Load Whisper model (runs locally, no API)
    print("[scraper] loading Whisper model...")
    whisper_model = whisper.load_model("base")
    print("[scraper] Whisper ready")

    # Load existing library to skip duplicates
    library = load_existing_library()
    processed_ids = {e["video_id"] for e in library["entries"]}
    print(f"[scraper] existing library: {len(processed_ids)} entries")

    # Get URL list
    urls = get_shorts_urls(COOKIES_PATH)
    if not urls:
        print("[scraper] no URLs found — check cookies and channel handle")
        return

    new_entries = 0
    skipped = 0

    for i, entry in enumerate(urls):
        video_id = entry["video_id"]

        # Skip already processed
        if video_id in processed_ids:
            print(f"[scraper] skip duplicate: {video_id}")
            skipped += 1
            continue

        print(f"\n[scraper] {i+1}/{len(urls)} — {entry['view_count']:,} views")

        result = process_video(entry, client, whisper_model, COOKIES_PATH)

        if result:
            library["entries"].append(result)
            processed_ids.add(video_id)
            new_entries += 1
            save_library(library)  # Save after each entry — crash-safe
            print(f"[scraper] ✅ saved: {video_id} ({result['status']})")
        else:
            print(f"[scraper] ❌ failed: {video_id}")

        # Rate limiting — 15 RPM Gemini free tier
        # Each video = 1-2 Gemini calls, sleep 5s between videos
        time.sleep(5)

    print(f"\n[scraper] complete: {new_entries} new, {skipped} skipped")
    print(f"[scraper] total library: {len(library['entries'])} entries")

if __name__ == "__main__":
    run_scraper()
