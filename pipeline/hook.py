# pipeline/hook.py — Generate a punchy hook with delivery markup for natural TTS
import os
import random
import re
import json
from typing import List, Dict, Optional

from google import genai
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

SYSTEM_PROMPT = """You write viral YouTube Shorts hooks for a GTA gaming channel.
Your hooks are spoken aloud as a voiceover over a flash-forward + blurred backdrop (duration 3-5 seconds, 6-14 words).

CRITICAL RULE — THE HOOK MUST NEVER DESCRIBE THE VISUAL:
The visual already shows what is happening. If your hook just names or
describes the scene, it adds ZERO value and viewers swipe away.

BAD (description — these get REJECTED):
- "off the dirt ramp" (just names the location)
- "Spider-Man just went off the edge" (describes what's already visible)
- "car launches into the air" (describes what's already visible)
- "crazy stunt right here" (vague label, no question)
- "watch this moment" (filler, no contrast)

GOOD (contrast/question — this is what you must write):
- "he is actually gonna make it" (implies expected failure, questions outcome)
- "there's no way he survives this" (implies expected death, creates suspense)
- "nobody thought this would work" (implies expected failure, questions reality)
- "this shouldn't even be possible" (implies expected impossibility, questions physics)

THE FORMULA — CONTRAST:
Every hook must imply [baseline expectation] vs [suggested alternative outcome] (duration 3-5 seconds, 6-14 words).
This creates a question in the viewer's mind they MUST stay to resolve.

Two types, both valid:
1. STATED — you say both sides explicitly, setting up the baseline expectation and the contrasting outcome: "most drivers would've crashed here but he somehow doesn't"
2. IMPLIED — you only state the alternative, where the baseline expectation is assumed known: "he actually survives this even though his car is completely crushed"

Before finalizing, ask: "Does this pose a QUESTION about an uncertain
outcome, or does it just describe what's on screen?" If it describes
the scene — REWRITE IT.

RULES:
- 6 to 14 words maximum (to fill the 3-5 seconds hook duration)
- Write for SPOKEN delivery — lowercase preferred
- NEVER end with a period — em dash or nothing
- The hook must feel INCOMPLETE — listener hasn't heard the full thought
- No emojis, no hashtags, no exclamation marks
- Active verbs, present tense, direct and simple language (6th grade level)
- Use 'he', 'this', 'it' — NOT vague filler like 'guys' or 'so'

IMPORTANT — THIS CHANNEL HAS NO BRAND TRUST YET:
Unlike established creators, this channel has no face on screen and no
prior audience trust. Vague or cryptic hooks that rely on creator
personality to work will NOT work here. Your hook words must carry ALL
the curiosity on their own — be MORE explicit about the contrast than a
trusted creator would need to be. Clarity over cleverness.

EXAMPLE HOOKS BY MOMENT TYPE (study the CONTRAST PATTERN, not the words):

Stunts/landings:
- "most drivers would've crashed here but he somehow doesn't" (stated)
- "he is actually gonna make it even with that flat tire" (implied)
- "any other car would've exploded but he sticks the landing" (stated)
- "nobody expected him to survive this vertical fall down the mountain" (implied)

Physics/glitches:
- "the game should've crashed here but it actually does the impossible" (stated)
- "gta physics says this shouldn't even be possible but it happens" (stated)
- "nobody can explain how he didn't crash into that wall" (implied)
- "this car doesn't follow normal physics and it makes no sense" (implied)

Ragdoll/impacts:
- "this impact should've killed him but he gets right back up" (stated)
- "he actually survives this crash even though his bike is destroyed" (implied)
- "watch how he does the impossible and escapes the explosion" (implied)
- "most players would've died here but he barely even takes damage" (stated)

OUTPUT FORMAT — RESPOND WITH ONLY VALID JSON, NOTHING ELSE:
{"hook_text": "...", "emphasis_word": "...", "contrast_type": "implied|stated"}

Where emphasis_word is the single word from hook_text that carries the
stakes/outcome meaning — the word that will get distinct visual
emphasis on screen beyond the standard word-by-word caption highlight.
Pick it yourself based on which word is doing the contrast work in the
hook you just wrote. Do not include any text outside the JSON object."""

FALLBACK_HOOKS = [
    {"hook_text": "most drivers would've crashed here but he somehow doesn't", "emphasis_word": "doesn't"},
    {"hook_text": "any other car would've exploded but this one lands perfectly", "emphasis_word": "perfectly"},
    {"hook_text": "this stunt should've failed instantly but he actually makes it", "emphasis_word": "actually"},
    {"hook_text": "most players would've died here but he barely even scratches it", "emphasis_word": "scratches"},
    {"hook_text": "the game should've crashed here but it does the impossible instead", "emphasis_word": "impossible"},
    {"hook_text": "this impact should've killed him but he gets right back up", "emphasis_word": "gets"},
    {"hook_text": "normally this car would spin out but it doesn't even slip", "emphasis_word": "doesn't"},
]

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


def _call_gemini(system_prompt: str, user_prompt: str, is_json: bool = False) -> Optional[str]:
    """Make a single Gemini Flash API call."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("[hook] error: GEMINI_API_KEY not set")
            return None

        client = genai.Client(api_key=api_key)
        
        # Configure model
        generation_config = genai.types.GenerateContentConfig(
            temperature=0.9,
            system_instruction=system_prompt,
            response_mime_type="application/json" if is_json else "text/plain"
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_prompt,
            config=generation_config
        )
        return response.text.strip()
    except Exception as e:
        print(f"[hook] Gemini API error: {e}")
        return None


def generate_raw_hook(context_str: str, style: dict) -> dict:
    """Stage 1: Generate a raw conversational hook using contrast structure."""
    try:
        hook_mode = config.HOOK_MODE
        if hook_mode == "legacy":
            # Use the old logic but call Gemini
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
            raw = _call_gemini(system, context_str + "\n\nWrite the hook.", is_json=False)
            if raw:
                # Clean up any wrapping quotes
                raw = raw.strip('"').strip("'")
                print(f"[hook] stage 1 legacy raw ({style['name']}): {raw}")
                return {"hook_text": raw, "emphasis_word": "", "contrast_type": "legacy"}
            return {}

        # Contrast mode (JSON output)
        raw = _call_gemini(SYSTEM_PROMPT, context_str + "\n\nWrite the hook.", is_json=True)
        if raw:
            try:
                # Strip backticks if Gemini added markdown formatting
                if raw.startswith("```json"):
                    raw = raw[7:-3].strip()
                elif raw.startswith("```"):
                    raw = raw[3:-3].strip()
                data = json.loads(raw)
                print(f"[hook] stage 1 contrast structured: {data}")
                return data
            except json.JSONDecodeError:
                print(f"[hook] JSON parse error on output: {raw}")
                # Fallback to treating it as raw text
                return {"hook_text": raw.strip('"').strip("'"), "emphasis_word": "", "contrast_type": "parse_fail"}
        return {}
    except Exception as e:
        print(f"[hook] raw generation error: {e}")
        return {}


def validate_hook(hook: str) -> bool:
    """
    Validate if the hook meets length and structural rules.
    Note: This is a backstop, not the primary guarantee of quality — the 
    real check is the few-shot prompt plus the scoring loop.
    """
    try:
        if not hook:
            return False
        clean = hook.strip()
        words = clean.split()
        word_count = len(words)
        
        # Word count check
        if word_count < 4 or word_count > 16:
            print(f"[hook] validation failed: word count is {word_count}")
            return False
            
        # Punctuation check
        if hook.strip().endswith("?"):
            print("[hook] validation failed: ends with a question mark")
            return False
            
        # Description-only regex patterns
        DESCRIPTION_ONLY_PATTERNS = [
            r'^(off|on|at|in|from|near) (the|a) ',
            r'^(this is|that was) (a |an )?(crazy|cool|wild|insane)',
            r'^(watch this|check this|look at this)$',
            r'^[A-Za-z-]+ (just )?(went|goes|jumps|launches|drives|flies|falls) ',
        ]
        
        for pattern in DESCRIPTION_ONLY_PATTERNS:
            if re.search(pattern, clean, re.IGNORECASE):
                print(f"[hook] validation failed: matched description-only pattern '{pattern}'")
                return False
                
        # Contrast / Uncertainty marker audit
        contrast_markers = {"actually", "shouldn't", "no way", "somehow", "barely", 
                            "survives", "broke", "never", "still", "wouldn't", "nobody",
                            "would've", "should've", "does", "doesn't"}
        has_contrast = any(marker in clean.lower() for marker in contrast_markers)
        if not has_contrast:
            # Log as likely-descriptive, but don't hard-reject
            print(f"[hook] WARNING: likely-descriptive (no explicit contrast markers found in '{clean}')")
            
        return True
    except Exception as e:
        print(f"[hook] validation error: {e}")
        return False


def score_hook_quality(hook_text: str, context: str) -> float:
    """
    Sends the generated hook + context to Gemini 2.5 Flash with a scoring rubric.
    Returns a float score 0-10.
    """
    rubric = """Score this YouTube Shorts hook from 0.0 to 10.0 based on these criteria:
1. Does it pose a contrast/question rather than describe the visual? (Description-only gets <4)
2. Is it clear at a 6th-grade reading level?
3. Is it free of vague filler phrases?
4. Is it concise (6-14 words)?
5. Does it carry the curiosity on its own without relying on established creator trust?

Output valid JSON only: {"score": float, "reasoning": "string"}
"""
    user_msg = f"Context:\n{context}\n\nHook to score:\n{hook_text}"
    
    try:
        raw = _call_gemini(rubric, user_msg, is_json=True)
        if not raw:
            return 0.0
            
        if raw.startswith("```json"):
            raw = raw[7:-3].strip()
        elif raw.startswith("```"):
            raw = raw[3:-3].strip()
            
        data = json.loads(raw)
        score = float(data.get("score", 0.0))
        print(f"[hook] quality score: {score} ({data.get('reasoning', '')})")
        return score
    except Exception as e:
        print(f"[hook] scoring error: {e}")
        return 0.0


def get_hook_with_fallback(
    video_title: str,
    visual_description: str = "",
    transcript_context: str = "",
    timestamp_comments: List[Dict] = []
) -> dict:
    """Generate a hook with a scoring loop, falling back to pre-written hooks on total failure."""
    context_str = build_context(video_title, visual_description, transcript_context, timestamp_comments)
    max_attempts = 5
    quality_threshold = 8.0
    
    best_attempt = None
    best_score = -1.0
    
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[hook] generation attempt {attempt}/{max_attempts}")
            style = _get_style()
            
            # Stage 1: Generate Hook Data
            hook_data = generate_raw_hook(context_str, style)
            if not hook_data or "hook_text" not in hook_data:
                continue

            hook_text = hook_data["hook_text"]
            
            # Validation
            if not validate_hook(hook_text):
                print(f"[hook] attempt {attempt} failed structural validation")
                continue
                
            # Score Quality
            score = score_hook_quality(hook_text, context_str)
            
            # Keep track of best
            if score > best_score:
                best_score = score
                best_attempt = {
                    "hook_text": hook_text,
                    "emphasis_word": hook_data.get("emphasis_word", ""),
                    "contrast_type": hook_data.get("contrast_type", "unknown"),
                    "hook_mode": config.HOOK_MODE,
                    "quality_score": score,
                    "score_attempts": attempt
                }
            
            # Early exit if good enough
            if score >= quality_threshold:
                print(f"[hook] attempt {attempt} cleared threshold ({score} >= {quality_threshold})")
                return best_attempt
                
        except Exception as e:
            print(f"[hook] attempt {attempt} failed: {e}")

    # If we got at least one valid hook but didn't clear the threshold, use the best one
    if best_attempt is not None:
        print(f"[hook] max attempts reached, using best scoring attempt ({best_score}/10): '{best_attempt['hook_text']}'")
        best_attempt["score_attempts"] = max_attempts
        return best_attempt

    # Total failure (API errors, etc)
    fallback = random.choice(FALLBACK_HOOKS)
    print(f"[hook] all attempts failed, using fallback: '{fallback['hook_text']}'")
    return {
        "hook_text": fallback["hook_text"],
        "emphasis_word": fallback["emphasis_word"],
        "contrast_type": "fallback",
        "hook_mode": config.HOOK_MODE,
        "quality_score": 0.0,
        "score_attempts": max_attempts
    }


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
    """Generate a viral, high-CTR title using Gemini."""
    try:
        context_str = f"Source Video Title: {video_title}\nVisual Description: {visual_description}\nTTS Hook: {hook_text}"
        title = _call_gemini(VIRAL_TITLE_PROMPT, context_str, is_json=False)
        if title:
            # Clean up the output
            title = title.strip().strip('"').strip("'").strip(".")
            # Strip competitor name/channel reference from title
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
    print(f"\nFinal hook payload: {json.dumps(result, indent=2)}")
