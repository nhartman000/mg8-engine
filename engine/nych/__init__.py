"""
Nych Protocol - Symbolic Determinism with Modality Operators + Emoji Gestalt
"""

MODALITIES = {
    "👁️": "visual_internal",
    "👀": "visual_external",
    "👂": "auditory_internal",
    "👂👂": "auditory_external",
    "👏": "kinesthetic_internal",
    "👏👏": "kinesthetic_external",
    "🧠💭": "mental_memory",
    "🧠🗯️": "mental_imagine",
}

# Fixed modality operators (you can expand)
MODALITY_LIST = list(MODALITIES.keys())

def strip_to_metadata(word: str) -> str:
    """Remove vowels, collapse double consonants, keep consonants only."""
    vowels = "aeiouAEIOU"
    s = "".join(c for c in word.lower() if c not in vowels)
    # collapse double consonants
    result = ""
    for c in s:
        if not result or result[-1] != c:
            result += c
    return result or word[:3]  # fallback

def gestalt_emoji(word: str) -> str:
    """
    Placeholder: In real use, call LLM here with strict prompt to pick closest emoji gestalt.
    For now, simple mapping or return a default.
    """
    simple_map = {
        "football": "🏈",
        "nail": "📌",
        "hammer": "🔨",
        "swing": "🔨",
        "test": "🔬",
        "operate": "⚙️",
        "exit": "🚪",
    }
    return simple_map.get(word.lower(), "❓")  # TODO: LLM call for rich gestalt
