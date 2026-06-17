# pipeline/clip_validator.py — Validates Gemini visual description for vagueness and matches comments
import os
import re
import json
import groq
from typing import List, Dict

# Specificity scoring keywords (lowercase matches)
ACTION_VERBS = {
    "crash", "crashed", "crashing", "crashes",
    "launch", "launched", "launching", "launches",
    "explode", "exploded", "exploding", "explodes",
    "fly", "flew", "flying", "flies",
    "flip", "flipped", "flipping", "flips",
    "land", "landed", "landing", "lands",
    "fall", "fell", "falling", "falls",
    "eject", "ejected", "ejecting", "ejects",
    "ram", "rammed", "ramming", "rams",
    "catapult", "catapulted", "catapulting", "catapults",
    "ragdoll", "ragdolled", "ragdolling", "ragdolls",
    "collide", "collided", "colliding", "collides",
    "jump", "jumped", "jumping", "jumps",
    "hit", "hits", "hitting",
    "bump", "bumped", "bumping", "bumps",
    "bounce", "bouncing", "bounced", "bounces",
    "destroy", "destroyed", "destroying", "destroys",
    "shoot", "shot", "shooting", "shoots",
    "stunt", "stunted", "stunting", "stunts",
    "chase", "chased", "chasing", "chases",
    "run", "runs", "running",
    "knock", "knocks", "knocked", "knocking",
}

SPECIFIC_OBJECTS = {
    "car", "vehicle", "auto", "helicopter", "chopper", "motorcycle", "bike",
    "truck", "pedestrian", "npc", "person", "man", "woman", "guy", "cop", "police",
    "boat", "train", "bus", "tank", "plane", "airplane", "skyscraper", "building",
    "cliff", "bridge", "ramp", "water", "river", "ocean", "highway", "street",
    "suv", "character", "player", "bumper", "ground",
}

PHYSICS_WORDS = {
    "midair", "skyward", "orbit", "spin", "spinning", "roll", "rolling",
    "airborne", "upside", "vertical", "horizontal", "velocity", "speed",
    "fast", "slow", "height", "high", "distance", "far", "crazy", "weird", "glitch",
    "bug", "broken", "physics", "gravity", "antigravity",
}

GENERIC_PHRASES = [
    r"\bplayer plays\b",
    r"\bgameplay footage\b",
    r"\bscene from gta\b",
    r"\bsomething happens\b",
    r"\bgta gameplay\b",
    r"\bgrand theft auto\b",
    r"\bvideo game\b",
    r"\bclip shows\b",
    r"\bfootage of\b",
]


def check_vagueness(description: str) -> dict:
    """
    Stage 1: Checks if the description is too vague to be useful for generating a hook.
    Returns: {"is_vague": bool, "score": int, "reasoning": str}
    """
    try:
        desc_lower = description.lower()
        score = 0
        matched_actions = []
        matched_objects = []
        matched_physics = []
        matched_directions = []
        
        # Tokenize by word
        words = re.findall(r"\b[a-z']+\b", desc_lower)
        
        # Action Verbs check (+2 each)
        for w in words:
            if w in ACTION_VERBS:
                score += 2
                matched_actions.append(w)
                
        # Specific Objects check (+1 each)
        for w in words:
            if w in SPECIFIC_OBJECTS:
                score += 1
                matched_objects.append(w)
                
        # Physics Words check (+2 each)
        for w in words:
            if w in PHYSICS_WORDS:
                score += 2
                matched_physics.append(w)
                
        # Numbers and direction words (+1 each)
        directions = {"up", "down", "left", "right", "forward", "backward", "north", "south", "east", "west", "top", "bottom"}
        for w in words:
            if w.isdigit() or w in directions:
                score += 1
                matched_directions.append(w)

        # Check for generic penalty phrases (-3 each)
        penalties = 0
        matched_penalties = []
        for pattern in GENERIC_PHRASES:
            matches = re.findall(pattern, desc_lower)
            if matches:
                penalties += 3 * len(matches)
                matched_penalties.append(pattern)
                
        score -= penalties
        
        is_vague = score < 3
        reasoning = (
            f"Score: {score} (Actions: {matched_actions}, Objects: {matched_objects}, "
            f"Physics: {matched_physics}, Directions/Numbers: {matched_directions}, Penalties: {matched_penalties})"
        )
        return {
            "is_vague": is_vague,
            "score": score,
            "reasoning": reasoning
        }
    except Exception as e:
        print(f"[clip_validator] Error in check_vagueness: {e}")
        # Fail open
        return {"is_vague": False, "score": 99, "reasoning": f"exception: {e}"}


def validate_vs_comments(description: str, timestamp_comments: List[Dict]) -> dict:
    """
    Stage 2: Cross-validates Gemini description against top comments using Groq.
    Returns: {"is_match": bool, "confidence": float, "reasoning": str}
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            print("[clip_validator] Warning: GROQ_API_KEY not set. Skipping validation.")
            return {"is_match": True, "confidence": 1.0, "reasoning": "GROQ_API_KEY not set"}

        # Format top comments (limit to 5)
        top_comments = sorted(
            timestamp_comments,
            key=lambda c: c.get("like_count", 0),
            reverse=True
        )[:5]
        
        formatted_comments = ""
        for i, c in enumerate(top_comments):
            text = c.get("text", "").strip()
            likes = c.get("like_count", 0)
            formatted_comments += f"{i+1}. \"{text}\" ({likes} likes)\n"

        system_prompt = (
            "You are a video content reviewer comparing an AI's visual analysis to real viewer "
            "comments about the SAME moment in a GTA gameplay clip."
        )

        user_prompt = (
            "Decide if the AI's visual description matches what real viewers are describing in their comments.\n\n"
            f"AI's description of what happens:\n\"{description}\"\n\n"
            f"Real viewers said this about the same moment:\n{formatted_comments}\n"
            "Criteria:\n"
            "- They must describe the SAME core event (same crash, same launch, same kill, same stunt, etc.).\n"
            "- Minor detail differences are acceptable (e.g. 'car' vs 'vehicle', or slightly different verbs).\n"
            "- If the AI describes a completely different action than what the comments describe, that is a MISMATCH.\n"
            "- If comments are vague reactions (e.g., 'lol', '💀', 'bruh') without describing a specific event or physical action, "
            "you cannot reliably judge. In that case, set confidence to 0.3.\n\n"
            "Respond ONLY with a JSON object in this format:\n"
            "{\n"
            "  \"is_match\": bool,\n"
            "  \"confidence\": float (0.0 to 1.0),\n"
            "  \"reasoning\": \"one sentence explanation\"\n"
            "}"
        )

        client = groq.Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=120,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        content = response.choices[0].message.content.strip()
        result = json.loads(content)
        
        print(f"[clip_validator] Groq match result: {result}")
        return {
            "is_match": bool(result.get("is_match", True)),
            "confidence": float(result.get("confidence", 1.0)),
            "reasoning": str(result.get("reasoning", ""))
        }
        
    except Exception as e:
        print(f"[clip_validator] Error in validate_vs_comments: {e}")
        # Fail open on API / parsing errors
        return {"is_match": True, "confidence": 1.0, "reasoning": f"exception: {e}"}


def validate_clip(description: str, timestamp_comments: List[Dict] = None) -> dict:
    """
    Orchestrates the two stages of validation.
    Returns: {"valid": bool, "reason": str, "detail": str}
    """
    if timestamp_comments is None:
        timestamp_comments = []

    print(f"[clip_validator] validating description: \"{description}\"")

    # Stage 1: check vagueness
    vagueness = check_vagueness(description)
    if vagueness["is_vague"]:
        print(f"[clip_validator] ❌ Rejected: Vague description. Score {vagueness['score']}. Detail: {vagueness['reasoning']}")
        return {
            "valid": False,
            "reason": "vague_description",
            "detail": f"Score: {vagueness['score']}. {vagueness['reasoning']}"
        }

    # Stage 2: check comments if available
    if not timestamp_comments:
        return {"valid": True, "skipped_comment_check": True}

    match_result = validate_vs_comments(description, timestamp_comments)
    if not match_result["is_match"] and match_result["confidence"] >= 0.6:
        print(f"[clip_validator] ❌ Rejected: Description mismatch. Confidence: {match_result['confidence']}. Reason: {match_result['reasoning']}")
        return {
            "valid": False,
            "reason": "description_mismatch",
            "detail": f"Confidence: {match_result['confidence']}. Reason: {match_result['reasoning']}"
        }

    print("[clip_validator] ✅ Passed validation")
    return {"valid": True}


if __name__ == "__main__":
    # Test cases for Stage 1 (Vagueness)
    print("--- Testing Stage 1 ---")
    test_vague = [
        "A car drives down a road.",
        "GTA gameplay footage showing a player.",
        "A player walking around the city in grand theft auto.",
        "A motorcycle stunt where a player jumps over a helicopter midair.",
        "A pedestrian is hit by a reversing car and launched skyward."
    ]
    for text in test_vague:
        res = check_vagueness(text)
        print(f"Text: \"{text}\"\n -> Vague: {res['is_vague']} (Score: {res['score']})\n")

    # Test cases for Stage 2 (Comments check)
    print("--- Testing Stage 2 ---")
    mock_comments = [
        {"text": "holy shit he flew into orbit 💀💀", "like_count": 120},
        {"text": "the way the car hit him and sent him to space was hilarious", "like_count": 80},
        {"text": "ragdoll physics in this game are undefeated", "like_count": 50}
    ]
    
    desc_match = "A pedestrian gets hit by a reversing car and launched skyward very fast."
    desc_specific_mismatch = "A player flying a military jet shoots down a police helicopter."
    desc_vague_mismatch = "A player enters a garage and modifies a sports car with new rims."
    desc_neutral = "A car drives on the highway."

    print(f"Desc (Match): \"{desc_match}\"")
    print(validate_clip(desc_match, mock_comments))

    print(f"\nDesc (Specific Mismatch): \"{desc_specific_mismatch}\"")
    print(validate_clip(desc_specific_mismatch, mock_comments))

    print(f"\nDesc (Vague Mismatch): \"{desc_vague_mismatch}\"")
    print(validate_clip(desc_vague_mismatch, mock_comments))
    
    print(f"\nDesc (Neutral/Vague): \"{desc_neutral}\"")
    print(validate_clip(desc_neutral, mock_comments))

    # Test vague comments (should fail open/pass with low confidence)
    vague_comments = [
        {"text": "💀💀💀", "like_count": 120},
        {"text": "lmaoooo bro", "like_count": 80}
    ]
    print(f"\nDesc (With Vague Comments): \"{desc_specific_mismatch}\"")
    print(validate_clip(desc_specific_mismatch, vague_comments))

