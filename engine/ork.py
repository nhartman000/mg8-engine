from .models import Mg8Unit, QsonEntry
from .nych_integration import apply_nych_tokenization, get_modality_name
from datetime import datetime

def build_strict_llm_prompt(unit: Mg8Unit, gate: "G8Gate", current_state: dict) -> str:
    nych = apply_nych_tokenization(str(current_state))
    modality_name = get_modality_name(gate.modality) if gate.modality else ""

    prompt = f"""
You are executing a deterministic MG8 intelligence unit under strict Nych protocol.

Domain: {unit.gst.domain}
Narrative Tense: {unit.gst.narrative_tense}
Global Constraints: {unit.gst.constraints}

Current GST State: {current_state}

Nych Tokenized Input: {nych['nych_tokens']}

=== GATE {gate.id} ({gate.type}) ===
Modality: {gate.modality} → {modality_name}
Intensity: {gate.intensity} (reasoning depth)
Pan: {gate.pan} (internal/external weighting)

Condition/Action: {gate.condition or gate.action}

Apply ONLY this gate. Use the exact modality. Prune everything outside the domain.
Output ONLY the transformed state as JSON. No explanation.

Respond with valid JSON representing the new state after this gate.
"""
    return prompt.strip()

def execute_ork(unit: Mg8Unit, llm_callback=None) -> Mg8Unit:
    """Main deterministic executor. llm_callback should take prompt and return output."""
    if llm_callback is None:
        # Dummy for testing — replace with real LLM call (Groq, OpenAI, etc.)
        def dummy_llm(p): return {"status": "processed", "result": "simulated_output"}
        llm_callback = dummy_llm

    state = unit.gst.state.copy()
    step = 0

    flow = unit.ork_flow or [g.id for g in unit.g8son.gates]

    for gate_id in flow:
        gate = next((g for g in unit.g8son.gates if g.id == gate_id), None)
        if not gate:
            continue

        step += 1
        prompt = build_strict_llm_prompt(unit, gate, state)

        output = llm_callback(prompt)

        entry = QsonEntry(
            trace_id=f"q_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{step}",
            gate_id=gate.id,
            step=step,
            input_state=state,
            llm_prompt=prompt,
            llm_output=output,
            modality=gate.modality,
        )
        unit.qson.entries.append(entry)

        # Update state with LLM output (you can make this more sophisticated)
        if isinstance(output, dict):
            state.update(output)

        # Simple TOTE example handling
        if gate.type.startswith("tote_") and gate.condition:
            # Expand this for full Test-Operate-Test-Exit loops
            pass

    unit.gst.state = state
    return unit
