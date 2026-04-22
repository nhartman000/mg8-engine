"""
Nych Symbolic Protocol
Minimal, reusable symbolic determinism layer.
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
    """Remove vowels and collapse double consonants."""
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
    """Convert text to Nych symbolic tokens."""
    import re
    words = re.findall(r'\w+', str(text).lower())
    tokens = []
    
    gestalt_map = {
        "nail": "📌", "hammer": "🔨", "swing": "🔨",
        "test": "🔬", "operate": "⚙️", "status": "📊",
        "transformed": "✅", "object": "📦", "done": "✔️",
        "not_done": "❌"
    }
    
    for word in words:
        meta = strip_metadata(word)
        emoji = gestalt_map.get(word, "❓")
        tokens.append(f"{emoji}{meta}")
    
    return {
        "original": text,
        "nych_tokens": " ".join(tokens),
        "modalities_used": [k for k in MODALITIES if k in text]
    }