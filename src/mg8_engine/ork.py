from uuid import uuid4

from .models import G8Gate, Mg8Unit, QsonEntry
from .nych.core import apply_nych_tokenization, get_modality_name
from .predicates import evaluate_conditions


def _gate_task(gate: G8Gate) -> str:
    if gate.condition:
        return gate.condition
    if gate.action:
        return gate.action
    if gate.conditions:
        return "; ".join(str(item) for item in gate.conditions)
    return "evaluate the current state and return a bounded result"


def build_strict_llm_prompt(unit: Mg8Unit, gate: G8Gate, current_state: dict) -> str:
    """Build the ADSR/Nych reference-profile prompt for one gate execution."""
    nych = apply_nych_tokenization(str(current_state))
    modality_name = get_modality_name(gate.modality) if gate.modality else "none"

    prompt = f"""
You are executing one bounded gate inside the MG8 reference runtime profile.

Domain: {unit.gst.domain}
Current State: {current_state}
GST Constraints: {unit.gst.constraints}
Nych Tokens: {nych['nych_tokens']}

Gate ID: {gate.gate_id}
Gate Type: {gate.type}
Modality: {gate.modality} → {modality_name}
ADSR extension profile: A={gate.attack} D={gate.decay} S={gate.sustain} R={gate.release} Pan={gate.pan}

Task / Conditions: {_gate_task(gate)}
Declared outcome routing: {gate.outcomes}

Return ONLY one valid JSON object. When meaningful, include:
- "transformed": true or false
- "gate_result": "PASS", "FAIL", or "INTERMEDIATE"
- any resulting state fields required by the task

Do not claim PASS unless the returned content/state satisfies the gate conditions.
"""
    return prompt.strip()


def _infer_gate_result(output) -> str | None:
    if not isinstance(output, dict):
        return None

    result = output.get("gate_result") or output.get("result")
    if isinstance(result, str) and result.upper() in {"PASS", "FAIL", "INTERMEDIATE"}:
        return result.upper()

    if output.get("transformed") is True:
        return "PASS"
    if output.get("transformed") is False:
        return "FAIL"
    return None


def execute_ork(unit: Mg8Unit, llm_callback=None) -> Mg8Unit:
    """Execute the reference-engine ORK flow and emit event-level QSON entries."""
    state = unit.gst.execution_state()
    step = 0
    max_iterations = 30

    if not unit.qson.run_id:
        unit.qson.run_id = f"RUN_{uuid4().hex}"

    flow = unit.ork_flow or [g.gate_id for g in unit.g8son.gates]
    i = 0

    while i < len(flow) and step < max_iterations:
        gate = next((g for g in unit.g8son.gates if g.gate_id == flow[i]), None)
        if not gate:
            raise ValueError(f"ORK flow references unknown gate ID: {flow[i]}")

        step += 1
        input_snapshot = state.copy()
        prompt = build_strict_llm_prompt(unit, gate, state)
        output = llm_callback(prompt) if llm_callback is not None else {}
        if isinstance(output, dict):
            control_fields = {"transformed", "gate_result", "result", "action"}
            candidate_state = {**state, **{k: v for k, v in output.items() if k not in control_fields}}
        else:
            candidate_state = dict(state)

        predicate = None
        if gate.conditions and gate.type.lower() != "tote_test":
            predicate = evaluate_conditions(gate.conditions, candidate_state, gate.type)
            gate_result = predicate.result
        else:
            gate_result = _infer_gate_result(output)
        if gate_result is None:
            gate_result = "INTERMEDIATE"
        action = gate.outcomes.get(gate_result)

        source_file_id = None
        if gate.model_extra:
            source_file_id = gate.model_extra.get("source_file_id")

        entry = QsonEntry(
            trace_id=f"TRJ_{uuid4().hex}",
            run_id=unit.qson.run_id,
            file_id=source_file_id or unit.g8son.file_id,
            gate_id=gate.gate_id,
            sequence=step,
            input_state_id=unit.gst.state_id,
            result=gate_result,
            action=action if isinstance(action, str) else None,
            input_state=input_snapshot,
            llm_prompt=prompt,
            llm_output=output,
            modality=gate.modality,
            evidence=predicate.evidence if predicate else None,
        )
        unit.qson.events.append(entry)

        if gate_result == "PASS":
            state = candidate_state

        # TOTE behavior is retained as a legacy/reference runtime extension rather than
        # generalized into the base MG8/G8SON specifications.
        if gate.type == "tote_test":
            test_passed = gate_result == "PASS"
            if gate_result is None:
                test_passed = any(
                    term in str(output).lower()
                    for term in ["nailed_down", "match", "success", "done"]
                )
                test_passed = test_passed or state.get("status") == "nailed_down"

            if test_passed:
                i += 1
            else:
                continue
        else:
            if action in {"stop", "review"} or gate_result != "PASS":
                break
            i += 1

    if step >= max_iterations and i < len(flow):
        raise RuntimeError(
            f"MG8 reference runtime exceeded max_iterations={max_iterations}"
        )

    unit.gst.state = state
    return unit
