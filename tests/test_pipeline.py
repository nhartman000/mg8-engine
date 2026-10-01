import json
import tempfile
import unittest
from pathlib import Path

from nych.gst_export import build_gst

from mg8_engine.core import load_mg8
from mg8_engine.pipeline import (
    PipelineError,
    build_mapping_prompt,
    run_pipeline,
    validate_plan,
)

TEXT = "Re-ran both test suites after changes"
MEDICAL = "gave Dr. Chen the metformin results"


def plan_from_gst(gst):
    """A rule-abiding fake first-LLM-call plan derived from the pretext."""
    mappings = [
        {"word": d["word"], "symbol_id": d["id"], "glyph": "🧪"}
        for d in gst["nych_pretext"]["needs_mapping"]
    ]
    gates = [
        {"id": "g.check", "type": "tote_test",
         "condition": "exit when the declared state is observed",
         "outcomes": {"PASS": "exit", "FAIL": "repeat"}},
        {"id": "g.done", "type": "condition",
         "condition": "finalize", "outcomes": {"PASS": "exit"}},
    ]
    return {
        "mappings": mappings,
        "g8son_files": [{"file_id": "loop.1", "gates": gates}],
        "flow": ["g.check", "g.done"],
    }


class PlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.gst = build_gst(TEXT)
        self.plan = plan_from_gst(self.gst)

    def test_valid_plan_passes(self):
        validate_plan(self.plan, self.gst)  # no raise

    def test_mapping_without_skeleton_rejected(self):
        self.plan["mappings"][0]["symbol_id"] = "gestalt.wrong"
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_unrequested_mapping_rejected(self):
        self.plan["mappings"].append(
            {"word": "surprise", "symbol_id": "gestalt.srprs"})
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_modality_operator_remap_rejected(self):
        self.plan["mappings"].append(
            {"word": "execute", "symbol_id": "gestalt.xct"})
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_protected_term_mapping_rejected(self):
        gst = build_gst(MEDICAL)
        plan = plan_from_gst(gst)
        protected_words = [p["word"] for p in gst["nych_pretext"]["protected"]]
        self.assertIn("metformin", protected_words)
        plan["mappings"].append(
            {"word": "metformin", "symbol_id": "gestalt.mtfrmn"})
        with self.assertRaises(PipelineError) as ctx:
            validate_plan(plan, gst)
        self.assertIn("protected", str(ctx.exception))

    def test_pinned_word_must_keep_its_mapping(self):
        self.gst["nych_pretext"]["pinned"] = [
            {"word": "suites", "symbol_id": "gestalt.sts",
             "tag": "#temp-invariant"}]
        self.plan["mappings"].append(
            {"word": "suites", "symbol_id": "gestalt.sts.other"})
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_g8son_file_gate_count_bounds(self):
        self.plan["g8son_files"][0]["gates"] = (
            self.plan["g8son_files"][0]["gates"] * 2)  # 4 gates
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_gate_without_exit_condition_rejected(self):
        self.plan["g8son_files"][0]["gates"][0] = {"id": "g.check",
                                                   "type": "tote_test"}
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)

    def test_flow_referencing_unknown_gate_rejected(self):
        self.plan["flow"] = ["g.check", "g.ghost"]
        with self.assertRaises(PipelineError):
            validate_plan(self.plan, self.gst)


class PipelineEndToEndTests(unittest.TestCase):
    def run_it(self, text=TEXT, **kwargs):
        gst = build_gst(text)
        captured = {}

        def mapping_llm(prompt):
            captured["prompt"] = prompt
            return plan_from_gst(gst)

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(gst, mapping_llm, tmp, **kwargs)
            files = {p.name for p in Path(tmp).iterdir()}
            output = json.loads((Path(tmp) / "output.mg8").read_text())
            reloaded = load_mg8(Path(tmp) / "output.mg8")
        return gst, result, files, output, reloaded, captured

    def test_unit_files_written_and_runnable(self):
        gst, result, files, output, reloaded, _ = self.run_it()
        self.assertLessEqual(
            {"pretext.gst", "gates.1.g8son", "flow.ork", "trace.qson",
             "unit.mg8", "output.mg8", "canon.1.1.gitson"},
            files,
        )
        # engine executed the flow and recorded gate-level qson entries
        gate_ids = [e.gate_id for e in result["unit"].qson.entries]
        self.assertIn("g.check", gate_ids)
        self.assertIn("g.done", gate_ids)

    def test_mapping_audit_entry_first_in_qson(self):
        _, result, _, _, _, _ = self.run_it()
        first = result["unit"].qson.entries[0]
        self.assertEqual(first.gate_id, "nych.gestalt_mapping")
        self.assertEqual(first.sequence, 0)
        ids = [m["symbol_id"] for m in first.llm_output["mappings"]]
        self.assertTrue(any(i.startswith("gestalt.") for i in ids))

    def test_output_mg8_reloadable_by_engine(self):
        _, _, _, _, reloaded, _ = self.run_it()
        self.assertEqual(reloaded.g8son.gates[0].gate_id, "g.check")
        self.assertTrue(reloaded.qson.entries)

    def test_pins_returned_for_caller_session(self):
        gst, result, _, _, _, _ = self.run_it()
        words = {m["word"] for m in result["pins"]}
        needs = {d["word"] for d in gst["nych_pretext"]["needs_mapping"]}
        self.assertEqual(words, needs)

    def test_prompt_carries_protected_terms_and_rules(self):
        _, _, _, _, _, captured = self.run_it(text=MEDICAL)
        self.assertIn("metformin", captured["prompt"])
        self.assertIn("PROTECTED TERMS", captured["prompt"])
        self.assertIn("INVARIANT", captured["prompt"])

    def test_invalid_llm_plan_rejected_not_run(self):
        gst = build_gst(TEXT)

        def bad_llm(_prompt):
            return {"mappings": [], "g8son_files": [], "flow": []}

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PipelineError):
                run_pipeline(gst, bad_llm, tmp)
            self.assertNotIn("output.mg8",
                             {p.name for p in Path(tmp).iterdir()})


if __name__ == "__main__":
    unittest.main()
