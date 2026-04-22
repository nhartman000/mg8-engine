
from .models import Mg8Unit

def execute_ork(unit: Mg8Unit, llm_callback=None):
    """
    Executes the flow defined in unit.ork_flow (or default sequential).
    For now: simple sequential gate execution.
    In full version: support loops, TOTE, branching.
    """
    trace = unit.qson
    current_state = unit.gst.state.copy()

    for step in unit.ork_flow or [g.id for g in unit.g8son.gates]:
        gate = next((g for g in unit.g8son.gates if g.id == step), None)
        if not gate:
            continue

        # TODO: Apply Nych tokenization + modality here
        # Call LLM with strict instructions + current gate constraints

        entry = QsonEntry(
            trace_id=f"trace_{len(trace.entries)+1}",
            gate_id=gate.id,
            input=current_state,
            output="LLM_OUTPUT_HERE",   # placeholder
            modality=gate.modality,
        )
        trace.entries.append(entry)

        # Simple condition example
        if gate.condition and "==" in gate.condition:
            # parse and evaluate (expand this heavily)
            pass

    return unit
