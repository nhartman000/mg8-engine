import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import G8Gate, G8son, Gst, Mg8Manifest, Mg8Unit, Qson
from .ork import execute_ork


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _resolve_resource(base_dir: Path, reference: str) -> Path:
    """Resolve a manifest resource and keep it inside the unit directory tree."""
    ref = Path(reference)
    if ref.is_absolute():
        raise ValueError(f"MG8 resource references must be relative: {reference}")

    base = base_dir.resolve()
    resolved = (base / ref).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"MG8 resource escapes unit directory: {reference}") from exc
    return resolved


def _iter_gate_dicts(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    gates = payload.get("gates")
    if isinstance(gates, list):
        if not 1 <= len(gates) <= 3:
            raise ValueError("Each .g8son file must contain between 1 and 3 gates")
        yield from gates
        return

    # Backward compatibility for the older single-gate profile.
    if payload.get("gate_id") or payload.get("id"):
        yield payload
        return

    raise ValueError("G8SON resource does not contain a gate or gates array")


def _load_ork_flow(path: Path) -> List[str]:
    """
    Load the reference-engine ORK JSON profile.

    This is intentionally a runtime profile, not a claim that the universal `.ork`
    grammar is limited to this JSON shape.
    """
    payload = _load_json(path)
    flow = payload.get("flow") or payload.get("ork_flow")
    if flow is None and isinstance(payload.get("steps"), list):
        flow = [
            step.get("gate_id") if isinstance(step, dict) else step
            for step in payload["steps"]
        ]
    if not isinstance(flow, list) or not all(isinstance(x, str) for x in flow):
        raise ValueError(
            f"Reference-engine ORK file {path} must provide flow/ork_flow as gate IDs"
        )
    return flow


def _merge_gst_resources(payloads: List[Dict[str, Any]]) -> Gst:
    if len(payloads) == 1:
        return Gst.model_validate(payloads[0])

    merged: Dict[str, Any] = {
        "state": {},
        "constraints": [],
        "source_state_ids": [],
    }
    for payload in payloads:
        state = payload.get("state")
        if isinstance(state, dict):
            merged["state"].update(state)
        constraints = payload.get("constraints")
        if isinstance(constraints, list):
            merged["constraints"].extend(constraints)
        if payload.get("state_id"):
            merged["source_state_ids"].append(payload["state_id"])

        # Later resources override earlier ones for the same named layer in this
        # reference profile. The dedicated GST specification remains authoritative.
        for key in (
            "prior",
            "current",
            "internal",
            "external",
            "intent",
            "outcome_expectation",
            "domain",
            "narrative_tense",
        ):
            if key in payload:
                merged[key] = payload[key]

    return Gst.model_validate(merged)


def _load_canonical_unit(path: Path, data: Dict[str, Any]) -> Mg8Unit:
    manifest = Mg8Manifest.model_validate(data)
    base_dir = path.parent

    gst_payloads = [
        _load_json(_resolve_resource(base_dir, ref)) for ref in manifest.state
    ]
    gst = _merge_gst_resources(gst_payloads)

    gates: List[G8Gate] = []
    gate_file_ids: List[str] = []
    for ref in manifest.gates:
        gate_path = _resolve_resource(base_dir, ref)
        gate_payload = _load_json(gate_path)
        file_id = gate_payload.get("file_id") or gate_path.stem
        gate_file_ids.append(file_id)
        for gate_dict in _iter_gate_dicts(gate_payload):
            enriched = dict(gate_dict)
            enriched.setdefault("source_file_id", file_id)
            gates.append(G8Gate.model_validate(enriched))

    if not gates:
        raise ValueError("Canonical MG8 unit contains no executable gates")

    flow_path = _resolve_resource(base_dir, manifest.entry)
    flow = _load_ork_flow(flow_path)

    gate_ids = {gate.gate_id for gate in gates}
    unknown = [gate_id for gate_id in flow if gate_id not in gate_ids]
    if unknown:
        raise ValueError(f"ORK flow references unknown gate IDs: {unknown}")

    return Mg8Unit(
        gst=gst,
        g8son=G8son(file_id="aggregate", gates=gates),
        qson=Qson(),
        ork_flow=flow,
        metadata={
            **manifest.metadata,
            "source_mg8": str(path),
            "source_g8son_file_ids": gate_file_ids,
            "trace_reference": manifest.trace,
            "runtime_profile": "mg8-engine-reference",
        },
        manifest=manifest,
    )


def load_mg8(path: str | Path) -> Mg8Unit:
    """
    Load a `.mg8` unit.

    Supported inputs:
    1. canonical resource-binding manifest (`mg8_version`, `unit_id`, `entry`,
       `state`, `gates`, `trace`);
    2. the earlier embedded ADSR/TOTE runtime profile (`gst`, `g8son`,
       `ork_flow`) for backward compatibility.
    """
    path = Path(path)
    data = _load_json(path)

    if "mg8_version" in data and "entry" in data:
        return _load_canonical_unit(path, data)

    return Mg8Unit.model_validate(data)


def run_mg8(path: str | Path, llm_callback=None) -> Mg8Unit:
    """Load and execute an MG8 unit using the reference ADSR/Nych runtime profile."""
    unit = load_mg8(path)
    return execute_ork(unit, llm_callback)
