import unittest

from mg8_engine.predicates import evaluate_conditions


class PredicateTests(unittest.TestCase):
    def test_and_pass(self):
        result = evaluate_conditions(
            ["external.detected == true", "external.confidence >= 0.9"],
            {"external": {"detected": True, "confidence": 0.95}}, "AND"
        )
        self.assertEqual(result.result, "PASS")

    def test_or_and_structured_predicate(self):
        result = evaluate_conditions(
            [{"path": "a", "operator": "==", "value": 1}, {"path": "b", "operator": "==", "value": 2}],
            {"a": 0, "b": 2}, "OR"
        )
        self.assertEqual(result.result, "PASS")

    def test_rejects_executable_expression(self):
        with self.assertRaises(ValueError):
            evaluate_conditions(["__import__('os').system('false')"], {}, "AND")


if __name__ == "__main__":
    unittest.main()
