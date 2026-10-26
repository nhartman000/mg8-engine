"""Regression checks for the clean-wheel verifier (no third-party dependencies)."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CleanWheelHarnessTests(unittest.TestCase):
    def test_clean_install_command_documents_dependency_override(self):
        result = subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts/clean_wheel.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--nych-wheel", result.stdout)
        self.assertIn("--work-dir", result.stdout)

    def test_clean_install_refuses_existing_work_directory(self):
        result = subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts/clean_wheel.py"),
             "--work-dir", str(ROOT.parent)], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fresh environments are required", result.stderr)

    def test_clean_install_refuses_source_work_directory(self):
        result = subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts/clean_wheel.py"),
             "--work-dir", str(ROOT / "forbidden-build")], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the source checkout", result.stderr)

    def test_verifier_rejects_nonisolated_python(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify_installed.py"),
             "--source-root", str(ROOT)], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires python -I", result.stderr)


if __name__ == "__main__":
    unittest.main()
