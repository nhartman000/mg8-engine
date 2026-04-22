from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class Gst(BaseModel):
    """Global State & Constraints"""
    state: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[str] = Field(default_factory=list)
    domain: str = "general"  # subjective domain pruning

class G8Gate(BaseModel):
    """Single logic gate — supports ADSR-like + pan/pot style in future"""
    id: str
    type: str  # "condition", "tote_loop", "transform", "modality_check", etc.
    condition: Optional[str] = None
    action: Optional[str] = None
    then: Optional[str] = None  # next gate id or "exit"
    else_: Optional[str] = None = Field(alias="else")
    modality: Optional[str] = None  # e.g. "👀" for visual_external
    intensity: float = 1.0  # ADSR-style "attack/sustain" proxy for reasoning depth

class G8son(BaseModel):
    """Sequence of gates"""
    gates: List[G8Gate] = Field(default_factory=list)

class QsonEntry(BaseModel):
    """Immutable trace entry"""
    trace_id: str
    gate_id: str
    input: Any
    output: Any
    modality: Optional[str] = None
    timestamp: str  # or use datetime

class Qson(BaseModel):
    entries: List[QsonEntry] = Field(default_factory=list)

class Mg8Unit(BaseModel):
    """Main .mg8 container"""
    gst: Gst
    g8son: G8son
    qson: Qson = Field(default_factory=Qson)
    ork_flow: List[str] = Field(default_factory=list)  # sequence of gate ids or special commands
