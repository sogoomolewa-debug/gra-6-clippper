# pipeline/hook.py — Generate a punchy hook with delivery markup for natural TTS
import os
import random
from typing import List, Dict, Optional

import groq
import config

# Stage 1: Generate raw hook text with conversational, human feel
RAW_HOOK_PROMPT = """You write viral YouTube Shorts hooks for a GTA gaming channel.

Rules:
- Exactly 1 sentence, maximum 12 words
- Write like a REAL PERSON reacting — not a marketing copywriter
- Use conversational fragments, not polished sentences
- Be SPECIFIC to what actually happened — use the visual description as your primary source
- Never reveal the outcome — create pure curiosity or shock
- No emojis, no hashtags, no quotes
- Output ONLY the hook sentence, nothing else

{style_instruction}

Example of this style: "{style_example}"
"""

# Stage 2: Add delivery markup for TTS naturalness
MARKUP_PROMPT = """You are a voice director. Take this hook and add delivery markup for text-to-speech.

Rules:
- Add "..." (three dots) where the speaker should PAUSE for dramatic effect (max 2 pauses)
- CAPITALIZE exactly 1-2 key words that should be EMPHASIZED
- Use "—" (em dash) for a sharp dramatic cut (max 1)
- Keep the original words — only add pauses and change capitalization
- The result must still be under 15 words
- Output ONLY the marked-up hook, nothing else

Original hook: "{raw_hook}"

Marked-up hook:"""

FALLBACK_HOOKS = [
    "Wait... nobody SAW this coming",
    "So this just... actually HAPPENED",
    "Bro WHAT... the game just broke",
    "Nobody talks about this... but WATCH",
    "This shouldn't be... even POSSIBLE",
    "Hold on... did that just HAPPEN",
    "They actually... pulled THIS off",
]


def _get_style() -> dict:
    """Pick a random hook delivery style to break AI patterns."""
    try:
        return random.choice(config.HOOK_STYLES)
    except Exception as e:
        print(f"[hook] error picking style: {e}")
        return {
            "name": "default",
            "instruction": "React naturally with surprise.",
            "example": "Wait... they actually did THAT",
        }


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


def _call_groq(system_prompt: str, user_prompt: str, max_tokens: int = 60) -> Optional[str]:
    """Make a single Groq API call."""
    try:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            print("[hook] error: GROQ_API_KEY not set")
            return None

        client = groq.Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=max_tokens,
            temperature=0.9,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        result = response.choices[0].message.content.strip()
        # Clean up any wrapping quotes the model might add
        result = result.strip('"').strip("'")
        return result
    except Exception as e:
        print(f"[hook] Groq API error: {e}")
        return None


def generate_raw_hook(context_str: str, style: dict) -> Optional[str]:
    """Stage 1: Generate a raw conversational hook."""
    try:
        system = RAW_HOOK_PROMPT.format(
            style_instruction=style["instruction"],
            style_example=style["example"]
        )
        raw = _call_groq(system, context_str + "\n\nWrite the hook.")
        if raw:
            print(f"[hook] stage 1 raw ({style['name']}): {raw}")
        return raw
    except Exception as e:
        print(f"[hook] raw generation error: {e}")
        return None


def add_delivery_markup(raw_hook: str) -> Optional[str]:
    """Stage 2: Add pauses, emphasis, and tone markers for TTS."""
    try:
        system = "You are a voice director who adds delivery markup to text for text-to-speech."
        user = MARKUP_PROMPT.format(raw_hook=raw_hook)
        marked = _call_groq(system, user, max_tokens=80)
        if marked:
            print(f"[hook] stage 2 markup: {marked}")
        return marked
    except Exception as e:
        print(f"[hook] markup error: {e}")
        return None


def validate_hook(hook: str) -> bool:
    """Validate if the hook meets length rules (more relaxed for markup)."""
    try:
        if not hook:
            return False
        # Strip markup for word count
        clean = hook.replace("...", " ").replace("—", " ").strip()
        words = clean.split()
        word_count = len(words)
        if word_count < 3 or word_count > 18:
            print(f"[hook] validation failed: word count is {word_count} (must be 3-18)")
            return False
        # Don't allow question marks (they weaken hooks)
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
    """Generate a hook with delivery markup. Falls back to pre-written hooks on failure."""
    try:
        context_str = build_context(video_title, visual_description, transcript_context, timestamp_comments)
        style = _get_style()
        print(f"[hook] using style: {style['name']}")

        for attempt in range(3):
            print(f"[hook] attempt {attempt + 1}/3")

            # Stage 1: Raw hook
            raw_hook = generate_raw_hook(context_str, style)
            if not raw_hook:
                continue

            # Stage 2: Add delivery markup
            marked_hook = add_delivery_markup(raw_hook)
            if not marked_hook:
                # If markup fails, use the raw hook as-is
                marked_hook = raw_hook

            if validate_hook(marked_hook):
                print(f"[hook] final: {marked_hook}")
                return marked_hook

            print(f"[hook] attempt {attempt + 1} failed validation")
            # Try a different style on retry
            style = _get_style()

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
    print(f"\nFinal hook: {result}")
