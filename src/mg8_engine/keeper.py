"""
keeper.py -- gated deterministic LLM querying with verbatim-reproducibility
verification (the "mgate-keeper" mechanism, hardened).

Origin: the mgate-keeper prototype demonstrated that a .gst interpretation
context plus .g8son gates of atomic requirements, flattened into a system
prompt and sent at temperature 0, produced character-identical responses
across separate API calls. Examination showed the determinism came from
the *constraint narrowing itself* -- the gates squeeze the admissible
answer space to effectively one rendering -- not from sampler seeding (the
prototype's two calls did not even have identical prompts, yet matched).

This implementation keeps that mechanism and fixes the prototype's three
measurement weaknesses:

    1. Requests are bit-identical across repeat calls: the prompt is built
       deterministically (stable ordering, no timestamps, no cache-buster).
       A reproducibility claim over non-identical requests is weaker
       evidence; we don't make it.
    2. The provider's `system_fingerprint` (model backend build) is
       recorded per call in the QSON audit. Verbatim match across calls on
       DIFFERENT fingerprints is stronger evidence of constraint-driven
       determinism; a match on the same fingerprint cannot distinguish
       constraint narrowing from backend stability. Both are disclosed.
    3. The repeat/exit loop is executed and verified in engine code, not
       handed to the LLM as a prose instruction it may or may not follow.

Transport stays a caller-supplied callback (same boundary as the rest of
this engine -- no vendored OpenAI dependency). The callback receives a
request dict {"messages", "temperature", "seed"} and must return either a
plain string or a dict {"content", "response_id", "system_fingerprint"}.

Honesty bar: `verify_reproducibility` reports exactly what happened --
deterministic or not, fingerprints seen, which calls diverged. A
divergence is a disclosed result, never retried away silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .models import G8Gate, Gst, Qson, QsonEntry

LLMTransport = Callable[[Dict[str, Any]], Any]

DEFAULT_SEED = 42
DEFAULT_TEMPERATURE = 0.0


# ---------------------------------------------------------------------------
# Compatibility: requirement-profile .g8son / context-profile .gst
# ---------------------------------------------------------------------------

def load_requirement_g8son(path: str | Path) -> List[G8Gate]:
    """Load a .g8son file in either the canonical profile (gates array /
    gate_id) or the mgate-keeper requirement profile (gate_id, gate_name,
    atomic_requirements). Requirement gates map onto canonical G8Gate as
    type="requirement" with the requirement texts as `conditions`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    dicts = payload.get("gates") if isinstance(payload.get("gates"), list) \
        else [payload]
    gates = []
    for d in dicts:
        if "atomic_requirements" in d:
            gates.append(G8Gate(
                id=d["gate_id"],
                type="requirement",
                conditions=[r["requirement"] for r in d["atomic_requirements"]],
                outcomes={"PASS": "exit", "FAIL": "repeat"},
                gate_name=d.get("gate_name"),
            ))
        else:
            gates.append(G8Gate.model_validate(d))
    return gates


def load_context_gst(path: str | Path) -> Gst:
    """Load a .gst file; the mgate-keeper context profile
    (interpretation_posture / primary_modality / constraints) rides on the
    canonical Gst model's extra="allow"."""
    return Gst.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8-sig")))


# ---------------------------------------------------------------------------
# Deterministic gated prompt
# ---------------------------------------------------------------------------

def build_gated_prompt(gst: Gst, gates: List[G8Gate], user_prompt: str) -> List[Dict[str, str]]:
    """Build the exact message list for a gated query. Deterministic by
    construction: stable field order, declared gate order, no timestamps,
    no cache-busting -- two builds from the same inputs are identical."""
    extra = gst.model_extra or {}
    lines = ["You are a controlled LLM operating under strict gates and "
             "context. Satisfy every gate requirement exactly."]
    posture = extra.get("interpretation_posture")
    modality = extra.get("primary_modality")
    if posture:
        lines.append(f"Posture: {posture}")
    if modality:
        lines.append(f"Modality: {modality}")
    if gst.domain and gst.domain != "general":
        lines.append(f"Domain: {gst.domain}")
    constraints = gst.constraints if isinstance(gst.constraints, list) else []
    if constraints:
        lines.append("Constraints:")
        lines.extend(f"- {c}" for c in constraints)
    if gates:
        lines.append("Gates to satisfy:")
        for gate in gates:
            name = (gate.model_extra or {}).get("gate_name") or gate.type
            lines.append(f"Gate {gate.gate_id} ({name}):")
            for req in gate.conditions:
                lines.append(f"- {req}")
            if gate.condition:
                lines.append(f"- {gate.condition}")
    system = "\n".join(lines)
    return [{"role": "system", "content": system},
            {"role": "user", "content": user_prompt}]


def _normalize_response(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        return {"content": raw, "response_id": None, "system_fingerprint": None}
    if isinstance(raw, dict):
        return {"content": raw.get("content"),
                "response_id": raw.get("response_id"),
                "system_fingerprint": raw.get("system_fingerprint")}
    raise TypeError(
        f"LLM transport returned {type(raw).__name__}; expected str or dict "
        "with 'content'/'response_id'/'system_fingerprint'")


# ---------------------------------------------------------------------------
# Keeper
# ---------------------------------------------------------------------------

class GateKeeper:
    """Gated deterministic querying with engine-verified reproducibility."""

    def __init__(self, gst: Gst, gates: List[G8Gate], *,
                 seed: int = DEFAULT_SEED,
                 temperature: float = DEFAULT_TEMPERATURE) -> None:
        self.gst = gst
        self.gates = gates
        self.seed = seed
        self.temperature = temperature

    @classmethod
    def from_project(cls, project_file: str | Path) -> "GateKeeper":
        """Load an mgate-keeper-style .mg8 project file (project profile:
        g8son_gates / gst_context / model / seed). Paths resolve relative
        to the project file's directory, falling back to as-written paths
        for compatibility with the prototype's cwd-relative layout."""
        project_path = Path(project_file)
        project = json.loads(project_path.read_text(encoding="utf-8-sig"))

        def resolve(ref: str) -> Path:
            candidate = project_path.parent / ref
            return candidate if candidate.is_file() else Path(ref)

        gates: List[G8Gate] = []
        for ref in project.get("g8son_gates", []):
            gates.extend(load_requirement_g8son(resolve(ref)))
        gst = load_context_gst(resolve(project["gst_context"])) \
            if project.get("gst_context") else Gst()
        keeper = cls(gst, gates, seed=project.get("seed", DEFAULT_SEED))
        keeper.project = project
        return keeper

    def request(self, user_prompt: str) -> Dict[str, Any]:
        """The exact, reproducible request payload for one gated query."""
        return {
            "messages": build_gated_prompt(self.gst, self.gates, user_prompt),
            "temperature": self.temperature,
            "seed": self.seed,
        }

    def query(self, user_prompt: str, transport: LLMTransport) -> Dict[str, Any]:
        return _normalize_response(transport(self.request(user_prompt)))

    def verify_reproducibility(self, user_prompt: str, transport: LLMTransport,
                               *, runs: int = 2,
                               qson: Optional[Qson] = None) -> Dict[str, Any]:
        """Send the IDENTICAL request `runs` times and verify verbatim
        equality in engine code.

        Returns a disclosed result record:
            deterministic          -- all contents character-identical
            contents / responses   -- everything observed, nothing dropped
            fingerprints           -- distinct system_fingerprints seen
            fingerprint_consistent -- all calls on one backend build (None
                                      when the transport reports none)
            evidence               -- honest strength assessment: a match
                                      across differing fingerprints is
                                      constraint-driven; a match on one
                                      fingerprint can't rule out backend
                                      stability as the cause.
        Divergence is reported, never silently retried."""
        if runs < 2:
            raise ValueError("reproducibility requires at least 2 runs")
        request = self.request(user_prompt)
        qson = qson if qson is not None else Qson()
        if not qson.run_id:
            qson.run_id = f"RUN_{uuid4().hex}"

        responses = []
        for call_number in range(1, runs + 1):
            resp = _normalize_response(transport(request))
            responses.append(resp)
            qson.entries.append(QsonEntry(
                trace_id=f"TRJ_{uuid4().hex}",
                run_id=qson.run_id,
                gate_id="keeper.reproducibility",
                step=call_number,
                action="gated-query",
                result=None,
                llm_prompt=request["messages"][0]["content"],
                llm_output=resp,
                input_state=({"user_prompt": user_prompt, "seed": self.seed,
                              "temperature": self.temperature}
                             if call_number == 1 else None),
                system_fingerprint=resp["system_fingerprint"],
            ))

        contents = [r["content"] for r in responses]
        deterministic = all(c == contents[0] for c in contents[1:])
        prints = [r["system_fingerprint"] for r in responses]
        known = [p for p in prints if p]
        fingerprint_consistent = (len(set(known)) == 1) if known else None

        if not deterministic:
            evidence = "divergent: responses differ under identical requests"
        elif fingerprint_consistent is False:
            evidence = ("strong: verbatim match across different backend "
                        "fingerprints -- constraint-driven determinism")
        elif fingerprint_consistent is True:
            evidence = ("moderate: verbatim match on a single backend "
                        "fingerprint -- cannot separate constraint "
                        "narrowing from backend stability")
        else:
            evidence = ("weak: verbatim match but transport reported no "
                        "system_fingerprint; backend build unknown")

        for entry in qson.entries[-runs:]:
            entry.result = "PASS" if deterministic else "FAIL"

        return {
            "deterministic": deterministic,
            "runs": runs,
            "contents": contents,
            "responses": responses,
            "fingerprints": sorted(set(known)),
            "fingerprint_consistent": fingerprint_consistent,
            "evidence": evidence,
            "request": request,
            "qson": qson,
        }
