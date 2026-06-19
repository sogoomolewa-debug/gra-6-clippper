# ARCHIVED DOCUMENT - HISTORICAL REFERENCE ONLY

**⚠️ WARNING:** This document describes the ORIGINAL pipeline design from project inception.
The actual implementation has diverged significantly. Refer to ARCHITECTURE.md for current design.

**Date archived:** 2026-06-18  
**Reason:** Architecture has evolved; many described features changed or replaced  
**Current docs:** See CLAUDE.md and ARCHITECTURE.md

---

# GTA6 Shorts Automation Pipeline — Full Blueprint

**Channel: BYNDUO | Stack: GitHub Actions + YouTube API + Claude API + Qwen3-TTS on Modal + ffmpeg**

-----

## System Architecture

```
[GitHub Actions Cron — Daily 8AM UTC]
              │
              ▼
     ┌─────────────────┐
     │   search.py     │  ← YouTube Data API v3
     │ Find viral vids │    Search + eligibility filter
     └────────┬────────┘
              │ Top 3 eligible video IDs
              ▼
     ┌─────────────────┐
     │  heatmap.py     │  ← yt-dlp --dump-json
     │ Find peak time  │    Parse heatmap[] array
     └────────┬────────┘
              │ (start_time, end_time, video_url)
              ▼
     ┌─────────────────┐
     │ transcript.py   │  ← yt-dlp --write-auto-sub
     │ Get context     │    Extract text at timestamp
     └────────┬────────┘
              │ transcript excerpt
              ▼
     ┌─────────────────┐
     │   hook.py       │  ← Claude API (claude-sonnet-4-6)
     │ Generate hook   │    1 punchy sentence, max 10 words
     └────────┬────────┘
              │ hook text
              ▼
     ┌─────────────────┐
     │   voice.py      │  ← Modal HTTP endpoint
     │ Synthesize audio│    Qwen3-TTS on A10G GPU
     └────────┬────────┘     (scales to zero, ~$0.01/day)
              │ hook_audio.wav
              ▼
     ┌─────────────────┐
     │   editor.py     │  ← ffmpeg
     │ Compose Short   │    Blur hook + reveal clip + captions
     └────────┬────────┘
              │ final_short.mp4
              ▼
     ┌─────────────────┐
     │  uploader.py    │  ← YouTube Data API v3
     │ Upload Short    │    With credits in description
     └─────────────────┘
```

-----

## Repository File Structure

```
gta6-shorts-pipeline/
├── .github/
│   └── workflows/
│       ├── daily.yml              # Daily pipeline — search, pick from queue, upload 1 Short
│       └── fetch_stats.yml        # Weekly stats fetcher — updates performance log
├── pipeline/
│   ├── search.py                  # YouTube search + filter (tiered: GTA6 → GTA5)
│   ├── heatmap.py                 # yt-dlp heatmap extractor
│   ├── transcript.py              # Transcript puller + slicer
│   ├── hook.py                    # Claude API hook generator
│   ├── voice.py                   # Modal endpoint caller
│   ├── editor.py                  # ffmpeg compositor
│   ├── uploader.py                # YouTube upload
│   └── queue_manager.py           # Queue read/write/dedup logic
├── assets/
│   └── voice_sample.wav           # Your 2-min voice clone sample
├── data/
│   ├── queue.json                 # Pending + processed video queue
│   └── performance_log.json       # Short performance snapshots (24h, 72h, 7d)
├── modal_tts.py                   # Modal deployment (deploy once, not in Actions)
├── pipeline.py                    # Main orchestrator
├── fetch_stats.py                 # Weekly stats updater
├── config.py                      # Constants and settings
└── requirements.txt               # Python dependencies
```

-----

## config.py — Constants & Settings

```python
# config.py

# --- Tiered content sources ---
# Tier 1 (GTA 6) searched every day
# Tier 2 (GTA 5) only activates when queue drops below QUEUE_MIN_SIZE
CONTENT_TIERS = [
    {
        "name": "gta6",
        "queries": [
            "GTA 6 gameplay",
            "GTA VI trailer",
            "Grand Theft Auto 6",
            "GTA 6 new footage",
            "GTA 6 details"
        ],
        "min_views": 20000,
        "max_age_hours": 48,
        "min_channel_subscribers": 10000
    },
    {
        "name": "gta5",                          # Fallback when queue is low
        "queries": [
            "GTA 5 funny moments 2026",
            "GTA V best clips",
            "GTA 5 insane moments"
        ],
        "min_views": 50000,                      # Higher bar — evergreen is competitive
        "max_age_hours": 168,                    # 7 days — not breaking news
        "min_channel_subscribers": 25000
    }
]

ELIGIBILITY = {
    "min_duration_seconds": 240,    # 4 min minimum source video
    "max_duration_seconds": 3600,   # 60 min maximum
    "min_like_ratio": 0.02,         # 2% likes/views
}

QUEUE = {
    "path": "data/queue.json",
    "min_size": 3,                  # Activate GTA5 fallback below this
    "max_pending": 20               # Cap to avoid stale backlog
}

CLIP = {
    "max_duration_seconds": 55,     # YouTube Shorts ceiling
    "hook_duration_seconds": 3,     # Blurred hook section
    "output_width": 1080,
    "output_height": 1920           # 9:16 vertical
}

TTS = {
    "voice_sample_path": "assets/voice_sample.wav",
    "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "modal_timeout_seconds": 90     # Accounts for cold start (~30s)
}

UPLOAD = {
    "limit_per_run": 1,             # 1 Short/day — change only after 10k subs
    "category_id": "20",            # Gaming
    "privacy_status": "public",
    "tags": ["GTA6", "GTA VI", "GTA6 Shorts", "Gaming", "GrandTheftAuto"]
}

LOGS = {
    "performance_path": "data/performance_log.json",
    "snapshot_intervals_hours": [24, 72, 168]   # When stats get fetched
}
```

-----

## requirements.txt

```
# Pipeline — runs in GitHub Actions
google-api-python-client==2.108.0
google-auth==2.23.4
google-auth-oauthlib==1.1.0
yt-dlp
ffmpeg-python==0.2.0
anthropic
requests==2.31.0
python-dotenv==1.0.0
isodate

# Modal — deploy from Codespaces only, not needed in Actions
modal
```

-----

## Headroom Setup (Do This First)

Headroom compresses tool outputs, logs, and files before they reach the LLM — 60-95% token savings with zero quality loss. Install it once, wrap your CLI tool, everything else is automatic.

```bash
# Install
pip install "headroom-ai[all]"

# Wrap your CLI tool — replace [your-cli] with whatever you use
headroom wrap [your-cli]

# Verify compression is active
headroom perf
```

Headroom sits silently between your prompts and the model. No changes to your workflow needed beyond the wrap command.

-----

## Single Master Prompt

**Copy and paste this entire prompt in one shot.** It builds the complete pipeline — all files, all modules, all configs — in a single session. No back-and-forth, no context overhead between modules.

-----

```
You are building a complete YouTube Shorts automation pipeline called gta6-shorts-pipeline.
Build every file listed below. Do not stop until all files are complete.
Write fully working production code — no placeholder comments, no "implement this later".
Every function must have real logic and full error handling.

════════════════════════════════════════════════════════════
PROJECT CONTEXT
════════════════════════════════════════════════════════════

This pipeline runs daily on GitHub Actions. It:
1. Searches YouTube for viral GTA 6 long-form videos (with GTA 5 as fallback)
2. Stores eligible videos in a persistent JSON queue
3. Pops the top-scored video from the queue
4. Finds the most-rewatched segment using yt-dlp heatmap data
5. Extracts transcript context around that timestamp
6. Calls Claude API to generate a 1-sentence hook (max 10 words)
7. Calls a Modal HTTP endpoint to synthesize hook audio in cloned voice (Qwen3-TTS)
8. Uses ffmpeg to build a 9:16 Short: [blurred clip + hook audio + captions] → [full clarity clip]
9. Uploads to YouTube as a Short with original creator credit in description
10. Logs performance metadata to a JSON file
11. Commits data/queue.json and data/performance_log.json back to the repo

════════════════════════════════════════════════════════════
FILE STRUCTURE TO CREATE
════════════════════════════════════════════════════════════

gta6-shorts-pipeline/
├── .github/workflows/
│   ├── daily.yml
│   └── fetch_stats.yml
├── pipeline/
│   ├── __init__.py              (empty)
│   ├── search.py
│   ├── heatmap.py
│   ├── transcript.py
│   ├── hook.py
│   ├── voice.py
│   ├── editor.py
│   ├── uploader.py
│   └── queue_manager.py
├── data/
│   ├── queue.json               (initialize: {"pending":[],"processed":[]})
│   └── performance_log.json     (initialize: {"shorts":[]})
├── assets/                      (empty dir, user drops voice_sample.wav here)
├── modal_tts.py
├── pipeline.py
├── fetch_stats.py
├── config.py
├── requirements.txt
├── setup.sh
└── .env.example

════════════════════════════════════════════════════════════
FILE: config.py
════════════════════════════════════════════════════════════

CONTENT_TIERS = [
  {
    "name": "gta6",
    "queries": ["GTA 6 gameplay","GTA VI trailer","Grand Theft Auto 6","GTA 6 new footage","GTA 6 details"],
    "min_views": 20000,
    "max_age_hours": 48,
    "min_channel_subscribers": 10000
  },
  {
    "name": "gta5",
    "queries": ["GTA 5 funny moments 2026","GTA V best clips","GTA 5 insane moments"],
    "min_views": 50000,
    "max_age_hours": 168,
    "min_channel_subscribers": 25000
  }
]

ELIGIBILITY = {
  "min_duration_seconds": 240,
  "max_duration_seconds": 3600,
  "min_like_ratio": 0.02
}

QUEUE = {
  "path": "data/queue.json",
  "min_size": 3,
  "max_pending": 20
}

CLIP = {
  "max_duration_seconds": 55,
  "hook_duration_seconds": 3,
  "output_width": 1080,
  "output_height": 1920
}

TTS = {
  "voice_sample_path": "assets/voice_sample.wav",
  "modal_timeout_seconds": 90
}

UPLOAD = {
  "limit_per_run": 1,
  "category_id": "20",
  "privacy_status": "public",
  "tags": ["GTA6","GTA VI","GTA6 Shorts","Gaming","GrandTheftAuto"]
}

LOGS = {
  "performance_path": "data/performance_log.json",
  "snapshot_intervals_hours": [24, 72, 168]
}

════════════════════════════════════════════════════════════
FILE: requirements.txt
════════════════════════════════════════════════════════════

google-api-python-client==2.108.0
google-auth==2.23.4
google-auth-oauthlib==1.1.0
yt-dlp
ffmpeg-python==0.2.0
anthropic
requests==2.31.0
python-dotenv==1.0.0
isodate
modal

════════════════════════════════════════════════════════════
FILE: setup.sh
════════════════════════════════════════════════════════════

Script that:
- sudo apt-get install -y ffmpeg
- pip install -r requirements.txt
- Verifies ffmpeg, yt-dlp installed (print versions)
- Creates data/ dir if missing, initializes queue.json and performance_log.json if missing
- Prints "Environment ready"

════════════════════════════════════════════════════════════
FILE: pipeline/search.py
════════════════════════════════════════════════════════════

IMPORTS: googleapiclient.discovery, google.auth, datetime, isodate, os, config

FUNCTION: get_top_videos(api_key: str, tier: str = "gta6", limit: int = 5) -> list[dict]

  Uses tier name to look up the matching dict in config.CONTENT_TIERS.
  
  Step 1 — search_recent_videos(api_key, queries, published_after, max_age_hours):
    For each query in tier["queries"]:
      Call YouTube search.list:
        type=video, videoDuration=medium, order=viewCount, maxResults=10
        publishedAfter = (now - max_age_hours).isoformat() + "Z"
    Deduplicate video IDs across queries.
    Return flat list of unique video IDs.

  Step 2 — get_video_details(api_key, video_ids):
    Call videos.list(part="statistics,contentDetails,snippet", id=",".join(ids))
    Call channels.list(part="statistics", id=",".join(channel_ids)) for subscriber counts
    Return list of dicts:
      video_id, url (https://youtube.com/watch?v={id}), title, description,
      channel_id, channel_title, channel_url (https://youtube.com/@{handle} or channel URL),
      view_count (int), like_count (int or 0 if hidden), duration_seconds (int),
      published_at (ISO str), subscriber_count (int)

  Step 3 — is_eligible(video, tier):
    duration_seconds >= config.ELIGIBILITY["min_duration_seconds"]
    duration_seconds <= config.ELIGIBILITY["max_duration_seconds"]
    view_count >= tier["min_views"]
    subscriber_count >= tier["min_channel_subscribers"]
    like_count/view_count >= config.ELIGIBILITY["min_like_ratio"] (skip check if like_count == 0)
    Returns bool

  Step 4 — score_video(video):
    hours_old = (now - published_at).total_seconds() / 3600
    recency_weight = 1.0 if hours_old < 12 else (0.7 if hours_old < 24 else 0.4)
    like_ratio = like_count / view_count if like_count > 0 else 0
    return (view_count * recency_weight) + (like_ratio * 50000)

  Filter eligible, score, sort descending, return top `limit` as list of dicts.
  Each dict must include: video_id, url, title, channel_title, channel_url,
  duration_seconds, score (float), view_count, like_count.

ERROR HANDLING: wrap all API calls in try/except, log errors, return [] on failure.
Add if __name__ == "__main__": block that prints results.

════════════════════════════════════════════════════════════
FILE: pipeline/heatmap.py
════════════════════════════════════════════════════════════

IMPORTS: subprocess, json, sys, config

FUNCTION: get_clip_timestamps(video_url: str) -> tuple[float, float]

  Step 1 — get_heatmap(video_url):
    Run: subprocess.run(["yt-dlp","--dump-json","--no-download", video_url], capture_output=True)
    Parse stdout as JSON. Extract "heatmap" key.
    Each item: {start_time: float, end_time: float, value: float 0-1}
    Return list or None if key missing.

  Step 2 — find_peak_window(heatmap, window=52.0):
    Sliding window across heatmap segments.
    For each window start: sum intensity values of segments overlapping this window,
    weighted by overlap proportion.
    Return (best_start, best_start + window).
    Clamp end to last segment end_time.

  Step 3 — get_duration(video_url):
    Parse "duration" from yt-dlp --dump-json output.
    Return float seconds.

  If heatmap exists and len >= 10: use find_peak_window.
  Else: fallback = (duration * 0.3, duration * 0.3 + 52)
  Print which path taken and timestamps.
  Return (start_time, end_time). Never raise exceptions.

Add if __name__ == "__main__": accepting URL as sys.argv[1].

════════════════════════════════════════════════════════════
FILE: pipeline/transcript.py
════════════════════════════════════════════════════════════

IMPORTS: subprocess, json, os, re, tempfile

FUNCTION: get_video_context(video_url: str, peak_start: float) -> str

  Step 1 — download_transcript(video_url, output_dir):
    Run yt-dlp --write-auto-sub --skip-download --sub-format json3 --sub-lang en
    output: output_dir/%(id)s.%(ext)s
    If fails, retry with --sub-lang en-US.
    Return path to .json3 file or None.

  Step 2 — parse_json3(file_path):
    Parse yt-dlp json3 subtitle format.
    Return list of {start_ms: int, end_ms: int, text: str}
    Clean text: strip HTML tags, collapse whitespace.

  Step 3 — extract_context(transcript, peak_start, window=30.0):
    Get all entries from (peak_start - window) to (peak_start + window) seconds.
    Join text into single string. Return "" if none found.

  Use tempfile.mkdtemp(), clean up after.
  Return context string or "" on any failure. Never raise.

════════════════════════════════════════════════════════════
FILE: pipeline/hook.py
════════════════════════════════════════════════════════════

IMPORTS: anthropic, os, random

SYSTEM_PROMPT = "You write viral YouTube Shorts hooks for a GTA 6 gaming channel.
Your hooks must be exactly 1 sentence, maximum 10 words.
Never spoil what happens. Create pure curiosity or shock.
No emojis. No hashtags. Output ONLY the hook sentence, nothing else."

FALLBACKS = [
  "Nobody saw this coming.",
  "This is why everyone is rewatching.",
  "GTA 6 just broke the internet.",
  "You need to see this moment.",
  "This scene has everyone talking."
]

FUNCTION: generate_hook(video_title: str, context: str = "") -> str
  Call anthropic.Anthropic().messages.create:
    model="claude-sonnet-4-6", max_tokens=50
    system=SYSTEM_PROMPT
    user message: "Video title: {video_title}\nContext: {context or 'not available'}\nWrite the hook."
  Extract text from response. Strip whitespace.

FUNCTION: validate_hook(hook: str) -> bool
  len(hook.split()) <= 15 and len(hook) > 0

FUNCTION: get_hook_with_fallback(video_title: str, context: str = "") -> str
  Try generate_hook up to 3 times, return first that passes validate_hook.
  If all fail: return random.choice(FALLBACKS)
  Wrap all in try/except — never raise.

Add if __name__ == "__main__": with sample inputs.

════════════════════════════════════════════════════════════
FILE: pipeline/voice.py
════════════════════════════════════════════════════════════

IMPORTS: requests, base64, os, config

FUNCTION: load_voice_sample(path: str = None) -> str
  path defaults to config.TTS["voice_sample_path"]
  Read as binary, return base64 encoded string.
  Print helpful error if file not found.

FUNCTION: call_modal_endpoint(text: str, ref_audio_b64: str, ref_text: str) -> bytes | None
  POST to os.environ["MODAL_TTS_ENDPOINT"]
  Payload: {"text": text, "ref_audio_b64": ref_audio_b64, "ref_text": ref_text}
  timeout = config.TTS["modal_timeout_seconds"]
  On success: decode response.json()["audio_b64"] and return bytes.
  On "error" key in response or exception: log and return None.

FUNCTION: verify_audio(path: str) -> bool
  File exists and size > 1000 bytes.

FUNCTION: generate_voice(text: str, output_path: str) -> bool
  Orchestrates: load_voice_sample → call_modal_endpoint → write bytes → verify.
  ref_text from os.environ.get("REF_TEXT", "")
  Print each step. Return bool. Never raise.

Add if __name__ == "__main__": synthesizing a test sentence.

════════════════════════════════════════════════════════════
FILE: pipeline/editor.py
════════════════════════════════════════════════════════════

IMPORTS: subprocess, os, tempfile, config

All ffmpeg calls via subprocess.run. Capture stderr. On non-zero returncode: print error, return False.

FUNCTION: download_clip(video_url, start_time, end_time, output_path) -> bool
  yt-dlp --download-sections "*{start_time}-{end_time}"
  -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
  -o output_path video_url

FUNCTION: get_audio_duration(audio_path) -> float
  ffprobe -v quiet -print_format json -show_streams audio_path
  Parse JSON, return duration from audio stream.

FUNCTION: compose_short(clip_path, hook_audio_path, hook_text, output_path) -> bool

  Use a temp directory for all intermediate files. Steps:

  STEP A — Crop to 9:16:
    ffmpeg -i clip_path -vf "scale=-2:1920,crop=1080:1920" -c:a copy vertical.mp4

  STEP B — Create hook section (blurred + voice audio):
    hook_dur = get_audio_duration(hook_audio_path)
    ffmpeg -i vertical.mp4 -i hook_audio_path
      -t {hook_dur}
      -filter_complex "[0:v]boxblur=20:5[v]"
      -map "[v]" -map 1:a
      hook_section.mp4

  STEP C — Add captions to hook section:
    Escape hook_text for ffmpeg drawtext (replace : with \:, ' with \' etc)
    ffmpeg -i hook_section.mp4
      -vf "drawtext=text='{escaped_text}':fontsize=55:fontcolor=white:
           box=1:boxcolor=black@0.5:boxborderw=12:
           x=(w-text_w)/2:y=h-180"
      hook_captioned.mp4

  STEP D — Create reveal section (clear clip from hook_dur to end):
    ffmpeg -i vertical.mp4 -ss {hook_dur} reveal_section.mp4

  STEP E — Concatenate using concat demuxer:
    Write concat list file: "file 'hook_captioned.mp4'\nfile 'reveal_section.mp4'"
    ffmpeg -f concat -safe 0 -i list.txt -c copy output_path

  Return True only if all steps succeed. Clean up temp dir.

FUNCTION: build_short(video_url, start_time, end_time, hook_audio, hook_text, output_path) -> bool
  Orchestrates download_clip → compose_short. Uses tempfile.mkdtemp(). Returns bool.

Add if __name__ == "__main__": with hardcoded test values.

════════════════════════════════════════════════════════════
FILE: pipeline/uploader.py
════════════════════════════════════════════════════════════

IMPORTS: googleapiclient.discovery, googleapiclient.http, google.oauth2.credentials,
google.auth.transport.requests, json, os, config

FUNCTION: get_youtube_client():
  Read os.environ["YOUTUBE_OAUTH_JSON"], parse JSON.
  Create Credentials(token=None, refresh_token=..., client_id=..., client_secret=..., token_uri=...)
  Refresh with google.auth.transport.requests.Request()
  Return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

FUNCTION: generate_metadata(video_title, original_channel, original_video_url) -> dict:
  title = "🔥 " + " ".join(video_title.split()[:8]) + " #GTA6 #Shorts"
  title = title[:100]
  description = (
    f"The most rewatched moment from this GTA 6 video.\n\n"
    f"Original video by {original_channel}: {original_video_url}\n\n"
    "#GTA6 #GTAVI #GrandTheftAuto #Gaming #Shorts"
  )
  Return dict with snippet (title, description, tags, categoryId) and
  status (privacyStatus, selfDeclaredMadeForKids=False)

FUNCTION: upload_video(file_path, metadata) -> str | None:
  MediaFileUpload with resumable=True, chunksize=5*1024*1024
  youtube.videos().insert(part="snippet,status", body=metadata, media_body=media)
  Resumable upload loop with progress printing. Retry transient errors up to 3x.
  Return video_id string or None.

FUNCTION: upload_short(file_path, video_title, original_channel, original_url) -> str | None:
  Orchestrates generate_metadata → upload_video.
  Print "✅ https://youtube.com/shorts/{video_id}" on success.

Add if __name__ == "__main__": for testing.

════════════════════════════════════════════════════════════
FILE: pipeline/queue_manager.py
════════════════════════════════════════════════════════════

IMPORTS: json, os, datetime, config

FUNCTION: load_queue() -> dict
  Read config.QUEUE["path"]. Return {"pending":[],"processed":[]} if missing or corrupt.

FUNCTION: save_queue(queue) -> None
  Create data/ dir if needed. Write JSON with indent=2. Catch and log errors.

FUNCTION: add_to_queue(queue, videos: list[dict], source_type: str) -> int
  existing_ids = set of all video_ids in pending + processed
  For each video not in existing_ids:
    Add source_type, queued_at (utcnow ISO), append to pending
  Re-sort pending by score desc. Trim to config.QUEUE["max_pending"].
  Return count added.

FUNCTION: pop_top(queue) -> dict | None
  Pop and return queue["pending"][0]. Return None if empty. Do not save.

FUNCTION: requeue(queue, video) -> None
  Append video to END of pending (lowest priority).

FUNCTION: mark_processed(queue, video, short_id: str) -> None
  Append to processed: {video_id, short_id, source_type, uploaded_at: utcnow ISO}
  Keep processed max 100 items (trim oldest).

FUNCTION: get_status(queue) -> str
  Return multiline string with pending/processed counts split by source_type.

Add if __name__ == "__main__": printing current queue status.

════════════════════════════════════════════════════════════
FILE: modal_tts.py
════════════════════════════════════════════════════════════

Deploy command: modal deploy modal_tts.py
After deploy: copy endpoint URL to GitHub secret MODAL_TTS_ENDPOINT

import modal, base64, io

app = modal.App("qwen3-tts")
volume = modal.Volume.from_name("qwen3-tts-weights", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.11").pip_install([
  "qwen-tts","soundfile","torch","transformers<5.0","numpy"
])

@app.function(image=image, gpu="A10G", volumes={"/model-cache": volume},
              timeout=120, container_idle_timeout=60)
@modal.web_endpoint(method="POST")
def generate(request: dict) -> dict:
  import torch, soundfile as sf, os
  from qwen_tts import Qwen3TTSModel
  os.environ["HF_HOME"] = "/model-cache"
  model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base", device_map="cuda", dtype=torch.bfloat16
  )
  ref_bytes = base64.b64decode(request["ref_audio_b64"])
  with open("/tmp/ref.wav","wb") as f: f.write(ref_bytes)
  wavs, sr = model.generate_voice_clone(
    text=request["text"], ref_audio="/tmp/ref.wav", ref_text=request["ref_text"]
  )
  buf = io.BytesIO()
  sf.write(buf, wavs, sr, format="WAV")
  return {"audio_b64": base64.b64encode(buf.getvalue()).decode(), "sample_rate": sr}

Wrap in try/except. Return {"error": str(e), "audio_b64": None} on failure.

════════════════════════════════════════════════════════════
FILE: pipeline.py
════════════════════════════════════════════════════════════

IMPORTS: pipeline.search, pipeline.heatmap, pipeline.transcript, pipeline.hook,
pipeline.voice, pipeline.editor, pipeline.uploader, pipeline.queue_manager,
config, os, json, datetime, subprocess

UPLOAD_LIMIT = config.UPLOAD["limit_per_run"]

FUNCTION: log_result(short_id, video, start_time, hook_text):
  Load data/performance_log.json (or {"shorts":[]}).
  Append entry:
    short_id, uploaded_at (utcnow ISO), source_video_id, source_type,
    hook_text, hook_word_count, peak_start, peak_position_pct, clip_duration,
    snapshots: {"24h":{views:0,likes:0,comments:0}, "72h":{...}, "7d":{...}}, notes: ""
  Save back.

FUNCTION: commit_data_files():
  subprocess git config, git add data/queue.json data/performance_log.json,
  git diff --staged --quiet || git commit -m "pipeline: {short_id} [{date}]"
  git push
  Wrap in try/except, print warning if fails (don't abort pipeline).

FUNCTION: run_pipeline():

  api_key = os.environ["YOUTUBE_API_KEY"]

  # 1. QUEUE REFRESH
  queue = queue_manager.load_queue()
  pending_count = len(queue["pending"])
  
  new_gta6 = search.get_top_videos(api_key, tier="gta6")
  added = queue_manager.add_to_queue(queue, new_gta6, "gta6")
  print(f"Added {added} GTA6 videos to queue")
  
  if pending_count < config.QUEUE["min_size"]:
    print(f"Queue low ({pending_count}), activating GTA5 fallback")
    new_gta5 = search.get_top_videos(api_key, tier="gta5")
    added5 = queue_manager.add_to_queue(queue, new_gta5, "gta5")
    print(f"Added {added5} GTA5 videos to queue")
  
  queue_manager.save_queue(queue)
  print(queue_manager.get_status(queue))

  # 2. PICK FROM QUEUE
  video = queue_manager.pop_top(queue)
  if not video:
    print("Queue empty — nothing to process today")
    return

  print(f"\n=== Processing: {video['title']} ({video['source_type']}) ===")

  # 3. PROCESS
  start_time, end_time = heatmap.get_clip_timestamps(video["url"])
  context = transcript.get_video_context(video["url"], start_time)
  hook_text = hook.get_hook_with_fallback(video["title"], context)
  print(f"Hook: {hook_text}")

  hook_audio = f"/tmp/hook_{video['video_id']}.wav"
  if not voice.generate_voice(hook_text, hook_audio):
    print("Voice gen failed — requeueing")
    queue_manager.requeue(queue, video)
    queue_manager.save_queue(queue)
    return

  output_path = f"/tmp/short_{video['video_id']}.mp4"
  if not editor.build_short(video["url"], start_time, end_time, hook_audio, hook_text, output_path):
    print("Edit failed — requeueing")
    queue_manager.requeue(queue, video)
    queue_manager.save_queue(queue)
    return

  short_id = uploader.upload_short(
    output_path, video["title"], video["channel_title"], video["url"]
  )
  if not short_id:
    print("Upload failed — requeueing")
    queue_manager.requeue(queue, video)
    queue_manager.save_queue(queue)
    return

  # 4. LOG + COMMIT
  log_result(short_id, video, start_time, hook_text)
  queue_manager.mark_processed(queue, video, short_id)
  queue_manager.save_queue(queue)
  commit_data_files()

  # 5. CLEANUP
  for f in [hook_audio, output_path]:
    if os.path.exists(f): os.remove(f)

  print(f"\n✅ Done: https://youtube.com/shorts/{short_id}")

if __name__ == "__main__":
  run_pipeline()

════════════════════════════════════════════════════════════
FILE: fetch_stats.py
════════════════════════════════════════════════════════════

IMPORTS: googleapiclient.discovery, google.oauth2.credentials,
google.auth.transport.requests, json, os, datetime, config

Uses same get_youtube_client() pattern as uploader.py.

FUNCTION: fetch_video_stats(youtube, video_id) -> dict | None
  Call videos.list(part="statistics", id=video_id)
  Return {views: int, likes: int, comments: int} or None.

FUNCTION: needs_snapshot(entry, label, hours) -> bool
  entry["snapshots"][label]["views"] == 0
  AND hours since entry["uploaded_at"] >= hours

FUNCTION: run():
  youtube = get_youtube_client()
  Load data/performance_log.json
  updates = 0
  For each entry in log["shorts"]:
    For (24,"24h"), (72,"72h"), (168,"7d"):
      If needs_snapshot: fetch and fill. updates += 1
  Save log. Print f"Stats fetch complete. {updates} snapshots updated."

if __name__ == "__main__": run()

════════════════════════════════════════════════════════════
FILE: .github/workflows/daily.yml
════════════════════════════════════════════════════════════

name: GTA6 Shorts Daily Pipeline
on:
  schedule: [{cron: "0 8 * * *"}]
  workflow_dispatch:
jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with: {token: "${{ secrets.GITHUB_TOKEN }}"}
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: sudo apt-get install -y ffmpeg
      - uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: pip-${{ hashFiles("requirements.txt") }}
      - run: pip install -r requirements.txt
      - run: python pipeline.py
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          YOUTUBE_OAUTH_JSON: ${{ secrets.YOUTUBE_OAUTH_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          MODAL_TTS_ENDPOINT: ${{ secrets.MODAL_TTS_ENDPOINT }}
          REF_TEXT: ${{ secrets.REF_TEXT }}

════════════════════════════════════════════════════════════
FILE: .github/workflows/fetch_stats.yml
════════════════════════════════════════════════════════════

name: Fetch Short Performance Stats
on:
  schedule: [{cron: "0 10 * * 1"}]
  workflow_dispatch:
jobs:
  fetch-stats:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with: {token: "${{ secrets.GITHUB_TOKEN }}"}
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install google-api-python-client google-auth
      - run: python fetch_stats.py
        env:
          YOUTUBE_OAUTH_JSON: ${{ secrets.YOUTUBE_OAUTH_JSON }}
      - run: |
          git config user.name "pipeline-bot"
          git config user.email "bot@pipeline"
          git add data/performance_log.json
          git diff --staged --quiet || git commit -m "stats: weekly update $(date +%Y-%m-%d)"
          git push

════════════════════════════════════════════════════════════
FINAL INSTRUCTIONS
════════════════════════════════════════════════════════════

1. Create every file listed above with full working code
2. Never use placeholder comments — all logic must be implemented
3. Every function needs try/except — pipeline must never crash hard
4. Add if __name__ == "__main__": to every pipeline/*.py module for isolated testing
5. After creating all files, print a checklist confirming each file was created
```

-----

**Key API calls:**

- `search.list` — find recent videos by query
- `videos.list` — get full stats, duration, channel info
- `channels.list` — verify subscriber count

```python
# search.py — skeleton shape

def search_recent_videos(api_key, query, published_after):
    # Returns list of video IDs from search.list
    pass

def get_video_details(api_key, video_ids):
    # Returns dict of stats, duration, channel for each ID
    pass

def parse_duration(iso_duration):
    # Converts PT4M30S → 270 seconds
    pass

def is_eligible(video_data):
    # Checks all ELIGIBILITY thresholds
    # Returns True/False
    pass

def score_video(video_data):
    # Score = (views * recency_weight) + (like_ratio * 1000)
    # Newer videos with high engagement score higher
    pass

def get_top_videos(api_key, limit=3):
    # Orchestrates search → details → filter → score → return top N
    pass
```

### Gemini CLI Prompt — search.py

```
Build a Python module called search.py for a YouTube automation pipeline.

TASK: Search YouTube for viral GTA 6 long-form videos published in the last 48 hours and return the top 3 by a composite score.

IMPORTS NEEDED: googleapiclient.discovery, datetime, isodate, os

FUNCTIONS TO BUILD:

1. search_recent_videos(api_key, queries: list, published_after: datetime) -> list[str]
   - Calls YouTube Data API v3 search.list for each query in queries list
   - Parameters: type=video, videoDuration=medium|long, order=viewCount, maxResults=10 per query
   - publishedAfter must be ISO 8601 format
   - Deduplicates video IDs across queries
   - Returns flat list of unique video IDs

2. get_video_details(api_key, video_ids: list) -> list[dict]
   - Calls videos.list with parts: statistics, contentDetails, snippet
   - For each video returns dict with: id, title, description, channel_id, channel_title, 
     view_count, like_count, duration_seconds, published_at, thumbnail_url
   - Also calls channels.list to get subscriber_count for each channel_id
   - Handles missing like_count gracefully (some channels hide likes)

3. is_eligible(video: dict) -> bool
   - Checks: duration_seconds >= 240 and <= 3600
   - Checks: view_count >= 20000
   - Checks: published within last 48 hours
   - Checks: subscriber_count >= 10000
   - Checks: like_count/view_count >= 0.02 (skip if like_count missing)
   - Returns True only if ALL checks pass

4. score_video(video: dict) -> float
   - recency_hours = hours since published_at
   - recency_weight = 1.0 if recency_hours < 12 else 0.7 if < 24 else 0.4
   - like_ratio = like_count / view_count (0 if missing)
   - score = (view_count * recency_weight) + (like_ratio * 50000)
   - Returns float score

5. get_top_videos(api_key: str, limit: int = 3) -> list[dict]
   - Searches from 48 hours ago using all queries in config.SEARCH_QUERIES
   - Gets details, filters eligible, scores, sorts descending, returns top N
   - Prints summary of each eligible video found

ERROR HANDLING:
- Wrap all API calls in try/except
- Log errors with print() showing which step failed
- Return empty list on total failure, not exception

Use config.py ELIGIBILITY constants for all thresholds.
Include a if __name__ == "__main__": block that runs get_top_videos and prints results.
```

-----

## Module 2 — heatmap.py

**What it does:** Takes a video URL, runs yt-dlp with –dump-json to get the heatmap array, finds the peak intensity window that fits within CLIP.max_duration_seconds, returns the start and end timestamp.

```python
# heatmap.py — skeleton shape

def get_heatmap_data(video_url):
    # yt-dlp --dump-json, parse heatmap[] from output
    # Returns list of {start_time, end_time, value} dicts
    pass

def find_peak_window(heatmap, window_duration=52):
    # Sliding window across heatmap segments
    # Returns (start_time, end_time) of highest avg intensity window
    pass

def get_clip_timestamps(video_url):
    # Orchestrates: get heatmap → find peak → return timestamps
    # Fallback if no heatmap: return (video_duration * 0.3, video_duration * 0.3 + 52)
    pass
```

### Gemini CLI Prompt — heatmap.py

```
Build a Python module called heatmap.py that extracts the most-rewatched segment timestamp from a YouTube video.

TASK: Use yt-dlp to get heatmap data from a video and identify the peak engagement window.

IMPORTS NEEDED: subprocess, json, sys

FUNCTIONS TO BUILD:

1. get_heatmap_data(video_url: str) -> list[dict] | None
   - Runs: subprocess.run(["yt-dlp", "--dump-json", "--no-download", video_url])
   - Parses stdout as JSON
   - Extracts the "heatmap" key from the JSON
   - Each heatmap item has: start_time (float), end_time (float), value (float 0-1)
   - Returns the heatmap list or None if key doesn't exist

2. find_peak_window(heatmap: list[dict], window_duration: float = 52.0) -> tuple[float, float]
   - Uses a sliding window approach across heatmap segments
   - For each possible window start, sums the intensity values of all segments that fall within window_duration seconds
   - Weights segments by their overlap with the window (partial segments count proportionally)
   - Returns (best_start_time, best_start_time + window_duration) tuple
   - Ensures end_time does not exceed last heatmap segment end_time

3. get_fallback_timestamps(video_url: str, window_duration: float = 52.0) -> tuple[float, float]
   - Runs yt-dlp --dump-json to get total duration
   - Returns timestamps at 30% into the video as fallback
   - Formula: start = duration * 0.3, end = start + window_duration

4. get_clip_timestamps(video_url: str) -> tuple[float, float]
   - Calls get_heatmap_data first
   - If heatmap exists and has >= 10 segments: uses find_peak_window
   - If heatmap missing or too short: uses get_fallback_timestamps
   - Prints which path was taken and what timestamps were found
   - Returns (start_time, end_time) as floats (seconds)

ERROR HANDLING:
- If yt-dlp subprocess fails, catch and return fallback timestamps
- Never raise exceptions — always return a valid timestamp tuple
- Print warning messages when falling back

Include if __name__ == "__main__": that accepts a URL as sys.argv[1] and prints timestamps.
```

-----

## Module 3 — transcript.py

**What it does:** Downloads auto-generated captions for a video using yt-dlp, extracts the text around the peak timestamp, feeds it to Claude API to understand what’s happening in that moment.

### Gemini CLI Prompt — transcript.py

```
Build a Python module called transcript.py for extracting and analyzing YouTube video transcript context around a specific timestamp.

TASK: Get the auto-generated captions for a YouTube video, extract text around a target timestamp, and return a clean context string.

IMPORTS NEEDED: subprocess, json, os, re, tempfile

FUNCTIONS TO BUILD:

1. download_transcript(video_url: str, output_dir: str) -> str | None
   - Runs yt-dlp with flags: --write-auto-sub --skip-download --sub-format json3 --sub-lang en
   - Output template: output_dir/%(id)s.%(ext)s
   - Finds the downloaded .json3 file in output_dir
   - Returns file path or None if download failed
   - Falls back to --sub-lang en-US if en fails

2. parse_json3_transcript(file_path: str) -> list[dict]
   - Parses the yt-dlp json3 subtitle format
   - Returns list of dicts: [{start_ms, end_ms, text}, ...]
   - Cleans text: removes HTML tags, strips extra whitespace
   - Converts start/end to milliseconds as integers

3. extract_context(transcript: list[dict], target_start: float, context_window: float = 30.0) -> str
   - target_start is in seconds
   - Extracts all subtitle entries from (target_start - context_window) to (target_start + context_window)
   - Joins their text into a single string
   - Returns empty string if no entries found in window

4. get_video_context(video_url: str, peak_start: float) -> str
   - Uses tempfile.mkdtemp() for output directory
   - Calls download_transcript, parse_json3_transcript, extract_context in sequence
   - Cleans up temp directory after extraction
   - Returns context string, or empty string on any failure
   - Prints progress at each step

ERROR HANDLING:
- All subprocess calls wrapped in try/except
- If any step fails, log the error and return empty string
- Never block pipeline execution

Include if __name__ == "__main__": that accepts video_url and timestamp as sys.argv args.
```

-----

## Module 4 — hook.py

**What it does:** Takes the transcript context and video metadata, calls Claude API, returns a single punchy 8-10 word sentence that creates curiosity without spoiling the clip.

### Gemini CLI Prompt — hook.py

```
Build a Python module called hook.py that uses the Anthropic API to generate a short hook sentence for a YouTube Short.

TASK: Generate a single curiosity-driven hook sentence (max 10 words) for a GTA 6 YouTube Short.

IMPORTS NEEDED: anthropic, os

SYSTEM PROMPT TO USE IN API CALL:
"You write viral YouTube Shorts hooks for a GTA 6 gaming channel. 
Your hooks must be exactly 1 sentence, maximum 10 words. 
Never spoil what happens. Create pure curiosity or shock.
No emojis. No hashtags. Output ONLY the hook sentence, nothing else."

FUNCTIONS TO BUILD:

1. generate_hook(video_title: str, context: str = "") -> str
   - Calls Anthropic API with model claude-sonnet-4-6, max_tokens 50
   - User message format:
     "Video title: {video_title}
      Context from the most-rewatched moment: {context if context else 'not available'}
      Write the hook."
   - Extracts text from response
   - Validates: must be <= 15 words (generous limit), must end with period or no punctuation
   - Returns the hook string

2. validate_hook(hook: str) -> bool
   - Word count <= 15
   - Not empty
   - Does not contain: "GTA 6" or "Grand Theft Auto" (redundant in context)
   - Returns bool

3. get_hook_with_fallback(video_title: str, context: str = "") -> str
   - Calls generate_hook up to 3 times
   - Returns first valid hook
   - If all 3 fail validation, returns hardcoded fallback:
     ["Nobody saw this coming.",
      "This is why everyone is rewatching.",
      "GTA 6 just broke the internet."]
     Pick randomly from fallbacks.

ENVIRONMENT:
- API key from os.environ["ANTHROPIC_API_KEY"]
- Wrap API call in try/except, return fallback on exception

Include if __name__ == "__main__": with sample video_title and context for testing.
```

-----

## Modal Deployment — modal_tts.py

**Deploy once from Codespaces with `modal deploy modal_tts.py`. Never needs redeploying unless you change the model. GitHub Actions just calls the endpoint URL.**

```python
# modal_tts.py
# Setup: pip install modal && modal token new
# Deploy: modal deploy modal_tts.py
# Copy endpoint URL → GitHub secret MODAL_TTS_ENDPOINT

import modal, base64, io

app = modal.App("qwen3-tts")

# Volume caches model weights — downloads once (~1.5GB), reused every call
volume = modal.Volume.from_name("qwen3-tts-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install([
        "qwen-tts",
        "soundfile",
        "torch",
        "transformers<5.0",     # Qwen3-TTS breaks on transformers >= 5.0
        "numpy"
    ])
)

@app.function(
    image=image,
    gpu="A10G",
    volumes={"/model-cache": volume},
    timeout=120,
    container_idle_timeout=60   # Scale to zero after 60s idle
)
@modal.web_endpoint(method="POST")
def generate(request: dict) -> dict:
    import torch, soundfile as sf, os
    from qwen_tts import Qwen3TTSModel

    os.environ["HF_HOME"] = "/model-cache"

    model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device_map="cuda",
        dtype=torch.bfloat16
    )

    ref_audio_bytes = base64.b64decode(request["ref_audio_b64"])
    with open("/tmp/ref.wav", "wb") as f:
        f.write(ref_audio_bytes)

    wavs, sr = model.generate_voice_clone(
        text=request["text"],
        ref_audio="/tmp/ref.wav",
        ref_text=request["ref_text"]
    )

    buf = io.BytesIO()
    sf.write(buf, wavs, sr, format="WAV")
    return {"audio_b64": base64.b64encode(buf.getvalue()).decode(), "sample_rate": sr}
```

### Gemini CLI Prompt — modal_tts.py

```
Build a Modal deployment file called modal_tts.py for Qwen3-TTS voice cloning.

REQUIREMENTS:
- App name: "qwen3-tts"
- GPU: A10G
- Model: Qwen/Qwen3-TTS-12Hz-0.6B-Base
- Cache model weights in Modal Volume called "qwen3-tts-weights" mounted at /model-cache
  Set HF_HOME=/model-cache so transformers uses the volume as cache
- container_idle_timeout: 60 seconds
- timeout: 120 seconds
- Pin transformers<5.0 (Qwen3-TTS breaks on 5.0+)

ENDPOINT:
- POST web_endpoint function called "generate"
- Input JSON: { text, ref_audio_b64, ref_text }
  - text: hook sentence to synthesize
  - ref_audio_b64: base64-encoded bytes of voice_sample.wav
  - ref_text: exact transcription of the voice sample recording
- Output JSON: { audio_b64, sample_rate }
  - audio_b64: base64-encoded WAV bytes of synthesized speech

IMAGE: debian_slim python 3.11, packages: qwen-tts, soundfile, torch, transformers<5.0, numpy

ERROR HANDLING:
- Wrap model inference in try/except
- Return {"error": str(e), "audio_b64": None} on failure

Add comments explaining:
- Deploy command: modal deploy modal_tts.py
- Where to find endpoint URL: Modal dashboard after deploy
- Model cold start: ~30s on first call after idle, subsequent calls faster
- Cost: ~$0.009/day at 1 call/day on A10G
```

-----

## Module 5 — voice.py

**What it does:** Loads your voice sample WAV, base64-encodes it, POSTs to the Modal endpoint with the hook text. Gets synthesized audio back in your cloned voice. Saves as WAV. No GPU or model needed locally.

```python
# voice.py — skeleton shape

def generate_voice(text: str, output_path: str) -> bool:
    # Encode voice_sample.wav as base64
    # POST to MODAL_TTS_ENDPOINT with text, ref_audio_b64, REF_TEXT
    # Decode response audio_b64, save to output_path
    # Return bool
    pass
```

### Gemini CLI Prompt — voice.py

```
Build a Python module called voice.py that calls a Modal HTTP endpoint to synthesize
speech using Qwen3-TTS voice cloning.

IMPORTS NEEDED: requests, base64, os

ENVIRONMENT VARIABLES USED:
- MODAL_TTS_ENDPOINT: full URL of the deployed Modal endpoint
- REF_TEXT: exact transcription of what was spoken in voice_sample.wav

FUNCTIONS TO BUILD:

1. load_voice_sample(sample_path: str = None) -> str
   - sample_path defaults to config.TTS["voice_sample_path"]
   - Opens WAV file as binary, returns base64-encoded string
   - Raises FileNotFoundError with helpful message if missing

2. call_modal_endpoint(text: str, ref_audio_b64: str, ref_text: str) -> bytes | None
   - POSTs to os.environ["MODAL_TTS_ENDPOINT"]
   - Payload: {"text": text, "ref_audio_b64": ref_audio_b64, "ref_text": ref_text}
   - timeout=90 (Modal cold start can take ~30s)
   - On success: decodes response["audio_b64"] and returns raw bytes
   - On "error" key in response: logs error and returns None
   - On request exception: logs and returns None

3. verify_audio(file_path: str) -> bool
   - Checks file exists and size > 1000 bytes
   - Returns bool

4. generate_voice(text: str, output_path: str) -> bool
   - Orchestrates: load_voice_sample → call_modal_endpoint → save bytes → verify
   - Prints each step
   - Returns bool success, never raises exceptions

COLD START NOTE: Add comment — Modal scales to zero after 60s idle.
First daily call takes 25-35s. timeout=90 handles this.

Include if __name__ == "__main__": synthesizing "Nobody saw this coming" for testing.
```

-----

## Module 6 — editor.py

**What it does:** The core ffmpeg compositor. Downloads the video segment, builds the Short in two sections — blurred hook with captions (1-3s), then the clear viral clip — and outputs a 9:16 vertical MP4.

### Gemini CLI Prompt — editor.py

```
Build a Python module called editor.py that uses ffmpeg via subprocess to compose a YouTube Short from a viral clip and a hook audio file.

TASK: Create a vertical 9:16 YouTube Short with two sections:
Section 1 (0s to hook_audio_duration): Blurred clip + hook voiceover audio + burned-in captions
Section 2 (hook_duration to end): Full clarity clip plays normally

IMPORTS NEEDED: subprocess, os, json, tempfile

FUNCTIONS TO BUILD:

1. download_clip(video_url: str, start_time: float, end_time: float, output_path: str) -> bool
   - Uses yt-dlp to download only the needed segment
   - Command: yt-dlp --download-sections "*{start_time}-{end_time}" 
     -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
     -o output_path video_url
   - Returns bool success

2. get_audio_duration(audio_path: str) -> float
   - Uses ffprobe to get duration of hook_audio.wav
   - Returns duration in seconds as float

3. crop_to_vertical(input_path: str, output_path: str) -> bool
   - Uses ffmpeg to crop 16:9 source to 9:16
   - Strategy: scale to height 1920, then crop width to 1080 from center
   - ffmpeg filter: scale=-2:1920,crop=1080:1920
   - Returns bool

4. compose_short(
     clip_path: str,
     hook_audio_path: str,
     hook_text: str,
     output_path: str
   ) -> bool
   
   Build with these ffmpeg steps in sequence using subprocess:

   STEP A — Crop source clip to vertical:
   ffmpeg -i clip_path → vertical_clip.mp4 (1080x1920)

   STEP B — Create hook section (blurred + audio):
   - Trim vertical_clip to hook_duration seconds
   - Apply boxblur filter: boxblur=20:5
   - Mix with hook_audio (replace original audio)
   - Output: hook_section.mp4

   STEP C — Create reveal section (clear clip):
   - Trim vertical_clip from hook_duration to end
   - Keep original audio
   - Output: reveal_section.mp4

   STEP D — Add captions to hook section:
   - Use ffmpeg drawtext filter to burn hook_text onto hook_section.mp4
   - Text settings: fontsize=60, fontcolor=white, 
     box=1, boxcolor=black@0.5, boxborderw=10
   - Position: x=(w-text_w)/2, y=h-200 (bottom center)
   - Font: use default ffmpeg font
   - Output: hook_captioned.mp4

   STEP E — Concatenate:
   - Use ffmpeg concat demuxer to join hook_captioned.mp4 + reveal_section.mp4
   - Output: output_path (final Short)

   Each step returns bool, abort sequence on any False.

5. build_short(video_url, start_time, end_time, hook_audio, hook_text, output_path) -> bool
   - Orchestrates download → compose_short
   - Uses tempfile.mkdtemp() for intermediate files
   - Cleans up temp dir on completion
   - Returns bool

ERROR HANDLING:
- Every subprocess.run call captures stderr
- On non-zero returncode: print the ffmpeg error and return False
- Never let exceptions propagate

Include if __name__ == "__main__": for manual testing with hardcoded test values.
```

-----

## Module 7 — uploader.py

**What it does:** Authenticates with YouTube Data API v3 via OAuth2, uploads the final MP4 as a YouTube Short with generated title, description with original creator credit, and tags.

### Gemini CLI Prompt — uploader.py

```
Build a Python module called uploader.py that uploads a video to YouTube using the YouTube Data API v3.

TASK: Upload a Short video file to YouTube with metadata and original creator credit.

IMPORTS NEEDED: 
google.oauth2.credentials, googleapiclient.discovery, googleapiclient.http,
google.auth.transport.requests, json, os

IMPORTANT: OAuth credentials are stored as JSON in environment variable YOUTUBE_OAUTH_JSON.
The JSON contains: client_id, client_secret, refresh_token, token_uri

FUNCTIONS TO BUILD:

1. get_youtube_client() -> youtube service object
   - Reads os.environ["YOUTUBE_OAUTH_JSON"]
   - Parses JSON to extract client_id, client_secret, refresh_token, token_uri
   - Creates google.oauth2.credentials.Credentials object
   - Refreshes token using google.auth.transport.requests.Request()
   - Returns googleapiclient.discovery.build("youtube", "v3", credentials=creds)

2. generate_metadata(video_title: str, original_channel: str, original_video_url: str) -> dict
   - Returns dict with:
     title: "🔥 {first 8 words of video_title} #GTA6 #Shorts"  (max 100 chars)
     description: 
       "The most rewatched moment from this GTA 6 video.\n\n"
       "Original video by {original_channel}: {original_video_url}\n\n"
       "#GTA6 #GTAVI #GrandTheftAuto #Gaming #Shorts"
     tags: config.UPLOAD["tags"]
     categoryId: config.UPLOAD["category_id"]
     privacyStatus: config.UPLOAD["privacy_status"]
     selfDeclaredMadeForKids: False

3. upload_video(file_path: str, metadata: dict) -> str | None
   - Gets YouTube client
   - Creates MediaFileUpload with resumable=True, chunksize=1024*1024*5
   - Calls youtube.videos().insert() with:
     part="snippet,status"
     body containing snippet (title, description, tags, categoryId) 
     and status (privacyStatus, selfDeclaredMadeForKids)
   - Executes with resumable upload loop (handle next_chunk)
   - Prints upload progress percentage at each chunk
   - Returns video_id string on success, None on failure

4. upload_short(file_path, video_title, original_channel, original_url) -> str | None
   - Orchestrates generate_metadata → upload_video
   - Prints final YouTube URL: https://youtube.com/shorts/{video_id}
   - Returns video_id

ERROR HANDLING:
- Wrap all API calls in try/except
- On HttpError: print status code and content, return None
- Resumable upload should retry up to 3 times on transient errors

Include if __name__ == "__main__": for testing with a sample video file.
```

-----

## pipeline.py — Main Orchestrator

### Gemini CLI Prompt — pipeline.py

```
Build a Python orchestrator script called pipeline.py that runs the full GTA6 Shorts
automation pipeline using a persistent queue system.

IMPORTS: 
pipeline.search, pipeline.heatmap, pipeline.transcript, pipeline.hook,
pipeline.voice, pipeline.editor, pipeline.uploader, pipeline.queue_manager, config
ALSO IMPORT: os, json, datetime

CONSTANTS AT TOP:
UPLOAD_LIMIT = config.UPLOAD["limit_per_run"]   # 1

MAIN FUNCTION: run_pipeline()

WORKFLOW:

1. QUEUE REFRESH — Search and refill queue
   a. Load current queue via queue_manager.load_queue()
   b. pending_count = len(queue["pending"])
   c. Always search Tier 1 (GTA6):
      new_videos = search.get_top_videos(api_key, tier="gta6")
      queue_manager.add_to_queue(queue, new_videos, source_type="gta6")
   d. If pending_count < config.QUEUE["min_size"]:
      Print "Queue low ({pending_count}), activating GTA5 fallback"
      fallback = search.get_top_videos(api_key, tier="gta5")
      queue_manager.add_to_queue(queue, fallback, source_type="gta5")
   e. queue_manager.save_queue(queue)
   f. Print queue status: "Queue: {len(pending)} pending, {len(processed)} processed"

2. PICK FROM QUEUE
   video = queue_manager.pop_top(queue)
   If None: print "Queue empty — no videos to process" and exit
   Print "=== Processing: {video['title']} ({video['source_type']}) ==="

3. PROCESS VIDEO
   a. HEATMAP
      start_time, end_time = heatmap.get_clip_timestamps(video['url'])

   b. TRANSCRIPT
      context = transcript.get_video_context(video['url'], start_time)

   c. HOOK
      hook_text = hook.get_hook_with_fallback(video['title'], context)
      Print "Hook: {hook_text}"

   d. VOICE
      hook_audio_path = f"/tmp/hook_{video['video_id']}.wav"
      success = voice.generate_voice(hook_text, hook_audio_path)
      If not success: queue_manager.requeue(queue, video); exit with error

   e. EDITOR
      output_path = f"/tmp/short_{video['video_id']}.mp4"
      success = editor.build_short(
          video_url=video['url'],
          start_time=start_time,
          end_time=end_time,
          hook_audio=hook_audio_path,
          hook_text=hook_text,
          output_path=output_path
      )
      If not success: queue_manager.requeue(queue, video); exit with error

   f. UPLOAD
      short_id = uploader.upload_short(
          file_path=output_path,
          video_title=video['title'],
          original_channel=video['channel_title'],
          original_url=video['url']
      )
      If not short_id: queue_manager.requeue(queue, video); exit with error

4. LOG RESULT
   log_entry = {
       "short_id": short_id,
       "uploaded_at": datetime.utcnow().isoformat() + "Z",
       "source_video_id": video['video_id'],
       "source_type": video['source_type'],
       "hook_text": hook_text,
       "hook_word_count": len(hook_text.split()),
       "peak_start": start_time,
       "peak_position_pct": round((start_time / video['duration_seconds']) * 100, 1),
       "clip_duration": round(end_time - start_time, 1),
       "snapshots": {
           "24h":  {"views": 0, "likes": 0, "comments": 0},
           "72h":  {"views": 0, "likes": 0, "comments": 0},
           "7d":   {"views": 0, "likes": 0, "comments": 0}
       },
       "notes": ""
   }
   Append to data/performance_log.json
   queue_manager.mark_processed(queue, video, short_id)
   queue_manager.save_queue(queue)

5. COMMIT DATA FILES BACK TO REPO
   Run subprocess git commands:
   git config user.name "pipeline-bot"
   git config user.email "bot@pipeline"
   git add data/queue.json data/performance_log.json
   git diff --staged --quiet || git commit -m "pipeline: uploaded {short_id} [{date}]"
   git push

6. CLEANUP
   Remove hook_audio_path and output_path

7. Print "✅ Done. Short: https://youtube.com/shorts/{short_id}"

Include if __name__ == "__main__": run_pipeline()
```

-----

## GitHub Actions — daily.yml

```yaml
name: GTA6 Shorts Daily Pipeline

on:
  schedule:
    - cron: '0 8 * * *'    # 8AM UTC daily
  workflow_dispatch:         # Manual trigger for testing

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    timeout-minutes: 30      # No local TTS — Modal handles it externally

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}   # Needed for git push back

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install system dependencies
        run: sudo apt-get install -y ffmpeg

      - name: Cache pip packages
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: pip-${{ hashFiles('requirements.txt') }}

      - name: Install Python dependencies
        run: pip install -r requirements.txt

      - name: Run pipeline
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          YOUTUBE_OAUTH_JSON: ${{ secrets.YOUTUBE_OAUTH_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          MODAL_TTS_ENDPOINT: ${{ secrets.MODAL_TTS_ENDPOINT }}
          REF_TEXT: ${{ secrets.REF_TEXT }}
        run: python pipeline.py
```

**No TTS model cache needed — Qwen3-TTS runs on Modal. Actions runtime ~15 min.**

-----

## GitHub Actions — fetch_stats.yml

```yaml
name: Fetch Short Performance Stats

on:
  schedule:
    - cron: '0 10 * * 1'    # Every Monday 10AM UTC
  workflow_dispatch:

jobs:
  fetch-stats:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - run: pip install google-api-python-client google-auth

      - name: Fetch and update stats
        env:
          YOUTUBE_OAUTH_JSON: ${{ secrets.YOUTUBE_OAUTH_JSON }}
        run: python fetch_stats.py

      - name: Commit updated logs
        run: |
          git config user.name "pipeline-bot"
          git config user.email "bot@pipeline"
          git add data/performance_log.json
          git diff --staged --quiet || git commit -m "stats: weekly update $(date +%Y-%m-%d)"
          git push
```

-----

## New Module — queue_manager.py

**What it does:** Manages `data/queue.json`. Handles adding new videos (with deduplication), popping the top-scored item for processing, requeueing on failure, and marking items as processed.

### Gemini CLI Prompt — queue_manager.py

```
Build a Python module called queue_manager.py that manages a persistent video queue
stored in data/queue.json.

QUEUE STRUCTURE:
{
  "pending": [list of video dicts, sorted by score descending],
  "processed": [list of processed dicts with short_id and uploaded_at]
}

VIDEO DICT SHAPE (pending):
{
  "video_id": str,
  "url": str,
  "title": str,
  "channel_title": str,
  "channel_url": str,
  "duration_seconds": int,
  "score": float,
  "source_type": str,          # "gta6" or "gta5"
  "queued_at": str             # ISO 8601 UTC
}

PROCESSED DICT SHAPE:
{
  "video_id": str,
  "short_id": str,
  "source_type": str,
  "uploaded_at": str
}

FUNCTIONS TO BUILD:

1. load_queue() -> dict
   - Reads data/queue.json
   - If file doesn't exist: returns {"pending": [], "processed": []}
   - Returns parsed dict

2. save_queue(queue: dict) -> None
   - Writes queue to data/queue.json with indent=2
   - Creates data/ directory if it doesn't exist

3. add_to_queue(queue: dict, videos: list[dict], source_type: str) -> int
   - Gets set of all existing video_ids (pending + processed)
   - For each video in videos:
     - Skip if video_id already in existing set (deduplication)
     - Add source_type field to video dict
     - Add queued_at as datetime.utcnow().isoformat() + "Z"
     - Append to queue["pending"]
   - Re-sorts queue["pending"] by score descending
   - Trims to config.QUEUE["max_pending"] items (drop lowest scores)
   - Returns count of newly added videos

4. pop_top(queue: dict) -> dict | None
   - Returns and removes the first item from queue["pending"]
   - Returns None if pending is empty
   - Does NOT save — caller saves after deciding outcome

5. requeue(queue: dict, video: dict) -> None
   - Puts video back at END of pending (lowest priority)
   - Prevents infinite retry loops on broken videos

6. mark_processed(queue: dict, video: dict, short_id: str) -> None
   - Appends to queue["processed"]:
     {video_id, short_id, source_type, uploaded_at: now}
   - Keeps processed list max 100 items (trim oldest)

7. get_status(queue: dict) -> str
   - Returns formatted string:
     "Queue: {pending} pending | {processed} processed total"
     "  GTA6 pending: {n} | GTA5 pending: {n}"

ERROR HANDLING:
- load_queue: catch JSON parse errors, return empty queue
- save_queue: catch write errors, print warning
- Never raise exceptions

Include if __name__ == "__main__": that prints current queue status.
```

-----

## New Module — fetch_stats.py

**What it does:** Reads `data/performance_log.json`, finds all Shorts with empty snapshot slots whose upload time has passed the snapshot interval, fetches current stats from YouTube API, fills in the data, saves back.

### Gemini CLI Prompt — fetch_stats.py

```
Build a Python script called fetch_stats.py that fetches YouTube performance stats
for uploaded Shorts and updates data/performance_log.json.

IMPORTS: googleapiclient.discovery, google.oauth2.credentials,
google.auth.transport.requests, json, os, datetime

SNAPSHOT INTERVALS from config.LOGS["snapshot_intervals_hours"]: [24, 72, 168]

FUNCTIONS TO BUILD:

1. get_youtube_client() -> service
   - Same OAuth pattern as uploader.py
   - Reads YOUTUBE_OAUTH_JSON from os.environ

2. fetch_video_stats(youtube, video_id: str) -> dict | None
   - Calls youtube.videos().list(part="statistics", id=video_id)
   - Returns dict: {views, likes, comments} as integers
   - Returns None if video not found or API error

3. load_log() -> dict
   - Reads data/performance_log.json
   - Returns {"shorts": []} if file missing

4. save_log(log: dict) -> None
   - Writes to data/performance_log.json with indent=2

5. needs_snapshot(entry: dict, interval_label: str, interval_hours: int) -> bool
   - interval_label is "24h", "72h", or "7d"
   - Returns True if:
     - entry["snapshots"][interval_label]["views"] == 0  (not yet fetched)
     - AND hours since entry["uploaded_at"] >= interval_hours

6. update_stats(youtube, log: dict) -> int
   - For each entry in log["shorts"]:
     For each interval in [(24, "24h"), (72, "72h"), (168, "7d")]:
       If needs_snapshot(entry, label, hours):
         stats = fetch_video_stats(youtube, entry["short_id"])
         If stats: entry["snapshots"][label] = stats
         Print "Updated {entry['short_id']} @ {label}: {stats}"
   - Returns count of updates made

7. run():
   - youtube = get_youtube_client()
   - log = load_log()
   - updates = update_stats(youtube, log)
   - save_log(log)
   - Print "Stats fetch complete. {updates} snapshots updated."

ERROR HANDLING:
- Skip entries with API errors, continue to next
- Never crash the whole run on one bad video_id

Include if __name__ == "__main__": run()
```

-----

## data/queue.json — Initial File

```json
{
  "pending": [],
  "processed": []
}
```

## data/performance_log.json — Initial File

```json
{
  "shorts": []
}
```

Create both files and commit before first pipeline run.

-----

## GitHub Secrets Required

|Secret Name         |What It Is                             |How to Get                                                     |
|--------------------|---------------------------------------|---------------------------------------------------------------|
|`YOUTUBE_API_KEY`   |YouTube Data API key                   |Google Cloud Console → APIs → YouTube Data API v3 → Credentials|
|`YOUTUBE_OAUTH_JSON`|OAuth2 credentials JSON                |Run get_oauth_token.py locally (see below)                     |
|`ANTHROPIC_API_KEY` |Claude API key                         |console.anthropic.com → API Keys                               |
|`MODAL_TTS_ENDPOINT`|Qwen3-TTS endpoint URL                 |Modal dashboard after `modal deploy modal_tts.py`              |
|`REF_TEXT`          |Exact transcription of voice_sample.wav|Type out word-for-word what you said in the recording          |

-----

## Getting Your YouTube OAuth Refresh Token

This is a one-time setup. Run this locally:

```python
# get_oauth_token.py — run this ONCE locally, not in Actions

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secrets.json",  # Download from Google Cloud Console
    scopes=SCOPES
)

creds = flow.run_local_server(port=8080)

import json
token_data = {
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "refresh_token": creds.refresh_token,
    "token_uri": creds.token_uri
}

print(json.dumps(token_data, indent=2))
# Copy this JSON into GitHub secret YOUTUBE_OAUTH_JSON
```

-----

## Build Order in Codespaces

```
Phase 1  — Run environment setup prompt, verify ffmpeg + yt-dlp work
Phase 2  — Build search.py with tiered support (gta6 + gta5), test finds real videos
Phase 3  — Build heatmap.py, test on a real video URL
Phase 4  — Build transcript.py, verify context extraction
Phase 5  — Build hook.py, verify Claude API returns valid hooks
Phase 6  — Deploy modal_tts.py (modal deploy), test endpoint with curl
Phase 7  — Build voice.py, confirm it calls Modal and saves WAV
Phase 8  — Build editor.py (most complex — test each ffmpeg step individually)
Phase 9  — Get OAuth token, build uploader.py, test with private video
Phase 10 — Build queue_manager.py, unit test all functions with mock data
Phase 11 — Build fetch_stats.py, test on a known Short video_id
Phase 12 — Initialize data/queue.json and data/performance_log.json, commit both
Phase 13 — Wire pipeline.py together with queue, run end-to-end locally
Phase 14 — Push to GitHub, add all secrets, trigger workflow_dispatch manually
Phase 15 — Verify daily.yml completes, confirm queue.json committed back by bot
Phase 16 — Enable daily cron + weekly fetch_stats.yml
Phase 17 — After 4 weeks: review performance_log.json for first improvement cycle
```

-----

## Gemini CLI — Environment Setup Prompt

Use this first in Codespaces:

```
I am building a YouTube Shorts automation pipeline in Python on GitHub Codespaces (Ubuntu).
Voice synthesis runs on Modal (external GPU endpoint) — no local TTS needed.

Set up my development environment:

1. Create requirements.txt:
   google-api-python-client==2.108.0
   google-auth==2.23.4
   google-auth-oauthlib==1.1.0
   yt-dlp
   ffmpeg-python==0.2.0
   anthropic
   requests==2.31.0
   python-dotenv==1.0.0
   isodate
   modal

2. Create .env template with placeholders:
   YOUTUBE_API_KEY=
   YOUTUBE_OAUTH_JSON=
   ANTHROPIC_API_KEY=
   MODAL_TTS_ENDPOINT=
   REF_TEXT=

3. Create setup.sh that:
   - Runs: sudo apt-get install -y ffmpeg
   - Runs: pip install -r requirements.txt
   - Verifies: ffmpeg -version
   - Verifies: yt-dlp --version
   - Prints "Environment ready"

4. Create folder structure:
   gta6-shorts-pipeline/
   ├── .github/workflows/
   │   ├── daily.yml
   │   └── fetch_stats.yml
   ├── pipeline/
   ├── data/
   │   ├── queue.json          (initialize as {"pending":[],"processed":[]})
   │   └── performance_log.json (initialize as {"shorts":[]})
   ├── assets/
   ├── modal_tts.py
   ├── pipeline.py
   ├── fetch_stats.py
   ├── config.py
   └── requirements.txt

Run setup.sh and confirm all tools are available.
```

-----

## Summary: Full Stack

|Component               |Tool                          |Cost                 |
|------------------------|------------------------------|---------------------|
|Video search + upload   |YouTube Data API v3           |Free (10k units/day) |
|Hook generation         |Claude API (claude-sonnet-4-6)|~$0.001/day          |
|Voice cloning           |Qwen3-TTS on Modal A10G       |~$0.009/day          |
|Heatmap + video download|yt-dlp                        |Free                 |
|Video composition       |ffmpeg                        |Free                 |
|Automation runner       |GitHub Actions                |Free (2000 min/month)|
|Queue + logging         |JSON files in repo            |Free                 |
|Stats fetching          |YouTube API (weekly)          |Free (within quota)  |

**Total daily cost: ~$0.01**
**Total monthly cost: ~$0.30 — entirely within Modal’s $30/month free credits**

-----

## Performance Log — What to Look For at Review

|Pattern                                       |Action                                                               |
|----------------------------------------------|---------------------------------------------------------------------|
|Low views across all Shorts                   |Improve hook quality or clip selection criteria                      |
|High views, low likes                         |Content is clickable but not satisfying — improve clip peak selection|
|GTA6 consistently outperforms GTA5            |Raise GTA5 `min_views` threshold or disable tier 2                   |
|Early-peak clips (< 30% into video) outperform|Bias heatmap window toward first half of video                       |
|Short hooks (< 6 words) beat longer ones      |Tighten Claude API word limit in hook.py prompt                      |
|Specific days of week spike                   |Adjust cron schedule to post day before peak                         |
|Queue frequently empty                        |Lower eligibility thresholds or add more search queries              |
