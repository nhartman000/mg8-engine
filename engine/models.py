from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class Gst(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[str] = Field(default_factory=list)
    domain: str = "general"
    narrative_tense: str = "present"   # for LLM prompting

class G8Gate(BaseModel):
    id: str
    type: str = "condition"   # tote_test, tote_operate, transform, modality_check, adsr_gate
    condition: Optional[str] = None
    action: Optional[str] = None
    then: Optional[str] = None
    else_: Optional[str] = Field(None, alias="else")
    modality: Optional[str] = None          # e.g. "👀"
    intensity: float = 1.0                  # ADSR proxy (0.0-2.0) — controls reasoning depth
    pan: float = 0.0                        # -1.0 left (internal) to +1.0 right (external)
    sustain: float = 1.0                    # how long to hold reasoning in this gate

class G8son(BaseModel):
    gates: List[G8Gate] = Field(default_factory=list)

class QsonEntry(BaseModel):
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
    gst: Gst
    g8son: G8son
    qson: Qson = Field(default_factory=Qson)
    ork_flow: List[str] = Field(default_factory=list)  # list of gate ids or special cmds like "tote_loop"
    metadata: Dict[str, Any] = Field(default_factory=dict)
