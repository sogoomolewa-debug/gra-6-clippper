# GTA6 Shorts Pipeline — Manual Testing Protocol

This guide outlines how to manually verify every stage of the pipeline to ensure a 100% success rate before the first automated production run.

---

## ✅ PHASE 1: Verified Modules (Already Tested)

### 1. Voice Synthesis (TTS)
*   **Goal**: Verify the Modal endpoint correctly clones your voice from `assets/voice_sample.wav` and handles speed & chunk stitching.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.voice
    ```
*   **Expected Result**: A success message and a valid WAV file at `assets/test_hook.wav`.
*   **Current Status**: **PASS** (Chunk-based synthesis and multi-speed stitching verified).

### 2. Search & Eligibility
*   **Goal**: Verify the YouTube API correctly filters for viral videos within the defined tiers.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.search
    ```
*   **Expected Result**: A list of scored videos (Title, View Count, Score) printed to the console.
*   **Current Status**: **PASS** (Successfully retrieves and scores eligible videos, excluding Rockstar Games).

### 3. Transcript & Context
*   **Goal**: Verify auto-caption download and context window extraction.
*   **Command**:
    ```bash
    python3 -m pipeline.transcript "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 45.0
    ```
*   **Expected Result**: A block of text representing the dialogue around the 45-second mark.
*   **Current Status**: **PASS** (Successfully downloads and parses JSON3 transcripts).

### 4. Clip Analysis (Qwen2.5-VL)
*   **Goal**: Verify video chunk downloading and Qwen2.5-VL visual analysis via Modal.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.clip_analyzer "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 10.0
    ```
*   **Expected Result**: Visual description of the clip and boundaries returned as JSON.
*   **Current Status**: **PASS** (Qwen2.5-VL Modal backend responds successfully with visual descriptions and natural clip boundaries).

### 5. Hook Generation (Groq Llama 3.3)
*   **Goal**: Verify Groq writes a valid hook (< 12 words, no emojis) with two-stage delivery markup (pauses, emphasis).
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.hook
    ```
*   **Expected Result**: A punchy 1-sentence hook printed with delivery markup (e.g. `...` and capitalized words).
*   **Current Status**: **PASS** (Stage 1 and Stage 2 prompts successfully run on Groq Llama-3.3-70b).

### 6. Video Editor (FFmpeg)
*   **Goal**: Verify the complex 9:16 composition (Blur -> Caption -> Replace Audio -> Reveal -> Concatenate).
*   **Command**:
    Runs via scratch/test_editor.py using a test MP4 and WAV file.
*   **Expected Result**: A 9:16 vertical MP4 with a blurred captioned intro section and clear reveal section.
*   **Current Status**: **PASS** (Successfully created vertical cropped output at `scratch/test_editor_output.mp4`).

---

## 🛠️ PHASE 2: Pending Modules (Need Manual Verification)

### 7. Uploader (OAuth2)
*   **Goal**: Verify the resumable upload flow.
*   **Pre-requisite**: Generate a refresh token and populate `YOUTUBE_OAUTH_JSON`.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.uploader
    ```
*   **Expected Result**: A "✅ successfully uploaded" message and a YouTube link.
*   **Current Status**: **PENDING** (Bypassed during dry-runs to avoid accidental uploads).

---

## 🏁 PHASE 3: End-to-End (E2E) Test

Once all individual modules pass, run the full orchestrator:

1.  **Command**: `python3 pipeline.py` (or `python3 scratch/run_e2e_dryrun.py` for a dry run that mocks the upload).
2.  **Verification Steps**:
    *   Check `data/queue.json`: Is it populated with new search results?
    *   Check `data/performance_log.json`: Is the new Short logged?
    *   Check `scratch/final_test_output.mp4`: Is the final video output correct?
    *   Check `git status`: Are the data files ready to be committed?
3.  **Current Status**: **PASS** (E2E dry-run successfully ran, verified all AI models and compiled the final 9:16 vertical video at `scratch/final_test_output.mp4`).

---

## 🛑 Troubleshooting Tips
- **FFmpeg Error**: Ensure `ffmpeg` is installed (`sudo apt install ffmpeg`).
- **Modal Timeout**: If the first voice call fails, it's likely a "Cold Start." Wait 30 seconds and retry.
- **Quota Error**: YouTube Search API has a low daily limit. If search fails, wait 24 hours or use a different API key.

