import unittest

from mg8_engine.core import load_mg8, run_mg8


class CanonicalMg8LoaderTests(unittest.TestCase):
    def test_loads_resource_bound_manifest(self):
        unit = load_mg8("examples/canonical/basic.mg8")

        self.assertIsNotNone(unit.manifest)
        self.assertEqual(unit.manifest.unit_id, "example.canonical.001")
        self.assertEqual(unit.gst.state_id, "STATE_EXAMPLE_001")
        self.assertEqual(unit.ork_flow, ["state_check"])
        self.assertEqual(len(unit.g8son.gates), 1)
        self.assertEqual(unit.g8son.gates[0].gate_id, "state_check")

        effective = unit.gst.execution_state()
        self.assertEqual(effective["internal"]["mode"], "active")
        self.assertTrue(effective["external"]["object_detected"])
        self.assertEqual(effective["external"]["confidence"], 0.95)
        self.assertEqual(effective["intent"], "evaluate the current external state")

    def test_run_emits_event_level_qson_identity(self):
        def deterministic_fixture(_prompt):
            return {
                "status": "accepted",
            }

        unit = run_mg8("examples/canonical/basic.mg8", deterministic_fixture)

        self.assertEqual(unit.gst.state["status"], "accepted")
        self.assertEqual(len(unit.qson.entries), 1)
        self.assertTrue(unit.qson.run_id.startswith("RUN_"))
        self.assertTrue(unit.qson.entries[0].trace_id.startswith("TRJ_"))
        self.assertEqual(unit.qson.entries[0].result, "PASS")
        self.assertEqual(unit.qson.entries[0].gate_id, "state_check")
        self.assertEqual(unit.qson.entries[0].file_id, "example.eligibility.001")
        self.assertEqual(unit.qson.entries[0].event_type, "gate_attempt")
        self.assertEqual(unit.qson.entries[0].actor.id, "mg8-engine")
        self.assertEqual(unit.qson.entries[0].action, "continue")

    def test_model_cannot_self_authorize_failed_gate(self):
        def untrusted_fixture(_prompt):
            return {"transformed": True, "gate_result": "PASS"}

        unit = load_mg8("examples/canonical/basic.mg8")
        unit.gst.external["current"]["confidence"] = 0.2
        from mg8_engine.ork import execute_ork
        result = execute_ork(unit, untrusted_fixture)
        self.assertEqual(result.qson.events[0].result, "FAIL")
        self.assertEqual(result.qson.events[0].action, "stop")

    def test_missing_state_is_intermediate(self):
        unit = load_mg8("examples/canonical/basic.mg8")
        del unit.gst.external["current"]["confidence"]
        from mg8_engine.ork import execute_ork
        result = execute_ork(unit)
        self.assertEqual(result.qson.events[0].result, "INTERMEDIATE")
        self.assertEqual(result.qson.events[0].action, "review")


if __name__ == "__main__":
    unittest.main()
