# pipeline/hook.py — Generate a punchy hook with delivery markup for natural TTS
import os
import random
import re
from typing import List, Dict, Optional

import groq
import config
from pipeline import rag

# Stage 3: Generate viral title for high-CTR curiosity gap
VIRAL_TITLE_PROMPT = """You write viral, high-CTR YouTube Shorts titles for a GTA gaming channel.
Use a "Curiosity Gap" approach: tease the setups, physical glitches, extreme stunts, or bizarre moments without giving away the final outcome.

Context:
- Visual Description: {visual_description}
- Hook Text: {hook_text}

Rules:
1. Length: 3 to 6 words (under 45 characters).
2. Curiosity Gap: Tease the action or setup, but NEVER reveal the outcome (e.g., use "Did this just happen?!" instead of "Car lands on helicopter").
3. Capitalization: CAPITALIZE exactly 1-2 emotional or action words for visual punch (e.g., "This GTA physics is BROKEN", "NO WAY he survived this").
4. Emojis: Use exactly 1 highly relevant emoji at the end of the text (e.g. 🤯, 💀, 😱, 😳).
5. Cleanliness: Output ONLY the title text. Do NOT include hashtags, quotes, markdown, or creator channel names.
"""

FALLBACK_TITLES = [
    "This was NOT supposed to happen",
    "Did this actually just HAPPEN?!",
    "Wait... is this even POSSIBLE?!",
    "This GTA physics is BROKEN",
    "NO WAY he survived this",
    "The luckiest GTA stunt EVER",
]

# Stage 1: Generate raw hook text with conversational, human feel
RAW_HOOK_PROMPT = """You write viral YouTube Shorts hooks for a gaming Shorts channel.

Rules:
- Exactly 1 sentence, maximum {max_words} words
- Write like a REAL PERSON reacting — not a marketing copywriter
- Use conversational fragments, not polished sentences
- Be SPECIFIC to what actually happened — use the visual description as your primary source
- Never reveal the outcome — create pure curiosity or shock
- No emojis, no hashtags, no quotes
- Output ONLY the hook sentence, nothing else

{style_instruction}

Example of this style: "{style_example}"
"""

CASUAL_RAW_HOOK_PROMPT = """You write short, casual creator-style captions for gaming Shorts.

Rules:
- Exactly 1 sentence fragment, 5 to {max_words} words
- Sound like a person reacting mid-clip, not an announcer
- Use a setup phrase that can be captioned one word at a time
- Use lowercase unless one word truly needs emphasis
- Be specific to the visual moment, but do not spoil the outcome
- Include a ... pause before the key reveal word for dramatic delivery
  (e.g. "bro really just... flew off the overpass")
- No emojis, no hashtags, no quotes
- Output ONLY the hook text

Reference tone examples:
- see there's always... a bigger fish
- never trust the quiet... gta player
- sometimes the road just... fights back
- bro picked the wrong... ramp today
"""

FALLBACK_HOOKS = [
    "bro really just sent it off the overpass",
    "this car had zero business surviving that",
    "ngl the physics gave up on this one",
    "tell me why this actually worked tho",
    "sometimes the npc fights back fr",
    "nobody was ready for that landing",
    "the bike said nah i'm out",
]

# System prompt for dramatic hook generation (used when prompt_family == "dramatic")
SYSTEM_PROMPT = """You write viral YouTube Shorts hooks for a GTA gaming channel.

Rules:
1. Maximum 10 words. Aim for 6-8.
2. Lowercase preferred. Only CAPITALIZE if one word truly needs shock emphasis.
3. NO exclamation marks. Ever.
4. Sound like a real person mid-reaction, not a copywriter.
5. Be SPECIFIC to the visual action — reference the vehicle, the stunt, the NPC, the physics.
6. Never reveal the outcome. Tease the setup so the viewer must watch.
7. No emojis, no hashtags, no quotes.

Blacklisted phrases (never use these):
- "you won't believe"
- "wait for it"
- "gone wrong"
- "what happens next"
- "nobody expected"
- "this is insane"
- "absolutely insane"

Emotional triggers to lean into:
- Disbelief: "bro really just...", "tell me why..."
- Specificity: name the vehicle, the ramp, the building
- Understatement: "the car simply... left", "physics said no"
- Casualness: "ngl", "fr", "tho", "lowkey"

Examples by clip type:

STUNT: "the bike hit the ramp and just... kept going"
STUNT: "bro cleared the entire highway on a bmx"
CRASH: "this truck had no business flipping like that"
CRASH: "the car folded in half and kept driving"
RAGDOLL: "physics really said nah for this one"
RAGDOLL: "he bounced off three buildings and survived"
EXPLOSION: "one grenade and the intersection was gone"
EXPLOSION: "the gas station chain reaction was WILD"
NPC: "the npc pulled up and chose violence"
NPC: "tell me why the cop did a backflip"
CHASE: "five stars and a bicycle... somehow it worked"
CHASE: "bro outran a helicopter on foot"
GLITCH: "the car went underground and came back different"
GLITCH: "physics engine had a full breakdown here"
WATER: "the boat launched into the sky and just... stayed"

Output ONLY the hook text. Nothing else."""


# Casual slang patterns for "pure gameplay" mode (matches reference video style)
CASUAL_SLANG_PATTERNS = [
    "ngl {action}",
    "bro really {action}",
    "no way {action}",
    "tell me why {action}",
    "{action} fr fr",
    "wait {action}",
]

CASUAL_FALLBACKS = [
    "ngl this was crazy",
    "bro really did that",
    "no way this happened",
    "wait that actually worked",
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

        # RAG context — retrieve similar HecticSG hooks
        similar = rag.retrieve_similar_hooks(
            visual_description=visual_description,
            timestamp_comments=timestamp_comments
        )
        if similar:
            rag_context = rag.format_rag_context(similar)
            parts.append(rag_context)

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
        profile = config.get_content_profile()
        hook_cfg = profile.get("hook", {})
        max_words = int(hook_cfg.get("max_words", 12))
        prompt_family = hook_cfg.get("prompt_family", "dramatic")
        if prompt_family in {"casual", "reference_casual"}:
            system = CASUAL_RAW_HOOK_PROMPT.format(max_words=max_words)
        else:
            system = RAW_HOOK_PROMPT.format(
                max_words=max_words,
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


def validate_hook(hook: str) -> bool:
    """Validate if the hook meets length rules."""
    try:
        if not hook:
            return False
        clean = hook.strip()
        words = clean.split()
        word_count = len(words)
        if word_count < 3 or word_count > 12:
            print(f"[hook] validation failed: word count is {word_count}")
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
) -> tuple[str, str]:
    """Generate a hook. Falls back to pre-written hooks on failure."""
    context_str = build_context(video_title, visual_description, transcript_context, timestamp_comments)
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            print(f"[hook] attempt {attempt + 1}/{max_attempts}")
            style = _get_style()
            
            # Stage 1: Generate Raw Hook
            hook = generate_raw_hook(context_str, style)
            if not hook:
                continue

            # Validation
            if validate_hook(hook):
                words = hook.split()
                if len(words) > 8:
                    print(f"[hook] hook too long ({len(words)} words) — truncating to 8")
                    hook = " ".join(words[:8])
                print(f"[hook] final: '{hook}' ({len(words)} words)")
                return hook, style['name']
            
            print(f"[hook] invalid hook, retrying... ({attempt+1}/{max_attempts})")

        except Exception as e:
            print(f"[hook] generation attempt {attempt+1} failed: {e}")

    # Fallback if all attempts fail
    fallback_hook = random.choice(FALLBACK_HOOKS)
    print(f"[hook] all generation attempts failed, using fallback: '{fallback_hook}'")
    words = fallback_hook.split()
    if len(words) > 8:
        print(f"[hook] fallback hook too long ({len(words)} words) — truncating to 8")
        fallback_hook = " ".join(words[:8])
    print(f"[hook] final fallback: '{fallback_hook}' ({len(words)} words)")
    return fallback_hook, "fallback"


def generate_casual_caption(visual_description: str) -> str:
    """Generate casual slang caption for pure gameplay mode (no TTS)."""
    try:
        action = visual_description.lower()

        # Extract action verb from description
        if "jump" in action or "leap" in action or "fall" in action:
            action_verb = "jumped"
        elif "crash" in action or "hit" in action or "collide" in action:
            action_verb = "crashed"
        elif "flip" in action or "spin" in action or "rotate" in action:
            action_verb = "flipped"
        elif "explode" in action or "blow" in action:
            action_verb = "exploded"
        elif "fly" in action or "flew" in action:
            action_verb = "flew"
        elif "land" in action:
            action_verb = "landed"
        elif "survive" in action:
            action_verb = "survived"
        else:
            action_verb = "did this"

        # Pick random casual pattern
        pattern = random.choice(CASUAL_SLANG_PATTERNS)
        caption = pattern.format(action=action_verb)

        print(f"[hook] casual caption generated: {caption}")
        return caption
    except Exception as e:
        print(f"[hook] casual caption error: {e}")
        return random.choice(CASUAL_FALLBACKS)


def generate_viral_title(video_title: str, visual_description: str, hook_text: str) -> str:
    """Generate a viral, high-CTR title using Groq."""
    try:
        context_str = f"Source Video Title: {video_title}\nVisual Description: {visual_description}\nTTS Hook: {hook_text}"
        title = _call_groq(VIRAL_TITLE_PROMPT.format(visual_description=visual_description, hook_text=hook_text), context_str)
        if title:
            # Clean up the output to make sure there are no quotes or trailing dots
            title = title.strip().strip('"').strip("'").strip(".")
            # Strip competitor name/channel reference from title as a precaution
            blacklist_names = ["prestige clips", "prestige", "red arcade", "hazardous", "whatever57010", "darkviperau", "darkviper", "call me kevin", "kevin"]
            title_lower = title.lower()
            for name in blacklist_names:
                if name in title_lower:
                    title = re.sub(re.escape(name), "", title, flags=re.IGNORECASE).strip()
            print(f"[hook] generated viral title: {title}")
            return title
        return random.choice(FALLBACK_TITLES)
    except Exception as e:
        print(f"[hook] error generating title: {e}")
        return random.choice(FALLBACK_TITLES)


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
