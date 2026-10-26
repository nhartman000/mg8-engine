# Clean-wheel installation checks

Run from this checkout with Python 3.11+ and Git available:

```bash
python -I scripts/clean_wheel.py --work-dir "$HOME/mg8-clean-wheel-proof"
```

The work directory must not exist and must be outside the checkout. The command
creates separate build and installation virtualenvs. It copies source before
building so setuptools cannot rewrite the checkout's tracked egg-info. It builds
MG8 Engine and its VCS dependencies into wheels, requires binary wheels for index
dependencies, installs the entire wheelhouse offline with dependency resolution
disabled, and runs `pip check`. No editable installation is used.

Before testing, an isolated interpreter (`python -I`) imports MG8 Engine, NYCH
(including `nych.schemas` and `nych.gst_export`), and TCTA from outside the source
checkout. Each module's resolved `__file__` must be under the fresh environment's
site-packages. Distribution versions and direct-wheel origins are printed, and
editable metadata is rejected. The verifier then changes directory to the
checkout for example fixtures and runs **all** `tests/test_*.py` with unittest
discovery. Only `tests/`, never `src/`, is added by discovery. Published response
contract evidence is checked offline after successful tests; no paid inference is
performed.

## Explicit local dependency wheel

When testing an unpublished NYCH packaging fix, use its actual built wheel:

```bash
python -I scripts/clean_wheel.py \
  --work-dir "$HOME/mg8-fixed-wheel-proof" \
  --nych-wheel /absolute/path/to/nych-0.1.0-py3-none-any.whl
```

This replaces only NYCH's dependency-build requirement. Engine metadata is not
rewritten. The local override is evidence for the local artifact, not proof of a
published dependency pin. Normal CI has no override and uses `pyproject.toml`.

## Pinned upstream packaging fix

The original NYCH commit `cee3610723ffe4877c424591711fed29717ab655` built a wheel
without `nych.schemas`. The former editable-source workaround concealed this
defect. NYCH PR #3 fixes package discovery and is merged at
`57b81e9220069dd5ff72197b41288c9613e3343b`, now pinned in
`[project].dependencies` in `pyproject.toml`. TCTA is also pinned to a full commit.

The normal command and CI use these declared dependencies without `--nych-wheel`.
The engine wheel's original `Requires-Dist` metadata remains unchanged throughout
installation; the optional local override is not used as release evidence.
The clean-wheel workflow runs Python 3.11 and 3.13 independently.
