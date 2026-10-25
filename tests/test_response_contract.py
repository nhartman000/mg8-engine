"""Offline response-contract-v1 tests; no paid inference."""
import json
import tempfile
import unittest
from pathlib import Path

from nych.gst_export import build_gst


class ResponseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gst = {"globals": {"voice": "active"}, "facts": {"subject": "Plants"}, "extra": ["retain"]}
        self.gate = {"gate_id": "G1", "atomic_requirements": [{"req_id": "R1", "requirement": "One sentence.", "extra": 7}], "metadata": {"retain": True}}
        self.flow = {"profile": "repeatability-experiment-v1", "action": "generate_once", "max_calls_per_trial": 1, "repair": False, "reuse_answers": False}
        self.manifest = {"mg8_version": "1.0", "unit_id": "test", "entry": "flow.ork", "state": ["context.gst"], "gates": ["conditions.g8son"], "trace": "trace/execution.qson", "metadata": {"runtime_profile": "response-contract-v1"}}
        for name, value in [("context.gst", self.gst), ("conditions.g8son", self.gate), ("flow.ork", self.flow), ("response.mg8", self.manifest)]:
            self.save(name, value)

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def load(self):
        from mg8_engine.response_contract import ResponseContract
        return ResponseContract.from_unit(self.root / "response.mg8")

    def test_rejects_unsupported_controls_duplicate_ids_and_resource_escapes(self):
        original = json.loads(json.dumps(self.manifest))
        for ref in ["../outside.gst", str(self.root / "context.gst")]:
            with self.subTest(ref=ref):
                self.manifest["state"] = [ref]
                self.save("response.mg8", self.manifest)
                with self.assertRaises(ValueError):
                    self.load()
        self.manifest = original
        self.save("response.mg8", self.manifest)
        outside = self.root.parent / (self.root.name + "-outside.gst")
        outside.write_text("{}")
        self.addCleanup(outside.unlink)
        (self.root / "escape.gst").symlink_to(outside)
        self.manifest["state"] = ["escape.gst"]
        self.save("response.mg8", self.manifest)
        with self.assertRaises(ValueError):
            self.load()
        self.manifest = original.copy()
        self.manifest["state"] = ["context.gst"]
        self.save("response.mg8", self.manifest)
        for key, value in [("routes", {"FAIL": "repeat"}), ("repair", True), ("max_calls_per_trial", 2), ("profile", "other")]:
            with self.subTest(control=key):
                changed = dict(self.flow, **{key: value})
                self.save("flow.ork", changed)
                with self.assertRaises(ValueError):
                    self.load()
        self.save("flow.ork", self.flow)
        self.gate["atomic_requirements"].append(dict(self.gate["atomic_requirements"][0]))
        self.save("conditions.g8son", self.gate)
        with self.assertRaises(ValueError):
            self.load()
        self.gate["atomic_requirements"].pop()
        self.save("conditions.g8son", self.gate)
        self.manifest["gates"].append("conditions.g8son")
        self.save("response.mg8", self.manifest)
        with self.assertRaises(ValueError):
            self.load()

    def test_multiple_gate_files_order_and_loaded_snapshot_survive_source_changes(self):
        second = {"gate_id": "G2", "atomic_requirements": [{"req_id": "R1", "requirement": "Retain all facts."}], "extra": {"custom": [1, 2]}}
        self.save("second.g8son", second)
        self.manifest["gates"].append("second.g8son")
        self.save("response.mg8", self.manifest)
        contract = self.load()
        before = contract.request("Explain.")
        self.save("context.gst", {"globals": {"changed": True}})
        self.save("conditions.g8son", {})
        self.assertEqual(before, contract.request("Explain."))
        context = json.loads(before["messages"][0]["content"].split("\n", 1)[1])
        self.assertEqual(context["G8SON"], [self.gate, second])

    def test_all_manifest_bindings_are_confined(self):
        for key, value in [("entry", "../flow.ork"), ("gates", ["../gate.g8son"]), ("trace", "../execution.qson"), ("trace", str(self.root / "execution.qson")), ("state", ["context.gst", "context.gst"]), ("trace", "invalid.json")]:
            with self.subTest(key=key, value=value):
                manifest = dict(self.manifest, **{key: value})
                self.save("response.mg8", manifest)
                with self.assertRaises(ValueError):
                    self.load()

    def test_verify_calls_fresh_transport_preserves_bytes_and_audits(self):
        import hashlib
        from dataclasses import FrozenInstanceError
        contract = self.load()
        with self.assertRaises(FrozenInstanceError):
            contract._gst_json = "{}"
        seen = []
        def transport(request):
            seen.append(json.loads(json.dumps(request)))
            request["messages"].clear()
            return {"content": " Café.\n", "response_id": str(len(seen)), "model": "test", "usage": {"input_tokens_details": {"cached_tokens": 0}}, "system_fingerprint": "fp"}
        out = self.root / "evidence"
        result = contract.verify("Explain.", transport, runs=3, output_dir=out)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen, [seen[0]] * 3)
        self.assertTrue(result["byte_equal"])
        self.assertEqual(result["outcome"], "MATCH")
        self.assertEqual(result["contents"], [" Café.\n"] * 3)
        self.assertEqual(result["hashes"], [hashlib.sha256(" Café.\n".encode()).hexdigest()] * 3)
        self.assertEqual((out / "attempt-0001.txt").read_bytes(), " Café.\n".encode())
        qson = json.loads((out / "trace/execution.qson").read_text())
        self.assertEqual([e["step"] for e in qson["entries"]], [1, 2, 3])
        self.assertEqual(len({e["trace_id"] for e in qson["entries"]}), 3)
        self.assertEqual(json.loads((out / "summary.json").read_text()), result)
        with self.assertRaises(FileExistsError):
            contract.verify("Explain.", transport, runs=3, output_dir=out)
        self.assertEqual(len(seen), 3)
        for runs in [1, True, 2.5]:
            with self.assertRaises(ValueError):
                contract.verify("Explain.", transport, runs=runs, output_dir=self.root / "bad")

    def test_reserved_trace_collisions_are_rejected_before_output_or_transport(self):
        from dataclasses import replace
        from unittest.mock import Mock
        contract = self.load()
        reserved = ["request.json", "contract.json", "summary.json", "attempt-0001.json", "attempt-0002.txt", "attempt-9999.json", "attempt-10000.txt"]
        for index, trace in enumerate([path for name in reserved for path in (name, name + "/execution.qson")]):
            with self.subTest(trace=trace):
                manifest = dict(self.manifest, trace=trace)
                if trace.endswith(".qson"):
                    self.save("response.mg8", manifest)
                    candidate = self.load()
                else:
                    # Exercise verify defensively, even for directly supplied snapshots.
                    candidate = replace(contract, _manifest_json=json.dumps(manifest))
                transport = Mock(return_value="A")
                out = self.root / f"collision-{index}"
                with self.assertRaisesRegex(ValueError, "collision"):
                    candidate.verify("Explain.", transport, runs=2, output_dir=out)
                transport.assert_not_called()
                self.assertFalse(out.exists())

    def test_verify_divergence_and_invalid_samples_are_not_matches(self):
        for index, values in enumerate([["A", "A\n", "A"], [None, "A", "A"], [{}, "A", "A"], [{"content": None}, "A", "A"], ["", "A", "A"], [3, "A", "A"], ["A", RuntimeError("provider failed"), "A"]]):
            with self.subTest(values=values):
                pending = iter(values)
                def transport(request):
                    value = next(pending)
                    if isinstance(value, Exception):
                        raise value
                    return value
                out = self.root / str(index)
                result = self.load().verify("Explain.", transport, runs=3, output_dir=out)
                self.assertFalse(result["byte_equal"])
                self.assertEqual(result["outcome"], "DIVERGENT" if index == 0 else "ERROR")
                self.assertEqual(len(result["attempts"]), 3)
                self.assertEqual(len(json.loads((out / "trace/execution.qson").read_text())["entries"]), 3)
                if index:
                    self.assertIn("ERROR", [a["status"] for a in result["attempts"]])
                self.assertEqual((out / "summary.json").exists(), True)

    def test_cli_request_only_needs_no_credentials_or_network(self):
        import os
        import subprocess
        import sys
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        command = [sys.executable, "-m", "mg8_engine.response_contract", str(self.root / "response.mg8"), "--prompt", "Explain.", "--request-only"]
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.load().request("Explain."))
        result = subprocess.run(command[:-1], capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)

    def test_evidence_retains_flow_failed_output_and_comparison_not_certification(self):
        result = self.load().verify("Explain.", lambda request: {"content": None, "response_id": "bad"}, runs=2, output_dir=self.root / "audit")
        qson = json.loads((self.root / "audit/trace/execution.qson").read_text())
        self.assertEqual(qson["comparison_outcome"], "ERROR")
        self.assertTrue(all(e["result"] == "UNKNOWN" for e in qson["entries"]))
        self.assertEqual(result["attempts"][0]["response"], {"content": None, "response_id": "bad"})
        snapshot = json.loads((self.root / "audit/contract.json").read_text())
        self.assertEqual(snapshot["ORK"], self.flow)

    def test_non_utf8_output_is_error_with_preserved_audit(self):
        result = self.load().verify("Explain.", lambda request: "\ud800", runs=2, output_dir=self.root / "unicode")
        self.assertEqual(result["outcome"], "ERROR")
        self.assertFalse(result["byte_equal"])
        self.assertEqual(json.loads((self.root / "unicode/attempt-0001.json").read_text())["response"]["content"], "\ud800")

    def test_failed_content_persistence_cannot_be_a_match(self):
        from unittest.mock import patch
        with patch.object(Path, "write_bytes", side_effect=OSError("disk write failed")):
            result = self.load().verify("Explain.", lambda request: "A", runs=2, output_dir=self.root / "disk-error")
        self.assertEqual(result["outcome"], "ERROR")
        self.assertFalse(result["byte_equal"])
        self.assertTrue(all(a["status"] == "ERROR" for a in result["attempts"]))

    def test_live_transport_exact_payload_and_text_no_retry(self):
        from unittest.mock import patch
        from mg8_engine.response_contract import openai_transport
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps({"status": "completed", "id": "resp", "model": "model", "usage": {"input_tokens": 3}, "output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": " A"}, {"type": "output_text", "text": "\nB "}]}]}).encode()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}), patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            transport = openai_transport("test-model")
            request = self.load().request("Explain.")
            response = transport(request)
            sent = urlopen.call_args.args[0]
            self.assertEqual(sent.full_url, "https://api.openai.com/v1/responses")
            self.assertEqual(json.loads(sent.data), {"model": "test-model", "instructions": request["messages"][0]["content"], "input": "Explain.", "store": False})
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)
            self.assertEqual(response["content"], " A\nB ")
            self.assertEqual(response["response_id"], "resp")
            self.assertEqual(response["usage"], {"input_tokens": 3})
            urlopen.side_effect = OSError("offline")
            with self.assertRaises(OSError):
                transport(request)
            self.assertEqual(urlopen.call_count, 2)

    def test_live_transport_missing_status_cannot_match(self):
        import io
        from unittest.mock import patch
        from mg8_engine.response_contract import openai_transport
        for index, status in enumerate([{}, {"status": None}]):
            with self.subTest(status=status):
                raw = dict(status, id="partial", usage={"output_tokens": 2}, output=[{"type": "message", "content": [{"type": "output_text", "text": "Partial text."}]}])
                with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}), patch("urllib.request.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(raw).encode())) as urlopen:
                    out = self.root / f"missing-status-{index}"
                    result = self.load().verify("Explain.", openai_transport("test-model"), runs=2, output_dir=out)
                self.assertEqual(result["outcome"], "ERROR")
                self.assertFalse(result["byte_equal"])
                self.assertEqual(urlopen.call_count, 2)
                for attempt in result["attempts"]:
                    self.assertEqual(attempt["status"], "ERROR")
                    self.assertIsNone(attempt["response"]["provider_status"])
                    self.assertEqual(attempt["response"]["content"], "Partial text.")
                    self.assertEqual(attempt["response"]["usage"], raw["usage"])

    def test_live_transport_rejects_incomplete_provider_response(self):
        from unittest.mock import patch
        from mg8_engine.response_contract import openai_transport
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps({"status": "incomplete", "id": "partial", "model": "test-model", "usage": {"output_tokens": 7}, "incomplete_details": {"reason": "max_output_tokens"}, "error": {"message": "provider detail"}, "output": [{"type": "message", "content": [{"type": "output_text", "text": "Partial text."}]}]}).encode()
        out = self.root / "incomplete"
        with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}), patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            result = self.load().verify("Explain.", openai_transport("test-model"), runs=2, output_dir=out)
        self.assertEqual(result["outcome"], "ERROR")
        self.assertFalse(result["byte_equal"])
        self.assertEqual(result["contents"], [None, None])
        self.assertEqual(urlopen.call_count, 2)
        for attempt in result["attempts"]:
            self.assertEqual(attempt["status"], "ERROR")
            self.assertIn("completed", attempt["error"]["message"])
            response = attempt["response"]
            self.assertEqual(response["content"], "Partial text.")
            self.assertEqual(response["response_id"], "partial")
            self.assertEqual(response["model"], "test-model")
            self.assertEqual(response["provider_status"], "incomplete")
            self.assertEqual(response["usage"], {"output_tokens": 7})
            self.assertEqual(response["incomplete_details"], {"reason": "max_output_tokens"})
            self.assertEqual(response["provider_error"], {"message": "provider detail"})
            self.assertEqual(json.loads((out / f"attempt-{attempt['sequence']:04d}.json").read_text()), attempt)
        self.assertEqual(json.loads((out / "summary.json").read_text()), result)
        qson = json.loads((out / "trace/execution.qson").read_text())
        self.assertEqual([entry["llm_output"] for entry in qson["entries"]], result["attempts"])

    def test_request_preserves_complete_context_and_exact_experiment_order(self):
        contract = self.load()
        prompt = "Explain plants.\n"
        request = contract.request(prompt)
        prefix = "Answer the user prompt by satisfying the active GST globals and all G8SON atomic requirements. Facts are supplied as semantic inputs, not a prior response. Do not output your analysis, gate verdicts or instructions. Emit only the requested sentence.\n"
        self.assertEqual(request, {"messages": [{"role": "system", "content": prefix + json.dumps({"GST": self.gst, "G8SON": [self.gate], "NYCH_intake": build_gst(prompt)}, ensure_ascii=False, indent=2)}, {"role": "user", "content": prompt}]})
        self.assertEqual(request, contract.request(prompt))
        request["messages"].clear()
        self.assertEqual(len(contract.request(prompt)["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
