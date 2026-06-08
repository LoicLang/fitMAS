"""Sport knowledge docs loader for LLM context injection."""

from pathlib import Path

# Map sport names to their knowledge file
_SPORT_FILE_MAP: dict[str, str] = {
    "running": "running.md",
    "trail": "running.md",
    "cycling": "cycling.md",
    "swimming": "swimming.md",
    "strength": "strength.md",
    "climbing": "climbing.md",
}

# Always included as base knowledge
_BASE_FILES = ["recovery.md", "periodization.md"]

_KNOWLEDGE_DIR = Path(__file__).parent


def load_sport_knowledge(sports: set[str], *, max_tokens: int = 1500) -> str:
    """Load and concatenate relevant sport knowledge docs, truncated if needed.

    Args:
        sports: Set of sport names to load knowledge for.
        max_tokens: Approximate max token budget (4 chars per token).

    Returns:
        Concatenated knowledge string, truncated per-file to stay within budget.
    """
    max_chars = max_tokens * 4

    # Collect unique files to load: base + sport-specific
    files_to_load: list[str] = list(_BASE_FILES)
    seen = set(_BASE_FILES)
    for sport in sorted(sports):
        fname = _SPORT_FILE_MAP.get(sport.lower())
        if fname and fname not in seen:
            files_to_load.append(fname)
            seen.add(fname)

    # Read all files
    contents: list[tuple[str, str]] = []
    for fname in files_to_load:
        fpath = _KNOWLEDGE_DIR / fname
        if fpath.exists():
            contents.append((fname, fpath.read_text(encoding="utf-8")))

    if not contents:
        return ""

    # Calculate per-file budget
    n_files = len(contents)
    per_file_chars = max_chars // n_files

    # Concatenate with truncation
    parts: list[str] = []
    total_chars = 0
    for fname, text in contents:
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        budget = min(per_file_chars, remaining)
        truncated = text[:budget]
        # Cut at last newline to avoid mid-line truncation
        if len(truncated) < len(text):
            last_nl = truncated.rfind("\n")
            if last_nl > 0:
                truncated = truncated[:last_nl]
            truncated += "\n[...tronque]\n"
        parts.append(truncated)
        total_chars += len(truncated)

    return "\n".join(parts)
