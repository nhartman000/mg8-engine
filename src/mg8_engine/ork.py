from uuid import uuid4

from nych.semantic_encoding import encode_text as nych_encode_text

from .models import G8Gate, Mg8Unit, QsonEntry


def _gate_task(gate: G8Gate) -> str:
    if gate.condition:
        return gate.condition
    if gate.action:
        return gate.action
    if gate.conditions:
        return "; ".join(str(item) for item in gate.conditions)
    return "evaluate the current state and return a bounded result"


def build_strict_llm_prompt(unit: Mg8Unit, gate: G8Gate, current_state: dict) -> str:
    """Build the ADSR/Nych reference-profile prompt for one gate execution.

    Gestalt symbolization of the current state goes through the real `nych`
    package (nych.semantic_encoding.encode_text) rather than a hardcoded
    ~10-word stub lexicon that used to live in this package and had drifted
    out of sync with nych's actual sense registry.
    """
    nych_encoded, _nych_records = nych_encode_text(str(current_state))

    prompt = f"""
You are executing one bounded gate inside the MG8 reference runtime profile.

Domain: {unit.gst.domain}
Current State: {current_state}
GST Constraints: {unit.gst.constraints}
Nych Tokens: {nych_encoded}

Gate ID: {gate.gate_id}
Gate Type: {gate.type}
Modality: {gate.modality or "none"}
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


class GateFailure(RuntimeError):
    """Raised when a gate returns FAIL and the executor halts the flow.

    No further gates or operations run after the failing gate. The partially
    executed unit is attached as ``.unit``; its QSON trace ends with a
    ``mg8.halt`` entry and ``unit.qson.status == "HALTED"``.
    """

    def __init__(self, unit: Mg8Unit, gate_id: str, step: int, output=None):
        self.unit = unit
        self.gate_id = gate_id
        self.step = step
        self.output = output
        self.status = "HALTED"
        super().__init__(
            f"MG8 execution halted: gate {gate_id!r} returned FAIL at step {step}; "
            "no further gates or operations were run"
        )


def _fail_route(gate: G8Gate) -> str:
    """Declared routing for a FAIL result. Only an explicit "repeat" retries."""
    route = (gate.outcomes or {}).get("FAIL")
    return route.lower() if isinstance(route, str) else "stop"


def execute_ork(unit: Mg8Unit, llm_callback=None) -> Mg8Unit:
    """Execute the reference-engine ORK flow and emit event-level QSON entries.

    Stop-on-fail: when a gate's result is FAIL, execution halts immediately --
    no later gate (or operation) in the flow runs, a ``mg8.halt`` entry is
    appended to the QSON trace, ``unit.qson.status`` is set to ``"HALTED"`` and
    :class:`GateFailure` is raised. The single exception is a gate that
    explicitly declares ``outcomes: {"FAIL": "repeat"}`` (a TOTE test loop):
    that gate is re-tested, bounded by ``max_iterations``. A completed flow
    sets ``unit.qson.status`` to ``"COMPLETED"``.
    """
    if llm_callback is None:
        def dummy_llm(_prompt):
            return {"transformed": True, "gate_result": "PASS"}
        llm_callback = dummy_llm

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
        output = llm_callback(prompt)
        gate_result = _infer_gate_result(output)

        source_file_id = None
        if gate.model_extra:
            source_file_id = gate.model_extra.get("source_file_id")

        entry = QsonEntry(
            trace_id=f"TRJ_{uuid4().hex}",
            run_id=unit.qson.run_id,
            file_id=source_file_id or unit.g8son.file_id,
            gate_id=gate.gate_id,
            step=step,
            input_state_id=unit.gst.state_id,
            result=gate_result,
            input_state=input_snapshot,
            llm_prompt=prompt,
            llm_output=output,
            modality=gate.modality,
        )
        unit.qson.entries.append(entry)

        if isinstance(output, dict):
            # Control fields describe the execution event; they are not copied into GST.
            control_fields = {"transformed", "gate_result", "result", "action"}
            state.update({k: v for k, v in output.items() if k not in control_fields})

        if gate_result == "FAIL" and _fail_route(gate) != "repeat":
            unit.qson.entries.append(QsonEntry(
                trace_id=f"TRJ_{uuid4().hex}",
                run_id=unit.qson.run_id,
                file_id=source_file_id or unit.g8son.file_id,
                gate_id="mg8.halt",
                step=step + 1,
                input_state_id=unit.gst.state_id,
                result="FAIL",
                action="halt",
                halted_at_gate=gate.gate_id,
                halted_at_step=step,
                skipped_gates=list(flow[i + 1:]),
                reason=f"gate {gate.gate_id} returned FAIL; stop-on-fail",
            ))
            unit.qson.status = "HALTED"
            unit.gst.state = state
            raise GateFailure(unit, gate.gate_id, step, output)

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
            i += 1

    if step >= max_iterations and i < len(flow):
        unit.qson.status = "HALTED"
        raise RuntimeError(
            f"MG8 reference runtime exceeded max_iterations={max_iterations}"
        )

    unit.gst.state = state
    unit.qson.status = "COMPLETED"
    return unit
