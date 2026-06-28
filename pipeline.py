# pipeline.py — Main orchestrator: daily entrypoint

import os
import json
from datetime import datetime
import pathlib
import subprocess
import dotenv

dotenv.load_dotenv()

from pipeline import search, heatmap, transcript, hook, voice, editor, uploader, queue_manager, clip_analyzer, clip_validator, channel_discovery, rag
from pipeline.channel_tracker import load_analytics, save_analytics
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
            ["git", "add", "data/queue.json", "data/performance_log.json", "data/channel_analytics.json", "config.py"],
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

        # CONTENT MODE ROTATION — cycle through modes to A/B test
        if config.CONTENT_MODE_ROTATION:
            log = load_performance_log()
            uploaded_count = sum(
                1 for s in log.get("shorts", [])
                if s.get("status") == "uploaded" and not s.get("short_id", "").startswith("dryrun_")
            )
            rotation = config.MODE_ROTATION_ORDER
            batch = config.MODE_ROTATION_BATCH_SIZE
            mode_index = (uploaded_count // batch) % len(rotation)
            selected_mode = rotation[mode_index]
            config.CONTENT_MODE = selected_mode
            print(f"[pipeline] mode rotation: {selected_mode} (upload #{uploaded_count + 1}, batch {batch})")
        else:
            print(f"[pipeline] content mode: {config.CONTENT_MODE} (rotation disabled)")

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

        # STEP 3b — DISCOVERY FALLBACK (find new candidate channels)
        discovery_cfg = getattr(config, "DISCOVERY", {})
        trigger_size = discovery_cfg.get("trigger_queue_size", 2)
        if len(queue["pending"]) < trigger_size:
            print(f"[pipeline] queue still low ({len(queue['pending'])}), running channel discovery")
            whitelist_ids = [ch["id"] for ch in config.SOURCING.get("whitelist_channels", [])]
            channel_bl = getattr(config, "CHANNEL_BLACKLIST", [])
            discovery_videos = search.search_discovery_videos(api_key, whitelist_ids, channel_bl)
            added_d = queue_manager.add_to_queue(queue, discovery_videos, source_type="candidate")
            print(f"[pipeline] added {added_d} discovery candidate videos to queue")

        queue_manager.save_queue(queue)

        # STEP 4 — PROCESS VIDEOS (retry until one succeeds or queue is empty)
        MAX_RETRIES = 5  # cap retries to stay within GitHub Actions timeout
        produced = False

        for attempt in range(MAX_RETRIES):
            video = queue_manager.pop_top(queue)
            if video is None:
                print("[pipeline] queue empty — nothing to process")
                break

            print(f"\n[pipeline] attempt {attempt + 1}/{MAX_RETRIES}: {video['title']}")
            print(f"[pipeline] source: {video['source_type']} | score: {video['score']:.0f}")

            success = _process_single_video(queue, video, api_key)
            if success:
                produced = True
                break
            else:
                print(f"[pipeline] attempt {attempt + 1} failed, trying next video...")

        if not produced:
            print("[pipeline] ⚠ no video produced this run")
            commit_data_files()

        print("=" * 60)

    except Exception as e:
        print(f"[pipeline] fatal error: {e}")


def _process_single_video(queue: dict, video: dict, api_key: str) -> bool:
    """Process a single video through the multi-signal cascade. Returns True if a short was produced."""
    try:
        from pipeline.heatmap import (get_video_metadata, find_top_peaks,
                                      extract_and_score_timestamps,
                                      get_best_comment_timestamp, get_timestamp_comments,
                                      analyze_comments_for_moment, get_position_segments)
        import config as cfg

        # FETCH COMMENTS
        print("[pipeline] fetching comments")
        comments = search.fetch_comments(video["video_id"], api_key)

        # GET METADATA (single yt-dlp call for duration + heatmap)
        metadata = get_video_metadata(video["url"])
        duration = metadata["duration"]
        heatmap_data = metadata["heatmap"]
        window = float(cfg.CLIP["max_duration_seconds"]) - 3.0
        min_viral = int(cfg.CLIP.get("min_viral_score", 7))
        max_peaks = int(cfg.CLIP.get("max_peaks_to_try", 3))

        # ── SIGNAL CASCADE ──────────────────────────────────────────

        # Signal 1: Heatmap multi-peak
        if heatmap_data and len(heatmap_data) >= 10:
            peaks = find_top_peaks(heatmap_data, window, n=max_peaks)
            if peaks:
                print(f"[pipeline] trying {len(peaks)} heatmap peaks")
                result = _try_peaks(queue, video, peaks, window, duration, comments, min_viral)
                if result:
                    if result.get("_skip_video_download_failed"):
                        _track_candidate_failure(video)
                        log_skip(video, "skipped_download_failed", "Video download failed (likely expired cookies)")
                        queue_manager.mark_processed(queue, video, "skipped_download_failed")
                        queue_manager.save_queue(queue)
                        return False
                    return _finalize_video(queue, video, result, duration, api_key)
                # All peaks failed gates — fall through to track failure
                _track_candidate_failure(video)
                log_skip(video, "skipped_low_viral", "All heatmap peaks below viral threshold or failed gates")
                queue_manager.mark_processed(queue, video, "skipped_low_viral")
                queue_manager.save_queue(queue)
                return False

        # Signal 2: Comment timestamps (regex — fast, free)
        if comments:
            clusters = extract_and_score_timestamps(comments, int(duration))
            peak_sec = get_best_comment_timestamp(clusters)
            if peak_sec:
                print(f"[pipeline] peak from comment timestamps: {peak_sec}s")
                timestamp_comments = get_timestamp_comments(comments, peak_sec)
                result = _try_peak(video, peak_sec, duration, timestamp_comments, min_viral, "comments")
                if result:
                    if result.get("_skip_video_download_failed"):
                        _track_candidate_failure(video)
                        log_skip(video, "skipped_download_failed", "Video download failed (likely expired cookies)")
                        queue_manager.mark_processed(queue, video, "skipped_download_failed")
                        queue_manager.save_queue(queue)
                        return False
                    return _finalize_video(queue, video, result, duration, api_key)
                # Single comment peak failed
                print("[pipeline] comment timestamp peak failed, trying Groq analysis...")

        # Signal 3: Groq comment analysis (moment description + position)
        if comments:
            print("[pipeline] running Groq comment analysis")
            moment_info = analyze_comments_for_moment(comments)
            if moment_info.get("confidence", 0.0) >= 0.3 and moment_info.get("moment_description"):
                segments = get_position_segments(duration, moment_info["position_hint"])
                print(f"[pipeline] trying {len(segments)} position segments based on Groq analysis")
                result = _try_segments(video, segments, duration, comments, moment_info, min_viral)
                if result:
                    if result.get("_skip_video_download_failed"):
                        _track_candidate_failure(video)
                        log_skip(video, "skipped_download_failed", "Video download failed (likely expired cookies)")
                        queue_manager.mark_processed(queue, video, "skipped_download_failed")
                        queue_manager.save_queue(queue)
                        return False
                    return _finalize_video(queue, video, result, duration, api_key)
                # All segments failed
                _track_candidate_failure(video)
                log_skip(video, "skipped_low_viral", "All position segments below viral threshold")
                queue_manager.mark_processed(queue, video, "skipped_low_viral")
                queue_manager.save_queue(queue)
                return False
            else:
                print(f"[pipeline] Groq confidence too low ({moment_info.get('confidence', 0):.1f}), no actionable moment")

        # Signal 4: No viable signal — skip
        print(f"[pipeline] ⚠ no viable signal for {video['video_id']}, skipping")
        _track_candidate_failure(video)
        log_skip(video, "skipped_no_signal", "No heatmap, timestamps, or useful comments")
        queue_manager.mark_processed(queue, video, "skipped_no_signal")
        queue_manager.save_queue(queue)
        return False

    except Exception as e:
        print(f"[pipeline] error processing video {video.get('video_id', '?')}: {e}")
        queue_manager.mark_processed(queue, video, "error")
        queue_manager.save_queue(queue)
        return False


def _track_candidate_failure(video: dict) -> None:
    """Track a candidate channel failure if applicable."""
    if video.get("source_type") == "candidate":
        analytics = load_analytics()
        channel_discovery.process_candidate_result(
            analytics, video.get("channel_id", ""), video.get("channel_title", ""), False
        )
        save_analytics(analytics)


def _try_peak(
    video: dict,
    peak_sec: int,
    duration: float,
    timestamp_comments: list,
    min_viral: int,
    signal_name: str
) -> dict | None:
    """Try a single peak timestamp through Gemini analysis + gates.

    Returns the full analysis result dict if it passes all gates and viral threshold,
    or None if it fails.
    """
    print(f"[pipeline] analyzing peak at {peak_sec}s (signal: {signal_name})")

    analysis = clip_analyzer.analyze_clip(
        video_url=video["url"],
        peak_sec_global=float(peak_sec),
        video_duration=duration,
        timestamp_comments=timestamp_comments
    )

    # Gate: is_gameplay
    if not analysis.get("is_gameplay", True):
        print(f"[pipeline]   ❌ not gameplay")
        return None

    # Gate: is_punchy
    if not analysis.get("is_punchy", True):
        print(f"[pipeline]   ❌ not punchy: {analysis.get('punchiness_reasoning', '')}")
        return None

    # Check if the download itself failed (e.g. 403 cookie expiry)
    if analysis.get("download_failed"):
        print(f"[pipeline]   ❌ download failed (likely expired cookies) — skipping entire video")
        return {"_skip_video_download_failed": True}

    # Gate: viral score
    viral_score = analysis.get("viral_score", 5)
    if viral_score < min_viral:
        print(f"[pipeline]   ❌ viral_score {viral_score} < {min_viral}")
        return None

    # Gate: clip validation
    validation = clip_validator.validate_clip(
        description=analysis.get("description", ""),
        timestamp_comments=timestamp_comments
    )
    if not validation.get("valid", True):
        reason = validation.get("reason", "unknown")
        detail = validation.get("detail", "")
        print(f"[pipeline]   ❌ validation failed ({reason}): {detail}")
        return None

    if validation.get("skipped_comment_check"):
        print("[pipeline]   ⚠ no timestamp comments — skipped comment cross-validation")

    # Gate: RAG viral potential filter
    print("[pipeline]   scoring viral potential via RAG…")
    viral_check = rag.score_viral_potential(
        visual_description=analysis.get("description", ""),
        timestamp_comments=timestamp_comments,
        moment_type=analysis.get("moment_type", "")
    )
    viral_verdict = viral_check["verdict"]
    viral_score_rag = viral_check["score"]

    if viral_verdict == "reject":
        print(f"[pipeline]   ❌ rejected by viral filter — {viral_check['reason']}")
        if viral_check.get("rejection_detail"):
            print(f"[pipeline]   detail: {viral_check['rejection_detail']}")
        return None

    if viral_verdict == "uncertain":
        print(f"[pipeline]   ⚠️ uncertain viral potential — proceeding with caution")

    print(f"[pipeline]   ✅ passed all gates (viral_score={viral_score}, rag_viral={viral_score_rag}/10)")

    # Attach metadata for downstream use
    analysis["_peak_sec"] = peak_sec
    analysis["_peak_signal"] = signal_name
    analysis["_timestamp_comments"] = timestamp_comments
    analysis["_viral_check"] = viral_check
    return analysis


def _try_peaks(
    queue: dict,
    video: dict,
    peaks: list,
    window: float,
    duration: float,
    comments: list,
    min_viral: int
) -> dict | None:
    """Try multiple heatmap peaks, return the first that passes all gates."""
    from pipeline.heatmap import get_timestamp_comments

    for i, (peak_start, peak_end) in enumerate(peaks):
        peak_sec = int(peak_start + window / 2)
        print(f"[pipeline] heatmap peak {i+1}/{len(peaks)}: {peak_start:.1f}s → {peak_end:.1f}s (center: {peak_sec}s)")

        timestamp_comments = []
        if comments:
            timestamp_comments = get_timestamp_comments(comments, peak_sec)

        result = _try_peak(video, peak_sec, duration, timestamp_comments, min_viral, f"heatmap_peak_{i+1}")
        if result:
            return result

    return None


def _try_segments(
    video: dict,
    segments: list,
    duration: float,
    comments: list,
    moment_info: dict,
    min_viral: int
) -> dict | None:
    """Try position-based segments from Groq analysis, return best passing result."""
    from pipeline.heatmap import get_timestamp_comments

    for i, (seg_start, seg_end) in enumerate(segments):
        peak_sec = int((seg_start + seg_end) / 2)
        print(f"[pipeline] position segment {i+1}/{len(segments)}: {seg_start:.1f}s → {seg_end:.1f}s (center: {peak_sec}s)")
        print(f"[pipeline]   looking for: \"{moment_info.get('moment_description', '')}\"")

        timestamp_comments = []
        if comments:
            timestamp_comments = get_timestamp_comments(comments, peak_sec)

        result = _try_peak(video, peak_sec, duration, timestamp_comments, min_viral, f"groq_segment_{i+1}")
        if result:
            return result

    return None


def _finalize_video(queue: dict, video: dict, analysis: dict, duration: float, api_key: str) -> bool:
    """Take a validated analysis result and run the remaining pipeline steps.

    Handles: candidate tracking, transcript, hook, voice, edit, upload, logging.
    Returns True on success.
    """
    try:
        global_start = analysis["global_start"]
        global_end = analysis["global_end"]
        visual_description = analysis["description"]
        viral_score = analysis.get("viral_score", 5)
        peak_sec = analysis.get("_peak_sec", int(global_start))
        peak_signal = analysis.get("_peak_signal", "unknown")
        timestamp_comments = analysis.get("_timestamp_comments", [])
        peak_pct = round((peak_sec / max(duration, 1)) * 100, 1)

        print(f"[pipeline] final clip: {global_start:.1f}s → {global_end:.1f}s (viral_score={viral_score})")

        # Track candidate channel success
        if video.get("source_type") == "candidate":
            analytics = load_analytics()
            action = channel_discovery.process_candidate_result(
                analytics,
                channel_id=video.get("channel_id", ""),
                channel_title=video.get("channel_title", ""),
                passed_all_gates=True
            )
            save_analytics(analytics)
            print(f"[pipeline] candidate channel '{video.get('channel_title')}' result: {action}")

        # TRANSCRIPT CONTEXT
        transcript_context = transcript.get_video_context(video["url"], float(peak_sec))

        # HOOK
        hook_text, hook_style = hook.get_hook_with_fallback(
            video_title=video["title"],
            visual_description=visual_description,
            transcript_context=transcript_context,
            timestamp_comments=timestamp_comments
        )

        # VIRAL TITLE
        raw_title = hook.generate_viral_title(
            video_title=video["title"],
            visual_description=visual_description,
            hook_text=hook_text
        )
        source_type = video.get("source_type", "general")
        title = f"{raw_title} {config.get_hashtags(source_type)}"

        if len(title) > 100:
            title = title[:97] + "..."
        print(f"[pipeline] final viral title: {title}")

        # VOICE
        hook_audio = f"/tmp/hook_{video['video_id']}.wav"
        if not voice.generate_voice(hook_text, hook_audio):
            print("[pipeline] ❌ voice generation failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            return False

        # EDIT
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
            return False

        # UPLOAD
        dry_run = getattr(config, "DRY_RUN", True)
        if dry_run:
            print("[pipeline] [DRY RUN] Bypassing upload, saving output to scratch/latest_output.mp4")
            import shutil
            shutil.copy(short_path, "scratch/latest_output.mp4")
            short_id = f"dryrun_{video['video_id']}"
        else:
            short_id = uploader.upload_short(
                file_path=short_path,
                title=title,
                visual_description=visual_description,
                source_type=video["source_type"],
                original_channel=video["channel_title"],
                original_url=video["url"]
            )
        if not short_id:
            print("[pipeline] ❌ upload failed — requeueing")
            queue_manager.requeue(queue, video)
            queue_manager.save_queue(queue)
            return False

        # LOG
        log = load_performance_log()

        try:
            published_at = video.get("published_at", "")
            published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_hours = (datetime.utcnow().replace(tzinfo=published_dt.tzinfo) - published_dt).total_seconds() / 3600
        except Exception:
            age_hours = 0

        entry = {
            "short_id": short_id,
            "short_url": f"https://youtube.com/shorts/{short_id}",
            "title": title,
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
            "source_video_id": video["video_id"],
            "source_url": video["url"],
            "source_channel_title": video.get("channel_title", ""),
            "source_type": video["source_type"],
            "source_video_views": video.get("view_count", 0),
            "source_video_age_hours": round(age_hours, 1),
            "hook_text": hook_text,
            "hook_style": hook_style,
            "hook_delivery": getattr(config, "CONTENT_MODE", "tts_narrated"),
            "hook_word_count": len(hook_text.split()),
            "peak_start": global_start,
            "peak_position_pct": peak_pct,
            "clip_duration": round(global_end - global_start, 1),
            "visual_description": visual_description,
            "is_punchy": analysis.get("is_punchy", True),
            "punchiness_reasoning": analysis.get("punchiness_reasoning", ""),
            "viral_score": viral_score,
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
            "notes": "",
            "repost_count": 0,
            "repost_video_path": "",
            "viral_potential_score": analysis.get("_viral_check", {}).get("score", 0),
            "viral_potential_verdict": analysis.get("_viral_check", {}).get("verdict", "unknown"),
            "viral_matched_triggers": analysis.get("_viral_check", {}).get("matched_triggers", []),
            "moment_type": analysis.get("moment_type", "")
        }
        append_log_entry(log, entry)
        save_performance_log(log)

        # MARK PROCESSED + SAVE QUEUE
        queue_manager.mark_processed(queue, video, short_id)
        queue_manager.save_queue(queue)

        # CLEANUP — preserve rendered video for potential repost, delete temp audio
        try:
            pathlib.Path(hook_audio).unlink()
        except Exception:
            pass

        # Move rendered video to scratch/ for repost monitor
        if not dry_run:
            preserved_path = f"scratch/repost_{video['video_id']}.mp4"
            try:
                import shutil
                pathlib.Path("scratch").mkdir(parents=True, exist_ok=True)
                shutil.move(short_path, preserved_path)
                # Update the log entry with the preserved path
                entry["repost_video_path"] = preserved_path
                save_performance_log(log)
                print(f"[pipeline] preserved video for repost: {preserved_path}")
            except Exception as e:
                print(f"[pipeline] warning: could not preserve video: {e}")
        else:
            try:
                pathlib.Path(short_path).unlink()
            except Exception:
                pass

        # COMMIT DATA FILES
        commit_data_files()

        print(f"\n[pipeline] ✅ complete: https://youtube.com/shorts/{short_id}")
        return True

    except Exception as e:
        print(f"[pipeline] error finalizing video {video.get('video_id', '?')}: {e}")
        queue_manager.requeue(queue, video)
        queue_manager.save_queue(queue)
        return False


if __name__ == "__main__":
    run_pipeline()

