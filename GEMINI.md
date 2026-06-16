# GTA6 Shorts Pipeline — Project Handover & Documentation

This document serves as a comprehensive guide for any AI agent or developer taking over the **GTA6 Shorts Pipeline** project.

## Current Project Status
*   **Core Engine**: Fully implemented in `pipeline/*.py`. All modules follow strict error boundaries (try/except), comprehensive logging, and standard pathlib path resolutions.
*   **Infrastructure**: Qwen3-TTS 1.7B voice cloning backend deployed on Modal with speed control and chunk-based synthesis.
*   **Visual Analysis & Gameplay Filter**: Single-call Gemini 2.5 Flash API for clip scene understanding, boundary detection, and gameplay validation using Pydantic structured schemas.
*   **Hook Generation**: Two-stage LLM pipeline (Groq/Llama 3.3 70B) with rotating delivery styles and markup for natural TTS phrasing.
*   **Voice Synthesis**: Tone variation and strategic pauses implemented by chunking hooks at delivery markers (`...` and `—`), synthesizing chunks at custom speeds, and stitching them with 280ms silences.
*   **Video Editor**: Crop to 9:16 vertical format, high-quality Gaussian background blur, word wrapping, and stylized safe-zone captions using thick outlines and 3D drop shadows (Oswald Bold font).
*   **Sourcing Filters**: Strict filtering layers applied to queries: restricting videos to YouTube Gaming Category (`20`), blocking channels from Rockstar Games, and filtering out news, essays, or podcasts using a keyword blacklist.
*   **Dry-Run Mode**: Pipeline executes fully but bypasses YouTube uploads, saving output locally to `scratch/latest_output.mp4` for quality control review.
*   **Automation**: GitHub Actions workflows created for daily processing (`daily.yml`) and weekly performance tracking (`fetch_stats.yml`).

---

## Technical Architecture

The pipeline follows a **Search → Analyze → Generate → Compose → Upload (or Dry Run)** flow:

```mermaid
graph TD
    A[Search: filter queries, cat 20, keywords, Rockstar block] --> B[Heatmap: comments, audio, yt-dlp]
    B --> C[Clip Analysis: download segment & call Gemini 2.5 Flash]
    C -->|is_gameplay: False| D[Skip video & Pop next]
    C -->|is_gameplay: True| E[Transcript & Hook Generation: Groq Llama 3.3]
    E --> F[TTS Voice: chunked synthesis & stitching]
    F --> G[Editor: FFmpeg Gaussian blur, wrap & burn captions]
    G --> H[Output check]
    H -->|DRY_RUN: True| I[Save locally to scratch/latest_output.mp4]
    H -->|DRY_RUN: False| J[Uploader: YouTube Shorts OAuth2 upload]
```

1.  **Search** (`pipeline/search.py`): Finds candidate gameplay videos matching refined queries. Filters out Rockstar Games channel, restricts candidate videos strictly to category `20` (Gaming), and discards videos with blacklist keywords (e.g. `rant`, `podcast`, `news`, `essay`) in the title/description.
2.  **Heatmap** (`pipeline/heatmap.py`): Detects viral spikes in the video timeline using 4 signals: comments volume, audio energy peaks, yt-dlp heatmap data, or 30% duration fallback.
3.  **Clip Analysis** (`pipeline/clip_analyzer.py`): Downloads a segment (peak -30s to +90s) and uploads it to Gemini 2.5 Flash. Executes a single structured API call with a Pydantic schema to:
    *   Validate if it shows actual direct gameplay (`is_gameplay` flag).
    *   Produce a one-sentence visual description.
    *   Identify natural start and end clip boundaries (clamped to target Short duration bounds).
4.  **Transcript** (`pipeline/transcript.py`): Pulls caption segments around the peak timestamp to provide verbal context for the hook generator.
5.  **Hook** (`pipeline/hook.py`): Calls Groq Llama 3.3 70B to write a hook rotating through 4 styles (Shocked, Deadpan, Hype, Storyteller) and applies delivery markup (silence gaps `...`, stress `CAPS`, tone shifts `—`).
6.  **Voice** (`pipeline/voice.py`): Splits the marked-up hook into chunks, synthesizes them at distinct speeds (suspense: 0.85x, reveal: 1.08x) using Modal Qwen3-TTS, and stitches them with 280ms silences and a 200ms breath pad.
7.  **Editor** (`pipeline/editor.py`): Trims and crops backdrop footage to 9:16. Applies smooth Gaussian blur (`gblur=sigma=20:steps=3`) to the intro hook backdrop, wraps caption text automatically (limit 18 chars/line), and burns capitalized text in Oswald Bold (`fontsize=90`) with thick black outlines and drop shadows.
8.  **Uploader / Dry Run** (`pipeline/uploader.py` & `pipeline.py`): Checks `config.DRY_RUN`. If enabled, saves the compiled video to `scratch/latest_output.mp4`. Otherwise, executes the OAuth2 resumable upload to YouTube Shorts.

---

## Directory Structure
```text
/workspaces/gra-6-clippper/
├── .github/workflows/   # daily.yml, fetch_stats.yml
├── assets/              # Oswald-Bold.ttf, Montserrat-Black.ttf, voice_sample.wav
├── data/                # queue.json, performance_log.json
├── pipeline/            # Core Python modules
│   ├── search.py        # Video discovery + category & blacklist filters
│   ├── heatmap.py       # Viral moment detection (4 signals)
│   ├── clip_analyzer.py # Gemini 2.5 Flash structured visual analysis
│   ├── transcript.py    # Caption extraction
│   ├── hook.py          # Two-stage hook generation + delivery markup
│   ├── voice.py         # Chunk-based TTS synthesis + WAV stitching
│   ├── editor.py        # FFmpeg video cropping, Gaussian blur, caption styling
│   ├── uploader.py      # YouTube Shorts OAuth2 upload
│   └── queue_manager.py # Queue management
├── modal_tts.py         # Modal TTS deployment (1.7B parameter Qwen3-TTS)
├── config.py            # All pipeline constants, queries, and DRY_RUN settings
├── pipeline.py          # Main orchestrator
└── fetch_stats.py       # Weekly stats updater
```

---

## Setup & Secrets
The following environment variables are required in `.env` (local) and GitHub Secrets (Actions):
*   `YOUTUBE_API_KEY`: Sourcing search and comments fetching.
*   `YOUTUBE_OAUTH_JSON`: Complete JSON credential string (OAuth2 refresh token).
*   `GROQ_API_KEY`: Groq Llama 3.3 hook generation.
*   `GEMINI_API_KEY`: Gemini 2.5 Flash API file upload and structured queries.
*   `MODAL_TTS_ENDPOINT`: Modal voice cloning endpoint.
*   `REF_TEXT`: Text prompt for voice sample reference alignment.
*   `YOUTUBE_COOKIES_PATH`: Netscape cookie file path to bypass downloader bot challenges.
