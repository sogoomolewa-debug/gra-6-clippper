# pipeline.py — Main orchestrator: daily entrypoint

import os
import json
from datetime import datetime
import pathlib
import subprocess

from pipeline import search, heatmap, transcript, hook, voice, editor, uploader, queue_manager
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
            ["git", "add", "data/queue.json", "data/performance_log.json"],
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

        # STEP 5 — HEATMAP
        start_time, end_time = heatmap.get_clip_timestamps(video["url"])
        peak_pct = round((start_time / max(video["duration_seconds"], 1)) * 100, 1)
        print(f"[pipeline] peak: {start_time:.1f}s → {end_time:.1f}s ({peak_pct}% into video)")

        # STEP 6 — TRANSCRIPT
        context = transcript.get_video_context(video["url"], start_time)

        # STEP 7 — HOOK
        hook_text = hook.get_hook_with_fallback(video["title"], context)

        # STEP 8 — VOICE
        hook_audio = f"/tmp/hook_{video['video_id']}.wav"
        if not voice.generate_voice(hook_text, hook_audio):
            print("[pipeline] ❌ voice generation failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # STEP 9 — EDIT
        short_path = f"/tmp/short_{video['video_id']}.mp4"
        if not editor.build_short(
            video_url=video["url"],
            start_time=start_time,
            end_time=end_time,
            hook_audio=hook_audio,
            hook_text=hook_text,
            output_path=short_path
        ):
            print("[pipeline] ❌ video editing failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            commit_data_files()
            return

        # STEP 10 — UPLOAD
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
            "source_type": video["source_type"],
            "hook_text": hook_text,
            "hook_word_count": len(hook_text.split()),
            "peak_start": start_time,
            "peak_position_pct": peak_pct,
            "clip_duration": round(end_time - start_time, 1),
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
