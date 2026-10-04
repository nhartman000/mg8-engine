import copy
import json
import tempfile
import unittest
from pathlib import Path

from nych.gst_export import build_gst

from mg8_engine.core import load_mg8
from mg8_engine.pipeline import (
    CongruenceNotPass,
    PipelineError,
    build_congruence_prompt,
    build_mapping_prompt,
    run_pipeline,
    validate_congruence_response,
    validate_mapping_plan,
)

TEXT = "Re-ran both test suites after changes"
MEDICAL = "gave Dr. Chen the metformin results"

THREE_GATE_FILES = [
    {"file_id": "loop.1", "gates": [
        {"id": "g.check", "type": "tote_test",
         "condition": "exit when the declared state is observed",
         "outcomes": {"PASS": "exit", "FAIL": "repeat"}},
    ]},
    {"file_id": "loop.2", "gates": [
        {"id": "g.cross_check", "type": "condition",
         "condition": "cross-check the observed state",
         "outcomes": {"PASS": "continue", "FAIL": "stop"}},
    ]},
    {"file_id": "loop.3", "gates": [
        {"id": "g.done", "type": "condition",
         "condition": "finalize", "outcomes": {"PASS": "exit"}},
    ]},
]
THREE_GATE_FLOW = ["g.check", "g.cross_check", "g.done"]


def mapping_plan_from_gst(gst):
    """A rule-abiding fake first-LLM-call (mapping-only) plan."""
    mappings = [
        {"word": d["word"], "symbol_id": d["id"], "glyph": "🧪"}
        for d in gst["nych_pretext"]["needs_mapping"]
    ]
    return {"mappings": mappings}


def congruence_pass_response():
    """A rule-abiding fake second-LLM-call response: congruent, three
    files, each 1-3 gates with an exit, flow covering all three."""
    return {
        "congruence_result": "PASS",
        "g8son_files": copy.deepcopy(THREE_GATE_FILES),
        "flow": list(THREE_GATE_FLOW),
    }


class MappingPlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.gst = build_gst(TEXT)
        self.plan = mapping_plan_from_gst(self.gst)

    def test_valid_plan_passes(self):
        validate_mapping_plan(self.plan, self.gst)  # no raise

    def test_mapping_without_skeleton_rejected(self):
        self.plan["mappings"][0]["symbol_id"] = "gestalt.wrong"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_unrequested_mapping_rejected(self):
        self.plan["mappings"].append(
            {"word": "surprise", "symbol_id": "gestalt.srprs"})
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_modality_operator_remap_rejected(self):
        self.plan["mappings"].append(
            {"word": "execute", "symbol_id": "gestalt.xct"})
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_operator_glyph_given_to_ordinary_word_rejected(self):
        self.plan["mappings"][0]["glyph"] = "👀"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_operator_glyph_inside_symbol_id_rejected(self):
        m = self.plan["mappings"][0]
        m["symbol_id"] = m["symbol_id"] + "💪"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_operator_glyph_without_variation_selector_rejected(self):
        self.plan["mappings"][0]["glyph"] = "\U0001F5EF"  # 🗯 without FE0F
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_canonical_operators_enforced_even_if_pretext_omits_them(self):
        self.gst["nych_pretext"]["modality_operators"] = {}
        self.plan["mappings"][0]["glyph"] = "👀"
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_protected_term_mapping_rejected(self):
        gst = build_gst(MEDICAL)
        plan = mapping_plan_from_gst(gst)
        protected_words = [p["word"] for p in gst["nych_pretext"]["protected"]]
        self.assertIn("metformin", protected_words)
        plan["mappings"].append(
            {"word": "metformin", "symbol_id": "gestalt.mtfrmn"})
        with self.assertRaises(PipelineError) as ctx:
            validate_mapping_plan(plan, gst)
        self.assertIn("protected", str(ctx.exception))

    def test_pinned_word_must_keep_its_mapping(self):
        self.gst["nych_pretext"]["pinned"] = [
            {"word": "suites", "symbol_id": "gestalt.sts",
             "tag": "#temp-invariant"}]
        self.plan["mappings"].append(
            {"word": "suites", "symbol_id": "gestalt.sts.other"})
        with self.assertRaises(PipelineError):
            validate_mapping_plan(self.plan, self.gst)

    def test_mapping_prompt_never_mentions_g8son_or_flow_as_output(self):
        prompt = build_mapping_prompt(self.gst)
        self.assertIn("mappings", prompt)
        self.assertNotIn('"g8son_files"', prompt)
        self.assertNotIn('"flow"', prompt)


class CongruenceResponseValidationTests(unittest.TestCase):
    def setUp(self):
        self.gst = build_gst(TEXT)
        self.response = congruence_pass_response()

    def test_valid_pass_response_passes(self):
        validate_congruence_response(self.response, self.gst)  # no raise

    def test_unknown_result_literal_rejected(self):
        self.response["congruence_result"] = "UNKNOWN"
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_unresolved_result_literal_rejected(self):
        self.response["congruence_result"] = "UNRESOLVED"
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_fail_with_no_files_raises_congruence_not_pass(self):
        response = {"congruence_result": "FAIL"}
        with self.assertRaises(CongruenceNotPass) as ctx:
            validate_congruence_response(response, self.gst)
        self.assertEqual(ctx.exception.result, "FAIL")

    def test_intermediate_with_no_files_raises_congruence_not_pass(self):
        response = {"congruence_result": "INTERMEDIATE"}
        with self.assertRaises(CongruenceNotPass) as ctx:
            validate_congruence_response(response, self.gst)
        self.assertEqual(ctx.exception.result, "INTERMEDIATE")

    def test_fail_with_files_anyway_is_a_hard_rejection(self):
        self.response["congruence_result"] = "FAIL"
        with self.assertRaises(PipelineError) as ctx:
            validate_congruence_response(self.response, self.gst)
        self.assertNotIsInstance(ctx.exception, CongruenceNotPass)

    def test_wrong_file_count_rejected(self):
        self.response["g8son_files"] = self.response["g8son_files"][:2]
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_four_files_rejected(self):
        extra = copy.deepcopy(THREE_GATE_FILES[0])
        extra["file_id"] = "loop.4"
        self.response["g8son_files"].append(extra)
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_g8son_file_gate_count_bounds(self):
        self.response["g8son_files"][0]["gates"] = (
            self.response["g8son_files"][0]["gates"] * 4)  # 4 gates
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_gate_without_exit_condition_rejected(self):
        self.response["g8son_files"][0]["gates"][0] = {"id": "g.check",
                                                        "type": "tote_test"}
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_flow_referencing_unknown_gate_rejected(self):
        self.response["flow"] = ["g.check", "g.ghost", "g.done"]
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_pass_with_no_flow_rejected(self):
        self.response["flow"] = []
        with self.assertRaises(PipelineError):
            validate_congruence_response(self.response, self.gst)

    def test_congruence_prompt_mentions_status_canon(self):
        prompt = build_congruence_prompt(self.gst, [])
        self.assertIn("PASS", prompt)
        self.assertIn("FAIL", prompt)
        self.assertIn("INTERMEDIATE", prompt)
        self.assertIn("exactly THREE", prompt)


class PipelineEndToEndTests(unittest.TestCase):
    def run_it(self, text=TEXT, congruence_response=None, **kwargs):
        gst = build_gst(text)
        captured = {}

        def mapping_llm(prompt):
            captured["mapping_prompt"] = prompt
            return mapping_plan_from_gst(gst)

        def congruence_llm(prompt):
            captured["congruence_prompt"] = prompt
            return (congruence_response if congruence_response is not None
                    else congruence_pass_response())

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(gst, mapping_llm, congruence_llm, tmp, **kwargs)
            files = {p.name for p in Path(tmp).iterdir()}
            output = json.loads((Path(tmp) / "output.mg8").read_text())
            reloaded = load_mg8(Path(tmp) / "output.mg8")
        return gst, result, files, output, reloaded, captured

    def test_unit_files_written_and_runnable(self):
        gst, result, files, output, reloaded, _ = self.run_it()
        self.assertLessEqual(
            {"pretext.gst", "gates.1.g8son", "gates.2.g8son", "gates.3.g8son",
             "flow.ork", "trace.qson", "unit.mg8", "output.mg8",
             "canon.1.1.gitson"},
            files,
        )
        # engine executed the flow across all three files and recorded
        # gate-level qson entries for each
        gate_ids = [e.gate_id for e in result["unit"].qson.entries]
        self.assertIn("g.check", gate_ids)
        self.assertIn("g.cross_check", gate_ids)
        self.assertIn("g.done", gate_ids)

    def test_mapping_audit_entry_first_in_qson(self):
        _, result, _, _, _, _ = self.run_it()
        first = result["unit"].qson.entries[0]
        self.assertEqual(first.gate_id, "nych.gestalt_mapping")
        self.assertEqual(first.sequence, 0)
        ids = [m["symbol_id"] for m in first.llm_output["mappings"]]
        self.assertTrue(any(i.startswith("gestalt.") for i in ids))

    def test_congruence_audit_entry_second_in_qson(self):
        _, result, _, _, _, _ = self.run_it()
        second = result["unit"].qson.entries[1]
        self.assertEqual(second.gate_id, "mg8.congruence_assessment")
        self.assertEqual(second.result, "PASS")

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
        self.assertIn("metformin", captured["mapping_prompt"])
        self.assertIn("PROTECTED TERMS", captured["mapping_prompt"])
        self.assertIn("INVARIANT", captured["mapping_prompt"])

    def test_congruence_prompt_carries_accepted_mappings(self):
        _, _, _, _, _, captured = self.run_it()
        self.assertIn("gestalt.", captured["congruence_prompt"])

    def test_invalid_mapping_plan_rejected_not_run(self):
        gst = build_gst(TEXT)

        def bad_mapping_llm(_prompt):
            return {"mappings": [{"word": "surprise", "symbol_id": "x"}]}

        def congruence_llm(_prompt):
            return congruence_pass_response()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PipelineError):
                run_pipeline(gst, bad_mapping_llm, congruence_llm, tmp)
            self.assertNotIn("output.mg8",
                             {p.name for p in Path(tmp).iterdir()})

    def test_congruence_fail_stops_pipeline_nothing_written(self):
        gst = build_gst(TEXT)

        def mapping_llm(_prompt):
            return mapping_plan_from_gst(gst)

        def failing_congruence_llm(_prompt):
            return {"congruence_result": "FAIL"}

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CongruenceNotPass) as ctx:
                run_pipeline(gst, mapping_llm, failing_congruence_llm, tmp)
            self.assertEqual(ctx.exception.result, "FAIL")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_congruence_intermediate_distinguishable_from_fail(self):
        gst = build_gst(TEXT)

        def mapping_llm(_prompt):
            return mapping_plan_from_gst(gst)

        def intermediate_congruence_llm(_prompt):
            return {"congruence_result": "INTERMEDIATE"}

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CongruenceNotPass) as ctx:
                run_pipeline(gst, mapping_llm, intermediate_congruence_llm, tmp)
            self.assertEqual(ctx.exception.result, "INTERMEDIATE")

    def test_invalid_congruence_response_rejected_not_run(self):
        gst = build_gst(TEXT)

        def mapping_llm(_prompt):
            return mapping_plan_from_gst(gst)

        def bad_congruence_llm(_prompt):
            return {"congruence_result": "PASS", "g8son_files": [], "flow": []}

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PipelineError):
                run_pipeline(gst, mapping_llm, bad_congruence_llm, tmp)
            self.assertNotIn("output.mg8",
                             {p.name for p in Path(tmp).iterdir()})


if __name__ == "__main__":
    unittest.main()
