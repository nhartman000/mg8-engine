"""
pipeline.py -- the full NYCH -> MG8 pipeline, built to the canon spec in
nych.bonit (steps 1-2, in the `nych` repo) and mg8.bonit (step 3, this
repo):

    USER -> natural-language input -> NYCH encoder (deterministic, the
    nych package) -> .gst pretext -> FIRST LLM CALL (Gestalt mapping
    ONLY -- nych.bonit STEP 2: ASSIGN_GESTALTS/WRITE_GST) -> SECOND LLM
    CALL (mg8.bonit STEP 3: congruence assessment, then -- only if
    congruent -- authoring exactly three .g8son files) -> the three
    files sequenced via .ork and executed in order -> output handed to
    the next LLM as .mg8 PLUS .gitson (canon bundle).

Division of labor, per spec:

- The nych package does everything deterministic and emits the .gst
  pretext (nych.gst_export.build_gst).
- The FIRST LLM call is given that pretext and returns ONLY Gestalt
  mappings for the requested words. It does not create any .g8son file
  and is not asked to -- that used to be true of this module (see the
  v1 note at the bottom of this file) and no longer is.
- The SECOND LLM call is given the accepted mappings plus the .gst
  pretext and must first return a congruence assessment
  (PASS/FAIL/INTERMEDIATE, per mg8.bonit's STATUS_CANON) before it may
  author anything. Only on PASS does it return exactly three .g8son
  files (each a bounded 1-3-gate file, every gate with its own exit
  condition) plus the .ork flow ordering their gates.
- This module validates both calls' output against the canon rules (it
  does not trust the LLM to have followed them either time), assembles
  the unit directory (.gst / .g8son x3 / .ork / .mg8) only when the
  congruence assessment passed, runs it through the existing engine
  (core.run_mg8 -> ork.execute_ork) in one call -- which executes the
  three files' gates in the .ork flow's declared order, i.e. file 1's
  gates, then file 2's, then file 3's -- and writes the output .mg8
  plus the .gitson canon bundle.

Rules enforced on the first-call (mapping) plan (violations raise
PipelineError):

    1. mappings may only cover words the pretext listed in needs_mapping;
    2. every mapping's symbol id must embed that word's consonant
       skeleton (the disambiguation clue);
    3. the four modality operators are never remapped, and no other word
       may be given an operator's glyph (in glyph or symbol_id);
    4. words already pinned #temp-invariant keep their existing mapping;
    5. protected terms -- scientific names, names of people, prescription
       drug names -- are NEVER Gestalt-mapped; they stay literal.

Rules enforced on the second-call (congruence) response, per mg8.bonit
(violations raise PipelineError; a legitimate non-PASS result raises the
narrower CongruenceNotPass instead -- see below):

    6. congruence_result must be one of PASS / FAIL / INTERMEDIATE (the
       STATUS_CANON this file's VALUES declare -- never a bare UNKNOWN or
       UNRESOLVED, those are the legacy vocabularies mg8.bonit's
       STATUS_CANON maps onto this one, not alternate spellings of it);
    7. no .g8son file may be present unless congruence_result == "PASS"
       (mg8.bonit: REJECT IF G8SON_AUTHORED_WHEN_CONGRUENCE_RESULT_NOT_PASS);
    8. on PASS, there must be exactly three .g8son files
       (REJECT IF G8SON_FILE_COUNT_NOT_EQUAL_THREE);
    9. each file holds 1-3 gates and every gate declares an exit
       condition; the .ork flow may only reference declared gates
       (same bounds as the first-call plan used to carry).

The accepted mappings are recorded in the unit's QSON ledger (the
consonant-embedded id strings are the audit trail), the congruence
assessment is recorded as its own QSON entry, and the mappings are
returned so the caller can pin them into its nych SessionInvariants
store.
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

# mg8.bonit STATUS_CANON: the one gate-result/assessment-result vocabulary
# for this pipeline. UNKNOWN (legacy NYCH MGate) and UNRESOLVED (.ork bound
# exhaustion) are not alternate values here -- they map onto this vocabulary
# (UNKNOWN -> INTERMEDIATE, UNRESOLVED -> FAIL) rather than being accepted
# as additional literals a response could return.
CONGRUENCE_RESULTS = {"PASS", "FAIL", "INTERMEDIATE"}

# Required file count for step 3's .g8son authoring, per mg8.bonit's RULES
# (g8son_file_count = 3 IF congruence_result == "PASS").
REQUIRED_G8SON_FILE_COUNT = 3


class PipelineError(ValueError):
    """Raised when an LLM plan or response violates the canon rules."""


class CongruenceNotPass(PipelineError):
    """Raised when the second-call congruence assessment legitimately
    returns FAIL or INTERMEDIATE rather than PASS.

    This is not a canon violation by itself -- the LLM did nothing wrong
    by reporting that the handoff wasn't congruent, or that it couldn't
    yet tell. mg8.bonit's RULES make this the normal way gate-authoring
    gets skipped (`g8son_authored = false IF congruence_result != "PASS"`)
    and its VALIDATION separately flags `REVISE IF
    CONGRUENCE_RESULT_INTERMEDIATE`: callers can check `.result` to tell
    a hard FAIL from an INTERMEDIATE worth retrying with more context,
    rather than treating both as the same dead end.
    """

    def __init__(self, result: str, assessment: Dict[str, Any]) -> None:
        self.result = result
        self.assessment = assessment
        super().__init__(
            f"congruence assessment returned {result!r}; no .g8son "
            "authored (mg8.bonit RULES: g8son_authored = false IF "
            "congruence_result != \"PASS\")"
        )


# The four canonical modality operators (mirrors nych.session_invariants
# and T.O.T.E-loops' modality_operators table).
CANON_MODALITY_OPERATORS = {
    "external_observe": "👀",
    "internal_model": "👁️🧠",
    "operative_intent": "🗯️",
    "execute": "💪",
}


def _bare_glyph(s: str) -> str:
    """Strip emoji variation selectors so "🗯" and "🗯️" compare equal."""
    return s.replace("️", "").replace("︎", "")


# ---------------------------------------------------------------------------
# First LLM call (nych.bonit STEP 2): Gestalt mapping only
# ---------------------------------------------------------------------------

def build_mapping_prompt(gst_payload: Dict[str, Any]) -> str:
    """Build the first-LLM-call prompt from a nych .gst pretext payload.

    This call does Gestalt mapping ONLY (nych.bonit STEP 2:
    ASSIGN_GESTALTS). It is never asked for .g8son gates or an .ork flow
    -- that is step 3's job (mg8.bonit), performed by a separate call
    after this one's mappings are validated and accepted.
    """
    pretext = gst_payload.get("nych_pretext", {})
    return f"""
You are the discretionary Gestalt-mapping step of the NYCH pipeline (step
2 of nych.bonit). All deterministic extraction is already done and is
given below as pretext. Follow every rule exactly; the engine validates
your output and rejects violations. Map words only -- do not propose any
.g8son gate or .ork flow; that happens in a separate, later call.

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
  "mappings": [{{"word": ..., "symbol_id": ..., "glyph": ...}}]
}}
""".strip()


def validate_mapping_plan(plan: Dict[str, Any], gst_payload: Dict[str, Any]) -> None:
    """Enforce the canon rules on a first-LLM-call (mapping-only) plan.
    Raises PipelineError with the specific violation; never repairs
    silently."""
    pretext = gst_payload.get("nych_pretext", {})
    needs = {d["word"].lower(): d for d in pretext.get("needs_mapping", [])}
    protected = {p["word"].strip(".,;:").lower()
                 for p in pretext.get("protected", [])}
    # The canonical operators are enforced even if a pretext omits or
    # alters its operator table -- the engine doesn't trust its inputs.
    operators = {**CANON_MODALITY_OPERATORS,
                 **pretext.get("modality_operators", {})}
    operator_words = set(operators) | set(operators.values())
    operator_glyphs = {_bare_glyph(g) for g in operators.values()}
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
        for field in ("glyph", "symbol_id"):
            value = _bare_glyph(str(m.get(field) or ""))
            if any(g in value for g in operator_glyphs):
                raise PipelineError(
                    f"mapping for {word!r} uses a modality operator glyph in "
                    f"its {field} ({m.get(field)!r}); operator glyphs belong "
                    "only to their operators")
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


# ---------------------------------------------------------------------------
# Second LLM call (mg8.bonit STEP 3): congruence assessment + 3 .g8son files
# ---------------------------------------------------------------------------

def build_congruence_prompt(gst_payload: Dict[str, Any],
                            accepted_mappings: List[Dict[str, Any]]) -> str:
    """Build the second-LLM-call prompt: mg8.bonit's CONGRUENCE_ASSESSMENT
    followed, only on PASS, by authoring exactly three .g8son files.

    Scope note: this reference runtime does not yet construct a separate
    nych_encoder-emitted .ork payload (nych.bonit STEP 1's
    EMIT_INITIAL_ORK isn't implemented here -- see pipeline step 1 in the
    nych package itself). Congruence is therefore assessed between the
    accepted Gestalt mappings and the .gst pretext/state, per
    mg8.bonit's CONGRUENCE_ASSESSMENT.CHECKS (state fields a gate would
    reference must actually exist in gst; no gate condition may
    contradict a gst constraint); the check against a separately-modeled
    .ork is left for when that payload exists.
    """
    pretext = gst_payload.get("nych_pretext", {})
    return f"""
You are the congruence-assessment + gate-authoring step of the MG8
pipeline (step 3 of mg8.bonit, mg8-engine's own ruleset). You receive the
accepted Gestalt mappings from step 2 plus the .gst pretext/state they
were mapped against.

FIRST: assess congruence per mg8.bonit's CONGRUENCE_ASSESSMENT.CHECKS --
does every state field a gate you might propose would reference actually
exist in the state below, and would no such gate contradict a declared
constraint? Return your result using mg8.bonit's STATUS_CANON, which is
canonical here: "PASS", "FAIL", or "INTERMEDIATE" -- never "UNKNOWN" (the
legacy NYCH MGate term) or "UNRESOLVED" (the .ork bound-exhaustion term);
those map onto INTERMEDIATE and FAIL respectively, they are not
additional values you may return directly.

SECOND: only if your result is "PASS", author exactly THREE .g8son
files. Each file holds 1-3 gates; every gate MUST declare an exit
condition ("outcomes", "condition", "conditions", or "then"). Then
provide the .ork "flow": the gate ids from all three files, in the order
they should execute. If your result is FAIL or INTERMEDIATE, return no
g8son_files and no flow -- do not author gates against a handoff you
have not confirmed is congruent.

ACCEPTED MAPPINGS (from step 2, already validated):
{json.dumps(accepted_mappings, ensure_ascii=False, indent=2)}

STATE (from the .gst pretext):
state: {json.dumps(gst_payload.get("state", {}), ensure_ascii=False)}
constraints: {json.dumps(gst_payload.get("constraints", []), ensure_ascii=False)}
tote_match: {json.dumps(pretext.get("tote_match"), ensure_ascii=False)}

Return ONLY one valid JSON object:
{{
  "congruence_result": "PASS" | "FAIL" | "INTERMEDIATE",
  "g8son_files": [{{"file_id": ..., "gates": [1-3 gate objects, each a
      bounded repeat loop with an exit condition: "id", "type",
      "condition" or "conditions", "outcomes"]}}],
  "flow": ["gate ids in execution order"]
}}
(g8son_files/flow present only when congruence_result is "PASS", and when
present, g8son_files MUST contain exactly 3 entries.)
""".strip()


def _gate_has_exit(gate: Dict[str, Any]) -> bool:
    return bool(gate.get("outcomes") or gate.get("condition")
                or gate.get("conditions") or gate.get("then"))


def validate_congruence_response(response: Dict[str, Any],
                                 gst_payload: Dict[str, Any]) -> None:
    """Enforce mg8.bonit's rules on a second-LLM-call response. Raises
    PipelineError for a malformed/out-of-canon response, or
    CongruenceNotPass when the response is well-formed but legitimately
    reports FAIL or INTERMEDIATE. Never repairs silently."""
    result = response.get("congruence_result")
    if result not in CONGRUENCE_RESULTS:
        raise PipelineError(
            f"congruence_result {result!r} is outside mg8.bonit's "
            f"STATUS_CANON {sorted(CONGRUENCE_RESULTS)}; UNKNOWN and "
            "UNRESOLVED are legacy vocabulary that map onto this canon, "
            "not values a response may return directly "
            "(REJECT IF GATE_RESULT_OUTSIDE_STATUS_CANON)"
        )

    files = response.get("g8son_files") or []
    flow = response.get("flow") or []

    if result != "PASS":
        if files or flow:
            raise PipelineError(
                f"congruence_result is {result!r} but the response still "
                "authored g8son_files/flow; mg8.bonit: REJECT IF "
                "G8SON_AUTHORED_WHEN_CONGRUENCE_RESULT_NOT_PASS"
            )
        raise CongruenceNotPass(result, response)

    if len(files) != REQUIRED_G8SON_FILE_COUNT:
        raise PipelineError(
            f"congruence_result is PASS but {len(files)} .g8son files "
            f"were authored, not the required {REQUIRED_G8SON_FILE_COUNT} "
            "(mg8.bonit: REJECT IF G8SON_FILE_COUNT_NOT_EQUAL_THREE)"
        )

    gate_ids: List[str] = []
    for f in files:
        gates = f.get("gates", [])
        if not 1 <= len(gates) <= 3:
            raise PipelineError(
                f".g8son file {f.get('file_id')!r} has {len(gates)} gates; "
                "each file must hold 1-3 (REJECT IF "
                "G8SON_FILE_GATE_COUNT_OUT_OF_BOUND)"
            )
        for g in gates:
            gid = g.get("id") or g.get("gate_id")
            if not gid:
                raise PipelineError("gate without an id")
            if not _gate_has_exit(g):
                raise PipelineError(
                    f"gate {gid!r} declares no exit condition; every gate "
                    "is a bounded repeat loop with exit conditions "
                    "(REJECT IF GATE_MISSING_EXIT_CONDITION)"
                )
            gate_ids.append(gid)

    if not flow:
        raise PipelineError(
            "congruence_result is PASS but the response contains no .ork "
            "flow"
        )
    unknown = [g for g in flow if g not in gate_ids]
    if unknown:
        raise PipelineError(
            f".ork flow references unknown gate ids: {unknown} "
            "(REJECT IF ORK_FLOW_REFERENCES_UNDECLARED_GATE)"
        )


# ---------------------------------------------------------------------------
# Legacy combined validator (pre-mg8.bonit one-call shape)
# ---------------------------------------------------------------------------

def validate_plan(plan: Dict[str, Any], gst_payload: Dict[str, Any]) -> None:
    """Legacy validator for the OLD single-call plan shape (mappings +
    g8son_files + flow together), kept only because
    experiments/run_experiment.py's already-published methodology
    (experiments/RESULTS.md) specifically measures that one-call shape
    for its NYCH-vs-plain comparison -- rewriting the experiment to the
    two-call mg8.bonit shape would change what it measured, which is a
    separate decision from bringing the live pipeline in line with
    nych.bonit/mg8.bonit.

    `run_pipeline` does NOT call this; it uses `validate_mapping_plan`
    (first call) and `validate_congruence_response` (second call). New
    callers should use those, not this.
    """
    validate_mapping_plan(plan, gst_payload)

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
# Unit assembly: .gst / .g8son x3 / .ork / .mg8 on disk
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def assemble_unit(gst_payload: Dict[str, Any], mappings: List[Dict[str, Any]],
                  g8son_plan: Dict[str, Any], out_dir: str | Path, *,
                  unit_id: Optional[str] = None) -> Path:
    """Write the canonical unit directory and return the .mg8 manifest
    path: pretext.gst, gates.N.g8son (one per the three authored files,
    written and sequenced in order per mg8.bonit's
    sequential_execution_order), flow.ork, and unit.mg8 binding them.

    `mappings` are the accepted step-2 mappings (for the unit's
    metadata); `g8son_plan` is the validated, congruence-passed step-3
    response (`g8son_files` + `flow`)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    unit_id = unit_id or f"nych-unit-{uuid4().hex[:8]}"

    _write_json(out / "pretext.gst", gst_payload)

    gate_refs = []
    for index, f in enumerate(g8son_plan["g8son_files"], start=1):
        name = f"gates.{index}.g8son"
        _write_json(out / name, {
            "g8son_version": "1.0",
            "file_id": f.get("file_id") or f"gates.{index}",
            "gates": f["gates"],
        })
        gate_refs.append(name)

    _write_json(out / "flow.ork", {"flow": g8son_plan["flow"]})
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
            "mappings": mappings,
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
# Two-call pipeline
# ---------------------------------------------------------------------------

def run_pipeline(gst_payload: Dict[str, Any], mapping_llm: LLMCallback,
                 congruence_llm: LLMCallback, out_dir: str | Path, *,
                 gate_llm: Optional[LLMCallback] = None,
                 unit_id: Optional[str] = None,
                 canon_blocks: Optional[List[Dict[str, str]]] = None,
                 gitson_max_bytes: int = DEFAULT_GITSON_MAX_BYTES) -> Dict[str, Any]:
    """Run the pipeline from a nych .gst pretext payload to the final
    .mg8 + .gitson handoff, per nych.bonit (steps 1-2) and mg8.bonit
    (step 3).

    `mapping_llm` performs the FIRST call (Gestalt mapping only).
    `congruence_llm` performs the SECOND call (congruence assessment,
    then -- only on PASS -- authoring exactly three .g8son files plus
    the .ork flow). `gate_llm` executes individual gates during the
    resulting sequential run (defaults to the engine's dummy PASS
    callback, unchanged from before).

    Returns the mapping plan, the congruence assessment, the executed
    unit, the accepted mappings (for the caller to pin #temp-invariant),
    and all output paths.

    Raises PipelineError for any canon violation in either call's
    output. Raises CongruenceNotPass (a PipelineError subclass) when the
    second call legitimately reports FAIL or INTERMEDIATE -- in that
    case nothing is written to `out_dir` and no gate is executed, per
    mg8.bonit: REJECT IF G8SON_AUTHORED_BEFORE_CONGRUENCE_ASSESSED."""
    # --- First call: Gestalt mapping (nych.bonit STEP 2) ---
    mapping_prompt = build_mapping_prompt(gst_payload)
    raw_mapping = mapping_llm(mapping_prompt)
    mapping_plan = json.loads(raw_mapping) if isinstance(raw_mapping, str) else raw_mapping
    if not isinstance(mapping_plan, dict):
        raise PipelineError(f"mapping LLM returned {type(mapping_plan).__name__}, "
                            "expected a JSON object")
    validate_mapping_plan(mapping_plan, gst_payload)
    mappings = mapping_plan.get("mappings", [])

    # --- Second call: congruence assessment + 3 .g8son files (mg8.bonit STEP 3) ---
    congruence_prompt = build_congruence_prompt(gst_payload, mappings)
    raw_congruence = congruence_llm(congruence_prompt)
    congruence = json.loads(raw_congruence) if isinstance(raw_congruence, str) else raw_congruence
    if not isinstance(congruence, dict):
        raise PipelineError(f"congruence LLM returned {type(congruence).__name__}, "
                            "expected a JSON object")
    validate_congruence_response(congruence, gst_payload)
    # validate_congruence_response raises CongruenceNotPass for FAIL/
    # INTERMEDIATE before returning, so reaching here means PASS.

    g8son_plan = {"g8son_files": congruence["g8son_files"], "flow": congruence["flow"]}

    mg8_path = assemble_unit(gst_payload, mappings, g8son_plan, out_dir, unit_id=unit_id)
    unit = run_mg8(mg8_path, gate_llm)

    # Audit trail: mapping acceptance (sequence 0) and the congruence
    # assessment that licensed authoring (sequence 1) both precede the
    # gate-execution entries execute_ork already appended.
    unit.qson.entries.insert(0, QsonEntry(
        trace_id=f"TRJ_{uuid4().hex}",
        run_id=unit.qson.run_id,
        gate_id="mg8.congruence_assessment",
        step=1,
        action="congruence-assessment",
        result=congruence["congruence_result"],
        llm_prompt=congruence_prompt,
        llm_output=congruence,
        input_state_id=gst_payload.get("state_id"),
    ))
    unit.qson.entries.insert(0, QsonEntry(
        trace_id=f"TRJ_{uuid4().hex}",
        run_id=unit.qson.run_id,
        gate_id="nych.gestalt_mapping",
        step=0,
        action="gestalt-mapping",
        llm_prompt=mapping_prompt,
        llm_output={"mappings": mappings, "tag": "#temp-invariant"},
        input_state_id=gst_payload.get("state_id"),
    ))

    handoff = write_output_handoff(unit, out_dir, canon_blocks=canon_blocks,
                                   max_bytes=gitson_max_bytes)
    return {
        "mapping_plan": mapping_plan,
        "congruence": congruence,
        "unit": unit,
        "pins": mappings,
        "paths": {"unit_mg8": mg8_path, **handoff},
    }


# v1 note: prior to this version, this module made a single first-LLM
# call that returned mappings + g8son_files + flow together (matching
# the ordering this repo's own README's "NYCH pipeline" section used to
# describe), with no congruence-assessment step and no fixed file count.
# That ordering conflicted with nych.bonit (first call: Gestalt mapping
# only) once that file was written, and left mg8.bonit's step 3
# (congruence assessment + exactly three .g8son files, sequentially
# executed) unimplemented. This version brings the code in line with
# both: `validate_plan`/`build_mapping_prompt`'s old combined
# responsibilities are now `validate_mapping_plan` (mapping only) and
# `validate_congruence_response` (the new second call), and
# `run_pipeline` takes `congruence_llm` as a required second callback.
