# pipeline/queue_manager.py — Manage data/queue.json

import json
import pathlib
from datetime import datetime

import config


def load_queue() -> dict:
    """Load queue from disk. Returns empty queue on any failure."""
    try:
        path = pathlib.Path(config.QUEUE["path"])
        if not path.exists():
            print("[queue] file not found, starting fresh")
            return {"pending": [], "processed": []}
        with open(path, "r") as f:
            data = json.load(f)
        print(f"[queue] loaded: {len(data.get('pending', []))} pending, {len(data.get('processed', []))} processed")
        return data
    except json.JSONDecodeError as e:
        print(f"[queue] warning: parse error ({e}), returning empty queue")
        return {"pending": [], "processed": []}
    except Exception as e:
        print(f"[queue] error loading: {e}")
        return {"pending": [], "processed": []}


def save_queue(queue: dict) -> None:
    """Save queue to disk."""
    try:
        path = pathlib.Path(config.QUEUE["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(queue, f, indent=2)
        print(f"[queue] saved: {len(queue.get('pending', []))} pending, {len(queue.get('processed', []))} processed")
    except Exception as e:
        print(f"[queue] error saving: {e}")


def add_to_queue(queue: dict, videos: list, source_type: str) -> int:
    """Add new videos to queue, skip duplicates. Returns count added."""
    try:
        existing_ids = set()
        for v in queue.get("pending", []):
            existing_ids.add(v.get("video_id"))
        for v in queue.get("processed", []):
            existing_ids.add(v.get("video_id"))

        added = 0
        for video in videos:
            vid = video.get("video_id")
            if vid in existing_ids:
                print(f"[queue] skip duplicate: {vid}")
                continue
            video["source_type"] = source_type
            video["queued_at"] = datetime.utcnow().isoformat() + "Z"
            queue["pending"].append(video)
            existing_ids.add(vid)
            added += 1

        # Sort by score descending
        queue["pending"].sort(key=lambda x: x.get("score", 0), reverse=True)

        # Trim to max_pending
        max_pending = config.QUEUE["max_pending"]
        if len(queue["pending"]) > max_pending:
            queue["pending"] = queue["pending"][:max_pending]

        print(f"[queue] added {added} new videos (source: {source_type})")
        return added
    except Exception as e:
        print(f"[queue] error adding to queue: {e}")
        return 0


def pop_top(queue: dict) -> dict | None:
    """Pop the highest-scored pending video. Caller must save."""
    try:
        if not queue.get("pending"):
            print("[queue] no pending videos to pop")
            return None
        video = queue["pending"].pop(0)
        print(f"[queue] popped: {video.get('video_id')} (score: {video.get('score', 0):.0f})")
        return video
    except Exception as e:
        print(f"[queue] error popping: {e}")
        return None


def requeue(queue: dict, video: dict) -> None:
    """Append video to end of pending list (lowest priority)."""
    try:
        queue["pending"].append(video)
        print(f"[queue] requeued: {video.get('video_id')} (will retry later)")
    except Exception as e:
        print(f"[queue] error requeueing: {e}")


def mark_processed(queue: dict, video: dict, short_id: str) -> None:
    """Move video to processed list with short_id and timestamp."""
    try:
        entry = {
            "video_id": video.get("video_id"),
            "short_id": short_id,
            "source_type": video.get("source_type"),
            "uploaded_at": datetime.utcnow().isoformat() + "Z"
        }
        queue["processed"].append(entry)
        # Trim processed to max 100 items (remove oldest)
        if len(queue["processed"]) > 100:
            queue["processed"] = queue["processed"][-100:]
        print(f"[queue] marked processed: {video.get('video_id')} → short {short_id}")
    except Exception as e:
        print(f"[queue] error marking processed: {e}")


def get_status(queue: dict) -> str:
    """Return multi-line status string."""
    try:
        pending = queue.get("pending", [])
        processed = queue.get("processed", [])
        gta6_count = sum(1 for v in pending if v.get("source_type") == "gta6")
        gta5_count = sum(1 for v in pending if v.get("source_type") == "gta5")
        return (
            f"Queue status: {len(pending)} pending | {len(processed)} processed total\n"
            f"  GTA6: {gta6_count} | GTA5: {gta5_count}"
        )
    except Exception as e:
        return f"Queue status: error ({e})"


if __name__ == "__main__":
    queue = load_queue()
    print(get_status(queue))
