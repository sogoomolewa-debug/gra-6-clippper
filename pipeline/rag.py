# NOTE ON FUNCTION OVERLAP:
# The retrieval function `retrieve_similar_hooks()` is shared between:
# 1. Phrasing retrieval (hook.py -> format_rag_context())
# 2. Viral scoring (score_viral_potential() -> internally calls retrieval)
# Modifying phrasing context formatting does NOT risk re-breaking the 
# moment_type override bug, because the Gemini override logic lives safely 
# inside score_viral_potential() operating on raw retrieval scores.

import json
import numpy
import pathlib
import os

from sentence_transformers import SentenceTransformer

HOOKS_PATH = pathlib.Path("data/reference_hooks.json")
EMBEDDINGS_PATH = pathlib.Path("data/reference_hooks_embeddings.npy")
INDEX_PATH = pathlib.Path("data/reference_hooks_index.json")

# Module-level cache — load once per pipeline run
_library = None
_embeddings = None
_index = None
_model = None


def _load_rag_assets() -> bool:
    """Load library, embeddings and index into module cache."""
    global _library, _embeddings, _index, _model
    try:
        if not HOOKS_PATH.exists() or not EMBEDDINGS_PATH.exists():
            print("[rag] reference assets not found — RAG disabled")
            return False

        _library = json.loads(HOOKS_PATH.read_text())
        _embeddings = numpy.load(str(EMBEDDINGS_PATH))
        _index = json.loads(INDEX_PATH.read_text())
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print(f"[rag] loaded {len(_index)} reference entries")
        return True
    except Exception as e:
        print(f"[rag] load error: {e} — RAG disabled for this run")
        return False


def build_query_text(
    visual_description: str,
    timestamp_comments: list[dict],
    clip_type_hint: str = ""
) -> str:
    """
    Build query text that matches the embedding space.
    Must use same psychological framing as build_retrieval_text().
    """
    parts = []

    if visual_description:
        parts.append(f"outcome: {visual_description}")

    if timestamp_comments:
        top_comment = sorted(
            timestamp_comments,
            key=lambda c: c.get("like_count", 0),
            reverse=True
        )
        if top_comment:
            parts.append(f"question: {top_comment[0]['text']}")

    if clip_type_hint:
        parts.append(f"moment: {clip_type_hint}")

    return " | ".join(parts)


def retrieve_similar_hooks(
    visual_description: str,
    timestamp_comments: list[dict] = [],
    clip_type_hint: str = "",
    top_k: int = 5
) -> list[dict]:
    """
    Main retrieval function. Called by hook.py at generation time.
    Returns top_k most similar reference entries ranked by cosine similarity.
    Returns empty list if RAG assets unavailable.
    """
    global _library, _embeddings, _index, _model

    if _library is None:
        if not _load_rag_assets():
            return []

    try:
        query_text = build_query_text(
            visual_description, timestamp_comments, clip_type_hint
        )
        query_embedding = _model.encode([query_text])

        # Cosine similarity
        norms_ref = numpy.linalg.norm(_embeddings, axis=1, keepdims=True)
        norms_q = numpy.linalg.norm(query_embedding, axis=1, keepdims=True)
        similarities = numpy.dot(
            _embeddings / (norms_ref + 1e-10),
            (query_embedding / (norms_q + 1e-10)).T
        ).flatten()

        top_indices = numpy.argsort(similarities)[::-1][:top_k]

        # Build entry map from library
        entry_map = {e["video_id"]: e for e in _library.get("entries", [])}

        results = []
        for idx in top_indices:
            if idx >= len(_index):
                continue
            video_id = _index[idx]["video_id"]
            entry = entry_map.get(video_id)
            if entry:
                results.append({
                    "similarity": round(float(similarities[idx]), 3),
                    "entry": entry
                })

        print(f"[rag] retrieved {len(results)} similar entries")
        for r in results[:3]:
            print(f"[rag]   sim={r['similarity']:.3f} | {r['entry'].get('title','')[:50]}")

        return results

    except Exception as e:
        print(f"[rag] retrieval error: {e}")
        return []


def score_viral_potential(
    visual_description: str,
    timestamp_comments: list[dict] = [],
    moment_type: str = "",
    viral_score_from_gemini: int = 0,
    min_similarity_threshold: float = 0.28
) -> dict:
    """
    Score a GTA clip's viral potential against the HecticSG reference library.

    Uses the same embedding space as retrieve_similar_hooks() but returns
    a structured verdict instead of entries for Groq context.

    CALIBRATION NOTE: all-MiniLM-L6-v2 produces a baseline similarity of
    ~0.40-0.50 for any pair of gaming-related descriptions regardless of
    viral quality.  The scoring formula accounts for this by:
      - Using a hard threshold of 0.28 (lowered from 0.45 to accept novel clips)
      - Weighting trigger scores by how much similarity EXCEEDS baseline
      - Penalising only genuinely mundane moment_types; character_interaction
        penalty is conditional on Gemini's viral score
      - Allowing Gemini high-confidence scores (8+) to override RAG rejections

    Returns:
        {
            "score": float (0-10),
            "verdict": "approve" | "reject" | "uncertain",
            "reason": str,
            "top_similarity": float,
            "matched_triggers": list[str],
            "rejection_detail": str
        }

    Verdicts:
        approve   → score >= 7.4 AND top_similarity >= threshold
        uncertain → score 4.0-7.3 OR similarity borderline (proceed with caution)
        reject    → score < 4.0 OR top_similarity < threshold (no viral pattern match)
    """
    global _library, _embeddings, _index, _model

    # Load RAG assets if not already loaded
    if _library is None:
        if not _load_rag_assets():
            # RAG unavailable — fail open, don't block pipeline
            return {
                "score": 5.0,
                "verdict": "uncertain",
                "reason": "RAG library unavailable — proceeding without viral filter",
                "top_similarity": 0.0,
                "matched_triggers": [],
                "rejection_detail": ""
            }

    try:
        # Retrieve similar entries using full psychological query
        similar = retrieve_similar_hooks(
            visual_description=visual_description,
            timestamp_comments=timestamp_comments,
            clip_type_hint=moment_type,
            top_k=5
        )

        if not similar:
            return {
                "score": 3.0,
                "verdict": "reject",
                "reason": "no similar entries found in reference library",
                "top_similarity": 0.0,
                "matched_triggers": [],
                "rejection_detail": "visual description matches no known viral moment type"
            }

        # --- SIGNAL 1: Similarity to reference library ---
        top_similarity = similar[0]["similarity"]
        avg_similarity = sum(r["similarity"] for r in similar) / len(similar)

        # Hard threshold — but Gemini high-confidence overrides it
        if top_similarity < min_similarity_threshold:
            if viral_score_from_gemini >= 8:
                print(f"[rag] ⚠️ Similarity {top_similarity:.3f} below {min_similarity_threshold} "
                      f"threshold but Gemini scored {viral_score_from_gemini}/10 — continuing")
            else:
                return {
                    "score": 2.0,
                    "verdict": "reject",
                    "reason": f"moment matches no known viral pattern (best similarity: {top_similarity:.3f})",
                    "top_similarity": top_similarity,
                    "matched_triggers": [],
                    "rejection_detail": (
                        f"Visual description: '{visual_description[:100]}'. "
                        f"No HecticSG reference entry matched above {min_similarity_threshold} threshold. "
                        f"This moment likely has no strong psychological trigger."
                    )
                }

        # --- SIGNAL 2: Moment type penalty ---
        # ONLY penalise genuinely mundane types.
        # Do NOT penalise types that describe physics outcomes.
        MUNDANE_TYPES = {"ordinary_interaction", "mundane_gameplay"}
        PHYSICS_TYPES = {
            "ragdoll", "impossible_survival", "physics_glitch",
            "impossible_height", "chain_reaction", "npc_behavior",
            "stunt_fail", "stunt_success", "speed_impact", "collision"
        }

        moment_penalty = 0.0
        if moment_type in MUNDANE_TYPES:
            moment_penalty = -2.0
            print(f"[rag] moment_type penalty: -2.0 ({moment_type} — mundane)")
        elif moment_type in PHYSICS_TYPES:
            moment_penalty = 0.5  # Small boost for confirmed physics moments
            print(f"[rag] moment_type boost: +0.5 ({moment_type} — physics outcome)")
        elif moment_type == "character_interaction":
            # Ambiguous — only penalise if Gemini also scored it low
            if viral_score_from_gemini < 6:
                moment_penalty = -1.0
                print(f"[rag] moment_type penalty: -1.0 (character_interaction + low Gemini score)")
            else:
                print(f"[rag] moment_type: no penalty (character_interaction but Gemini={viral_score_from_gemini}/10)")

        # --- SIGNAL 3: Psychological trigger quality ---
        # Weight triggers by how much similarity EXCEEDS baseline (0.40)
        # This ensures only genuinely close matches contribute trigger points
        BASELINE_SIMILARITY = 0.40
        STRONG_TRIGGERS = {
            "cognitive_dissonance": 2.0,
            "impossibility": 2.0,
            "absurdity": 1.8,
            "awe": 1.5,
            "horror": 1.5,
            "surprise": 1.3,
            "humor": 1.2,
            "schadenfreude": 1.0,
            "anticipation": 0.8,
            "satisfaction": 0.6
        }

        matched_triggers = []
        trigger_score = 0.0
        for r in similar:
            # Only count triggers from entries that are meaningfully similar
            excess_similarity = max(0.0, r["similarity"] - BASELINE_SIMILARITY)
            if excess_similarity < 0.05:
                continue  # Too close to baseline — triggers are noise

            psych = r["entry"].get("psychology", {})
            primary = psych.get("primary_trigger", "")
            secondary = psych.get("secondary_trigger", "")
            if primary and primary not in matched_triggers:
                matched_triggers.append(primary)
                trigger_score += STRONG_TRIGGERS.get(primary, 0.5) * excess_similarity
            if secondary and secondary != "none" and secondary not in matched_triggers:
                matched_triggers.append(secondary)
                trigger_score += STRONG_TRIGGERS.get(secondary, 0.3) * excess_similarity * 0.5

        # Normalize trigger score to 0-4 range
        # excess_similarity maxes around 0.3, so trigger_score raw tops ~1.5
        trigger_score_normalized = min(4.0, trigger_score * 4)

        # --- SIGNAL 4: Reference clippability quality ---
        clippability_scores = [
            r["entry"].get("clippability", {}).get("score", 5)
            for r in similar
        ]
        avg_clippability = sum(clippability_scores) / len(clippability_scores)
        # Normalize to 0-3 range
        clippability_normalized = (avg_clippability / 10.0) * 3.0

        # --- SIGNAL 5: Similarity excess weight ---
        # 0-3 points based on how far above baseline the top match is
        similarity_excess = max(0.0, top_similarity - BASELINE_SIMILARITY)
        similarity_score = min(3.0, similarity_excess * 15)

        # --- COMPOSITE SCORE ---
        score = round(
            trigger_score_normalized +
            clippability_normalized +
            similarity_score +
            moment_penalty,
            1
        )
        score = min(10.0, max(0.0, score))

        # --- VERDICT ---
        if score >= 7.4 and top_similarity >= min_similarity_threshold:
            verdict = "approve"
            reason = (
                f"strong viral pattern match (score: {score}/10, "
                f"similarity: {top_similarity:.3f}, "
                f"trigger: {matched_triggers[0] if matched_triggers else 'unknown'})"
            )
            rejection_detail = ""

        elif score >= 4.0:
            verdict = "uncertain"
            reason = (
                f"weak viral match — proceeding cautiously "
                f"(score: {score}/10, similarity: {top_similarity:.3f})"
            )
            rejection_detail = ""

        else:
            verdict = "reject"
            best_match_title = similar[0]["entry"].get("title", "unknown") if similar else "none"
            reason = (
                f"low viral potential (score: {score}/10). "
                f"Best reference match: '{best_match_title[:50]}' "
                f"(similarity: {top_similarity:.3f})"
            )
            rejection_detail = (
                f"Visual description: '{visual_description[:100]}'. "
                f"Matched triggers: {matched_triggers}. "
                f"Moment type: {moment_type}. "
                f"This moment lacks the cognitive_dissonance, impossibility, or "
                f"absurdity trigger that makes clips worth rewatching. "
                f"Common causes: expected gameplay behavior, ordinary character "
                f"interactions, mundane physics without impossible outcomes."
            )

        # ── GEMINI HIGH CONFIDENCE OVERRIDE ──────────────────────────
        # If Gemini watched the actual clip and scored it 8+ viral,
        # RAG cannot fully reject — maximum downgrade is "uncertain".
        # Hierarchy: Gemini saw the clip. RAG matches patterns blindly.
        # A 9/10 Gemini score on a ragdoll freefall should never be blocked
        # by pattern similarity scores.

        if verdict == "reject" and viral_score_from_gemini >= 8:
            old_reason = reason
            verdict = "uncertain"
            reason = (
                f"RAG pattern match weak (RAG score: {score:.1f}/10) but "
                f"Gemini scored this clip {viral_score_from_gemini}/10 viral — "
                f"proceeding with caution. RAG reason was: {old_reason}"
            )
            print(f"[rag] ⚠️ Gemini override: viral_score={viral_score_from_gemini} "
                  f"prevents RAG reject → downgraded to uncertain")

        # Also apply Gemini boost to uncertain when Gemini is very confident
        if verdict == "uncertain" and viral_score_from_gemini >= 9:
            verdict = "approve"
            reason = (
                f"Gemini scored {viral_score_from_gemini}/10 — overriding uncertain "
                f"to approve (RAG score was {score:.1f}/10)"
            )
            print(f"[rag] ✅ Gemini 9+/10 upgrades uncertain → approve")

        # ── END OVERRIDE ──────────────────────────────────────────────

        print(f"[rag] viral_potential: {score}/10 | verdict: {verdict}")
        print(f"[rag] triggers matched: {matched_triggers[:3]}")
        print(f"[rag] top similarity: {top_similarity:.3f} (excess: {similarity_excess:.3f})")
        # moment_type penalty already logged in SIGNAL 2 block above

        return {
            "score": score,
            "verdict": verdict,
            "reason": reason,
            "top_similarity": top_similarity,
            "matched_triggers": matched_triggers,
            "rejection_detail": rejection_detail
        }

    except Exception as e:
        print(f"[rag] viral_potential scoring error: {e}")
        # Fail open — don't block pipeline on scoring errors
        return {
            "score": 5.0,
            "verdict": "uncertain",
            "reason": f"scoring error: {e}",
            "top_similarity": 0.0,
            "matched_triggers": [],
            "rejection_detail": ""
        }




def format_rag_context(similar_entries: list[dict]) -> str:
    """
    Format retrieved entries into Groq context string.
    Passes full depth — not just hook text, but WHY each worked.
    This is what makes the RAG system qualitatively different
    from using example hooks.
    """
    if not similar_entries:
        return ""

    context_parts = [
        "REFERENCE HOOKS FROM SIMILAR VIRAL MOMENTS:",
        "",
        "IMPORTANT: This channel has NO face on screen and NO prior brand ",
        "trust — unlike the creator below who has 5M+ views of audience ",
        "trust built up. Do NOT mirror his vague or cryptic phrasing — ",
        "that vagueness only works because of his on-screen personality ",
        "and trust, which this channel does not have yet.",
        "",
        "Extract ONLY the CONTRAST STRUCTURE from each reference — what ",
        "baseline expectation versus what suggested outcome creates the ",
        "question. Apply that same contrast structure but write it with ",
        "MORE explicit clarity than the reference uses, since the words ",
        "must do all the work here with no face or trust to lean on.",
        ""
    ]

    for i, item in enumerate(similar_entries, 1):
        entry = item["entry"]
        hook = entry.get("hook", {})
        delivery = entry.get("delivery", {})
        psych = entry.get("psychology", {})
        clip = entry.get("clippability", {})
        visual = entry.get("visual", {})

        context_parts.append(f"REFERENCE {i} (similarity: {item['similarity']:.2f})")
        context_parts.append(f"Game: {visual.get('game', 'unknown')}")
        context_parts.append(f"Moment: {visual.get('moment_type','unknown')} — {visual.get('moment_outcome','')}")
        context_parts.append(f"His hook: \"{hook.get('text', '')}\"")
        context_parts.append(f"Hook pattern: {hook.get('hook_pattern', '')}")
        context_parts.append(f"Why incomplete: {hook.get('why_incomplete', '')}")
        context_parts.append(f"Delivery: {delivery.get('tone','')} | {delivery.get('energy_level','')} | intonation ends {delivery.get('intonation_final_word','')}")
        context_parts.append(f"Psychological trigger: {psych.get('primary_trigger','')}")
        context_parts.append(f"Viewer question created: {psych.get('viewer_question_created','')}")
        context_parts.append(f"Why it loops: {psych.get('loop_mechanism','')}")
        context_parts.append(f"GTA equivalent: {clip.get('gta_equivalent_moment','')}")
        context_parts.append(f"GTA hook translation: {clip.get('gta_hook_translation','')}")
        context_parts.append("")

    context_parts.append(
        "Now write a hook for the current GTA VI clip that applies these "
        "same psychological patterns — same incompleteness, same trigger, "
        "same delivery energy. Adapt to GTA VI context, do not copy."
    )

    return "\n".join(context_parts)
