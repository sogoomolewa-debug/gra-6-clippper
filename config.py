# config.py — single source of truth for all pipeline constants

CONTENT_TIERS = [
    {
        "name": "gta6",
        "queries": [
            "GTA 6 gameplay walkthrough",
            "GTA VI gameplay",
            "Grand Theft Auto 6 gameplay",
            "GTA 6 stunts gameplay"
        ],
        "min_views": 20000,
        "max_age_hours": 48,
        "min_channel_subscribers": 10000
    },
    {
        "name": "gta5",
        "queries": [
            "GTA 5 stunts gameplay",
            "GTA 5 funny moments gameplay",
            "GTA V heist gameplay"
        ],
        "min_views": 50000,
        "max_age_hours": 168,
        "min_channel_subscribers": 25000
    }
]

ELIGIBILITY = {
    "min_duration_seconds": 240,
    "max_duration_seconds": 3600,
    "min_like_ratio": 0.02,
}

QUEUE = {
    "path": "data/queue.json",
    "min_size": 3,
    "max_pending": 20
}

CLIP = {
    "max_duration_seconds": 12,  # Changed from 14 to match reference video
    "min_duration_seconds": 10,
    "hook_duration_seconds": 3,
    "blur_intro_enabled": True,  # NEW: Set to False for instant-action hooks
    "output_width": 1080,
    "output_height": 1920,
    "font_path": "assets/Oswald-Bold.ttf",
    "font_size_hook": 90,
    "font_size_reveal": 65,
    "caption_outline_width": 6,
    "caption_outline_color": "black",
    "caption_shadow_x": 3,
    "caption_shadow_y": 3,
    "caption_shadow_color": "black",
    "hook_caps": True,
    "safe_zone_margin_bottom": 220,
    "min_viral_score": 7,          # minimum Gemini viral score (1-10) to proceed
    "max_peaks_to_try": 3,         # max heatmap peaks to evaluate per video
}

TTS = {
    "voice_sample_path": "assets/voice_sample.wav",
    "modal_timeout_seconds": 90,
    "breath_pad_ms": 200,           # silence before speech starts
    "chunk_gap_ms": 280,            # silence between chunks
    "speed_suspense": 0.85,         # slower for build-up chunks
    "speed_reveal": 1.08,           # faster for payoff chunks
    "speed_default": 0.95,          # neutral speed
    # --- Humanization parameters ---
    "humanize_pitch_jitter_pct": 1.0,           # ±% random pitch per 200ms window
    "humanize_room_tone_db": -42,               # brownian noise floor level
    "humanize_breath_db": -30,                  # synthetic breath level in gaps
    "humanize_reverb_rt60": 0.1,                # room impulse response decay (seconds)
    "humanize_high_shelf_cut_db": -2,            # HF rolloff above 12kHz
    "humanize_low_shelf_boost_db": 1.5,          # warmth boost at 150Hz
    "humanize_compression_threshold_db": -18,    # compressor threshold
    "humanize_compression_ratio": 2.0,           # compressor ratio
}

# Rotating hook delivery styles to break the AI pattern
HOOK_STYLES = [
    {
        "name": "shocked",
        "instruction": "React like you just witnessed something unbelievable. Use a dramatic pause before the reveal.",
        "example": "Wait... they actually LANDED on the helicopter",
    },
    {
        "name": "deadpan",
        "instruction": "State the fact calmly, almost dismissively, then let the absurdity speak for itself.",
        "example": "So this guy just... drove off a cliff and survived",
    },
    {
        "name": "hype",
        "instruction": "Pure energy and disbelief. Short punchy fragments with emphasis on the action word.",
        "example": "Bro WHAT... the car just flew across the map",
    },
    {
        "name": "storyteller",
        "instruction": "Set up a mini-narrative tension. Make the viewer feel like they're about to hear a secret.",
        "example": "Nobody talks about this... but watch what happens NEXT",
    },
]

UPLOAD = {
    "limit_per_run": 1,
    "category_id": "20",
    "privacy_status": "public",
    "tags": ["GTA6", "GTA VI", "GTA6 Shorts", "Gaming", "GrandTheftAuto"]
}

LOGS = {
    "performance_path": "data/performance_log.json",
    "snapshot_intervals": [(24, "24h"), (72, "72h"), (168, "7d")]
}

import os
YOUTUBE_COOKIES_PATH = os.environ.get("YOUTUBE_COOKIES_PATH", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

# Content Strategy Mode
# "tts_narrated" = Full TTS voiceover + blur intro (storytelling/drama)
# "pure_gameplay" = No TTS, instant action, casual captions (authentic/minimalist)
# "reference_inspired" = Measured pacing, blur intro, casual 5-7 word hooks
CONTENT_MODE = os.environ.get("CONTENT_MODE", "reference_inspired")

# Content Mode Rotation — cycles through modes to collect comparison data
# Set CONTENT_MODE_ROTATION=true in .env or GitHub Secrets to enable
CONTENT_MODE_ROTATION = os.environ.get("CONTENT_MODE_ROTATION", "true").lower() == "true"
MODE_ROTATION_ORDER = ["reference_inspired", "tts_narrated", "pure_gameplay"]
MODE_ROTATION_BATCH_SIZE = 3  # post N videos in each mode before switching


CONTENT_PROFILES = {
    "tts_narrated": {
        "description": "Blurred setup with TTS hook, then clean reveal.",
        "blur_intro_enabled": True,
        "hook_caps": True,
        "font_size_hook": 90,
        "caption_max_chars": 18,
        "tts": {
            "breath_pad_ms": 200,
            "chunk_gap_ms": 280,
            "speed_suspense": 0.85,
            "speed_reveal": 1.08,
            "speed_default": 0.95,
        },
        "hook": {
            "max_words": 12,
            "prompt_family": "dramatic",
        },
        "hashtags": {
            "gta6": "#GTA6 #GTAVI #GrandTheftAuto #Gaming #Shorts",
            "gta5": "#GTA5 #GTAV #GrandTheftAuto #Gaming #Shorts",
            "gta": "#GTA #GrandTheftAuto #Gaming #Shorts",
            "general": "#Gaming #Gameplay #Shorts",
        },
        "upload_tags": ["GTA6", "GTA VI", "GTA6 Shorts", "Gaming", "GrandTheftAuto"],
    },
    "pure_gameplay": {
        "description": "Fast clear-footage setup with minimal narration feel.",
        "blur_intro_enabled": False,
        "hook_caps": False,
        "font_size_hook": 74,
        "caption_max_chars": 20,
        "tts": {
            "breath_pad_ms": 80,
            "chunk_gap_ms": 140,
            "speed_suspense": 1.0,
            "speed_reveal": 1.12,
            "speed_default": 1.05,
        },
        "hook": {
            "max_words": 10,
            "prompt_family": "casual",
        },
        "hashtags": {
            "gta6": "#GTA6 #Gaming #Shorts",
            "gta5": "#GTA5 #Gaming #Shorts",
            "gta": "#GTA #Gaming #Shorts",
            "general": "#Gaming #Gameplay #Shorts",
        },
        "upload_tags": ["Gaming", "Gameplay", "Shorts"],
    },
    "reference_inspired": {
        "description": "Measured creator-reference pacing: blurred setup, 5-7 word casual speech, hard GTA reveal.",
        "blur_intro_enabled": True,
        "hook_caps": False,
        "font_size_hook": 78,
        "caption_max_chars": 18,
        "tts": {
            "breath_pad_ms": 100,
            "chunk_gap_ms": 180,
            "speed_suspense": 0.95,
            "speed_reveal": 1.10,
            "speed_default": 1.03,
        },
        "hook": {
            "max_words": 7,
            "prompt_family": "reference_casual",
        },
        "hashtags": {
            "gta6": "#GTA6 #Gaming #Shorts",
            "gta5": "#GTA5 #Gaming #Shorts",
            "gta": "#GTA #Gaming #Shorts",
            "general": "#Gaming #Gameplay #Shorts",
        },
        "upload_tags": ["GTA6", "GTA VI", "GTA6 Shorts", "Gaming", "GrandTheftAuto"],
    },
}


def get_content_profile(mode: str | None = None) -> dict:
    """Return the active content profile, falling back to the narrated default."""
    selected = mode or CONTENT_MODE
    return CONTENT_PROFILES.get(selected, CONTENT_PROFILES["tts_narrated"])


def get_profile_value(key: str, default=None, mode: str | None = None):
    """Read a top-level profile override."""
    return get_content_profile(mode).get(key, default)


def get_tts_value(key: str, default=None, mode: str | None = None):
    """Read a TTS profile override."""
    return get_content_profile(mode).get("tts", {}).get(key, default)


def get_hashtags(source_type: str = "general", mode: str | None = None) -> str:
    """Return hashtags for a source type under the active content profile."""
    hashtags = get_content_profile(mode).get("hashtags", {})
    return hashtags.get(source_type, hashtags.get("general", "#Gaming #Shorts"))


def get_upload_tags(mode: str | None = None) -> list[str]:
    """Return YouTube upload tags for the active content profile."""
    return get_content_profile(mode).get("upload_tags", UPLOAD["tags"])

SOURCING = {
    "mode": os.environ.get("SOURCING_MODE", "whitelist"),
    "whitelist_channels": [
        {"name": "Hazardous", "id": "UCgXfEXQBy0r4MywuzNf3iGQ", "priority": 1.0},
        {"name": "whatever57010", "id": "UCoKYYUrm0En0U2wAIkxSh5A", "priority": 1.0},
        {"name": "Prestige Clips", "id": "UCC-uu-OqgYEx52KYQ-nJLRw", "priority": 1.0},
        {"name": "Red Arcade", "id": "UCHZZo1h1cI1vg4I9g2RqOUQ", "priority": 1.0},
        # END WHITELIST
    ],
    "max_age_hours": 168,
    "min_views": 20000,
    "keyword_filter": "gta",
}

# Title blacklist — phrases that indicate non-gameplay content (checked before any API call)
TITLE_BLACKLIST = [
    # Analysis / news / opinion
    "analysis", "explained", "breakdown", "everything we know", "all details",
    "theory", "theories", "confirmed", "debunked", "rumor", "rumour",
    "leak", "leaks", "leaked", "news", "update", "updates",
    "official trailer", "cover art", "box art", "announcement",
    # Reaction / talk shows
    "reaction", "reacts", "react", "rant", "essay", "podcast",
    "review", "opinion", "thoughts on", "let's talk", "real talk",
    "face reveal", "q&a", "interview",
    # Listicle / compilation
    "top 10", "top 5", "top 20", "top 15", "top 50", "top 100",
    "things you didn't know", "things you missed",
    "hidden details", "easter egg", "easter eggs",
    # Non-gameplay formats
    "stream highlight", "vlog", "rambles", "drama",
    "speculation", "comparison", "vs real life",
    "map size", "map comparison", "graphics comparison",
    # Wrong game / franchise
    "fortnite", "minecraft", "roblox", "call of duty", "cod",
    "red dead", "rdr", "cyberpunk", "saints row",
]

# Channel discovery — auto-grow the whitelist by testing candidate channels
DISCOVERY = {
    "trigger_queue_size": 2,          # run discovery when queue drops below this
    "queries": [
        "GTA 6 gameplay stunts",
        "GTA V ragdoll physics",
        "GTA 5 funny moments gameplay",
        "GTA online insane stunts",
    ],
    "max_results_per_query": 5,
    "min_views": 15000,
    "max_age_hours": 336,                 # 14 days — wider window than whitelist
    "max_subscriber_count": 5000000,  # skip mega-channels that may DMCA
    "promotion_threshold": 3,         # clips passed before auto-whitelist
    "demotion_threshold": 5,          # clips attempted with 0 passes before blacklist
}

# Permanent channel blacklist — confirmed wrong-content or problematic channels
CHANNEL_BLACKLIST = [
    "MrBossFTW",
    "TGG",
    "Digital Car Addict",
    # END CHANNEL_BLACKLIST
]
