"""
pipeline.py -- the full NYCH -> MG8 pipeline, built to the canon spec:

    USER -> natural-language input -> NYCH encoder (deterministic, the
    nych package) -> .gst pretext -> FIRST LLM CALL (chunk/compress the
    findings, render Gestalt symbol matches with consonant skeletons
    embedded, create the .g8son files) -> .ork script ordering the .g8son
    files -> MG8 engine compiles and runs the .mg8 unit in one call ->
    output handed to the next LLM as .mg8 PLUS .gitson (canon bundle).

Division of labor, per spec:

- The nych package does everything deterministic and emits the .gst
  pretext (nych.gst_export.build_gst).
- The first LLM call is given that pretext and returns a PLAN: the
  Gestalt mappings and the .g8son gate files (each .g8son is a bounded
  repeat loop with its own exit conditions, 1-3 gates per file).
- This module validates the plan against the canon rules (it does not
  trust the LLM to have followed them), assembles the unit directory
  (.gst / .g8son / .ork / .mg8), runs it through the existing engine
  (core.run_mg8 -> ork.execute_ork) in one call, and writes the output
  .mg8 plus the .gitson canon bundle.

Rules enforced on the LLM plan (violations raise PipelineError):

    1. mappings may only cover words the pretext listed in needs_mapping;
    2. every mapping's symbol id must embed that word's consonant
       skeleton (the disambiguation clue);
    3. the four modality operators are never remapped;
    4. words already pinned #temp-invariant keep their existing mapping;
    5. protected terms -- scientific names, names of people, prescription
       drug names -- are NEVER Gestalt-mapped; they stay literal;
    6. each .g8son file holds 1-3 gates and every gate declares an exit
       condition; the .ork flow may only reference declared gates.

The accepted mappings are recorded in the unit's QSON ledger (the
consonant-embedded id strings are the audit trail) and returned so the
caller can pin them into its nych SessionInvariants store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .core import run_mg8
from .gitson import make_block, split_canon_bundle, write_parts
from .models import Mg8Unit, QsonEntry

LLMCallback = Callable[[str], Any]

# Default platform size limit for .gitson parts. Configurable per call --
# an external constraint, never a semantic property of the format.
DEFAULT_GITSON_MAX_BYTES = 900_000


class PipelineError(ValueError):
    """Raised when an LLM plan violates the canon rules."""


# ---------------------------------------------------------------------------
# First LLM call: prompt + plan validation
# ---------------------------------------------------------------------------

def build_mapping_prompt(gst_payload: Dict[str, Any]) -> str:
    """Build the first-LLM-call prompt from a nych .gst pretext payload."""
    pretext = gst_payload.get("nych_pretext", {})
    return f"""
You are the discretionary Gestalt-mapping step of the NYCH pipeline. All
deterministic extraction is already done and is given below as pretext.
Follow every rule exactly; the engine validates your output and rejects
violations.

RULES:
{json.dumps(pretext.get("discretion_rules", []), ensure_ascii=False, indent=2)}

PRUNING (perform the inverse-transform narrowing with dither as instructed):
{json.dumps(pretext.get("pruning", {}), ensure_ascii=False, indent=2)}

DETERMINISTIC FINDINGS:
state: {json.dumps(gst_payload.get("state", {}), ensure_ascii=False)}
analysis: {json.dumps(pretext.get("analysis", {}), ensure_ascii=False)}
tote_match: {json.dumps(pretext.get("tote_match"), ensure_ascii=False)}
modality_operators (INVARIANT, never remap): {json.dumps(pretext.get("modality_operators", {}), ensure_ascii=False)}
already pinned #temp-invariant (reuse, never re-decide): {json.dumps(pretext.get("pinned", []), ensure_ascii=False)}
PROTECTED TERMS (never Gestalt-mapped, keep literal): {json.dumps(pretext.get("protected", []), ensure_ascii=False)}

WORDS NEEDING A GESTALT MAPPING (embed each word's skeleton in your id):
{json.dumps(pretext.get("needs_mapping", []), ensure_ascii=False, indent=2)}

Return ONLY one valid JSON object:
{{
  "mappings": [{{"word": ..., "symbol_id": ..., "glyph": ...}}],
  "g8son_files": [{{"file_id": ..., "gates": [1-3 gate objects, each a
      bounded repeat loop with an exit condition: "id", "type",
      "condition" or "conditions", "outcomes"]}}],
  "flow": ["gate ids in execution order"]
}}
""".strip()


def _gate_has_exit(gate: Dict[str, Any]) -> bool:
    return bool(gate.get("outcomes") or gate.get("condition")
                or gate.get("conditions") or gate.get("then"))


def validate_plan(plan: Dict[str, Any], gst_payload: Dict[str, Any]) -> None:
    """Enforce the canon rules on a first-LLM-call plan. Raises
    PipelineError with the specific violation; never repairs silently."""
    pretext = gst_payload.get("nych_pretext", {})
    needs = {d["word"].lower(): d for d in pretext.get("needs_mapping", [])}
    protected = {p["word"].strip(".,;:").lower()
                 for p in pretext.get("protected", [])}
    operators = pretext.get("modality_operators", {})
    operator_words = set(operators) | set(operators.values())
    pinned = {p["word"].lower(): p["symbol_id"]
              for p in pretext.get("pinned", [])}

    for m in plan.get("mappings", []):
        word = m.get("word", "")
        key = word.lower()
        if key in protected or word in protected:
            raise PipelineError(
                f"protected term {word!r} was Gestalt-mapped; scientific "
                "names, names of people, and prescription drug names are "
                "never rendered into Gestalt"
            )
        if word in operator_words or key in operators:
            raise PipelineError(
                f"modality operator {word!r} is invariant and was remapped")
        if key in pinned:
            if m.get("symbol_id") != pinned[key]:
                raise PipelineError(
                    f"{word!r} is pinned #temp-invariant to "
                    f"{pinned[key]!r}; plan tried {m.get('symbol_id')!r}")
            continue
        if key not in needs:
            raise PipelineError(
                f"mapping for {word!r} which the pretext did not request")
        skeleton = needs[key]["skeleton"] or needs[key]["id"].rsplit(".", 1)[-1]
        if skeleton not in str(m.get("symbol_id", "")):
            raise PipelineError(
                f"mapping for {word!r} does not embed its consonant "
                f"skeleton {skeleton!r} in symbol_id {m.get('symbol_id')!r}")

    files = plan.get("g8son_files", [])
    if not files:
        raise PipelineError("plan contains no .g8son files")
    gate_ids: List[str] = []
    for f in files:
        gates = f.get("gates", [])
        if not 1 <= len(gates) <= 3:
            raise PipelineError(
                f".g8son file {f.get('file_id')!r} has {len(gates)} gates; "
                "each file must hold 1-3")
        for g in gates:
            gid = g.get("id") or g.get("gate_id")
            if not gid:
                raise PipelineError("gate without an id")
            if not _gate_has_exit(g):
                raise PipelineError(
                    f"gate {gid!r} declares no exit condition; every gate "
                    "is a bounded repeat loop with exit conditions")
            gate_ids.append(gid)

    flow = plan.get("flow") or []
    if not flow:
        raise PipelineError("plan contains no .ork flow")
    unknown = [g for g in flow if g not in gate_ids]
    if unknown:
        raise PipelineError(f".ork flow references unknown gate ids: {unknown}")


# ---------------------------------------------------------------------------
# Unit assembly: .gst / .g8son / .ork / .mg8 on disk
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def assemble_unit(gst_payload: Dict[str, Any], plan: Dict[str, Any],
                  out_dir: str | Path, *, unit_id: Optional[str] = None) -> Path:
    """Write the canonical unit directory and return the .mg8 manifest
    path: pretext.gst, gates.N.g8son (one per plan file), flow.ork, and
    unit.mg8 binding them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    unit_id = unit_id or f"nych-unit-{uuid4().hex[:8]}"

    _write_json(out / "pretext.gst", gst_payload)

    gate_refs = []
    for index, f in enumerate(plan["g8son_files"], start=1):
        name = f"gates.{index}.g8son"
        _write_json(out / name, {
            "g8son_version": "1.0",
            "file_id": f.get("file_id") or f"gates.{index}",
            "gates": f["gates"],
        })
        gate_refs.append(name)

    _write_json(out / "flow.ork", {"flow": plan["flow"]})
    _write_json(out / "trace.qson", {"qson_version": "1.0", "entries": []})

    manifest = {
        "mg8_version": "1.0",
        "unit_id": unit_id,
        "entry": "flow.ork",
        "state": ["pretext.gst"],
        "gates": gate_refs,
        "trace": "trace.qson",
        "metadata": {
            "pipeline": "nych-mg8",
            "mappings": plan.get("mappings", []),
            "protected_terms": gst_payload.get("nych_pretext", {}).get("protected", []),
        },
    }
    return _write_json(out / "unit.mg8", manifest)


# ---------------------------------------------------------------------------
# Output handoff: .mg8 + .gitson
# ---------------------------------------------------------------------------

def write_output_handoff(unit: Mg8Unit, out_dir: str | Path, *,
                         bundle_id: Optional[str] = None,
                         canon_blocks: Optional[List[Dict[str, str]]] = None,
                         max_bytes: int = DEFAULT_GITSON_MAX_BYTES) -> Dict[str, Any]:
    """Write the executed unit as output.mg8 (embedded profile, loadable
    by load_mg8) plus the .gitson canon bundle for the receiving LLM."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    output_payload = unit.model_dump(mode="json", by_alias=True,
                                     exclude={"manifest"})
    mg8_path = _write_json(out / "output.mg8", output_payload)

    blocks = canon_blocks if canon_blocks is not None else [make_block(
        "canon.pointer",
        "NYCH + MG8 canon ingestion pointer",
        "https://github.com/nhartman000",
        "This bundle accompanies an .mg8 output. Ingest the referenced "
        "repositories for the complete NYCH and MG8 canon: file formats "
        "(.gst/.g8son/.ork/.qson/.mg8/.gitson), the modality operators, "
        "the Gestalt-mapping rules (consonant-skeleton ids, "
        "#temp-invariant pins, protected terms), and the TOTE loop seeds.",
    )]
    parts = split_canon_bundle(
        blocks,
        bundle_id=bundle_id or f"canon-{uuid4().hex[:8]}",
        max_bytes=max_bytes,
    )
    gitson_paths = write_parts(parts, out, stem="canon")
    return {"mg8": mg8_path, "gitson": gitson_paths}


# ---------------------------------------------------------------------------
# One-call pipeline
# ---------------------------------------------------------------------------

def run_pipeline(gst_payload: Dict[str, Any], mapping_llm: LLMCallback,
                 out_dir: str | Path, *,
                 gate_llm: Optional[LLMCallback] = None,
                 unit_id: Optional[str] = None,
                 canon_blocks: Optional[List[Dict[str, str]]] = None,
                 gitson_max_bytes: int = DEFAULT_GITSON_MAX_BYTES) -> Dict[str, Any]:
    """Run the pipeline from a nych .gst pretext payload to the final
    .mg8 + .gitson handoff.

    `mapping_llm` performs the first LLM call (pruning + Gestalt mapping +
    .g8son creation); `gate_llm` executes individual gates (defaults to
    the engine's dummy PASS callback). Returns the plan, the executed
    unit, the accepted mappings (for the caller to pin #temp-invariant),
    and all output paths."""
    prompt = build_mapping_prompt(gst_payload)
    raw = mapping_llm(prompt)
    plan = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(plan, dict):
        raise PipelineError(f"mapping LLM returned {type(plan).__name__}, "
                            "expected a JSON object")

    validate_plan(plan, gst_payload)

    mg8_path = assemble_unit(gst_payload, plan, out_dir, unit_id=unit_id)
    unit = run_mg8(mg8_path, gate_llm)

    # Audit trail: the accepted consonant-embedded mapping ids go into the
    # QSON ledger as a dedicated mapping event (sequence 0).
    unit.qson.entries.insert(0, QsonEntry(
        trace_id=f"TRJ_{uuid4().hex}",
        run_id=unit.qson.run_id,
        gate_id="nych.gestalt_mapping",
        step=0,
        action="gestalt-mapping",
        llm_prompt=prompt,
        llm_output={"mappings": plan.get("mappings", []),
                    "tag": "#temp-invariant"},
        input_state_id=gst_payload.get("state_id"),
    ))

    handoff = write_output_handoff(unit, out_dir, canon_blocks=canon_blocks,
                                   max_bytes=gitson_max_bytes)
    return {
        "plan": plan,
        "unit": unit,
        "pins": plan.get("mappings", []),
        "paths": {"unit_mg8": mg8_path, **handoff},
    }
