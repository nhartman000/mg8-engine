# mg8-engine Reference Architecture

`mg8-engine` is an implementation profile layered on the canonical MG8 file-family interfaces.

## Canonical resource path

```text
basic.mg8
   │
   ├── entry ──> flow.ork
   ├── state ──> one or more .gst files
   ├── gates ──> one or more .g8son files
   └── trace ──> .qson output path
                  │
                  ▼
            load / validate
                  │
                  ▼
             Mg8Unit
                  │
                  ▼
          reference ORK executor
                  │
                  ▼
       event-level QSON records
```

## What is canonical versus profile-specific

Canonical interfaces consumed by the engine:

- `.mg8` binds resources.
- `.gst` carries state/context/constraints.
- each `.g8son` file contains 1–3 bounded gates.
- `.qson` records execution events with separate run/gate/trace identity.

Reference-engine extensions:

- the JSON `flow` shape used by the example `.ork` file;
- Nych prompt tokenization;
- ADSR/Pan gate parameters;
- TOTE-specific loop behavior;
- the Gemini adapter.

The extension layer is intentionally kept separate from the base format definitions so experimentation does not redefine the file standards.

## Identity chain

```text
MG8 unit
  ↓
GST state_id
  ↓
G8SON file_id
  ↓
gate_id
  ↓
RUN_* runtime execution
  ↓
TRJ_* gate-attempt trace_id
  ↓
QSON event
```

## Loader safety

Canonical resource references are required to be relative to the `.mg8` unit directory. Absolute paths and `..` traversal that escape the unit directory are rejected by the reference loader.

## Backward compatibility

The loader continues to accept the earlier embedded profile containing:

```text
gst
g8son
ork_flow
```

This exists so prior experiments remain reproducible. New examples should use the resource-bound manifest form.
