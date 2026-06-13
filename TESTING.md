# GTA6 Shorts Pipeline — Manual Testing Protocol

This guide outlines how to manually verify every stage of the pipeline to ensure a 100% success rate before the first automated production run.

---

## ✅ PHASE 1: Verified Modules (Already Tested)

### 1. Voice Synthesis (TTS)
*   **Goal**: Verify the Modal endpoint correctly clones your voice from `assets/voice_sample.wav`.
*   **Command**:
    ```bash
    export MODAL_TTS_ENDPOINT="https://hakeemolanrewajuadebimpe--qwen3-tts-generate.modal.run"
    export REF_TEXT="Disparity between the number of foreign and local patent application"
    python3 -m pipeline.voice
    ```
*   **Expected Result**: A success message and a valid WAV file at `/tmp/test_hook.wav`.
*   **Current Status**: **PASS** (Verified with 1.7B model).

### 2. Search & Eligibility
*   **Goal**: Verify the YouTube API correctly filters for viral videos within the defined tiers.
*   **Command**:
    ```bash
    # Load .env variables first
    set -a; source .env; set +a
    python3 -m pipeline.search
    ```
*   **Expected Result**: A list of scored videos (Title, View Count, Score) printed to the console.
*   **Current Status**: **READY** (Keys populated in .env).

---

## 🛠️ PHASE 2: Pending Modules (Need Manual Verification)

### 3. Transcript & Context
*   **Goal**: Verify auto-caption download and context window extraction.
*   **Command**:
    ```bash
    # Note: Requires a video URL and a start timestamp
    python3 -m pipeline.transcript "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 45.0
    ```
*   **Expected Result**: A block of text representing the dialogue around the 45-second mark.
*   **Note**: Cloud IP blocking may cause this to return an empty string; the pipeline will continue using the video title for the AI hook if this happens.

### 5. Hook Generation (Claude)
*   **Goal**: Verify Claude-3.5-Sonnet writes a valid hook (< 10 words, no emojis).
*   **Command**:
    ```bash
    export ANTHROPIC_API_KEY="your_key_here"
    python3 -m pipeline.hook
    ```
*   **Expected Result**: A punchy 1-sentence hook printed.

### 6. Video Editor (FFmpeg)
*   **Goal**: Verify the complex 9:16 composition (Blur -> Caption -> Reveal).
*   **Command**:
    *Manual test requires a local MP4 and WAV file.*
*   **Expected Result**: A 9:16 vertical MP4 with a blurred intro section and clear reveal section.

### 7. Uploader (OAuth2)
*   **Goal**: Verify the resumable upload flow.
*   **Pre-requisite**: Generate a refresh token and populate `YOUTUBE_OAUTH_JSON`.
*   **Expected Result**: A "✅ successfully uploaded" message and a YouTube link.

---

## 🏁 PHASE 3: End-to-End (E2E) Test

Once all individual modules pass, run the full orchestrator:

1.  **Command**: `python3 pipeline.py`
2.  **Verification Steps**:
    *   Check `data/queue.json`: Is it populated with new search results?
    *   Check `data/performance_log.json`: Is the new Short logged?
    *   Check `git status`: Are the data files ready to be committed?

---

## 🛑 Troubleshooting Tips
- **FFmpeg Error**: Ensure `ffmpeg` is installed (`sudo apt install ffmpeg`).
- **Modal Timeout**: If the first voice call fails, it's likely a "Cold Start." Wait 30 seconds and retry.
- **Quota Error**: YouTube Search API has a low daily limit. If search fails, wait 24 hours or use a different API key.
d Start." Wait 30 seconds and retry.
- **Quota Error**: YouTube Search API has a low daily limit. If search fails, wait 24 hours or use a different API key.
