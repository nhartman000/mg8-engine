import json
import tempfile
import unittest
from pathlib import Path

from mg8_engine.keeper import (
    GateKeeper,
    build_gated_prompt,
    load_context_gst,
    load_requirement_g8son,
)
from mg8_engine.models import Gst

REQ_G8SON = {
    "gate_id": "G_EXPLANATION",
    "gate_name": "Scientific Explanation",
    "atomic_requirements": [
        {"req_id": "R1", "requirement": "Provide a clear scientific definition"},
        {"req_id": "R2", "requirement": "Keep explanation simple"},
    ],
}

CTX_GST = {
    "context_id": "CTX_TEST",
    "interpretation_posture": "Factual",
    "primary_modality": "Scientific",
    "constraints": ["Be precise and accurate"],
}


def write_fixtures(tmp):
    tmp = Path(tmp)
    (tmp / "g8son").mkdir()
    (tmp / "gst").mkdir()
    (tmp / "g8son/exp.g8son").write_text(json.dumps(REQ_G8SON))
    (tmp / "gst/ctx.gst").write_text(json.dumps(CTX_GST))
    project = {
        "project_name": "t", "project_id": "T1",
        "g8son_gates": ["g8son/exp.g8son"],
        "gst_context": "gst/ctx.gst",
        "seed": 7,
    }
    (tmp / "proj.mg8").write_text(json.dumps(project))
    return tmp / "proj.mg8"


class CompatibilityLoaderTests(unittest.TestCase):
    def test_requirement_profile_maps_to_canonical_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.g8son"
            p.write_text(json.dumps(REQ_G8SON))
            gates = load_requirement_g8son(p)
        self.assertEqual(gates[0].gate_id, "G_EXPLANATION")
        self.assertEqual(gates[0].type, "requirement")
        self.assertEqual(len(gates[0].conditions), 2)
        self.assertEqual(gates[0].outcomes, {"PASS": "exit", "FAIL": "repeat"})

    def test_context_gst_loads_via_extra_allow(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.gst"
            p.write_text(json.dumps(CTX_GST))
            gst = load_context_gst(p)
        self.assertEqual(gst.model_extra["interpretation_posture"], "Factual")
        self.assertEqual(gst.constraints, ["Be precise and accurate"])

    def test_from_project_resolves_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            keeper = GateKeeper.from_project(write_fixtures(tmp))
        self.assertEqual(keeper.seed, 7)
        self.assertEqual(keeper.gates[0].gate_id, "G_EXPLANATION")


class PromptDeterminismTests(unittest.TestCase):
    def setUp(self):
        self.gst = Gst.model_validate(CTX_GST)
        self.gates = []
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.g8son"
            p.write_text(json.dumps(REQ_G8SON))
            self.gates = load_requirement_g8son(p)

    def test_identical_inputs_give_identical_messages(self):
        a = build_gated_prompt(self.gst, self.gates, "What is photosynthesis?")
        b = build_gated_prompt(self.gst, self.gates, "What is photosynthesis?")
        self.assertEqual(a, b)

    def test_no_timestamp_or_cache_buster_in_prompt(self):
        msgs = build_gated_prompt(self.gst, self.gates, "q")
        self.assertNotIn("unique-id", msgs[0]["content"])
        self.assertNotIn("time", msgs[0]["content"].lower().split("gates")[0])

    def test_prompt_contains_gates_context_and_requirements(self):
        system = build_gated_prompt(self.gst, self.gates, "q")[0]["content"]
        self.assertIn("Posture: Factual", system)
        self.assertIn("G_EXPLANATION", system)
        self.assertIn("Keep explanation simple", system)
        self.assertIn("Be precise and accurate", system)

    def test_keeper_request_is_reproducible(self):
        k = GateKeeper(self.gst, self.gates, seed=42)
        self.assertEqual(k.request("q"), k.request("q"))
        self.assertEqual(k.request("q")["temperature"], 0.0)
        self.assertEqual(k.request("q")["seed"], 42)


LONG_ANSWER = (
    "Photosynthesis is the process by which green plants, algae, and some "
    "bacteria convert light energy, water, and carbon dioxide into glucose "
    "and oxygen inside their chloroplasts."
)


class ReproducibilityTests(unittest.TestCase):
    def setUp(self):
        self.keeper = GateKeeper(Gst.model_validate(CTX_GST), [])

    def test_deterministic_transport_verified(self):
        calls = []

        def transport(request):
            calls.append(request)
            return {"content": LONG_ANSWER, "response_id": f"r{len(calls)}",
                    "system_fingerprint": "fp_a"}

        result = self.keeper.verify_reproducibility("q", transport, runs=3)
        self.assertTrue(result["deterministic"])
        self.assertEqual(result["fingerprint_consistent"], True)
        self.assertEqual(result["evidence_level"], "inconclusive")
        self.assertIn("no-gates control", result["evidence"])
        # all requests bit-identical
        self.assertTrue(all(c == calls[0] for c in calls))
        # qson audit carries fingerprint and PASS results
        entries = result["qson"].entries
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(e.result == "PASS" for e in entries))
        self.assertEqual(entries[0].model_extra["system_fingerprint"], "fp_a")

    def test_substantial_match_across_fingerprints_is_suggestive_not_proof(self):
        fps = iter(["fp_a", "fp_b"])

        def transport(_request):
            return {"content": LONG_ANSWER, "response_id": "r",
                    "system_fingerprint": next(fps)}

        result = self.keeper.verify_reproducibility("q", transport)
        self.assertTrue(result["deterministic"])
        self.assertEqual(result["fingerprint_consistent"], False)
        self.assertEqual(result["evidence_level"], "suggestive")
        self.assertIn("not proof", result["evidence"])
        self.assertNotIn("strong", result["evidence"])

    def test_short_match_is_weak_even_across_fingerprints(self):
        fps = iter(["fp_a", "fp_b"])

        def transport(_request):
            return {"content": "same", "response_id": "r",
                    "system_fingerprint": next(fps)}

        result = self.keeper.verify_reproducibility("q", transport)
        self.assertTrue(result["deterministic"])
        self.assertEqual(result["evidence_level"], "weak")
        self.assertEqual(result["word_count"], 1)

    def test_min_substantial_words_is_configurable(self):
        fps = iter(["fp_a", "fp_b"])

        def transport(_request):
            return {"content": "a b c", "response_id": "r",
                    "system_fingerprint": next(fps)}

        result = self.keeper.verify_reproducibility(
            "q", transport, min_substantial_words=3)
        self.assertEqual(result["evidence_level"], "suggestive")

    def test_divergence_disclosed_not_retried(self):
        outputs = iter(["answer one", "answer two"])

        def transport(_request):
            return next(outputs)

        result = self.keeper.verify_reproducibility("q", transport)
        self.assertFalse(result["deterministic"])
        self.assertIn("divergent", result["evidence"])
        self.assertEqual(result["contents"], ["answer one", "answer two"])
        self.assertTrue(all(e.result == "FAIL" for e in result["qson"].entries))

    def test_missing_fingerprint_weakens_evidence(self):
        result = self.keeper.verify_reproducibility(
            "q", lambda _r: "same answer")
        self.assertTrue(result["deterministic"])
        self.assertIsNone(result["fingerprint_consistent"])
        self.assertEqual(result["evidence_level"], "weak")

    def test_missing_fingerprint_is_weak_even_when_substantial(self):
        result = self.keeper.verify_reproducibility(
            "q", lambda _r: LONG_ANSWER)
        self.assertEqual(result["evidence_level"], "weak")
        self.assertIn("no system_fingerprint", result["evidence"])

    def test_fewer_than_two_runs_rejected(self):
        with self.assertRaises(ValueError):
            self.keeper.verify_reproducibility("q", lambda _r: "x", runs=1)


if __name__ == "__main__":
    unittest.main()
