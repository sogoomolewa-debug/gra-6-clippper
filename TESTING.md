# GTA6 Shorts Pipeline — Manual Testing Protocol

This guide outlines how to manually verify every stage of the pipeline to ensure a 100% success rate.

---

## ✅ PHASE 1: Verified Modules

### 1. Voice Synthesis (TTS)
*   **Goal**: Verify the Modal endpoint correctly clones your voice from `assets/voice_sample.wav` and handles speed & chunk stitching.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.voice
    ```
*   **Expected Result**: A success message and a valid WAV file at `scratch/test_hook.wav`.
*   **Current Status**: **PASS** (1.7B parameter model, chunk-based synthesis, and multi-speed stitching verified).

### 2. Sourcing & Whitelist Sourcing
*   **Goal**: Verify that the YouTube API retrieves uploads playlists directly from whitelisted channels (Red Arcade, Prestige Clips, Hazardous, whatever57010, DarkViperAU, Call Me Kevin) and ranks them using priority-weighted scoring.
*   **Command**:
    ```bash
    python3 -c "
    import dotenv, os, sys
    dotenv.load_dotenv()
    sys.path.insert(0, '.')
    from pipeline.search import get_top_videos
    videos = get_top_videos(os.environ['YOUTUBE_API_KEY'], 'whitelist', limit=10)
    for v in videos:
        print(f'- {v[\"title\"]} | Channel: {v[\"channel_title\"]} | Score: {v[\"score\"]:.0f}')
    "
    ```
*   **Expected Result**: A list of eligible gaming videos from the whitelist ranked by priority score (High-Priority channels multiplied by 2.0x, Low-Priority by 0.5x).
*   **Current Status**: **PASS** (Successfully fetches, filters by Category 20 + keyword blacklist, applies priority multipliers, and ranks).

### 3. Transcript & Context
*   **Goal**: Verify auto-caption download and context window extraction.
*   **Command**:
    ```bash
    python3 -m pipeline.transcript "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 45.0
    ```
*   **Expected Result**: A block of text representing the dialogue around the 45-second mark.
*   **Current Status**: **PASS** (Successfully downloads and parses JSON3 transcripts).

### 4. Clip Analysis (Gemini 2.5 Flash Visual Gameplay Filter)
*   **Goal**: Verify that the single-call structured Gemini 2.5 Flash query correctly provides visual description, natural boundaries, and visual gameplay validation.
*   **Command**:
    ```bash
    python3 -c "
    import dotenv, os, sys
    dotenv.load_dotenv()
    sys.path.insert(0, '.')
    from pipeline.clip_analyzer import analyze_clip
    res = analyze_clip('https://youtube.com/watch?v=DsWKi3-sDDA', 173.0, 538.0)
    print('VERIFICATION RESULT:', res)
    "
    ```
*   **Expected Result**: Returns `is_gameplay` (boolean), `description`, `global_start`, and `global_end`. If the clip is a commentary vlog or news slides (non-gameplay), `is_gameplay` is set to `False`.
*   **Current Status**: **PASS** (Gemini structured Pydantic analysis verified and successfully flags non-gameplay rants).

### 5. Hook Generation (Groq Llama 3.3)
*   **Goal**: Verify Groq writes a valid hook (< 12 words) with two-stage delivery markup (pauses, emphasis).
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.hook
    ```
*   **Expected Result**: A punchy 1-sentence hook printed with delivery markup (e.g. `...` and capitalized words).
*   **Current Status**: **PASS** (Stage 1 and Stage 2 prompts successfully run on Groq Llama-3.3-70b).

### 6. Video Editor (Watermark & Captions)
*   **Goal**: Verify the vertical composition, smooth Gaussian blur backdrop, word wrapping, safe-zone Oswald Bold captions, and top-left credit watermark (`CLIP: @[CHANNEL_NAME]`).
*   **Command**:
    Runs via E2E compilation:
    ```bash
    python3 test_e2e.py
    ```
*   **Expected Result**: A 9:16 vertical MP4 built at `scratch/test_output_short.mp4` with Oswald Bold captions and credit watermark.
*   **Current Status**: **PASS** (FFmpeg drawing and rendering verified).

---

## 🛠️ PHASE 2: Uploader (OAuth2)

*   **Goal**: Verify the resumable upload flow.
*   **Pre-requisite**: Generate a refresh token and populate `YOUTUBE_OAUTH_JSON`.
*   **Command**:
    ```bash
    set -a; source .env; set +a
    python3 -m pipeline.uploader
    ```
*   **Expected Result**: A "✅ successfully uploaded" message and a YouTube link.
*   **Current Status**: **PASS** (Resumable upload verified with successful live upload of Short `FbUICzVkgtQ`).

---

## 🏁 PHASE 3: End-to-End (E2E) Test

Once all individual modules pass, run the full orchestrator in dry-run mode:

1.  **Command**: `set -a; source .env; set +a; python pipeline.py` (ensure `DRY_RUN = True` in `config.py` or `.env` is set).
2.  **Verification Steps**:
    *   Check `data/queue.json`: Is it refilled from the whitelist channels?
    *   Check `data/performance_log.json`: Is the new Short logged with a `dryrun_` ID?
    *   Check `scratch/latest_output.mp4`: Is the final compiled video output correct, and does it burn the creator's credit watermark?
    *   Check `git status`: Are the queue and logs committed to git?
3.  **Current Status**: **PASS** (Fully tested E2E cycle: fetched uploads playlist, applied priority scoring, downloaded segment, parsed hook/voice, and outputted the video locally).

---

## 🛑 Troubleshooting Tips
- **FFmpeg Error**: Ensure `ffmpeg` is installed (`sudo apt install ffmpeg`).
- **Modal Timeout**: If the first voice call fails, it's likely a "Cold Start." Wait 30 seconds and retry.
- **Quota Error (Gemini / YouTube)**: If API hits a 429 quota limit, the pipeline falls back gracefully to default boundaries and continues without crashing.
