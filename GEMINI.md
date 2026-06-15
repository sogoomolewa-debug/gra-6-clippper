# GTA6 Shorts Pipeline — Project Handover & Documentation

This document serves as a comprehensive guide for any AI agent or developer taking over the **GTA6 Shorts Pipeline** project.

## Current Project Status
- **Core Engine**: Fully implemented in `pipeline/*.py`. All modules follow the "Universal Rules" (try/except, strict logging, pathlib).
*   **Infrastructure**: Qwen3-TTS voice cloning backend deployed on Modal with speed control.
*   **Visual Analysis**: Gemini 2.5 Flash API for clip scene understanding (migrated from Modal Qwen2.5-VL).
*   **Hook Generation**: Two-stage LLM pipeline (Groq/Llama 3.3 70B) with delivery markup for natural TTS.
*   **Voice Synthesis**: Chunk-based TTS — hooks are split at delivery markers, each chunk synthesized at different speeds, then stitched with silence gaps for natural rhythm.
*   **Automation**: GitHub Actions workflows created for daily processing and weekly performance tracking.
*   **Data**: Data structures for queueing and logging initialized in `data/`.
*   **Assets**: Voice sample recording converted and ready at `assets/voice_sample.wav`.
*   **YouTube Bypass**: Cookie-based auth + Node.js runtime for yt-dlp signature challenges.
*   **Channel Filtering**: Rockstar Games channel blocked to avoid re-uploading official content.

## Technical Architecture
The pipeline follows a **Search → Analyze → Generate → Compose → Upload** flow:
1.  **Search**: `pipeline/search.py` finds viral long-form videos based on tiered queries (GTA 6 primary, GTA 5 fallback). Filters out Rockstar Games channel.
2.  **Heatmap**: `pipeline/heatmap.py` uses comments, audio energy, yt-dlp heatmap, and 30% fallback to find the viral moment.
3.  **Clip Analysis**: `pipeline/clip_analyzer.py` uploads the peak segment to Gemini 2.5 Flash via the File API for visual scene description and boundary detection.
4.  **Transcript**: `pipeline/transcript.py` pulls captions around the peak timestamp for AI context.
5.  **Hook (Two-Stage)**:
    - Stage 1: `pipeline/hook.py` calls Groq (Llama 3.3 70B) to write a conversational hook using a randomly rotated style (shocked/deadpan/hype/storyteller).
    - Stage 2: A second LLM call adds delivery markup — `...` pauses, CAPS emphasis, `—` tone shifts.
6.  **Voice (Chunk-Based)**: `pipeline/voice.py` splits the marked-up hook at `...` and `—` markers, synthesizes each chunk via Modal TTS at different speeds (0.85x suspense, 1.08x reveal), then stitches WAV segments with 280ms gaps and a 200ms breath pad.
7.  **Editor**: `pipeline/editor.py` (FFmpeg) crops to 9:16, blurs the hook intro, burns captions, and joins it with the reveal clip.
8.  **Uploader**: `pipeline/uploader.py` handles OAuth2 resumable upload to YouTube Shorts.

## Current Setup & Secrets
The following environment variables are required in `.env` (local) and GitHub Secrets (Actions):
- `YOUTUBE_API_KEY`: For searching and stats fetching.
- `YOUTUBE_OAUTH_JSON`: Full JSON string for OAuth2 (upload scope).
- `GROQ_API_KEY`: For hook generation via Llama 3.3 70B.
- `GEMINI_API_KEY`: For clip visual analysis via Gemini 2.5 Flash.
- `MODAL_TTS_ENDPOINT`: `https://richardmarenco55--qwen3-tts-generate.modal.run`
- `REF_TEXT`: `Disparity between the number of foreign and local patent application`
- `YOUTUBE_COOKIES_PATH`: Path to Netscape-format cookies file for yt-dlp bot bypass.

## Directory Structure
```text
/workspaces/gra-6-clippper/
├── .github/workflows/   # daily.yml, fetch_stats.yml
├── assets/              # voice_sample.wav
├── data/                # queue.json, performance_log.json
├── pipeline/            # Core Python modules
│   ├── search.py        # Video discovery + Rockstar filter
│   ├── heatmap.py       # Viral moment detection (4 signals)
│   ├── clip_analyzer.py # Gemini 2.5 Flash visual analysis
│   ├── transcript.py    # Caption extraction
│   ├── hook.py          # Two-stage hook generation + delivery markup
│   ├── voice.py         # Chunk-based TTS synthesis + WAV stitching
│   ├── editor.py        # FFmpeg video editing
│   ├── uploader.py      # YouTube Shorts upload
│   └── queue_manager.py # Queue management
├── modal_tts.py         # Modal TTS deployment (speed parameter)
├── config.py            # All pipeline constants + hook styles
├── pipeline.py          # Main orchestrator
└── fetch_stats.py       # Weekly stats updater
```

## Hook Delivery System
The hook system uses 4 rotating styles to avoid predictable AI patterns:
- **Shocked**: "Wait... they actually LANDED on the helicopter"
- **Deadpan**: "So this guy just... drove off a cliff and survived"
- **Hype**: "Bro WHAT... the car just flew across the map"
- **Storyteller**: "Nobody talks about this... but watch what happens NEXT"

## Voice Synthesis (Chunk-Based)
Based on research into natural AI voice generation, the TTS uses:
1. **Tone variation** — different speeds per chunk (suspense=0.85x, reveal=1.08x)
2. **Strategic pauses** — 280ms silence gaps between chunks
3. **Emphasis** — CAPITALIZED words in the hook text
4. **Breath pad** — 200ms silence before speech starts

## Immediate Next Steps
1.  **Configure OAuth**: The `YOUTUBE_OAUTH_JSON` needs to be populated using a refresh token flow.
2.  **End-to-End Test**: Run `python pipeline.py` with a single manual video entry in the queue to verify the FFmpeg and Upload stages.
3.  **Tune TTS Parameters**: Adjust `speed_suspense`, `speed_reveal`, `chunk_gap_ms` in `config.py` based on listening tests.
