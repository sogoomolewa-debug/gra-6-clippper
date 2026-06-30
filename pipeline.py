# pipeline.py — Main orchestrator: daily entrypoint

import os
import json
from datetime import datetime
import pathlib
import subprocess
import dotenv

dotenv.load_dotenv()

from pipeline import search, heatmap, transcript, hook, voice, editor, uploader, queue_manager, clip_analyzer, channel_discovery
from pipeline import rag
from pipeline import clip_validator
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

        # Locked format — never rotate
        content_profile = config.get_content_profile()
        print(f"[pipeline] content mode: {config.CONTENT_MODE} (locked)")

        # STEP 1 — LOAD QUEUE
        queue = queue_manager.load_queue()
        print(queue_manager.get_status(queue))

        # STEP 2 — SOURCING CASCADE: whitelist → gta6 search → gta5 search → discovery
        # Each tier only activates if the queue is still low after the previous tier.
        min_queue = config.QUEUE["min_size"]

        # Tier 1: Whitelist channels (always tried first — trusted quality)
        print("[pipeline] sourcing tier 1: whitelist channels")
        whitelist_videos = search.get_top_videos(api_key, tier_name="whitelist", limit=15)
        added = queue_manager.add_to_queue(queue, whitelist_videos, source_type="gta")
        print(f"[pipeline] added {added} new whitelisted videos to queue")

        # Tier 2: GTA6 search (if whitelist didn't fill the queue)
        if len(queue["pending"]) < min_queue:
            print(f"[pipeline] queue low ({len(queue['pending'])}), sourcing tier 2: gta6 search")
            gta6_videos = search.get_top_videos(api_key, tier_name="gta6", limit=15)
            added6 = queue_manager.add_to_queue(queue, gta6_videos, source_type="gta6")
            print(f"[pipeline] added {added6} new gta6 videos to queue")

        # Tier 3: GTA5 search (always run — GTA5 has more actual gameplay with heatmaps)
        print(f"[pipeline] sourcing tier 3: gta5 search")
        gta5_videos = search.get_top_videos(api_key, tier_name="gta5", limit=15)
        added5 = queue_manager.add_to_queue(queue, gta5_videos, source_type="gta5")
        print(f"[pipeline] added {added5} new gta5 videos to queue")

        # Tier 4: Discovery (find new candidate channels — last resort)
        discovery_cfg = getattr(config, "DISCOVERY", {})
        trigger_size = discovery_cfg.get("trigger_queue_size", 2)
        if len(queue["pending"]) < trigger_size:
            print(f"[pipeline] queue still low ({len(queue['pending'])}), sourcing tier 4: discovery")
            whitelist_ids = [ch["id"] for ch in config.SOURCING.get("whitelist_channels", [])]
            channel_bl = getattr(config, "CHANNEL_BLACKLIST", [])
            discovery_videos = search.search_discovery_videos(api_key, whitelist_ids, channel_bl)
            added_d = queue_manager.add_to_queue(queue, discovery_videos, source_type="candidate")
            print(f"[pipeline] added {added_d} discovery candidate videos to queue")

        queue_manager.save_queue(queue)

        # STEP 4 — PROCESS VIDEOS (retry until one succeeds or queue is empty)
        MAX_RETRIES = 10  # cap retries to stay within GitHub Actions timeout
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
    """Process a single video through the heatmap-only signal cascade. Returns True if a short was produced."""
    try:
        from pipeline.heatmap import get_video_metadata, find_top_peaks
        import config as cfg

        # GET METADATA (single yt-dlp call for duration + heatmap)
        print("[pipeline] fetching heatmap data")
        metadata = get_video_metadata(video["url"])
        duration = metadata["duration"]
        heatmap_data = metadata["heatmap"]
        
        if not heatmap_data or len(heatmap_data) < 10:
            print(f"[pipeline] no heatmap data for {video['video_id']} — skipping")
            log_skip(video, "skipped_no_heatmap", "video has no YouTube heatmap data (insufficient views or too new)")
            queue_manager.mark_processed(queue, video, "skipped_no_heatmap")
            queue_manager.save_queue(queue)
            commit_data_files()
            return False

        window = float(cfg.CLIP["max_duration_seconds"]) - 3.0
        peaks = find_top_peaks(heatmap_data, window_duration=window, n=3)
        print(f"[pipeline] found {len(peaks)} heatmap peaks")

        if not peaks:
            print(f"[pipeline] heatmap produced no valid peaks — skipping")
            log_skip(video, "skipped_no_peaks", "heatmap yielded no valid peak windows")
            queue_manager.mark_processed(queue, video, "skipped_no_peaks")
            queue_manager.save_queue(queue)
            commit_data_files()
            return False

        # Try each peak through Gemini gates
        peak_passed = False
        peak_sec = None
        peak_signal = None
        analysis = None
        min_viral = int(cfg.CLIP.get("min_viral_score", 7))

        for peak_idx, (peak_start, peak_end, peak_intensity) in enumerate(peaks):
            peak_sec_candidate = int((peak_start + peak_end) / 2)
            signal_name = f"heatmap_peak_{peak_idx + 1}"
            print(f"[pipeline] analyzing peak {peak_idx+1}/{len(peaks)}: "
                  f"{peak_start:.1f}s → {peak_end:.1f}s (center: {peak_sec_candidate}s, intensity: {peak_intensity:.2f})")

            analysis_candidate = clip_analyzer.analyze_clip(
                video_url=video["url"],
                peak_sec_global=float(peak_sec_candidate),
                video_duration=duration,
                timestamp_comments=[]   # No comments passed — heatmap only
            )

            # Check if the download itself failed (e.g. 403 cookie expiry)
            if analysis_candidate.get("download_failed"):
                print(f"[pipeline]   ❌ download failed (likely expired cookies) — skipping entire video")
                _track_candidate_failure(video)
                log_skip(video, "skipped_download_failed", "Video download failed (likely expired cookies)")
                queue_manager.mark_processed(queue, video, "skipped_download_failed")
                queue_manager.save_queue(queue)
                commit_data_files()
                return False

            reason = []
            if not analysis_candidate.get("is_gameplay", True):
                reason.append("not gameplay")
            if not analysis_candidate.get("is_punchy", True):
                reason.append(f"not punchy: {analysis_candidate.get('punchiness_reasoning','')}")
                
            viral_score = analysis_candidate.get("viral_score", 5)
            if viral_score < min_viral:
                reason.append(f"viral_score {viral_score} < {min_viral}")
            if not analysis_candidate.get("action_fills_clip", True):
                reason.append("action doesn't fill full clip (dead time)")
            if not analysis_candidate.get("loop_worthy", True):
                reason.append("ending not loop-worthy")

            if not reason:
                peak_sec = peak_sec_candidate
                peak_signal = signal_name
                analysis = analysis_candidate
                peak_passed = True
                print(f"[pipeline] peak {peak_idx+1} passed Gemini gates ✓")
                break
            else:
                print(f"[pipeline] peak {peak_idx+1} rejected: {', '.join(reason)}")

        if not peak_passed:
            print("[pipeline] all heatmap peaks rejected by Gemini — skipping video")
            _track_candidate_failure(video)
            log_skip(video, "skipped_all_peaks_failed",
                     "all heatmap peaks rejected by Gemini gates")
            queue_manager.mark_processed(queue, video, "skipped_all_peaks_failed")
            queue_manager.save_queue(queue)
            commit_data_files()
            return False

        # Attach metadata for downstream use
        analysis["_peak_sec"] = peak_sec
        analysis["_peak_signal"] = peak_signal
        analysis["_timestamp_comments"] = []

        # ── RAG QUALITY GATE ──────────────────────────────────────────
        print(f"[pipeline]   scoring viral potential via RAG…")
        rag_score = 0
        try:
            viral_check = rag.score_viral_potential(
                visual_description=analysis.get("description", ""),
                timestamp_comments=[],
                moment_type=analysis.get("moment_type", "other"),
                viral_score_from_gemini=analysis.get("viral_score", 0)
            )
            analysis["_viral_check"] = viral_check
            rag_score = viral_check.get("score", 0)
            rag_verdict = viral_check.get("verdict", "reject")
            matched_triggers = viral_check.get("matched_triggers", [])
            print(f"[pipeline]   RAG score: {rag_score:.1f}/10 | verdict: {rag_verdict}")
            print(f"[pipeline]   triggers: {matched_triggers}")

            if rag_verdict == "reject":
                print(f"[pipeline]   ❌ RAG rejected clip — skipping video")
                _track_candidate_failure(video)
                log_skip(video, "skipped_rag_rejected",
                         f"RAG rejected: score={rag_score:.1f}, triggers={matched_triggers}")
                queue_manager.mark_processed(queue, video, "skipped_rag_rejected")
                queue_manager.save_queue(queue)
                commit_data_files()
                return False
        except Exception as e:
            print(f"[pipeline]   RAG check error (continuing): {e}")
            analysis["_viral_check"] = {"score": 0, "verdict": "error", "matched_triggers": []}

        # ── CLIP VALIDATOR GATE ────────────────────────────────────────
        try:
            description = analysis.get("description", "")
            if description:
                val_result = clip_validator.validate_clip(description, [])
                if not val_result.get("passed", True):
                    print(f"[pipeline]   ❌ clip validator rejected: {val_result.get('reasoning', '')}")
                    _track_candidate_failure(video)
                    log_skip(video, "skipped_vague_description",
                             f"clip validator: {val_result.get('reasoning', '')}")
                    queue_manager.mark_processed(queue, video, "skipped_vague_description")
                    queue_manager.save_queue(queue)
                    commit_data_files()
                    return False
                print(f"[pipeline]   ✅ clip validator passed")
        except Exception as e:
            print(f"[pipeline]   clip validator error (continuing): {e}")

        print(f"[pipeline]   ✅ passed all gates (viral_score={analysis.get('viral_score')}, rag={rag_score:.1f}/10)")

        return _finalize_video(queue, video, analysis, duration, api_key)

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


def _finalize_video(queue: dict, video: dict, analysis: dict, duration: float, api_key: str) -> bool:
    """Take a validated analysis result and run the remaining pipeline steps.

    Handles: candidate tracking, transcript, hook, voice, edit, upload, logging.
    Returns True on success.
    """
    try:
        global_start = analysis["global_start"]
        global_end = analysis["global_end"]
        climax_sec = analysis.get("climax_sec", global_end)
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
        # Loop engineering: end 0.5s after climax (mid-chaos) instead of at natural_end
        min_clip = float(config.CLIP.get("min_duration_seconds", 10))
        effective_end = min(climax_sec + 0.5, global_end)
        if (effective_end - global_start) < min_clip:
            print(f"[pipeline] climax_sec too early ({climax_sec:.1f}s) — using natural_end instead")
            effective_end = global_end
        print(f"[pipeline] loop engineering: climax={climax_sec:.1f}s, effective_end={effective_end:.1f}s (was {global_end:.1f}s)")

        if not editor.build_short(
            video_url=video["url"],
            global_start=global_start,
            global_end=effective_end,
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

        # POST ENGAGEMENT COMMENT (non-fatal — upload is never affected)
        if not dry_run and short_id:
            try:
                comment = uploader.generate_engagement_comment(
                    visual_description=visual_description,
                    moment_type=analysis.get("moment_type", "")
                )
                uploader.post_first_comment(short_id, comment)
            except Exception as e:
                print(f"[pipeline] engagement comment failed (non-fatal): {e}")

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
            "climax_sec": climax_sec,
            "effective_end": effective_end,
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

