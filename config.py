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
    "max_duration_seconds": 55,
    "hook_duration_seconds": 3,
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
    "safe_zone_margin_bottom": 220
}

TTS = {
    "voice_sample_path": "assets/voice_sample.wav",
    "modal_timeout_seconds": 90,
    "breath_pad_ms": 200,           # silence before speech starts
    "chunk_gap_ms": 280,            # silence between chunks
    "speed_suspense": 0.85,         # slower for build-up chunks
    "speed_reveal": 1.08,           # faster for payoff chunks
    "speed_default": 0.95,          # neutral speed
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
