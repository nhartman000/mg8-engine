from .models import Mg8Unit, QsonEntry, G8Gate
from .nych.core import apply_nych_tokenization, get_modality_name
from datetime import datetime

def build_strict_llm_prompt(unit: Mg8Unit, gate: G8Gate, current_state: dict) -> str:
    """Improved prompt optimized for Gemini to return clean JSON."""
    nych = apply_nych_tokenization(str(current_state))
    modality_name = get_modality_name(gate.modality) if gate.modality else "none"

    prompt = f"""
You are a precise deterministic executor in an MG8 unit using Nych protocol.

Domain: {unit.gst.domain}
Current State: {current_state}
Nych Tokens: {nych['nych_tokens']}

Gate: {gate.id} ({gate.type})
Modality: {gate.modality} → {modality_name}
ADSR: A={gate.attack} D={gate.decay} S={gate.sustain} R={gate.release} Pan={gate.pan}

Task: {gate.condition or gate.action or "update the state"}

Return ONLY a valid JSON object with the new state. Always include "transformed": true.
Update relevant fields based on the task and modality.

Example for nail task:
{{"object": "nail", "status": "nailed_down", "transformed": true}}

Respond with valid JSON only. No other text.
"""
    return prompt.strip()


def execute_ork(unit: Mg8Unit, llm_callback=None) -> Mg8Unit:
    if llm_callback is None:
        def dummy_llm(p):
            return {"transformed": True}
        llm_callback = dummy_llm

    state = unit.gst.state.copy()
    step = 0
    max_iterations = 30

    flow = unit.ork_flow or [g.id for g in unit.g8son.gates]
    i = 0

    while i < len(flow) and step < max_iterations:
        gate = next((g for g in unit.g8son.gates if g.id == flow[i]), None)
        if not gate:
            i += 1
            continue

        step += 1
        prompt = build_strict_llm_prompt(unit, gate, state)
        output = llm_callback(prompt)

        entry = QsonEntry(
            trace_id=f"q_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{step}",
            gate_id=gate.id,
            step=step,
            input_state=state.copy(),
            llm_prompt=prompt,
            llm_output=output,
            modality=gate.modality,
        )
        unit.qson.entries.append(entry)

        if isinstance(output, dict):
            state.update(output)

        if gate.type == "tote_test":
            test_passed = any(term in str(output).lower() for term in ["nailed_down", "match", "success", "done"])
            test_passed = test_passed or state.get("status") == "nailed_down"

            if test_passed:
                print(f"   [TOTE Test PASSED]")
                i += 1
            else:
                print(f"   [TOTE Test FAILED - repeating]")
                continue
        else:
            i += 1

    unit.gst.state = state
    return unit