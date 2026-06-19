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
CONTENT_MODE = os.environ.get("CONTENT_MODE", "tts_narrated")

SOURCING = {
    "mode": "whitelist",
    "whitelist_channels": [
        # High priority - pure gameplay, proven performers
        {"name": "Hazardous", "id": "UCgXfEXQBy0r4MywuzNf3iGQ", "priority": 2.0},
        {"name": "whatever57010", "id": "UCoKYYUrm0En0U2wAIkxSh5A", "priority": 2.0},
        {"name": "Prestige Clips", "id": "UCC-uu-OqgYEx52KYQ-nJLRw", "priority": 2.0},
        {"name": "GTA Series Videos", "id": "UCuWcjpKbIDAbZfHoru1toFg", "priority": 2.0},  # Fixed ID
        {"name": "GTAMen", "id": "UC4zMEl8Qh_nE5nDnp0cxRFQ", "priority": 2.0},  # Fixed ID
        {"name": "TGG", "id": "UC72PuhDwKtZ5MikpGNhPAtA", "priority": 1.8},  # Fixed ID

        # Medium priority - good content but some rejections
        {"name": "Red Arcade", "id": "UCHZZo1h1cI1vg4I9g2RqOUQ", "priority": 1.2},  # 57% rejection rate
        {"name": "MrBossFTW", "id": "UC0PMQXAwF6O6aeTpv962miA", "priority": 1.5},  # Fixed ID
        {"name": "Digital Car Addict", "id": "UCD9qy7cc3bb5rrMjJ9tRTTA", "priority": 1.5},  # Fixed ID

        # Low priority - comedy/entertainment (not pure gameplay)
        {"name": "Call Me Kevin", "id": "UCdoPCztTOW7BJUPk2h5ttXA", "priority": 0.5},

        # REMOVED: DarkViperAU (100% rejection - commentary only, no gameplay)
    ],
    "max_age_hours": 168,
    "min_views": 20000,
}
