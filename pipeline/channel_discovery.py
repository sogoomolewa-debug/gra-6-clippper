# pipeline/channel_discovery.py — Auto-grow whitelist by testing candidate channels

import json
import pathlib
import re
from datetime import datetime

import config

ANALYTICS_PATH = pathlib.Path("data/channel_analytics.json")
CONFIG_PATH = pathlib.Path("config.py")


def load_analytics() -> dict:
    """Load channel analytics from disk, ensuring 'candidates' key exists."""
    try:
        if not ANALYTICS_PATH.exists():
            return {"last_updated": None, "channels": {}, "candidates": {}}
        with open(ANALYTICS_PATH, "r") as f:
            data = json.load(f)
        if "candidates" not in data:
            data["candidates"] = {}
        return data
    except Exception as e:
        print(f"[channel_discovery] error loading analytics: {e}")
        return {"last_updated": None, "channels": {}, "candidates": {}}


def save_analytics(analytics: dict) -> None:
    """Write analytics with last_updated timestamp."""
    try:
        ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        analytics["last_updated"] = datetime.utcnow().isoformat() + "Z"
        with open(ANALYTICS_PATH, "w") as f:
            json.dump(analytics, f, indent=2)
        print("[channel_discovery] analytics saved")
    except Exception as e:
        print(f"[channel_discovery] error saving analytics: {e}")


def load_candidates(analytics: dict) -> dict:
    """Extract candidates dict from analytics."""
    return analytics.get("candidates", {})


def save_candidates(analytics: dict, candidates: dict) -> None:
    """Write candidates back into analytics dict."""
    analytics["candidates"] = candidates


def record_attempt(candidates: dict, channel_id: str, channel_title: str, passed: bool) -> None:
    """Increment attempt/pass/reject counters for a candidate channel."""
    if channel_id not in candidates:
        candidates[channel_id] = {
            "channel_title": channel_title,
            "clips_attempted": 0,
            "clips_passed": 0,
            "clips_rejected": 0,
            "first_seen": datetime.utcnow().isoformat() + "Z",
        }
    entry = candidates[channel_id]
    entry["clips_attempted"] += 1
    if passed:
        entry["clips_passed"] += 1
    else:
        entry["clips_rejected"] += 1
    entry["last_seen"] = datetime.utcnow().isoformat() + "Z"


def should_promote(candidate: dict) -> bool:
    """Returns True if candidate has enough successful clips for promotion."""
    threshold = getattr(config, "DISCOVERY", {}).get("promotion_threshold", 3)
    return candidate.get("clips_passed", 0) >= threshold


def should_blacklist(candidate: dict) -> bool:
    """Returns True if candidate has enough attempts with zero passes for blacklisting."""
    threshold = getattr(config, "DISCOVERY", {}).get("demotion_threshold", 5)
    return (
        candidate.get("clips_attempted", 0) >= threshold
        and candidate.get("clips_passed", 0) == 0
    )


def promote_channel(channel_id: str, channel_title: str) -> bool:
    """Write a new whitelist entry into config.py above the '# END WHITELIST' marker."""
    try:
        content = CONFIG_PATH.read_text()
        marker = "# END WHITELIST"
        if marker not in content:
            print(f"[channel_discovery] marker '{marker}' not found in config.py")
            return False

        new_entry = f'        {{"name": "{channel_title}", "id": "{channel_id}", "priority": 1.0}},\n'
        content = content.replace(
            f"        {marker}",
            f"{new_entry}        {marker}"
        )
        CONFIG_PATH.write_text(content)
        print(f"[channel_discovery] ✅ promoted channel '{channel_title}' ({channel_id}) to whitelist")
        return True
    except Exception as e:
        print(f"[channel_discovery] error promoting channel: {e}")
        return False


def blacklist_channel(channel_id: str, channel_title: str) -> bool:
    """Write a new entry into config.py above the '# END CHANNEL_BLACKLIST' marker."""
    try:
        content = CONFIG_PATH.read_text()
        marker = "# END CHANNEL_BLACKLIST"
        if marker not in content:
            print(f"[channel_discovery] marker '{marker}' not found in config.py")
            return False

        new_entry = f'    "{channel_title}",\n'
        content = content.replace(
            f"    {marker}",
            f"{new_entry}    {marker}"
        )
        CONFIG_PATH.write_text(content)
        print(f"[channel_discovery] ⛔ blacklisted channel '{channel_title}' ({channel_id})")
        return True
    except Exception as e:
        print(f"[channel_discovery] error blacklisting channel: {e}")
        return False


def process_candidate_result(
    analytics: dict,
    channel_id: str,
    channel_title: str,
    passed_all_gates: bool
) -> str:
    """Main entry point — records result, checks promote/blacklist thresholds.

    Returns:
        'promoted', 'blacklisted', or 'tracking' to indicate the action taken.
    """
    try:
        candidates = load_candidates(analytics)
        record_attempt(candidates, channel_id, channel_title, passed_all_gates)

        candidate = candidates[channel_id]
        action = "tracking"

        if should_promote(candidate):
            if promote_channel(channel_id, channel_title):
                action = "promoted"
                candidate["status"] = "promoted"
                print(f"[channel_discovery] channel '{channel_title}' promoted after "
                      f"{candidate['clips_passed']} successful clips")

        elif should_blacklist(candidate):
            if blacklist_channel(channel_id, channel_title):
                action = "blacklisted"
                candidate["status"] = "blacklisted"
                print(f"[channel_discovery] channel '{channel_title}' blacklisted after "
                      f"{candidate['clips_attempted']} failed attempts")

        save_candidates(analytics, candidates)
        return action
    except Exception as e:
        print(f"[channel_discovery] error processing candidate result: {e}")
        return "tracking"


if __name__ == "__main__":
    analytics = load_analytics()
    candidates = load_candidates(analytics)
    print(f"[channel_discovery] loaded {len(candidates)} candidate channels")
    for cid, data in candidates.items():
        print(f"  {data.get('channel_title', 'unknown')}: "
              f"attempted={data.get('clips_attempted', 0)} "
              f"passed={data.get('clips_passed', 0)} "
              f"status={data.get('status', 'tracking')}")
