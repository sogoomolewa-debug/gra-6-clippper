# pipeline.py — Main orchestrator: daily entrypoint

import os
import json
from datetime import datetime
import pathlib
import subprocess
import dotenv

dotenv.load_dotenv()

from pipeline import search, heatmap, transcript, hook, voice, editor, uploader, queue_manager, clip_analyzer, clip_validator
import config


def load_performance_log() -> dict:
    """Load performance log from disk."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        if not path.exists():
            return {"shorts": []}
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[pipeline] error loading performance log: {e}")
        return {"shorts": []}


def save_performance_log(log: dict) -> None:
    """Save performance log to disk."""
    try:
        path = pathlib.Path(config.LOGS["performance_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[pipeline] performance log saved: {len(log.get('shorts', []))} entries")
    except Exception as e:
        print(f"[pipeline] error saving performance log: {e}")


def append_log_entry(log: dict, entry: dict) -> None:
    """Append an entry to the performance log."""
    try:
        log["shorts"].append(entry)
    except Exception as e:
        print(f"[pipeline] error appending log entry: {e}")


def log_skip(video: dict, status: str, notes: str = "") -> None:
    """Log a skipped/rejected video to performance_log.json."""
    try:
        log = load_performance_log()
        entry = {
            "short_id": status,
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
            "source_video_id": video["video_id"],
            "source_channel_title": video.get("channel_title", "unknown"),
            "source_type": video["source_type"],
            "status": status,
            "notes": notes,
            "snapshots": {
                "24h": {"views": 0, "likes": 0, "comments": 0},
                "72h": {"views": 0, "likes": 0, "comments": 0},
                "7d": {"views": 0, "likes": 0, "comments": 0}
            }
        }
        append_log_entry(log, entry)
        save_performance_log(log)
    except Exception as e:
        print(f"[pipeline] error logging skip: {e}")


def commit_data_files() -> None:
    """Commit updated data files to git."""
    try:
        # Check if we are in a git repo
        if not pathlib.Path(".git").exists():
             print("[pipeline] skip git commit: not a git repository")
             return

        commands = [
            ["git", "config", "user.name", "pipeline-bot"],
            ["git", "config", "user.email", "bot@pipeline"],
            ["git", "add", "data/queue.json", "data/performance_log.json", "data/channel_analytics.json"],
        ]
        for cmd in commands:
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except Exception:
                pass

        # Only commit if there are staged changes
        try:
            diff_result = subprocess.run(
                ["git", "diff", "--staged", "--quiet"],
                capture_output=True, text=True, timeout=30
            )
            if diff_result.returncode != 0:
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                subprocess.run(
                    ["git", "commit", "-m", f"pipeline: {date_str}"],
                    capture_output=True, text=True, timeout=30
                )
                subprocess.run(
                    ["git", "push"],
                    capture_output=True, text=True, timeout=60
                )
        except Exception:
            pass

        print("[pipeline] data files committed")
    except Exception as e:
        print(f"[pipeline] git commit error: {e}")


def run_pipeline() -> None:
    """Run the full daily pipeline."""
    try:
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            print("[pipeline] error: YOUTUBE_API_KEY not set")
            return

        print("=" * 60)
        print(f"[pipeline] starting run: {datetime.utcnow().isoformat()}Z")
        print("=" * 60)

        # STEP 1 — LOAD QUEUE
        queue = queue_manager.load_queue()
        print(queue_manager.get_status(queue))

        # STEP 2 — SEARCH AND REFILL QUEUE
        mode = getattr(config, "SOURCING", {}).get("mode", "search")
        if mode == "whitelist":
            print("[pipeline] sourcing from whitelist channels")
            whitelist_videos = search.get_top_videos(api_key, tier_name="whitelist", limit=5)
            added = queue_manager.add_to_queue(queue, whitelist_videos, source_type="gta")
            print(f"[pipeline] added {added} new whitelisted videos to queue")
        else:
            print("[pipeline] searching tier: gta6")
            gta6_videos = search.get_top_videos(api_key, tier_name="gta6", limit=5)
            added = queue_manager.add_to_queue(queue, gta6_videos, source_type="gta6")
            print(f"[pipeline] added {added} new gta6 videos to queue")

            # STEP 3 — FALLBACK TIER IF QUEUE LOW
            if len(queue["pending"]) < config.QUEUE["min_size"]:
                print(f"[pipeline] queue low ({len(queue['pending'])}), activating gta5 fallback")
                gta5_videos = search.get_top_videos(api_key, tier_name="gta5", limit=5)
                added5 = queue_manager.add_to_queue(queue, gta5_videos, source_type="gta5")
                print(f"[pipeline] added {added5} new gta5 videos to queue")

        queue_manager.save_queue(queue)

        # STEP 4 — POP TOP VIDEO
        video = queue_manager.pop_top(queue)
        if video is None:
            print("[pipeline] queue empty — nothing to process today")
            return

        print(f"\n[pipeline] processing: {video['title']}")
        print(f"[pipeline] source: {video['source_type']} | score: {video['score']:.0f}")

        # STEP 3 — FETCH COMMENTS
        print("[pipeline] fetching comments")
        comments = search.fetch_comments(video["video_id"], api_key)

        # STEP 4 — FIND PEAK TIMESTAMP FROM COMMENTS
        from pipeline.heatmap import (extract_and_score_timestamps,
                                      get_best_comment_timestamp, get_timestamp_comments,
                                      get_video_duration, get_heatmap_data, find_peak_window,
                                      get_fallback_timestamps, download_audio_only, audio_energy_peak)
        import pathlib, config as cfg

        duration = get_video_duration(video["url"])
        window = float(cfg.CLIP["max_duration_seconds"]) - 3.0
        timestamp_comments = []
        peak_sec = None
        peak_signal = "fallback"

        # 1. yt-dlp heatmap as the primary signal
        heatmap_list = get_heatmap_data(video["url"])
        if heatmap_list and len(heatmap_list) >= 10:
            start, _ = find_peak_window(heatmap_list, window)
            peak_sec = int(start + window / 2)
            peak_signal = "heatmap"
            print(f"[pipeline] peak from heatmap: {peak_sec}s")

        # 2. Comment signal fallback
        if not peak_sec and comments:
            clusters = extract_and_score_timestamps(comments, int(duration))
            peak_sec = get_best_comment_timestamp(clusters)
            if peak_sec:
                peak_signal = "comments"
                print(f"[pipeline] peak from comment timestamps: {peak_sec}s")

        # 3. Audio energy fallback
        if not peak_sec:
            print("[pipeline] trying audio energy")
            tmp_audio = f"/tmp/audio_{video['video_id']}.mp3"
            if download_audio_only(video["url"], tmp_audio):
                start, _ = audio_energy_peak(tmp_audio, window)
                peak_sec = int(start + window / 2)
                peak_signal = "audio_energy"
                pathlib.Path(tmp_audio).unlink(missing_ok=True)
                print(f"[pipeline] peak from audio energy: {peak_sec}s")

        # 4. 30% fallback
        if not peak_sec:
            peak_sec = int(duration * 0.3)
            peak_signal = "fallback_30"
            print(f"[pipeline] using 30% fallback: {peak_sec}s")

        # Decouple comments from primary signal detection - still extract them for downstream context
        if comments and peak_sec:
            timestamp_comments = get_timestamp_comments(comments, peak_sec)
            print(f"[pipeline] extracted {len(timestamp_comments)} timestamp comments around peak {peak_sec}s for context")

        # STEP 5 — CLIP ANALYZER (Qwen2.5-VL watches the segment)
        print("[pipeline] running visual clip analysis")
        analysis = clip_analyzer.analyze_clip(
            video_url=video["url"],
            peak_sec_global=float(peak_sec),
            video_duration=duration,
            timestamp_comments=timestamp_comments
        )

        # Check if the video contains actual gameplay
        if not analysis.get("is_gameplay", True):
            print(f"[pipeline] ❌ video {video['video_id']} is not gameplay (flagged by Gemini). Skipping and marking processed.")
            log_skip(video, "skipped_non_gameplay", "Flagged as non-gameplay by Gemini")
            queue_manager.mark_processed(queue, video, "skipped_non_gameplay")
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # Check if the video is punchy enough for a short clip
        if not analysis.get("is_punchy", True):
            reason = analysis.get("punchiness_reasoning", "No reason provided")
            print(f"[pipeline] ❌ video {video['video_id']} is not punchy (flagged by Gemini: {reason}). Skipping and marking processed.")
            log_skip(video, "skipped_not_punchy", f"Flagged as not punchy: {reason}")
            queue_manager.mark_processed(queue, video, "skipped_not_punchy")
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        global_start = analysis["global_start"]
        global_end = analysis["global_end"]
        visual_description = analysis["description"]
        peak_pct = round((peak_sec / max(duration, 1)) * 100, 1)
        print(f"[pipeline] final clip: {global_start:.1f}s → {global_end:.1f}s")

        # STEP 5b — VALIDATE DESCRIPTION (vagueness + comment cross-check)
        validation = clip_validator.validate_clip(
            description=visual_description,
            timestamp_comments=timestamp_comments
        )
        if not validation.get("valid", True):
            reason = validation.get("reason", "unknown")
            detail = validation.get("detail", "")
            print(f"[pipeline] ❌ clip validation failed ({reason}): {detail}. Skipping.")
            log_skip(video, f"skipped_{reason}", detail)
            queue_manager.mark_processed(queue, video, f"skipped_{reason}")
            queue_manager.save_queue(queue)
            commit_data_files()
            return
        if validation.get("skipped_comment_check"):
            print("[pipeline] ⚠ no timestamp comments — skipped comment cross-validation")

        # STEP 6 — TRANSCRIPT CONTEXT (around peak, may be empty)
        transcript_context = transcript.get_video_context(video["url"], float(peak_sec))

        # STEP 7 — HOOK (visual description is primary source)
        hook_text = hook.get_hook_with_fallback(
            video_title=video["title"],
            visual_description=visual_description,
            transcript_context=transcript_context,
            timestamp_comments=timestamp_comments
        )

        # STEP 8 — VOICE
        hook_audio = f"/tmp/hook_{video['video_id']}.wav"
        if not voice.generate_voice(hook_text, hook_audio):
            print("[pipeline] ❌ voice generation failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # STEP 9 — EDIT (now uses global_start and global_end from clip_analyzer)
        short_path = f"/tmp/short_{video['video_id']}.mp4"
        if not editor.build_short(
            video_url=video["url"],
            global_start=global_start,
            global_end=global_end,
            hook_audio=hook_audio,
            hook_text=hook_text,
            output_path=short_path,
            original_channel=video.get("channel_title", "")
        ):
            print("[pipeline] ❌ video editing failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # STEP 10 — UPLOAD
        dry_run = getattr(config, "DRY_RUN", True)
        if dry_run:
            print("[pipeline] [DRY RUN] Bypassing upload, saving output to scratch/latest_output.mp4")
            import shutil
            shutil.copy(short_path, "scratch/latest_output.mp4")
            short_id = f"dryrun_{video['video_id']}"
        else:
            short_id = uploader.upload_short(
                file_path=short_path,
                video_title=video["title"],
                original_channel=video["channel_title"],
                original_url=video["url"]
            )
        if not short_id:
            print("[pipeline] ❌ upload failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # STEP 11 — LOG
        log = load_performance_log()
        entry = {
            "short_id": short_id,
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
            "source_video_id": video["video_id"],
            "source_channel_title": video.get("channel_title", ""),
            "source_type": video["source_type"],
            "hook_text": hook_text,
            "hook_word_count": len(hook_text.split()),
            "peak_start": global_start,
            "peak_position_pct": peak_pct,
            "clip_duration": round(global_end - global_start, 1),
            "visual_description": visual_description,
            "natural_boundaries_used": True,
            "peak_signal": peak_signal,
            "peak_sec": peak_sec,
            "global_start": global_start,
            "global_end": global_end,
            "status": "uploaded",
            "snapshots": {
                "24h": {"views": 0, "likes": 0, "comments": 0},
                "72h": {"views": 0, "likes": 0, "comments": 0},
                "7d": {"views": 0, "likes": 0, "comments": 0}
            },
            "notes": ""
        }
        append_log_entry(log, entry)
        save_performance_log(log)

        # STEP 12 — MARK PROCESSED + SAVE QUEUE
        queue_manager.mark_processed(queue, video, short_id)
        queue_manager.save_queue(queue)

        # STEP 13 — CLEANUP
        for f in [hook_audio, short_path]:
            try:
                pathlib.Path(f).unlink()
            except Exception:
                pass

        # STEP 14 — COMMIT DATA FILES
        commit_data_files()

        print(f"\n[pipeline] ✅ complete: https://youtube.com/shorts/{short_id}")
        print("=" * 60)

    except Exception as e:
        print(f"[pipeline] fatal error: {e}")


if __name__ == "__main__":
    run_pipeline()
