import json
import numpy
import pathlib
import os

from sentence_transformers import SentenceTransformer

HOOKS_PATH = pathlib.Path("data/reference_hooks.json")
EMBEDDINGS_PATH = pathlib.Path("data/reference_hooks_embeddings.npy")
INDEX_PATH = pathlib.Path("data/reference_hooks_index.json")


def build_retrieval_text(entry: dict) -> str:
    """
    Build the text that gets embedded for each entry.
    This determines what similarity search actually matches on.
    Combines psychological triggers, moment type, hook pattern
    and GTA equivalence — NOT the actual words of the hook.
    Matching on psychology not vocabulary.
    """
    parts = []

    # Psychological core
    psych = entry.get("psychology", {})
    if psych.get("primary_trigger"):
        parts.append(f"trigger: {psych['primary_trigger']}")
    if psych.get("secondary_trigger") and psych["secondary_trigger"] != "none":
        parts.append(f"secondary: {psych['secondary_trigger']}")
    if psych.get("viewer_question_created"):
        parts.append(f"question: {psych['viewer_question_created']}")
    if psych.get("why_viewer_replays"):
        parts.append(f"loop: {psych['why_viewer_replays']}")

    # Visual moment
    visual = entry.get("visual", {})
    if visual.get("moment_type"):
        parts.append(f"moment: {visual['moment_type']}")
    if visual.get("moment_outcome"):
        parts.append(f"outcome: {visual['moment_outcome']}")

    # Hook pattern
    hook = entry.get("hook", {})
    if hook.get("hook_pattern"):
        parts.append(f"pattern: {hook['hook_pattern']}")

    # GTA equivalence — critical for cross-game retrieval
    clip = entry.get("clippability", {})
    if clip.get("gta_equivalent_moment"):
        parts.append(f"gta_equiv: {clip['gta_equivalent_moment']}")

    # RAG tags
    tags = entry.get("rag_retrieval_tags", [])
    if tags:
        parts.append(f"tags: {' '.join(tags)}")

    return " | ".join(parts)


def build_embeddings() -> None:
    """Load library, encode all entries, save embeddings and index."""
    if not HOOKS_PATH.exists():
        print("[embeddings] reference_hooks.json not found — run scraper first")
        return

    library = json.loads(HOOKS_PATH.read_text())
    entries = library.get("entries", [])
    # Only embed clippable entries
    clippable = [e for e in entries if e.get("status") == "clippable"]
    print(f"[embeddings] encoding {len(clippable)} clippable entries")

    print("[embeddings] loading sentence-transformers model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    texts = [build_retrieval_text(e) for e in clippable]
    print("[embeddings] generating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True)

    numpy.save(str(EMBEDDINGS_PATH), embeddings)

    # Save index mapping embedding position → entry video_id
    index = [{"position": i, "video_id": e["video_id"]} for i, e in enumerate(clippable)]
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"[embeddings] saved {len(clippable)} embeddings → {EMBEDDINGS_PATH}")
    print(f"[embeddings] saved index → {INDEX_PATH}")


if __name__ == "__main__":
    build_embeddings()
