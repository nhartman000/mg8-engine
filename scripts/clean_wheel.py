"""Build a wheelhouse, install only wheels, and test in a fresh isolated env."""
import argparse
from email.parser import BytesParser
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None):
    print("+", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path,
                        help="New, nonexistent directory outside the source checkout")
    parser.add_argument("--nych-wheel", type=Path,
                        help="Explicit fixed NYCH wheel; replaces only the NYCH build requirement")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if work == ROOT or ROOT in work.parents:
        parser.error("--work-dir must be outside the source checkout")
    if work.exists():
        parser.error("--work-dir must not already exist (fresh environments are required)")
    nych = args.nych_wheel.resolve() if args.nych_wheel else None
    if nych and (not nych.is_file() or nych.suffix != ".whl"):
        parser.error("--nych-wheel must name an existing .whl file")
    work.mkdir(parents=True)
    wheelhouse = work / "wheelhouse"
    wheelhouse.mkdir()
    # Build a disposable copy: setuptools must not rewrite tracked egg-info.
    source = work / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(
        ".git", "*.egg-info", "__pycache__", "build", "dist", ".venv"))
    build = work / "build-env"
    installed = work / "installed-env"
    venv.EnvBuilder(with_pip=True).create(build)
    build_python = build / "bin/python"
    run(build_python, "-I", "-m", "pip", "wheel", "--no-deps", "--wheel-dir", wheelhouse, source)
    engine, = wheelhouse.glob("mg8_engine-*.whl")
    with zipfile.ZipFile(engine) as archive:
        metadata, = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        requirements = BytesParser().parsebytes(archive.read(metadata)).get_all("Requires-Dist", [])
    if nych:
        requirements = [req for req in requirements if not re.match(r"^nych(?:\s|[<>=!~;\[]|$)", req, re.I)]
        requirements.append(str(nych))
    run(build_python, "-I", "-m", "pip", "wheel", "--only-binary=:all:",
        "--wheel-dir", wheelhouse, *requirements)
    venv.EnvBuilder(with_pip=True).create(installed)
    python = installed / "bin/python"
    # No resolver can follow a direct VCS URL here: every artifact is explicit,
    # dependency resolution is disabled, and the install is offline.
    run(python, "-I", "-m", "pip", "install", "--no-index", "--no-deps",
        *sorted(wheelhouse.glob("*.whl")), cwd=work)
    run(python, "-I", "-m", "pip", "check", cwd=work)
    run(python, "-I", ROOT / "scripts/verify_installed.py", "--source-root", ROOT, cwd=work)
    run(python, "-I", ROOT / "experiments/response-contracts/verify_evidence.py", cwd=ROOT)


if __name__ == "__main__":
    main()
