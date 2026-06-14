# pipeline/hook.py — Generate a punchy hook using Groq API with context layers
import os
import random
from typing import List, Dict, Optional

import groq
import config

SYSTEM_PROMPT = """You write viral YouTube Shorts hooks for a GTA gaming channel.
Rules:
- Exactly 1 sentence
- Maximum 10 words
- Be SPECIFIC to what actually happened — use the visual description as your primary source
- Never reveal the outcome — create pure curiosity or shock
- No emojis, no hashtags, no quotes, no exclamation marks
- Output ONLY the hook sentence, nothing else"""

FALLBACK_HOOKS = [
    "Nobody saw this coming.",
    "This is why everyone is rewatching.",
    "GTA just broke everyone's brain.",
    "Most players never noticed this.",
    "This changes everything about GTA.",
    "The internet cannot stop watching this.",
    "This scene hit completely different."
]

def build_context(
    video_title: str,
    visual_description: str,
    transcript_context: str,
    timestamp_comments: List[Dict]
) -> str:
    """Build context string from video details, visual description, transcript, and comments."""
    try:
        parts = [f"Video title: {video_title}"]

        # Visual description is PRIMARY — Qwen2.5-VL actually watched the clip
        if visual_description.strip():
            parts.append(f"What visually happens at this moment (most important):\n{visual_description}")

        # Transcript (may be empty for silent gameplay)
        if transcript_context.strip():
            parts.append(f"What was said at this moment:\n{transcript_context[:400]}")

        # Comments describing this timestamp
        if timestamp_comments:
            lines = [c["text"] for c in timestamp_comments[:5]]
            parts.append(
                "What viewers said about this moment:\n" +
                "\n".join(f"- {l}" for l in lines)
            )

        context_str = "\n\n".join(parts)
        return context_str
    except Exception as e:
        print(f"[hook] error building context: {e}")
        return f"Video title: {video_title}"

def generate_hook(context_str: str) -> Optional[str]:
    """Call Groq API to generate hook text."""
    try:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            print("[hook] error: GROQ_API_KEY not set")
            return None

        client = groq.Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=50,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context_str + "\n\nWrite the hook."}
            ]
        )
        hook_content = response.choices[0].message.content.strip()
        print(f"[hook] Groq returned: {hook_content}")
        return hook_content
    except Exception as e:
        print(f"[hook] Groq API error: {e}")
        return None

def validate_hook(hook: str) -> bool:
    """Validate if the hook meets all length and punctuation rules."""
    try:
        if not hook:
            return False
        words = hook.split()
        word_count = len(words)
        if word_count < 3 or word_count > 15:
            print(f"[hook] validation failed: word count is {word_count} (must be between 3 and 15)")
            return False
        if hook.strip().endswith("?"):
            print("[hook] validation failed: ends with a question mark")
            return False
        return True
    except Exception as e:
        print(f"[hook] validation error: {e}")
        return False

def get_hook_with_fallback(
    video_title: str,
    visual_description: str = "",
    transcript_context: str = "",
    timestamp_comments: List[Dict] = []
) -> str:
    """Attempt Groq hook generation up to 3 times, fallback to random hook on failure."""
    try:
        context_str = build_context(video_title, visual_description, transcript_context, timestamp_comments)
        for attempt in range(3):
            print(f"[hook] attempt {attempt + 1}/3")
            hook_candidate = generate_hook(context_str)
            if hook_candidate and validate_hook(hook_candidate):
                print(f"[hook] generated: {hook_candidate}")
                return hook_candidate
            print(f"[hook] attempt {attempt + 1} failed validation")

        # Fallback if all attempts fail
        fallback_hook = random.choice(FALLBACK_HOOKS)
        print(f"[hook] using fallback: {fallback_hook}")
        return fallback_hook
    except Exception as e:
        print(f"[hook] error generating hook: {e}")
        fallback_hook = random.choice(FALLBACK_HOOKS)
        print(f"[hook] using fallback: {fallback_hook}")
        return fallback_hook

if __name__ == "__main__":
    sample = {
        "visual_description": "Player jumps from a skyscraper and lands on a moving helicopter.",
        "timestamp_comments": [
            {"text": "2:34 no way he survived that 💀", "like_count": 420}
        ]
    }
    result = get_hook_with_fallback(
        video_title="GTA 6 Gameplay First 2 Hours",
        visual_description=sample["visual_description"],
        timestamp_comments=sample["timestamp_comments"]
    )
    print(f"Final hook: {result}")
