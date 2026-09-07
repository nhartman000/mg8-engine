# mg8-engine

**Reference runtime profile for the MG8 file family**

`mg8-engine` is a small Python executor used to exercise MG8 interfaces and experimental Nych/ADSR/TOTE extensions. It is **not** the canonical definition of MG8 itself; the dedicated `mg8`, `gst`, `g8son`, and `qson` repositories define the current public format baselines.

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
