"""Regressions for the third-opinion review of 2026-11-03 (engine-nych-review.md findings 2, 3, 5)."""
import copy
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from nych.gst_export import build_gst

from mg8_engine.pipeline import (PipelineError, run_pipeline, validate_congruence_response,
                                 validate_mapping_plan)
from test_pipeline import TEXT, congruence_pass_response, mapping_plan_from_gst


class FlowCoverageOrderTests(unittest.TestCase):
    def setUp(self):
        self.gst = build_gst(TEXT)
        self.response = congruence_pass_response()

    def test_declared_order_accepted(self):
        validate_congruence_response(self.response, self.gst)

    def test_partial_flow_rejected(self):
        self.response["flow"] = ["g.check"]
        with self.assertRaisesRegex(PipelineError, "ORK_FLOW_NOT_COMPLETE_DECLARED_ORDER"):
            validate_congruence_response(self.response, self.gst)

    def test_reversed_flow_rejected(self):
        self.response["flow"] = ["g.done", "g.cross_check", "g.check"]
        with self.assertRaisesRegex(PipelineError, "ORK_FLOW_NOT_COMPLETE_DECLARED_ORDER"):
            validate_congruence_response(self.response, self.gst)

    def test_repeated_gate_in_flow_rejected(self):
        self.response["flow"] = ["g.check", "g.cross_check", "g.done", "g.done"]
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_duplicate_gate_id_across_files_rejected(self):
        self.response["g8son_files"][2]["gates"][0]["id"] = "g.check"
        self.response["flow"] = ["g.check", "g.cross_check", "g.check"]
        with self.assertRaisesRegex(PipelineError, "G8SON_DUPLICATE_GATE_ID"):
            validate_congruence_response(self.response, self.gst)


class ModalityTableReplacementTests(unittest.TestCase):
    def test_supplied_table_cannot_replace_canonical_glyphs(self):
        gst = build_gst(TEXT)
        table = gst["nych_pretext"]["modality_operators"]
        gst["nych_pretext"]["modality_operators"] = {k: f"NONCANON-{i}" for i, k in enumerate(table)}
        plan = mapping_plan_from_gst(gst)
        plan["mappings"][0]["glyph"] = "👀"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(plan, gst)

    def test_supplied_noncanonical_values_are_also_protected(self):
        gst = build_gst(TEXT)
        gst["nych_pretext"]["modality_operators"] = {"extra_op": "🛸"}
        plan = mapping_plan_from_gst(gst)
        plan["mappings"][0]["glyph"] = "🛸"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(plan, gst)


class TracePersistenceTests(unittest.TestCase):
    def test_trace_qson_flushed_and_sequence_monotonic(self):
        gst = build_gst(TEXT)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(gst, lambda p: mapping_plan_from_gst(gst),
                                  lambda p: congruence_pass_response(), tmp)
            manifest = json.loads((Path(tmp) / "unit.mg8").read_text())
            trace = json.loads((Path(tmp) / manifest["trace"]).read_text())
            output = json.loads((Path(tmp) / "output.mg8").read_text())
        entries = result["unit"].qson.entries
        self.assertEqual(len(trace["entries"]), len(entries))
        self.assertEqual(len(trace["entries"]), len(output["qson"]["entries"]))
        self.assertGreaterEqual(len(entries), 6)
        seqs = [e["step"] for e in trace["entries"]]
        self.assertEqual(seqs, list(range(len(seqs))))
        self.assertEqual([e["trace_id"] for e in trace["entries"]], [e.trace_id for e in entries])
        gate = [e for e in trace["entries"] if e["gate_id"] == "g.check"][0]
        self.assertIn("gate_step", gate)


class ReadmeApiTests(unittest.TestCase):
    def test_readme_documents_current_run_pipeline_signature(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("run_pipeline(gst_payload, mapping_llm, out_dir)", readme)
        self.assertIn("run_pipeline(gst_payload, mapping_llm, congruence_llm, out_dir)", readme)
        params = list(inspect.signature(run_pipeline).parameters)[:4]
        self.assertEqual(params, ["gst_payload", "mapping_llm", "congruence_llm", "out_dir"])

    def test_readme_quickstart_does_not_use_conflicting_double_editable(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("pip install -e . -e ../nych", readme)


if __name__ == "__main__":
    unittest.main()
