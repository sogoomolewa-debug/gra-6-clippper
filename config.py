# config.py — single source of truth for all pipeline constants

CONTENT_TIERS = [
    {
        "name": "gta6",
        "queries": [
            "GTA 6 gameplay",
            "GTA VI trailer",
            "Grand Theft Auto 6",
            "GTA 6 new footage",
            "GTA 6 details"
        ],
        "min_views": 20000,
        "max_age_hours": 48,
        "min_channel_subscribers": 10000
    },
    {
        "name": "gta5",
        "queries": [
            "GTA 5 funny moments 2026",
            "GTA V best clips",
            "GTA 5 insane moments"
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
    "output_height": 1920
}

TTS = {
    "voice_sample_path": "assets/voice_sample.wav",
    "modal_timeout_seconds": 90
}

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
