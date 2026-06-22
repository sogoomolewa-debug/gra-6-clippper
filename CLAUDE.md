---
title: CLAUDE.md
tags:
  - obsidian
---

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an automated YouTube Shorts pipeline that discovers viral GTA gameplay moments, generates hook narration with voice cloning, edits vertical shorts with captions, and uploads to YouTube. The pipeline runs daily via GitHub Actions.

**Channel**: BYNDUO  
**Stack**: Python, ffmpeg, yt-dlp, GitHub Actions, Modal (TTS), YouTube Data API v3, Groq (Llama 3.3), Gemini 2.5 Flash

## Core Pipeline Flow

```
[Daily GitHub Action 18:00 UTC]
         ↓
[1. Search & Queue Refill] → pipeline/search.py
    - Fetch videos from whitelisted channels (Hazardous, Red Arcade, etc.)
    - Apply priority-weighted scoring (High-Priority: 2.0x, Low-Priority: 0.5x)
    - Deduplicate & populate data/queue.json
         ↓
[2. Pop Top Video from Queue] → pipeline/queue_manager.py
         ↓
[3. Find Peak Moment] → pipeline/heatmap.py
    - Primary: yt-dlp heatmap data (viewer rewatch patterns)
    - Fallback 1: Comment timestamp clustering
    - Fallback 2: Audio energy peak detection
    - Fallback 3: 30% into video
         ↓
[4. Clip Analysis & Validation] → pipeline/clip_analyzer.py + clip_validator.py
    - Gemini 2.5 Flash vision: detect gameplay vs non-gameplay
    - Visual description of viral moment
    - Natural boundary detection (action start/end)
    - Punchiness filter + vagueness check
         ↓
[5. Hook Generation] → pipeline/hook.py
    - Groq Llama 3.3 70B: two-stage hook prompt
    - Rotating delivery styles (shocked, deadpan, hype, storyteller)
    - Delivery markup: pauses (...), emphasis (CAPS)
         ↓
[6. Voice Synthesis] → pipeline/voice.py + voice_humanizer.py
    - Modal endpoint: Qwen3-TTS voice cloning (A10G GPU)
    - Multi-speed stitching: slower suspense, faster reveal
    - Humanization: pitch jitter, room tone, reverb, compression
         ↓
[7. Video Editing] → pipeline/editor.py
    - Crop to 9:16 vertical (1080x1920)
    - Hook section: Gaussian blur + voiceover + Oswald Bold captions
    - Reveal section: clear gameplay
    - Credit watermark: "CLIP: @[CHANNEL_NAME]"
         ↓
[8. Upload to YouTube] → pipeline/uploader.py
    - OAuth2 resumable upload
    - Viral title generation + hashtags
    - Original creator credit in description
         ↓
[9. Logging & Git Commit] → pipeline.py
    - Update data/performance_log.json with snapshots
    - Commit queue + logs back to repo
    - Push to main
```

## Key Architecture Decisions

### Multi-Tier Sourcing System
- **Whitelist Mode** (current): Fetches from curated high-quality channels
- **Search Mode** (fallback): GTA6 tier → GTA5 tier when queue drops below min_size
- Priority multipliers favor specific creators (2.0x for Hazardous, Red Arcade; 0.5x for DarkViperAU)

### Visual AI Quality Gates
- **Gemini 2.5 Flash** analyzes video frames to reject non-gameplay content (commentary vlogs, news slides)
- **Punchiness filter**: Rejects slow/boring clips before editing
- **Vagueness validator**: Cross-checks visual description against comment context

### Voice Pipeline
- **Modal serverless TTS**: Cold start ~30s, then scales to zero after 60s idle
- **Chunk-based synthesis**: Splits hook into suspense/reveal chunks with different speeds
- **Humanization layer**: Adds pitch variance, room tone, reverb to avoid AI voice detection

### Video Editing Strategy
- **Natural boundaries**: Gemini suggests action start/end instead of fixed windows
- **Gaussian blur backdrop**: Smooth background for hook section (not boxblur)
- **Oswald Bold font**: High-contrast captions in safe zone (220px from bottom)
- **Credit watermark**: Top-left corner ensures attribution visibility

## Common Commands

### Run Pipeline Locally (Dry Run)
```bash
export DRY_RUN=true
python pipeline.py
# Output: scratch/latest_output.mp4
```

### Test Individual Modules
```bash
# Voice synthesis (requires Modal endpoint)
set -a; source .env; set +a
python3 -m pipeline.voice

# Whitelist sourcing
python3 -c "
import dotenv, os, sys
dotenv.load_dotenv()
sys.path.insert(0, '.')
from pipeline.search import get_top_videos
videos = get_top_videos(os.environ['YOUTUBE_API_KEY'], 'whitelist', limit=10)
for v in videos: print(f'{v[\"title\"]} | {v[\"channel_title\"]} | Score: {v[\"score\"]:.0f}')
"

# Hook generation
set -a; source .env; set +a
python3 -m pipeline.hook

# Clip analysis (Gemini vision)
python3 -c "
import dotenv, os, sys
dotenv.load_dotenv()
sys.path.insert(0, '.')
from pipeline.clip_analyzer import analyze_clip
res = analyze_clip('https://youtube.com/watch?v=VIDEO_ID', 173.0, 538.0)
print('Result:', res)
"
```

### End-to-End Test (Full Integration)
```bash
# Cached video at: scratch/cached_analyzer_segment.mp4
python test_e2e.py
# Verifies: dimensions, duration, frames, audio, captions, watermark
```

### Manual Upload Test
```bash
set -a; source .env; set +a
python3 -m pipeline.uploader
```

## Configuration (config.py)

### Critical Settings
- `DRY_RUN`: Set to `false` for live uploads (default: `true`)
- `SOURCING["mode"]`: `"whitelist"` or `"search"`
- `CLIP["max_duration_seconds"]`: Currently `12` (YouTube Shorts max: 60)
- `CLIP["min_duration_seconds"]`: `10`
- `QUEUE["min_size"]`: Activates GTA5 fallback when queue drops below `3`
- `QUEUE["max_pending"]`: Caps queue at `20` videos to prevent stale backlog

### Whitelist Channels
```python
SOURCING["whitelist_channels"] = [
    {"name": "Hazardous", "id": "UCgXfEXQBy0r4MywuzNf3iGQ", "priority": 1.0},
    {"name": "whatever57010", "id": "UCoKYYUrm0En0U2wAIkxSh5A", "priority": 1.0},
    {"name": "Prestige Clips", "id": "UCC-uu-OqgYEx52KYQ-nJLRw", "priority": 1.0},
    {"name": "GTA Series Videos", "id": "UCuWcjpKbIDAbZfHoru1toFg", "priority": 1.0},
    {"name": "GTAMen", "id": "UC4zMEl8Qh_nE5nDnp0cxRFQ", "priority": 1.0},
    {"name": "TGG", "id": "UC72PuhDwKtZ5MikpGNhPAtA", "priority": 1.0},
    {"name": "Red Arcade", "id": "UCHZZo1h1cI1vg4I9g2RqOUQ", "priority": 1.0},
    {"name": "MrBossFTW", "id": "UC0PMQXAwF6O6aeTpv962miA", "priority": 1.0},
    {"name": "Digital Car Addict", "id": "UCD9qy7cc3bb5rrMjJ9tRTTA", "priority": 1.0},
    {"name": "Call Me Kevin", "id": "UCdoPCztTOW7BJUPk2h5ttXA", "priority": 1.0},
]
```

### Hook Delivery Styles
Rotating styles to break AI pattern detection:
- **shocked**: Dramatic pause before reveal
- **deadpan**: Calm statement, absurdity speaks for itself
- **hype**: Pure energy, short punchy fragments
- **storyteller**: Mini-narrative tension, secret reveal

## Environment Variables

Required secrets (`.env` locally, GitHub Secrets in CI):
```bash
YOUTUBE_API_KEY=           # YouTube Data API v3 key
YOUTUBE_OAUTH_JSON=        # OAuth2 refresh token (JSON format)
GROQ_API_KEY=              # Groq API for hook generation
GEMINI_API_KEY=            # Gemini 2.5 Flash for video analysis
MODAL_TTS_ENDPOINT=        # Modal Qwen3-TTS endpoint URL
REF_TEXT=                  # Transcription of voice_sample.wav
YOUTUBE_COOKIES_PATH=      # Path to YouTube cookies (for yt-dlp age-gated videos)
DRY_RUN=                   # "true" or "false"
```

## Data Files (Committed to Repo)

### data/queue.json
```json
{
  "pending": [
    {
      "video_id": "...",
      "url": "https://youtube.com/watch?v=...",
      "title": "...",
      "channel_title": "...",
      "duration_seconds": 538,
      "score": 156789.5,
      "source_type": "gta6",
      "queued_at": "2026-06-18T18:00:00Z"
    }
  ],
  "processed": [
    {
      "video_id": "...",
      "short_id": "...",
      "source_type": "gta6",
      "uploaded_at": "2026-06-18T18:15:00Z"
    }
  ]
}
```

### data/performance_log.json
```json
{
  "shorts": [
    {
      "short_id": "FbUICzVkgtQ",
      "title": "...",
      "uploaded_at": "2026-06-18T18:15:00Z",
      "source_video_id": "...",
      "source_channel_title": "Hazardous",
      "source_type": "gta6",
      "hook_text": "Wait... they actually LANDED on the helicopter",
      "hook_word_count": 7,
      "peak_start": 173.5,
      "peak_position_pct": 32.3,
      "clip_duration": 13.2,
      "visual_description": "...",
      "peak_signal": "heatmap",
      "status": "uploaded",
      "snapshots": {
        "24h": {"views": 0, "likes": 0, "comments": 0},
        "72h": {"views": 0, "likes": 0, "comments": 0},
        "7d": {"views": 0, "likes": 0, "comments": 0}
      }
    }
  ]
}
```

## GitHub Actions Workflows

### .github/workflows/daily.yml
- **Schedule**: Daily at 18:00 UTC
- **Runtime**: ~15-20 minutes
- **Actions**: Search → Queue → Process → Upload → Commit
- **Secrets Required**: All env vars listed above

### .github/workflows/fetch_stats.yml
- **Schedule**: Weekly Monday 10:00 UTC
- **Runtime**: ~5 minutes
- **Actions**: Fetch YouTube stats for uploaded Shorts, update performance_log.json

## Module Details

### pipeline/search.py
- Fetches from channel uploads playlists (whitelist mode) or search API (search mode)
- Applies Category 20 (Gaming) filter + keyword blacklist
- Deduplicates by video_id across pending + processed
- Priority-weighted scoring: `(view_count * recency_weight * channel_priority) + (like_ratio * 50000)`

### pipeline/heatmap.py
- Parses yt-dlp `--dump-json` heatmap array
- Sliding window algorithm to find peak engagement window
- Fallbacks: comment timestamps → audio energy → 30% position

### pipeline/clip_analyzer.py
- Uploads video segment to Gemini File API
- Gemini 2.5 Flash structured output (Pydantic schema)
- Returns: `is_gameplay`, `is_punchy`, `description`, `natural_start`, `natural_end`

### pipeline/clip_validator.py
- Vagueness check: Rejects generic descriptions like "a player does something"
- Comment cross-check: If comments mention specific action but description is vague → reject

### pipeline/hook.py
- Two-stage Groq prompt:
  1. Generate raw hook ideas from visual description + comments
  2. Refine into delivery-optimized hook with pauses/emphasis
- Validates: max 12 words, no generic phrases, no redundant game mentions

### pipeline/voice.py
- Loads `assets/voice_sample.wav` (2-min voice clone reference)
- POSTs to Modal endpoint with text + ref_audio_b64 + ref_text
- Timeout: 90s (accounts for cold start)

### pipeline/voice_humanizer.py
- Splits hook into suspense/reveal chunks
- Applies speed modulation per chunk
- Adds pitch jitter, room tone, reverb, compression
- Stitches with configurable breath gaps

### pipeline/editor.py
- **crop_to_vertical**: Scale to 1920px height, crop width to 1080px
- **create_blur_backdrop**: Gaussian blur (sigma=20), no letterbox
- **build_hook_section**: Blur + voiceover + Oswald Bold captions (upper case)
- **build_reveal_section**: Clear gameplay from natural_start to natural_end
- **concatenate**: ffmpeg concat demuxer
- **add_watermark**: "CLIP: @[CHANNEL_NAME]" in top-left corner

### pipeline/uploader.py
- OAuth2 refresh token flow (stored in YOUTUBE_OAUTH_JSON)
- Resumable upload with 5MB chunks
- Generates viral title: hook-inspired + #GTA6 #Shorts hashtags
- Description includes original video credit

### pipeline/queue_manager.py
- `add_to_queue`: Deduplicates, sorts by score descending, trims to max_pending
- `pop_top`: Returns highest-scored video, removes from queue
- `requeue`: Appends to end (low priority) on upload failure
- `mark_processed`: Moves to processed list, keeps last 100 entries

## Testing Strategy

All modules have `if __name__ == "__main__":` blocks for isolated testing.

**Testing checklist (TESTING.md)**:
1. Voice synthesis (Modal endpoint)
2. Whitelist sourcing (YouTube API)
3. Transcript extraction (yt-dlp)
4. Clip analysis (Gemini vision)
5. Hook generation (Groq)
6. Video editing (ffmpeg)
7. Uploader (OAuth2)
8. E2E test (test_e2e.py)

## Failure Handling

### Requeueing Logic
If voice generation, editing, or upload fails → `queue_manager.requeue()` appends video to end of queue (low priority) to prevent blocking pipeline.

### API Fallbacks
- **Gemini quota exceeded**: Uses fallback boundaries (30% position, max duration)
- **Groq rate limit**: Returns random hardcoded hook from fallback list
- **Modal timeout**: Retries once, then skips video

### Git Commit Safety
Pipeline only commits if `git diff --staged --quiet` returns non-zero (changes exist). Prevents empty commits.

## Performance Optimization

### Cost Efficiency
- **Total daily cost**: ~$0.01 (entirely within Modal's $30/month free credits)
- **YouTube API quota**: ~200 units/day (well under 10,000 daily limit)
- **Groq API**: Free tier (30 req/min)
- **Gemini API**: Free tier (50 req/day)

### GitHub Actions Optimization
- **pip cache**: Cached by `requirements.txt` hash
- **yt-dlp**: No video download cache (short runtime, minimal benefit)
- **Runtime**: ~15-20 min per run

## Common Issues

### "Modal timeout after 90s"
- **Cause**: Cold start can take 25-35s on first daily call
- **Fix**: Modal automatically retries; no action needed

### "Gemini quota exceeded"
- **Cause**: >50 requests/day to Gemini 2.5 Flash
- **Fix**: Pipeline falls back to 30% position + max duration boundaries

### "YouTube upload failed: invalid credentials"
- **Cause**: OAuth2 refresh token expired (rare, ~6 months lifetime)
- **Fix**: Regenerate token using `get_token.py` script

### "ffmpeg concat demuxer failed"
- **Cause**: Hook section and reveal section have different codecs/framerates
- **Fix**: editor.py re-encodes both sections to consistent format before concat

### "Queue empty — nothing to process today"
- **Cause**: All whitelisted channels uploaded no eligible videos in last 7 days
- **Fix**: Adjust `SOURCING["max_age_hours"]` to 336 (14 days) or add more channels

## Asset Files

### assets/voice_sample.wav
- 2-minute voice clone reference recording
- Requirements: Clean audio, no background noise, consistent speaking style
- Used as reference for Qwen3-TTS voice cloning

### assets/Oswald-Bold.ttf
- Font for captions (burned into video)
- High contrast, legible at 9:16 resolution

## When Modifying the Pipeline

### Adding New Whitelist Channel
1. Get channel ID from YouTube channel URL
2. Add to `config.SOURCING["whitelist_channels"]` with priority
3. Test: `python3 -m pipeline.search` to verify videos are fetched

### Changing Clip Duration
1. Update `config.CLIP["max_duration_seconds"]` (max: 60)
2. Update `config.CLIP["min_duration_seconds"]` (min: 10)
3. Run `test_e2e.py` to verify editing pipeline handles new duration

### Modifying Hook Style
1. Add new style to `config.HOOK_STYLES` with instruction + example
2. Test: `python3 -m pipeline.hook` to generate samples

### Adjusting Voice Humanization
1. Tweak parameters in `config.TTS["humanize_*"]`
2. Test: `python3 -m pipeline.voice` to hear result

## Performance Review Cadence

After 4 weeks of automated uploads, review `data/performance_log.json`:
- Low views across all Shorts → improve hook quality or clip selection
- High views, low likes → clips are clickable but unsatisfying (improve peak detection)
- GTA6 consistently outperforms GTA5 → disable GTA5 fallback tier
- Early-peak clips (< 30%) outperform → bias heatmap toward first half
- Short hooks (< 6 words) beat longer → tighten word limit in hook.py
