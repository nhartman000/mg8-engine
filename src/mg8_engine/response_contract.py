"""Opt-in response-contract-v1: prompt assembly and observed byte comparison.

Atomic requirements are supplied to the model, not independently certified.
The legacy keeper and runtime are intentionally not involved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nych.gst_export import build_gst

PREFIX = (
    "Answer the user prompt by satisfying the active GST globals and all G8SON atomic requirements. "
    "Facts are supplied as semantic inputs, not a prior response. "
    "Do not output your analysis, gate verdicts or instructions. Emit only the requested sentence.\n"
)


@dataclass(frozen=True)
class ResponseContract:
    """Immutable JSON snapshots preserve authored fields and insertion order."""

    _gst_json: str
    _gates_json: str
    _manifest_json: str
    _flow_json: str

    @classmethod
    def from_unit(cls, path: str | Path) -> ResponseContract:
        path = Path(path)
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        from .core import _resolve_resource
        from .models import Mg8Manifest

        binding = Mg8Manifest.model_validate(manifest)
        if len(binding.state) != 1:
            raise ValueError("response-contract-v1 requires exactly one GST")
        trace = _resolve_resource(path.parent, binding.trace)
        if trace.suffix != ".qson":
            raise ValueError("trace must name a .qson resource")
        flow_path = _resolve_resource(path.parent, binding.entry)
        flow = json.loads(flow_path.read_text(encoding="utf-8-sig"))
        expected = {"profile": "repeatability-experiment-v1", "action": "generate_once", "max_calls_per_trial": 1, "repair": False, "reuse_answers": False}
        if flow != expected or type(flow.get("max_calls_per_trial")) is not int or type(flow.get("repair")) is not bool or type(flow.get("reuse_answers")) is not bool:
            raise ValueError("Unsupported ORK controls; expected repeatability-experiment-v1 generate_once subset")
        gst = json.loads(_resolve_resource(path.parent, binding.state[0]).read_text(encoding="utf-8-sig"))
        if not isinstance(gst, dict):
            raise ValueError("GST must be an object")
        gates = []
        gate_ids = set()
        for ref in binding.gates:
            gate = json.loads(_resolve_resource(path.parent, ref).read_text(encoding="utf-8-sig"))
            if not isinstance(gate, dict) or not isinstance(gate.get("gate_id"), str) or not gate["gate_id"] or gate["gate_id"] in gate_ids:
                raise ValueError("Expected unique nonempty atomic gate_id")
            gate_ids.add(gate["gate_id"])
            requirements = gate.get("atomic_requirements")
            if not isinstance(requirements, list) or not requirements:
                raise ValueError("Expected nonempty atomic_requirements")
            ids = set()
            for req in requirements:
                if not isinstance(req, dict) or not isinstance(req.get("req_id"), str) or not req["req_id"] or req["req_id"] in ids or not isinstance(req.get("requirement"), str) or not req["requirement"]:
                    raise ValueError("Expected unique nonempty req_id and requirement within each gate")
                ids.add(req["req_id"])
            gates.append(gate)
        return cls(json.dumps(gst, ensure_ascii=False), json.dumps(gates, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False), json.dumps(flow, ensure_ascii=False))

    def verify(self, prompt: str, transport, *, runs: int = 3, output_dir: str | Path) -> dict:
        """Observe fresh calls, never repair/retry, and compare exact UTF-8 bytes.

        A failed attempt is recorded and the remaining scheduled trials continue.
        MATCH is an observation, not semantic or grade-level certification.
        """
        import copy
        import hashlib
        from uuid import uuid4
        from .models import Qson, QsonEntry
        from .core import _resolve_resource

        if type(runs) is not int or runs < 2:
            raise ValueError("runs must be an integer >= 2")
        request = self.request(prompt)  # NYCH first; fixed snapshot across repeats
        root = Path(output_dir)
        manifest = json.loads(self._manifest_json)
        trace_path = _resolve_resource(root, manifest["trace"])
        # Evidence files occupy the root namespace, including their descendants.
        import re
        trace_root = trace_path.relative_to(root.resolve()).parts[0]
        if trace_root in {"request.json", "contract.json", "summary.json"} or re.fullmatch(r"attempt-[0-9]{4,}\.(json|txt)", trace_root):
            raise ValueError("Trace collision with reserved evidence path: " + manifest["trace"])
        root.mkdir(parents=True, exist_ok=False)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        qson = Qson(run_id="RUN_" + uuid4().hex)
        attempts = []
        contents = []
        hashes = []

        def persist(name, value):
            (root / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        persist("request.json", request)
        persist("contract.json", {"manifest": manifest, "GST": json.loads(self._gst_json), "G8SON": json.loads(self._gates_json), "ORK": json.loads(self._flow_json)})
        for sequence in range(1, runs + 1):
            attempt = {"sequence": sequence, "attempt_id": "ATT_" + uuid4().hex, "status": "ERROR"}
            try:
                raw = transport(copy.deepcopy(request))
                response = {"content": raw} if isinstance(raw, str) else copy.deepcopy(raw)
                # Preserve invalid JSON-compatible provider output for diagnosis too.
                try:
                    json.dumps(response, ensure_ascii=False)
                    attempt["response"] = response
                except (TypeError, ValueError):
                    attempt["response_type"] = type(response).__name__
                if not isinstance(response, dict) or not isinstance(response.get("content"), str) or not response["content"]:
                    raise ValueError("Transport must return nonempty string content")
                if "provider_status" in response and response["provider_status"] != "completed":
                    raise ValueError("Provider response was not completed: " + str(response["provider_status"]))
                content = response["content"]
                data = content.encode("utf-8")
                digest = hashlib.sha256(data).hexdigest()
                # Check metadata serializability before accepting the sample.
                json.dumps(response, ensure_ascii=False)
                attempt.update(status="OBSERVED", response=response, sha256=digest, utf8_bytes=len(data))
                (root / f"attempt-{sequence:04d}.txt").write_bytes(data)
                contents.append(content)
                hashes.append(digest)
            except Exception as exc:
                attempt["status"] = "ERROR"
                attempt["error"] = {"type": type(exc).__name__, "message": str(exc)}
                contents.append(None)
                hashes.append(None)
            attempts.append(attempt)
            qson.entries.append(QsonEntry(
                trace_id=attempt["attempt_id"], run_id=qson.run_id,
                gate_id="response-contract.byte-comparison", step=sequence,
                result="UNKNOWN", action="generate_once",
                llm_prompt=request["messages"][0]["content"],
                llm_output=copy.deepcopy(attempt),
                input_state={"user_prompt": prompt},
                comparison_status=attempt["status"],
            ))
            persist(f"attempt-{sequence:04d}.json", attempt)
            trace_path.write_text(json.dumps(qson.model_dump(by_alias=True), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        valid = all(a["status"] == "OBSERVED" for a in attempts)
        equal = valid and all(c.encode("utf-8") == contents[0].encode("utf-8") for c in contents[1:])
        outcome = "ERROR" if not valid else ("MATCH" if equal else "DIVERGENT")
        qson = qson.model_copy(update={"comparison_outcome": outcome})
        trace_path.write_text(json.dumps(qson.model_dump(by_alias=True), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        result = {"profile": "response-contract-v1", "run_id": qson.run_id, "runs": runs,
                  "outcome": outcome, "byte_equal": equal, "contents": contents,
                  "hashes": hashes, "attempts": attempts,
                  "claim": "Observed byte comparison only; no semantic-accuracy or grade-level certification, universal determinism, or causal attribution."}
        persist("summary.json", result)
        return result

    def request(self, prompt: str) -> dict:
        """Run canonical NYCH intake first; return messages only, no sampler controls."""
        intake = build_gst(prompt)
        context = {"GST": json.loads(self._gst_json), "G8SON": json.loads(self._gates_json), "NYCH_intake": intake}
        return {"messages": [{"role": "system", "content": PREFIX + json.dumps(context, ensure_ascii=False, indent=2)}, {"role": "user", "content": prompt}]}


def openai_transport(model: str):
    """Stdlib Responses adapter. No retries, sampler overrides, or normalization."""
    import os
    import urllib.request

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is required for live calls")
    if not isinstance(model, str) or not model:
        raise ValueError("model is required")

    def send(request):
        messages = request["messages"]
        payload = {"model": model, "instructions": messages[0]["content"],
                   "input": messages[1]["content"], "store": False}
        wire = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(wire, timeout=120) as response:
            raw = json.load(response)
        text = "".join(part["text"] for item in raw.get("output", [])
                       if item.get("type") == "message"
                       for part in item.get("content", []) if part.get("type") == "output_text")
        return {"content": text, "response_id": raw.get("id"), "model": raw.get("model"),
                "usage": raw.get("usage"), "system_fingerprint": raw.get("system_fingerprint"),
                "provider_status": raw.get("status"), "incomplete_details": raw.get("incomplete_details"),
                "provider_error": raw.get("error")}

    return send


def main(argv=None):
    """Request-only is offline; live mode explicitly requires model and evidence path."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit", type=Path)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model")
    parser.add_argument("--request-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.request_only and (not args.model or args.output_dir is None):
        parser.error("live mode requires --model and --output-dir")
    try:
        contract = ResponseContract.from_unit(args.unit)
        if args.request_only:
            print(json.dumps(contract.request(args.prompt), ensure_ascii=False, indent=2))
            return 0
        result = contract.verify(args.prompt, openai_transport(args.model), runs=args.runs, output_dir=args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["outcome"] == "MATCH" else (2 if result["outcome"] == "ERROR" else 1)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"response-contract: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
