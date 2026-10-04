"""Tests for mg8_engine.tcta_bridge and its wiring into pipeline.run_pipeline.

Uses stdlib unittest, same as test_pipeline.py (no pytest install available
in this session)."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from nych.gst_export import build_gst

from tcta_engine.file_format import parse_tcta, serialize_tcta

from mg8_engine.pipeline import run_pipeline
from mg8_engine.tcta_bridge import (
    build_tcta_file,
    compute_mapping_narrowing,
    verify_compliance,
)

from test_pipeline import TEXT, THREE_GATE_FILES, THREE_GATE_FLOW

GST = build_gst(TEXT)
NEEDS = GST["nych_pretext"]["needs_mapping"]


def _mapping_plan(words_mapped):
    """A mapping plan that maps exactly `words_mapped` of NEEDS, in order."""
    chosen = NEEDS[:words_mapped]
    return {
        "mappings": [
            {"word": d["word"], "symbol_id": d["id"], "glyph": "🧪"}
            for d in chosen
        ]
    }


def _full_mapping_plan():
    return _mapping_plan(len(NEEDS))


def _congruence_pass_response():
    return {
        "congruence_result": "PASS",
        "g8son_files": copy.deepcopy(THREE_GATE_FILES),
        "flow": list(THREE_GATE_FLOW),
    }


class TestComputeMappingNarrowing(unittest.TestCase):
    def test_fully_resolved_plan_gives_zero_spread_and_localized(self):
        narrowing = compute_mapping_narrowing(GST, _full_mapping_plan())
        self.assertEqual(narrowing.omega_c_count, len(NEEDS))
        self.assertEqual(narrowing.t_g_count, 0)
        self.assertEqual(narrowing.unresolved_words, [])
        self.assertAlmostEqual(narrowing.spread, 0.0)
        self.assertEqual(narrowing.algorithm_select_result, "HDRP_LOCALIZED")

    def test_unresolved_plan_gives_full_spread_and_unresolved(self):
        empty_plan = {"mappings": []}
        narrowing = compute_mapping_narrowing(GST, empty_plan)
        self.assertEqual(narrowing.t_g_count, len(NEEDS))
        self.assertAlmostEqual(narrowing.spread, 1.0)
        self.assertEqual(narrowing.algorithm_select_result, "UNRESOLVED")
        self.assertEqual(narrowing.algorithm_select_reason, "spread_high")

    def test_partially_resolved_plan_reports_which_words_remain(self):
        self.assertGreaterEqual(len(NEEDS), 2)
        partial = _mapping_plan(1)
        narrowing = compute_mapping_narrowing(GST, partial)
        self.assertEqual(narrowing.t_g_count, len(NEEDS) - 1)
        expected_unresolved = {d["word"] for d in NEEDS[1:]}
        self.assertEqual(set(narrowing.unresolved_words), expected_unresolved)

    def test_no_candidate_words_discloses_undefined_spread(self):
        gst_no_needs = {**GST, "nych_pretext": {**GST["nych_pretext"], "needs_mapping": []}}
        narrowing = compute_mapping_narrowing(gst_no_needs, {"mappings": []})
        self.assertEqual(narrowing.omega_c_count, 0)
        self.assertIsNone(narrowing.spread)
        self.assertIsNone(narrowing.algorithm_select_result)
        self.assertIsNotNone(narrowing.note)

    def test_custom_thresholds_are_respected(self):
        # Leave at least one word unresolved so spread > 0, then set
        # spread_low near zero: select_algorithm only picks HDRP_LOCALIZED
        # when spread <= spread_low, so any positive spread should now
        # fail to qualify.
        partial = _mapping_plan(len(NEEDS) - 1 if len(NEEDS) > 1 else 0)
        narrowing = compute_mapping_narrowing(GST, partial, spread_low=0.001, spread_high=0.5)
        self.assertGreater(narrowing.spread, 0.0)
        self.assertNotEqual(narrowing.algorithm_select_result, "HDRP_LOCALIZED")


class TestVerifyCompliance(unittest.TestCase):
    def test_passes_for_a_normally_computed_narrowing(self):
        narrowing = compute_mapping_narrowing(GST, _full_mapping_plan())
        verify_compliance(narrowing)  # should not raise

    def test_passes_for_the_undefined_spread_case(self):
        gst_no_needs = {**GST, "nych_pretext": {**GST["nych_pretext"], "needs_mapping": []}}
        narrowing = compute_mapping_narrowing(gst_no_needs, {"mappings": []})
        verify_compliance(narrowing)  # should not raise: both spread and result are None


class TestBuildTctaFile(unittest.TestCase):
    def test_round_trips_through_parse_and_serialize(self):
        narrowing = compute_mapping_narrowing(GST, _mapping_plan(1))
        tcta = build_tcta_file("nych-unit-test1", narrowing)
        round_tripped = parse_tcta(serialize_tcta(tcta))
        self.assertEqual(round_tripped, tcta)

    def test_discloses_spread_and_algorithm_select(self):
        narrowing = compute_mapping_narrowing(GST, _full_mapping_plan())
        tcta = build_tcta_file("nych-unit-test2", narrowing)
        self.assertAlmostEqual(tcta.spread.value, 0.0)
        self.assertEqual(tcta.algorithm_select.result, "HDRP_LOCALIZED")
        self.assertEqual(tcta.consumption_points.trajectory_narrowing.status, "implemented")
        self.assertEqual(tcta.consumption_points.domain_prune.status, "not_yet_wired")

    def test_uses_given_thresholds_in_parameters(self):
        narrowing = compute_mapping_narrowing(GST, _full_mapping_plan(), spread_low=0.3, spread_high=0.7)
        tcta = build_tcta_file("nych-unit-test3", narrowing, spread_low=0.3, spread_high=0.7)
        self.assertAlmostEqual(tcta.parameters.spread_low, 0.3)
        self.assertAlmostEqual(tcta.parameters.spread_high, 0.7)


class TestRunPipelineTctaWiring(unittest.TestCase):
    def _run(self, **kwargs):
        gst = build_gst(TEXT)

        def mapping_llm(_prompt):
            return _full_mapping_plan()

        def congruence_llm(_prompt):
            return _congruence_pass_response()

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(gst, mapping_llm, congruence_llm, tmp, **kwargs)
            files = {p.name for p in Path(tmp).iterdir()}
            tcta_text = (
                (Path(tmp) / "trajectory.tcta").read_text()
                if (Path(tmp) / "trajectory.tcta").exists() else None
            )
            return result, files, tcta_text

    def test_tcta_file_written_by_default(self):
        result, files, tcta_text = self._run()
        self.assertIn("trajectory.tcta", files)
        self.assertIsNotNone(result["tcta_narrowing"])
        self.assertIn("trajectory_tcta", result["paths"])
        reparsed = parse_tcta(tcta_text)
        self.assertEqual(reparsed.algorithm_select.result, "HDRP_LOCALIZED")

    def test_tcta_narrowing_entry_is_third_in_qson(self):
        result, _, _ = self._run()
        third = result["unit"].qson.entries[2]
        self.assertEqual(third.gate_id, "tcta.trajectory_narrowing")
        self.assertEqual(third.sequence, 2)
        self.assertEqual(third.result, "HDRP_LOCALIZED")

    def test_existing_mapping_and_congruence_entries_unaffected(self):
        result, _, _ = self._run()
        first = result["unit"].qson.entries[0]
        second = result["unit"].qson.entries[1]
        self.assertEqual(first.gate_id, "nych.gestalt_mapping")
        self.assertEqual(second.gate_id, "mg8.congruence_assessment")

    def test_compute_tcta_false_skips_everything(self):
        result, files, _ = self._run(compute_tcta=False)
        self.assertNotIn("trajectory.tcta", files)
        self.assertIsNone(result["tcta_narrowing"])
        self.assertNotIn("trajectory_tcta", result["paths"])
        # No third QSON entry either -- just mapping(0)/congruence(1) plus
        # gate-execution entries.
        gate_ids_at_2_plus = [e.gate_id for e in result["unit"].qson.entries[2:]]
        self.assertNotIn("tcta.trajectory_narrowing", gate_ids_at_2_plus)

    def test_custom_spread_thresholds_propagate_to_the_written_file(self):
        result, _, tcta_text = self._run(tcta_spread_low=0.01, tcta_spread_high=0.02)
        reparsed = parse_tcta(tcta_text)
        self.assertAlmostEqual(reparsed.parameters.spread_low, 0.01)
        self.assertAlmostEqual(reparsed.parameters.spread_high, 0.02)


if __name__ == "__main__":
    unittest.main()
