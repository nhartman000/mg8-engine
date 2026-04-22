"""
Nych Protocol - Symbolic Determinism
Fixed modality operators + emoji gestalt + vowel-stripped metadata + TOTE support
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

def strip_metadata(word: str) -> str:
    """Remove vowels, collapse consecutive identical consonants."""
    if not word:
        return ""
    vowels = set("aeiouAEIOU")
    s = "".join(c.lower() for c in word if c not in vowels)
    result = []
    for c in s:
        if not result or result[-1] != c:
            result.append(c)
    return "".join(result) or word[:4].lower()

def get_modality_name(symbol: str) -> str:
    return MODALITIES.get(symbol, "unknown_modality")

def apply_nych_tokenization(text: str) -> dict:
    """Tokenize text with Nych rules. Returns dict for LLM prompt injection."""
    words = text.split()
    tokens = []
    for word in words:
        meta = strip_metadata(word)
        # In real use, replace with LLM call for best emoji gestalt
        emoji = "❓"  # TODO: LLM gestalt selector
        tokens.append(f"{emoji}{meta}")
    return {
        "original": text,
        "nych_tokens": " ".join(tokens),
        "modalities_used": [k for k in MODALITIES if k in text]
    }
