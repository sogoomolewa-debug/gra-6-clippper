# pipeline/hook.py — Generate a punchy 1-sentence hook using Claude API

import os
import random

import config

SYSTEM_PROMPT = """You write viral YouTube Shorts hooks for a GTA gaming channel.
Rules:
- Exactly 1 sentence
- Maximum 10 words
- Never reveal what happens — create pure curiosity or shock
- No emojis, no hashtags, no quotes
- Output ONLY the hook sentence, nothing else"""

FALLBACK_HOOKS = [
    "Nobody saw this coming.",
    "This is why everyone is rewatching.",
    "GTA just broke everyone's brain.",
    "Most players never noticed this.",
    "This changes everything about GTA.",
    "The internet cannot stop watching this.",
    "This scene hit different."
]


def generate_hook(video_title: str, context: str = "") -> str | None:
    """Generate a hook using Claude API."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("[hook] error: ANTHROPIC_API_KEY not set")
            return None
            
        client = anthropic.Anthropic(api_key=api_key)
        user_msg = (
            f"Video title: {video_title}\n"
            f"Context from most-rewatched moment: {context if context else 'not available'}\n"
            f"Write the hook."
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=50,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        text = response.content[0].text.strip()
        print(f"[hook] Claude returned: {text}")
        return text
    except Exception as e:
        print(f"[hook] Claude API error: {e}")
        return None


def validate_hook(hook: str) -> bool:
    """Validate hook meets criteria."""
    try:
        if not hook:
            return False
        word_count = len(hook.split())
        if word_count < 3 or word_count > 15:
            print(f"[hook] validation failed: {word_count} words (need 3-15)")
            return False
        if hook.strip().endswith("?"):
            print("[hook] validation failed: ends with question mark")
            return False
        return True
    except Exception as e:
        print(f"[hook] validation error: {e}")
        return False


def get_hook_with_fallback(video_title: str, context: str = "") -> str:
    """Try generating a hook up to 3 times, fallback to preset hooks."""
    try:
        for attempt in range(3):
            print(f"[hook] attempt {attempt + 1}/3")
            hook = generate_hook(video_title, context)
            if hook and validate_hook(hook):
                print(f"[hook] generated: {hook}")
                return hook
            print(f"[hook] attempt {attempt + 1} failed validation")

        # All attempts failed, use fallback
        hook = random.choice(FALLBACK_HOOKS)
        print(f"[hook] using fallback: {hook}")
        return hook
    except Exception as e:
        print(f"[hook] error: {e}")
        hook = random.choice(FALLBACK_HOOKS)
        print(f"[hook] using fallback: {hook}")
        return hook


if __name__ == "__main__":
    hook = get_hook_with_fallback(
        video_title="GTA 6 First Gameplay Trailer Breakdown",
        context="The character pulls out a weapon nobody has seen before"
    )
    print(f"Final hook: {hook}")
