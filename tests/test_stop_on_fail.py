"""Stop-on-fail: a FAIL gate result halts the executor (no later gate runs)."""

import unittest

from mg8_engine import GateFailure
from mg8_engine.models import G8son, Gst, Mg8Unit
from mg8_engine.ork import execute_ork


def _unit(gates, flow=None):
    return Mg8Unit(
        gst=Gst(state={"status": "start"}, domain="test"),
        g8son=G8son(file_id="f", gates=gates),
        ork_flow=flow or [g["id"] for g in gates],
    )


class ScriptedLLM:
    """Returns scripted outputs per gate id and records which gates ran."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, prompt):
        gate_id = next(line.split(":", 1)[1].strip()
                       for line in prompt.splitlines() if line.startswith("Gate ID:"))
        self.calls.append(gate_id)
        result = self.results[gate_id]
        if isinstance(result, list):
            result = result.pop(0)
        return dict(result)


PASS = {"gate_result": "PASS", "status": "ok"}
FAIL = {"gate_result": "FAIL", "status": "bad"}


class StopOnFailTests(unittest.TestCase):
    def test_fail_halts_no_further_gates_run(self):
        gates = [{"id": "g1", "type": "condition"},
                 {"id": "g2", "type": "condition"},
                 {"id": "g3", "type": "operation", "action": "side effect"}]
        llm = ScriptedLLM({"g1": PASS, "g2": FAIL, "g3": PASS})
        with self.assertRaises(GateFailure) as ctx:
            execute_ork(_unit(gates), llm)
        # old behavior ran g3 after g2 failed
        self.assertEqual(llm.calls, ["g1", "g2"])
        err = ctx.exception
        self.assertEqual(err.gate_id, "g2")
        self.assertEqual(err.status, "HALTED")
        self.assertEqual(err.unit.qson.status, "HALTED")

    def test_trace_records_halt(self):
        gates = [{"id": "g1", "type": "condition"},
                 {"id": "g2", "type": "condition"},
                 {"id": "g3", "type": "condition"}]
        llm = ScriptedLLM({"g1": FAIL, "g2": PASS, "g3": PASS})
        with self.assertRaises(GateFailure) as ctx:
            execute_ork(_unit(gates), llm)
        entries = ctx.exception.unit.qson.entries
        self.assertEqual([e.gate_id for e in entries], ["g1", "mg8.halt"])
        halt = entries[-1]
        self.assertEqual(halt.result, "FAIL")
        self.assertEqual(halt.action, "halt")
        self.assertEqual(halt.model_extra["halted_at_gate"], "g1")
        self.assertEqual(halt.model_extra["skipped_gates"], ["g2", "g3"])

    def test_transformed_false_counts_as_fail(self):
        gates = [{"id": "g1", "type": "condition"}, {"id": "g2", "type": "condition"}]
        llm = ScriptedLLM({"g1": {"transformed": False}, "g2": PASS})
        with self.assertRaises(GateFailure):
            execute_ork(_unit(gates), llm)
        self.assertEqual(llm.calls, ["g1"])

    def test_tote_test_fail_without_declared_repeat_halts(self):
        gates = [{"id": "t1", "type": "tote_test"}, {"id": "op", "type": "tote_operate"}]
        llm = ScriptedLLM({"t1": FAIL, "op": PASS})
        with self.assertRaises(GateFailure):
            execute_ork(_unit(gates), llm)
        self.assertEqual(llm.calls, ["t1"])

    def test_declared_fail_repeat_retries_then_continues(self):
        gates = [{"id": "t1", "type": "tote_test", "outcomes": {"PASS": "exit", "FAIL": "repeat"}},
                 {"id": "g2", "type": "condition"}]
        llm = ScriptedLLM({"t1": [FAIL, FAIL, PASS], "g2": PASS})
        unit = execute_ork(_unit(gates), llm)
        self.assertEqual(llm.calls, ["t1", "t1", "t1", "g2"])
        self.assertEqual(unit.qson.status, "COMPLETED")

    def test_all_pass_completes(self):
        gates = [{"id": "g1", "type": "condition"}, {"id": "g2", "type": "condition"}]
        unit = execute_ork(_unit(gates), ScriptedLLM({"g1": PASS, "g2": PASS}))
        self.assertEqual(unit.qson.status, "COMPLETED")
        self.assertNotIn("mg8.halt", [e.gate_id for e in unit.qson.entries])


if __name__ == "__main__":
    unittest.main()
