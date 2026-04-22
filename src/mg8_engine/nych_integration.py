"""
Nych Protocol - Symbolic Determinism
Supports future sensor modalities (haptic, optical, etc.)
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
    # Future sensor analogs
    "🔴": "optical_sensor",
    "📳": "haptic_sensor",
    "🌡️": "thermal_sensor",
}

def strip_metadata(word: str) -> str:
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
    """Nych tokenization - ready for sensor data translation"""
    import re
    words = re.findall(r'\w+', str(text).lower())
    tokens = []
    
    for word in words:
        meta = strip_metadata(word)
        gestalt_map = {
            "nail": "📌",
            "hammer": "🔨",
            "swing": "🔨",
            "test": "🔬",
            "operate": "⚙️",
            "status": "📊",
            "transformed": "✅",
            "object": "📦",
            "done": "✔️",
            "not_done": "❌"
        }
        emoji = gestalt_map.get(word, "❓")
        tokens.append(f"{emoji}{meta}")
    
    return {
        "original": text,
        "nych_tokens": " ".join(tokens),
        "modalities_used": [k for k in MODALITIES if k in text]
    }