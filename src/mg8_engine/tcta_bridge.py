"""tcta_bridge.py -- a thin, honestly-scoped application of tcta_engine's
Omega(C)/SPREAD/ALGORITHM_SELECT to mg8-engine's own Gestalt-mapping step
(nych.bonit STEP 2 -- see pipeline.build_mapping_prompt/
validate_mapping_plan).

Why this is thinner than nych's own `tcta_bridge.py`: nych's domain ->
constraint -> selection stage (domain.expand_domain,
constraint.apply_constraints, selection.select_candidate) already
enumerates and narrows a real multi-candidate space (ConstraintMask,
SelectionResult). mg8-engine's Gestalt-mapping step has no such enumerated
candidate set -- it hands the LLM a list of words needing a symbol
(`nych_pretext.needs_mapping`) and gets back whichever subset it mapped
(`mapping_plan["mappings"]`). That IS a genuine admissible-space / target-
space pair, just a coarser one:

    Omega(C) = needs_mapping (every word this step was asked to resolve)
    T_G      = the words still UNRESOLVED after the call (needs_mapping
               minus what mapping_plan actually mapped)

SPREAD = S(T_G)/S(Omega(C)) reads as "how much of the candidate mapping
problem is still open after this call" -- SPREAD near 0 (most/all words
got mapped) selects HDRP_LOCALIZED; SPREAD near/above SPREAD_HIGH (most
words remain unresolved) selects UNRESOLVED, which is the honest signal
that this call under-delivered, independent of `validate_mapping_plan`'s
own canon checks (those catch WRONG mappings; this catches MISSING ones).

This module does not use Gamma/Psi/HDRP's Phi -- there is no multi-step
trajectory or dual-register prediction at this step, so ENGINE.GAMMA_REF/
PSI_REF/PHI_REF are left null in the `.tcta` file this module writes, and
CONSUMPTION_POINTS.DOMAIN_PRUNE/COMPETENCY_PRUNE stay `not_yet_wired`:
nych's domain/competency classification lives in a DIFFERENT, currently
unconnected pipeline (nych.pipeline's stage 7-10, see nych.tcta_bridge),
not in the Gestalt-mapping handoff this module instruments. Disclosed
here rather than implied by omission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tcta_engine.core import compute_spread, select_algorithm
from tcta_engine.compliance import check_compliance
from tcta_engine.file_format import (
    AlgorithmSelect,
    ConsumptionPoint,
    ConsumptionPoints,
    Engine,
    Goal,
    Parameters,
    Spread,
    TctaFile,
)

DEFAULT_SPREAD_LOW = 0.2
DEFAULT_SPREAD_HIGH = 0.8


@dataclass(frozen=True)
class TctaNarrowingResult:
    """Disclosed record of one Gestalt-mapping call's SPREAD/
    ALGORITHM_SELECT computation. `unresolved_words` are the actual
    surviving candidate words (T_G), not just a count, so a caller or
    QSON reader can see which words are still open."""

    omega_c_count: int
    t_g_count: int
    unresolved_words: List[str] = field(default_factory=list)
    spread: Optional[float] = None
    algorithm_select_result: Optional[str] = None
    algorithm_select_reason: Optional[str] = None
    note: Optional[str] = None


def compute_mapping_narrowing(
    gst_payload: Dict[str, Any],
    mapping_plan: Dict[str, Any],
    *,
    spread_low: float = DEFAULT_SPREAD_LOW,
    spread_high: float = DEFAULT_SPREAD_HIGH,
) -> TctaNarrowingResult:
    """Computes Omega(C)/SPREAD/ALGORITHM_SELECT for one accepted (already
    `validate_mapping_plan`-passed) mapping plan against the pretext's
    `needs_mapping` candidate list. Pure and side-effect-free -- safe to
    call even when a later pipeline step (congruence) goes on to fail;
    see pipeline.run_pipeline for where this is actually wired in and why
    it is computed before, but its `.tcta` file only written after, unit
    assembly succeeds.
    """
    pretext = gst_payload.get("nych_pretext", {})
    needs = pretext.get("needs_mapping", [])
    omega_c_count = len(needs)

    mapped_words = {str(m.get("word", "")).lower() for m in mapping_plan.get("mappings", [])}
    unresolved = [d["word"] for d in needs if str(d["word"]).lower() not in mapped_words]
    t_g_count = len(unresolved)

    if omega_c_count <= 0:
        return TctaNarrowingResult(
            omega_c_count=0,
            t_g_count=0,
            unresolved_words=[],
            note="no candidate words needed mapping this call; SPREAD is "
                 "undefined (S(Omega(C)) must be > 0)",
        )

    spread = compute_spread(s_tg=float(t_g_count), s_omega_c=float(omega_c_count))
    result, reason = select_algorithm(spread, spread_low=spread_low, spread_high=spread_high)
    return TctaNarrowingResult(
        omega_c_count=omega_c_count,
        t_g_count=t_g_count,
        unresolved_words=unresolved,
        spread=spread,
        algorithm_select_result=result,
        algorithm_select_reason=reason,
    )


def verify_compliance(narrowing: TctaNarrowingResult) -> None:
    """Self-check, not a second decision process: re-runs tcta_engine's
    own COMPLIANCE REJECT IF checks against what `compute_mapping_narrowing`
    produced. No branch of that function can set ALGORITHM_SELECT without
    first setting SPREAD, and this step declares no GOAL.DESIRED_SR and
    uses no separate engine to substitute, so this should never raise --
    it exists at the same bar as `validate_mapping_plan`/
    `validate_congruence_response`: never trust a computed result without
    re-checking it against the rules it claims to satisfy."""
    check_compliance(
        declared_method_ref="mg8_engine.tcta_bridge.compute_mapping_narrowing",
        used_method_ref="mg8_engine.tcta_bridge.compute_mapping_narrowing",
        desired_sr=None,
        omega_c_computed=True,
        spread_value=narrowing.spread,
        algorithm_select_result=narrowing.algorithm_select_result,
    )


def build_tcta_file(
    unit_id: str,
    narrowing: TctaNarrowingResult,
    *,
    spread_low: float = DEFAULT_SPREAD_LOW,
    spread_high: float = DEFAULT_SPREAD_HIGH,
) -> TctaFile:
    """Builds the `.tcta` reference-representation file disclosing this
    call's narrowing, per tcta_file_format_v1.md's "Reference
    representation (v1)" shape. Written into the unit directory as
    `trajectory.tcta` by `pipeline.run_pipeline`, alongside `.gst`/
    `.g8son`/`.ork`/`.qson` -- see that file's own relationship diagram:
    ".tcta sits beside .g8son, not above or inside it."
    """
    tcta = TctaFile(name=unit_id, applies_to=f"{unit_id}/pretext.gst")
    tcta.goal = Goal(desired_sr=None, source=None)
    tcta.engine = Engine(gamma_ref=None, psi_ref=None, phi_ref=None)
    tcta.parameters = Parameters(
        eta=None,
        lambda_rec=None,
        alpha=None,
        epsilon=None,
        prefix_k=None,
        spread_low=spread_low,
        spread_high=spread_high,
    )
    tcta.consumption_points = ConsumptionPoints(
        domain_prune=ConsumptionPoint(
            source="nych.domain.expand_domain (a separate NYCH pipeline "
                   "stage; not consulted by mg8-engine's Gestalt-mapping "
                   "step)",
            defined=None,
            status="not_yet_wired",
        ),
        competency_prune=ConsumptionPoint(
            source="nych.competency.analyze_utterance (its output rides "
                   "in nych_pretext.analysis but is not used to prune "
                   "mapping candidates here)",
            defined=None,
            status="not_yet_wired",
        ),
        inverse_transform=ConsumptionPoint(source=None, defined=False, status="not_yet_wired"),
        trajectory_narrowing=ConsumptionPoint(source="ENGINE", defined=None, status="implemented"),
    )
    tcta.spread = Spread(value=narrowing.spread, epsilon_check=None)
    tcta.algorithm_select = AlgorithmSelect(
        result=narrowing.algorithm_select_result,
        reason=narrowing.algorithm_select_reason,
    )
    tcta.compliance = [
        "ALGORITHM_SUBSTITUTED",
        "GOAL_PURSUED_WITHOUT_OMEGA_C",
        "SPREAD_NOT_COMPUTED_BEFORE_SELECTION",
    ]
    return tcta
