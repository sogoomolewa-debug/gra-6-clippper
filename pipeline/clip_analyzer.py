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
from pipeline import ytdlp


def download_segment(
    video_url: str,
    global_start: float,
    global_end: float,
    output_path: str
) -> bool:
    """Download a video segment around the peak timestamp using yt-dlp."""
    try:
        cmd = ytdlp.command() + [
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
    is_gameplay: bool = Field(description="True if the video segment shows actual direct game graphics specifically from a Grand Theft Auto game (GTA V, GTA Online, GTA 6). False if it is a talking head, reaction video, or gameplay from any other game like Fortnite or Minecraft.")
    is_punchy: bool = Field(description="True if this moment can be fully understood, enjoyed, and impactful in under 20 seconds. False if it requires a long buildup or extended context to make sense (e.g., a 40-second conversation or a long chase).")
    punchiness_reasoning: str = Field(description="One sentence explaining why this clip is or is not punchy.")
    description: str = Field(description="A single sentence describing the visual action at the peak timestamp.")
    natural_start: float = Field(description="The timestamp in seconds where the action peak's setup naturally begins.")
    natural_end: float = Field(description="The timestamp in seconds where the reaction to the action peak naturally ends.")
    viral_score: int = Field(description="Rate the viral potential of this specific moment from 1 to 10. 1-3: Mundane gameplay (driving normally, walking, menus, inventory). 4-5: Mildly interesting (small crash, basic combat, minor stunt). 6-7: Notable moment (impressive stunt, funny physics, unexpected outcome). 8-10: Exceptional (jaw-dropping physics glitch, perfect stunt landing, chain reaction explosion, hilarious NPC behavior). Only score 8+ if a typical viewer would genuinely want to rewatch or share this moment.")
    moment_type: str = Field(
        description=(
            "Classify by the VISUAL OUTCOME viewers see — NOT the cause or action. "
            "Focus on what physically results from the moment, not what triggered it. "
            "\n\nCLASSIFICATION RULES:"
            "\n- If a character's body launches, tumbles, or spins from physics: 'ragdoll'"
            "\n- If someone falls from a great or impossible height: 'impossible_height'"
            "\n- If vehicle or character physics behave impossibly: 'physics_glitch'"
            "\n- If a vehicle launches off terrain or ramp: 'stunt_fail' or 'stunt_success'"
            "\n- If multiple objects chain react: 'chain_reaction'"
            "\n- If NPC does unexpected autonomous behavior: 'npc_behavior'"
            "\n- Only use 'character_interaction' when the moment shows NORMAL EXPECTED "
            "gameplay with NO dramatic physics outcome — e.g. routine combat with no "
            "ragdoll, NPC dialogue, characters walking. "
            "\n\nCRITICAL EXAMPLES:"
            "\n- Hulk punches Spider-Man → Spider-Man ragdolls off skyscraper = 'ragdoll'"
            "\n- Car hits ramp and spins wildly = 'stunt_fail'"
            "\n- Character survives fall from impossible height = 'impossible_survival'"
            "\n- Spider-Man kicks truck, truck does nothing unusual = 'character_interaction'"
            "\n- NPC spontaneously launches into air = 'npc_behavior'"
            "\nWhen in doubt between 'character_interaction' and a physics type: "
            "choose the physics type if any dramatic body movement results."
        )
    )
    action_fills_clip: bool = Field(description="True if the clip window from natural_start to natural_end is engaging throughout. The first 1-3 seconds may show setup/approach (a car approaching a ramp, a character running toward something) — this counts as engaging because it builds anticipation. False ONLY if there are extended dead segments (5+ seconds of uneventful driving, walking, menus, or static scenery with no building tension).")
    loop_worthy: bool = Field(
        description=(
            "True if the clip ends DURING maximum action — mid-ragdoll, mid-explosion, "
            "mid-collision, mid-freefall. The best loops end at climax_sec, not after resolution. "
            "Clips that end during calm aftermath are NOT loop-worthy even if the climax was impressive. "
            "A clip that cuts mid-flight is more loop-worthy than one that shows the landing."
        )
    )
    climax_sec: float = Field(
        description=(
            "The exact timestamp (in seconds within this segment) of MAXIMUM visual chaos — "
            "the single frame where the action is most intense. "
            "This is the impact frame, the apex of the ragdoll arc, the moment of collision, "
            "the peak of the explosion — NOT the setup before it and NOT the aftermath/resolution after it. "
            "Must be between natural_start and natural_end."
        )
    )


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
            f"1. Determine if this clip shows actual, direct in-game gameplay graphics specifically from a Grand Theft Auto game (GTA V, GTA Online, GTA 6). If it is a talking head, news/speculation slides, podcast, commentary show, reaction video, OR gameplay from any other game (like Fortnite, Minecraft, Call of Duty), set is_gameplay to false.\n"
            f"2. Determine if the moment is 'punchy'. Can this moment be fully understood, enjoyed, and impactful in under 20 seconds? If it requires a long buildup or extended context to make sense (e.g., a 40-second conversation or a long chase), set is_punchy to false. We only want fast, punchy action or immediate comedy.\n"
            f"3. Describe in exactly ONE sentence what visually happens at {peak_sec_local:.0f} seconds. Focus on the physical action, stunt, crash, or character interaction (e.g., car collisions, character physics/ragdoll launches, stunt failures or successes, explosive chain reactions) rather than static scenery. Be specific about the vehicles, characters, and motion involved. Avoid generic descriptions (e.g., do NOT just say 'a player drives a car' or 'gameplay footage showing a scene').\n"
            f"4. Find where the peak action at {peak_sec_local:.0f} seconds naturally begins (setup) and naturally ends (reaction complete). "
            f"Requirements: window must be 10-15 seconds long. Include 1-3 seconds of setup/approach BEFORE the action starts — "
            f"this gives viewers context and builds anticipation. Peak at {peak_sec_local:.0f}s must be inside the window.\n"
            f"5. Rate the viral potential of this moment on a scale of 1-10. "
            f"Focus on: Would a casual scroller stop for this? Would they rewatch it? Would they send it to a friend? "
            f"Only score 8+ for truly jaw-dropping or hilarious moments.\n"
            f"6. Classify the moment_type by its VISUAL OUTCOME not its cause. "
            f"If the action results in ragdoll physics: use 'ragdoll'. "
            f"If it results in a character falling from great height: 'impossible_height'. "
            f"If vehicle physics break: 'physics_glitch'. "
            f"A punch that launches a character into freefall = 'ragdoll' not 'character_interaction'. "
            f"Only use 'character_interaction' for mundane expected interactions with no dramatic physics. "
            f"Available types: ragdoll | impossible_survival | physics_glitch | npc_behavior | "
            f"stunt_success | stunt_fail | collision | impossible_height | speed_impact | "
            f"chain_reaction | character_interaction | environmental_reaction | "
            f"ordinary_interaction | mundane_gameplay | other\n"
            f"7. Action density: Does exciting visual action fill the ENTIRE window from natural_start to natural_end? "
            f"If the peak action only lasts 3-4 seconds but the window is 10 seconds, the rest is dead time — set action_fills_clip to false. "
            f"Only set true if every second of the window has something visually engaging happening.\n"
            f"8. Loop potential: Does the clip end at a moment that triggers an immediate rewatch? "
            f"The best viral clips end right at the peak of impact, comedy, or surprise — making the viewer's brain want to see it again instantly. "
            f"If the clip just fades out or ends during a calm moment, set loop_worthy to false.\n"
            f"9. Identify the climax timestamp: the EXACT second within the clip window where "
            f"the visual chaos peaks — the frame of impact, the apex of the ragdoll, "
            f"the moment the car leaves the ground. This must be between natural_start and natural_end. "
            f"This is NOT the same as natural_end — natural_end is where the REACTION completes, "
            f"climax_sec is where the ACTION peaks."
        )

        response = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[video_file, prompt],
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": VideoAnalysis,
                    }
                )
                break  # Success!
            except Exception as ex:
                error_str = str(ex)
                is_503 = "503" in error_str or "UNAVAILABLE" in error_str
                is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

                if attempt == max_attempts:
                    print(f"[analyzer] all {max_attempts} attempts failed: {ex}")
                    raise ex

                if is_503:
                    wait = 30 * attempt  # 30s, 60s, 90s — server needs real time to recover
                    print(f"[analyzer] 503 rate limit — waiting {wait}s before retry {attempt+1}")
                elif is_429:
                    wait = 60  # Quota exhausted — wait a full minute
                    print(f"[analyzer] 429 quota exhausted — waiting {wait}s")
                else:
                    wait = 5
                    print(f"[analyzer] attempt {attempt} failed: {ex} — retrying in {wait}s")

                time.sleep(wait)

        import json
        data = json.loads(response.text)
        print(f"[analyzer] Gemini analysis result: {data}")

        return {
            "is_gameplay": data.get("is_gameplay", True),
            "is_punchy": data.get("is_punchy", True),
            "punchiness_reasoning": data.get("punchiness_reasoning", ""),
            "description": data.get("description", ""),
            "viral_score": int(data.get("viral_score", 5)),
            "moment_type": data.get("moment_type", "other"),
            "action_fills_clip": data.get("action_fills_clip", True),
            "loop_worthy": data.get("loop_worthy", True),
            "natural_start": float(data.get("natural_start", max(0.0, peak_sec_local - 4.0))),
            "natural_end": float(data.get("natural_end", max(0.0, peak_sec_local - 4.0) + config.CLIP["max_duration_seconds"]))
        }
    except Exception as e:
        print(f"[analyzer] Gemini analysis error: {e}")
        return {
            "is_gameplay": True,
            "is_punchy": True,
            "punchiness_reasoning": "fallback error",
            "description": "",
            "viral_score": 5,
            "moment_type": "other",
            "action_fills_clip": True,
            "loop_worthy": True,
            "natural_start": max(0.0, peak_sec_local - 4.0),
            "natural_end": max(0.0, peak_sec_local - 4.0) + config.CLIP["max_duration_seconds"]
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
    min_dur = float(config.CLIP["min_duration_seconds"])

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
        natural_start = max(0.0, peak_sec_local - 4.0)
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
        fallback_start = max(0.0, peak_sec_global - 4.0)
        return {
            "is_gameplay": True,
            "is_punchy": True,
            "punchiness_reasoning": reason,
            "description": "",
            "viral_score": 5,
            "moment_type": "other",
            "download_failed": "download" in reason.lower(),
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
            fallback_start = max(0.0, peak_sec_local - 4.0)
            result = {
                "description": "",
                "natural_start": fallback_start,
                "natural_end": fallback_start + config.CLIP["max_duration_seconds"]
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
            "is_punchy": result.get("is_punchy", True),
            "punchiness_reasoning": result.get("punchiness_reasoning", ""),
            "description": result.get("description", ""),
            "viral_score": result.get("viral_score", 5),
            "moment_type": result.get("moment_type", "other"),
            "global_start": global_start,
            "global_end": global_end
        }

    except Exception as e:
        print(f"[analyzer] analyze_clip error: {e}")
        fallback_start = max(0.0, peak_sec_global - 4.0)
        return {
            "is_gameplay": True,
            "is_punchy": True,
            "punchiness_reasoning": "error",
            "description": "",
            "viral_score": 5,
            "moment_type": "other",
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
