# GTA6 Shorts Pipeline — Project Handover & Documentation

This document serves as a comprehensive guide for any AI agent or developer taking over the **GTA6 Shorts Pipeline** project.

## Current Project Status
- **Core Engine**: Fully implemented in `pipeline/*.py`. All modules follow the "Universal Rules" (try/except, strict logging, pathlib).
*   **Infrastructure**: Qwen3-TTS voice cloning backend deployed on Modal.
*   **Automation**: GitHub Actions workflows created for daily processing and weekly performance tracking.
*   **Data**: Data structures for queueing and logging initialized in `data/`.
*   **Assets**: Voice sample recording converted and ready at `assets/voice_sample.wav`.

## Technical Architecture
The pipeline follows a **Search → Analyze → Generate → Compose → Upload** flow:
1.  **Search**: `pipeline/search.py` finds viral long-form videos based on tiered queries (GTA 6 primary, GTA 5 fallback).
2.  **Heatmap**: `pipeline/heatmap.py` uses `yt-dlp` to find the "Most Rewatched" segment.
3.  **Transcript**: `pipeline/transcript.py` pulls captions around the peak timestamp for AI context.
4.  **Hook**: `pipeline/hook.py` calls Claude (claude-3-5-sonnet) to write a curiosity-driven 10-word hook.
5.  **Voice**: `pipeline/voice.py` calls the Modal endpoint to synthesize the hook in the user's cloned voice.
6.  **Editor**: `pipeline/editor.py` (FFmpeg) crops to 9:16, blurs the hook intro, burns captions, and joins it with the reveal clip.
7.  **Uploader**: `pipeline/uploader.py` handles OAuth2 resumable upload to YouTube Shorts.

## Current Setup & Secrets
The following environment variables are required in `.env` (local) and GitHub Secrets (Actions):
- `YOUTUBE_API_KEY`: For searching and stats fetching.
- `YOUTUBE_OAUTH_JSON`: Full JSON string for OAuth2 (upload scope).
- `ANTHROPIC_API_KEY`: For hook generation.
- `MODAL_TTS_ENDPOINT`: `https://hakeemolanrewajuadebimpe--qwen3-tts-generate.modal.run`
- `REF_TEXT`: `Disparity between the number of foreign and local patent application`

## Directory Structure
```text
/workspaces/gra-6-clippper/
├── .github/workflows/   # daily.yml, fetch_stats.yml
├── assets/              # voice_sample.wav
├── data/                # queue.json, performance_log.json
├── pipeline/            # Core Python modules
├── modal_tts.py         # Modal deployment script
├── pipeline.py          # Main orchestrator
└── fetch_stats.py       # Weekly stats updater
```

## Immediate Next Steps
1.  **Verify Voice**: Run `python pipeline/voice.py` to ensure the Modal endpoint produces a valid WAV.
2.  **Configure OAuth**: The `YOUTUBE_OAUTH_JSON` needs to be populated using a refresh token flow.
3.  **End-to-End Test**: Run `python pipeline.py` with a single manual video entry in the queue to verify the FFmpeg and Upload stages.
