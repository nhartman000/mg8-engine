# mg8-engine

**Reference runtime profile for the MG8 file family — and the one-command entry point for the whole NYCH system**

`mg8-engine` is a small Python executor used to exercise MG8 interfaces and experimental Nych/ADSR/TOTE extensions. It is **not** the canonical definition of MG8 itself; the dedicated `mg8`, `gst`, `g8son`, and `qson` repositories define the current public format baselines.

## The whole system, in one place

NYCH is a pipeline that puts deterministic structure around an LLM instead of trusting prose. The flow:

```text
sentence
  → nych (deterministic: role tagging, domain/competency, TOTE-loop lookup,
          consonant skeletons, protected terms)          [nych repo]
  → .gst pretext                                          [gst spec]
  → FIRST REAL LLM CALL (Gestalt mapping + gate plan)
  → engine-side canon validation (validate_plan — the model is NOT trusted)
  → .g8son gates (1–3 per file, every gate has an exit)   [g8son spec]
  → .ork flow → .mg8 unit executed here                   [mg8 spec]
  → .qson audit trace                                     [qson spec]
  → output.mg8 + .gitson canon bundle                     [gitson spec]
```

The repositories, and what each one is:

| repo | role |
|---|---|
| [nych](https://github.com/nhartman000/nych) | the deterministic encoder (code) |
| [mg8-engine](https://github.com/nhartman000/mg8-engine) | this repo: runtime, pipeline, validator, keeper, demo, experiment (code) |
| [T.O.T.E-loops](https://github.com/nhartman000/T.O.T.E-loops) | the TOTE loop database, built from seeds with one command (code + data) |
| [mg8](https://github.com/nhartman000/mg8) | `.mg8` unit container spec |
| [gst](https://github.com/nhartman000/gst) | `.gst` state/pretext spec |
| [g8son](https://github.com/nhartman000/g8son) | `.g8son` gate spec |
| [qson](https://github.com/nhartman000/qson) | `.qson` audit-trace spec |
| [gitson-](https://github.com/nhartman000/gitson-) | `.gitson` canon-bundle transport spec |
| [TCTA](https://github.com/nhartman000/TCTA) | the transform-algebra theory behind it |

### Quickstart: real LLM, end to end, one command

```bash
mkdir nych-workspace && cd nych-workspace
git clone https://github.com/nhartman000/nych.git
git clone https://github.com/nhartman000/T.O.T.E-loops.git
git clone https://github.com/nhartman000/mg8-engine.git
cd mg8-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -e ../nych

python3 demo.py "Re-ran both test suites after changes"
```

On first run the demo asks which provider you use (Anthropic / OpenAI / Gemini / Vertex / Vertex Batch), lets you paste the API key, and saves it to a git-ignored `.env` — or copy [`.env.example`](.env.example) to `.env` yourself. The TOTE database is built automatically from the sibling checkout.

For the 140-call experiment, use `NYCH_LLM_PROVIDER=vertex_batch` with your GCP project set in `.env` — Vertex Batch Prediction has no per-minute rate limits and processes all calls in one job.

### The experiment

[`experiments/run_experiment.py`](experiments/run_experiment.py) runs 50 real commit messages (collected from these repositories' own git logs) through the NYCH pipeline and through plain prompting, and measures: plan-validation pass rate, provider-reported token cost, a content-retention accuracy proxy, and gated-vs-no-gates determinism (the control run the keeper's docs demand). Results are written to `experiments/results.json` and `experiments/RESULTS.md`.

```bash
python3 experiments/run_experiment.py              # full run
python3 experiments/run_experiment.py --limit 5    # cheap smoke run
python3 experiments/run_experiment.py --skip-llm   # coverage stats only, no API
```

Nothing in the results is pre-claimed: if the no-gates control is as deterministic as the gated runs, that is what the report says.

## What this engine supports

The loader now supports two input profiles:

1. **Canonical resource-bound `.mg8` manifests**
2. **Earlier embedded ADSR/TOTE `.mg8` examples** for backward compatibility

Canonical loading follows:

```text
.mg8 manifest
    ↓
entry → .ork reference flow
state → one or more .gst resources
gates → one or more .g8son resources
trace → .qson output location
    ↓
MG8 in-memory execution unit
    ↓
reference executor
    ↓
event-level QSON trace
```

## Canonical manifest example

```json
{
  "mg8_version": "1.0",
  "unit_id": "example.canonical.001",
  "entry": "flow.ork",
  "state": ["state/current.gst"],
  "gates": ["gates/eligibility.g8son"],
  "trace": "trace/execution.qson"
}
```

See [`examples/canonical/basic.mg8`](examples/canonical/basic.mg8) for a complete resource-bound fixture.

## G8SON bounds and identity

Each referenced `.g8son` file is checked for the canonical **1–3 gate** bound. The runtime may aggregate gates from multiple bounded files.

Execution traces preserve:

```text
run_id   = one runtime execution
file_id  = source .g8son file identity
gate_id  = stable gate definition identity
trace_id = one attempted gate execution
```

Every gate attempt receives a new `TRJ_*` trace identifier.

## QSON output

The CLI writes the **QSON trace object itself**, not a serialized dump of the entire MG8 runtime object.

For canonical manifests, the default output path comes from the manifest's `trace` field.

## ADSR / Nych / TOTE profile

The repository retains its original experimental profile:

- Nych symbolic tokenization
- ADSR parameters (`attack`, `decay`, `sustain`, `release`)
- Pan weighting
- TOTE-style test/operate sequencing

These are **runtime-profile extensions**. They are not presented as mandatory fields in the base MG8/G8SON standards.

The older fixture remains at:

```text
examples/tote_example.mg8
```

## NYCH pipeline (`mg8_engine.pipeline`)

`src/mg8_engine/pipeline.py` implements the full NYCH → MG8 pipeline:

```text
USER → NYCH encoder (deterministic, the nych package) → .gst pretext →
first LLM call (prune with dither + Gestalt mapping + .g8son creation) →
.ork flow ordering → MG8 engine compiles/runs the .mg8 in one call →
output handed off as .mg8 + .gitson canon bundle
```

`run_pipeline(gst_payload, mapping_llm, out_dir)` takes the `.gst` pretext
produced by `nych.gst_export.build_gst`, prompts the mapping LLM, and
**validates the returned plan against the canon rules** rather than
trusting it: mappings only for requested words with the consonant skeleton
embedded in each symbol id; modality operators never remapped;
`#temp-invariant` pins respected; **scientific names, people's names, and
prescription drug names never Gestalt-mapped**; 1–3 gates per `.g8son`,
every gate a bounded loop with an exit condition; `.ork` flow restricted
to declared gates. Violations raise `PipelineError` — nothing is repaired
silently.

The accepted mappings are recorded as sequence-0 `nych.gestalt_mapping`
QSON audit entries (the consonant-embedded id strings are the audit trail)
and returned as `pins` for the caller's nych `SessionInvariants` store.
The executed unit is written as `output.mg8` (reloadable by `load_mg8`)
plus a `.gitson` canon bundle (`mg8_engine.gitson`) so a receiving LLM can
ingest the NYCH/MG8 rules; the `.gitson` size limit is a configurable
parameter, never hard-coded.

## Gate keeper: gated deterministic querying (`mg8_engine.keeper`)

`src/mg8_engine/keeper.py` implements the mgate-keeper mechanism —
flattening a `.gst` interpretation context plus `.g8son` requirement gates
into a system prompt at temperature 0, on the hypothesis that the gates
collapse the LLM's admissible answer space to a verbatim-reproducible
response. The module is built to *test* that hypothesis rather than
assume it, hardened against the prototype's measurement weaknesses:

- requests are **bit-identical** across repeat calls (deterministic prompt
  construction, no timestamps or cache-busters);
- the provider's `system_fingerprint` is recorded per call in the QSON
  audit, and the result reports an `evidence_level` that never claims
  proof: a substantial response matching verbatim across *different*
  backend fingerprints is **suggestive**; a match on one fingerprint is
  **inconclusive** (can't rule out backend stability); a match with no
  fingerprint, or any match shorter than `min_substantial_words`
  (default 20) — short answers coincide easily — is **weak**. Every
  result names the decisive test: a no-gates control run of the same
  prompt. If that also matches verbatim, the gates weren't the cause;
- the repeat/exit loop is executed and verified in engine code
  (`verify_reproducibility`), not handed to the LLM as a prose
  instruction; divergence is a disclosed FAIL, never silently retried.

Compatibility loaders accept the mgate-keeper file profiles unchanged:
requirement-style `.g8son` (`gate_id`/`gate_name`/`atomic_requirements` →
canonical `G8Gate` with `type="requirement"`), context-style `.gst`
(via `Gst`'s `extra="allow"`), and project-style `.mg8`
(`GateKeeper.from_project`). Transport remains a caller-supplied callback
returning `{"content", "response_id", "system_fingerprint"}` — no vendored
provider SDK.

## Installation

```bash
git clone https://github.com/nhartman000/mg8-engine.git
cd mg8-engine
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

The package declares the dependencies used by the CLI/runtime:

- Pydantic
- Click
- `google-genai`

## Run with Gemini

Set credentials locally:

```bash
export GEMINI_API_KEY="..."
```

Optionally select a model without editing source:

```bash
export GEMINI_MODEL="your-model-name"
```

Run:

```bash
mg8-run examples/canonical/basic.mg8
```

Provider errors are surfaced as execution errors rather than converted into fake successful transforms.

## No-network validation

The canonical loader and trace identity can be exercised without an API key:

```bash
python -m unittest tests.test_canonical_loader
```

The test uses a deterministic local callback and verifies:

- canonical manifest loading;
- relative GST/G8SON/ORK resource resolution;
- gate identity;
- `RUN_*` execution identity;
- unique `TRJ_*` event identity;
- QSON result recording.

## Determinism statement

This engine can make the **control flow, resource resolution, event identity, and trace construction deterministic** when its inputs and callback are deterministic.

It does not claim that a third-party stochastic model becomes mathematically deterministic merely because it is called through MG8. Provider behavior must be measured separately.

## Repository status

Current role: reference implementation / interface-validation runtime.

The universal `.ork` grammar is not yet claimed by this repo. `examples/canonical/flow.ork` uses a deliberately small JSON **reference-engine profile** containing an ordered `flow` list of gate IDs.
