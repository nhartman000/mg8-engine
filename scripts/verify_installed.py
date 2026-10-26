"""Verify wheel import provenance before running source tests and fixtures."""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import sysconfig
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.error("requires python -I (no PYTHONPATH or user-site imports)")
    source = args.source_root.resolve()
    roots = {Path(sysconfig.get_path(key)).resolve() for key in ("purelib", "platlib")}
    # This happens before discover adds the tests directory, outside the repo.
    if Path.cwd() == source or source in Path.cwd().parents:
        parser.error("run the provenance check from outside the source checkout")
    failures = []
    for name in ("mg8_engine", "mg8_engine.pipeline", "mg8_engine.response_contract",
                 "nych", "nych.schemas", "nych.gst_export", "tcta_engine", "tcta_engine.file_format"):
        try:
            module = importlib.import_module(name)
            if module.__file__ is None:
                raise RuntimeError(f"module has no concrete wheel file: {name}")
            path = Path(module.__file__).resolve()
            if not any(root in path.parents for root in roots):
                raise RuntimeError(f"source import instead of installed wheel: {path}")
            print(f"WHEEL IMPORT {name}: {path}", flush=True)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    for name in ("mg8-engine", "nych", "tcta-engine"):
        dist = importlib.metadata.distribution(name)
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        if direct.get("dir_info", {}).get("editable"):
            failures.append(f"{name}: editable install is not wheel evidence")
        print(f"DISTRIBUTION {name}=={dist.version}: {json.dumps(direct)}", flush=True)
    if failures:
        print("WHEEL PROVENANCE FAILED:\n" + "\n".join(failures), file=sys.stderr, flush=True)
    # Tests use checkout examples as fixtures, never checkout/src as imports.
    os.chdir(source)
    suite = unittest.defaultTestLoader.discover(str(source / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if failures or not result.wasSuccessful() or result.testsRun == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
