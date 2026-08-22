from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Gst(BaseModel):
    """GST state/context payload consumed by this reference runtime profile."""

    model_config = ConfigDict(extra="allow")

    gst_version: Optional[str] = None
    state_id: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[Any] = Field(default_factory=list)

    # Canonical state-continuity fields are optional because older examples predate them.
    prior: Any = None
    current: Any = None
    internal: Any = None
    external: Any = None
    intent: Any = None
    outcome_expectation: Any = None

    # Legacy/reference-profile fields retained for compatibility.
    domain: str = "general"
    narrative_tense: str = "present"


class G8Gate(BaseModel):
    """One bounded G8SON gate, with optional ADSR/Nych runtime-profile extensions."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    gate_id: str = Field(alias="id")
    order: Optional[int] = None
    type: str = "condition"
    conditions: List[Any] = Field(default_factory=list)
    outcomes: Dict[str, Any] = Field(default_factory=dict)

    # Earlier runtime-profile fields.
    condition: Optional[str] = None
    action: Optional[str] = None
    then: Optional[str] = None
    else_: Optional[str] = Field(None, alias="else")
    modality: Optional[str] = None

    # ADSR + Pan are extension fields for this engine profile, not the base G8SON standard.
    attack: float = 1.0
    decay: float = 0.8
    sustain: float = 1.0
    release: float = 0.7
    pan: float = 0.0

    @property
    def id(self) -> str:
        """Backward-compatible accessor used by the original executor."""
        return self.gate_id


class G8son(BaseModel):
    """Canonical bounded G8SON file shape: one to three gates."""

    model_config = ConfigDict(extra="allow")

    g8son_version: str = "1.0"
    file_id: Optional[str] = None
    gates: List[G8Gate] = Field(min_length=1, max_length=3)


class QsonEntry(BaseModel):
    """Event-level audit record emitted for one gate execution attempt."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    trace_id: str
    run_id: Optional[str] = None
    file_id: Optional[str] = None
    gate_id: str
    sequence: int = Field(alias="step")
    input_state_id: Optional[str] = None
    output_state_id: Optional[str] = None
    result: Optional[str] = None
    action: Optional[str] = None
    actor: str = "mg8-engine"

    # Reference-profile evidence retained for reproducibility/debugging.
    input_state: Any = None
    llm_prompt: Optional[str] = None
    llm_output: Any = None
    modality: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def step(self) -> int:
        return self.sequence


class Qson(BaseModel):
    model_config = ConfigDict(extra="allow")

    qson_version: str = "1.0"
    run_id: Optional[str] = None
    entries: List[QsonEntry] = Field(default_factory=list)


class Mg8Manifest(BaseModel):
    """Canonical resource-binding .mg8 manifest."""

    model_config = ConfigDict(extra="allow")

    mg8_version: str
    unit_id: str
    entry: str
    state: List[str] = Field(min_length=1)
    gates: List[str] = Field(min_length=1)
    trace: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Mg8Unit(BaseModel):
    """
    In-memory execution unit used by this reference engine.

    The runtime can be populated from the older embedded `.mg8` profile or from a
    canonical resource-binding manifest resolved by `core.load_mg8`.
    """

    model_config = ConfigDict(extra="allow")

    gst: Gst
    g8son: G8son
    qson: Qson = Field(default_factory=Qson)
    ork_flow: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    manifest: Optional[Mg8Manifest] = None
