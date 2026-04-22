from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class Gst(BaseModel):
    """Global State & Constraints"""
    state: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[str] = Field(default_factory=list)
    domain: str = "general"
    narrative_tense: str = "present"


class G8Gate(BaseModel):
    """Core gate with ADSR + Pan as primary control mechanism"""
    id: str
    type: str = "condition"                    # tote_test, tote_operate, transform, etc.
    condition: Optional[str] = None
    action: Optional[str] = None
    then: Optional[str] = None
    else_: Optional[str] = Field(None, alias="else")

    # Nych modality
    modality: Optional[str] = None             # 👀, 👏👏, 🧠🗯️, etc.

    # ADSR Gating - the primary expressive mechanism
    attack: float = 1.0      # Initial reasoning intensity
    decay: float = 0.8       # Drop from peak
    sustain: float = 1.0     # Steady reasoning depth (most important)
    release: float = 0.7     # Exit speed

    # Pan for internal vs external weighting
    pan: float = 0.0         # -1.0 = internal, +1.0 = external


class G8son(BaseModel):
    """Collection of gates"""
    gates: List[G8Gate] = Field(default_factory=list)


class QsonEntry(BaseModel):
    """Immutable trace entry"""
    trace_id: str
    gate_id: str
    step: int
    input_state: Any
    llm_prompt: str
    llm_output: Any
    modality: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Qson(BaseModel):
    entries: List[QsonEntry] = Field(default_factory=list)


class Mg8Unit(BaseModel):
    """Main MG8 container - kept minimal and extensible"""
    gst: Gst
    g8son: G8son
    qson: Qson = Field(default_factory=Qson)
    ork_flow: List[str] = Field(default_factory=list)   # sequence of gate ids
    metadata: Dict[str, Any] = Field(default_factory=dict)