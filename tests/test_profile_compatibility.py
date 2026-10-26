"""Historical ORK profiles must not silently impersonate another runtime."""
import json
from pathlib import Path
import tempfile
import unittest

from mg8_engine.core import _load_ork_flow


class ProfileCompatibilityTests(unittest.TestCase):
    def load(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'flow.ork'
            path.write_text(json.dumps(payload), encoding='utf-8')
            return _load_ork_flow(path)

    def test_preserves_explicit_reference_and_legacy_sequential_shapes(self):
        for payload in [
            {'ork_profile':'mg8-engine-reference-1','flow':['x']},
            {'flow':['x']}, {'ork_flow':['x']}, {'steps':['x']},
            {'steps':[{'gate_id':'x'}]},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.load(payload), ['x'])

    def test_rejects_foreign_profile_without_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported ORK profile'):
            self.load({'ork_profile': 'mg8-runtime-sequential/0.1', 'flow': ['x']})

    def test_rejects_foreign_profiles_and_ignored_policy_or_control_fields(self):
        for payload in [
            {'ork_profile':'mg8-runtime-sequential/0.1','bonit':'policy.bonit','flow':['x']},
            {'flow':['x'],'bonit':'policy.bonit'},
            {'ork_profile':'mg8-engine-reference-1','flow':['x'],'max_iterations':100},
            {'steps':[{'gate_id':'x','on_fail':'continue'}]},
            {'flow':['x'],'ork_flow':['y']},
            {'ork_version':'0.3','flow':['x']},
            {'flow':[]},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, 'Unsupported|Ambiguous'):
                    self.load(payload)
