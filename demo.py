#!/usr/bin/env python3
"""
demo.py -- the NYCH -> MG8 pipeline end to end with ONE real LLM, in one
command.

    python3 demo.py "Re-ran both test suites after changes"
    python3 demo.py            # uses that default sentence

What happens, in order (and is printed as it happens):

    1. nych deterministic extraction: roles, domain, TOTE-loop lookup,
       consonant skeletons, protected terms -> the .gst pretext.
    2. FIRST REAL LLM CALL (nych.bonit STEP 2): Gestalt mapping only. No
       .g8son, no .ork flow -- just mappings for the requested words.
    3. Engine-side validation of that plan against the canon rules
       (validate_mapping_plan -- the model is not trusted to have
       followed them).
    4. SECOND REAL LLM CALL (mg8.bonit STEP 3): congruence assessment
       first; only on PASS does the model author exactly three 1-3-gate
       .g8son files plus the .ork flow ordering them.
    5. Engine-side validation of that response (validate_congruence_response).
       A FAIL/INTERMEDIATE result stops here -- CongruenceNotPass is
       raised and nothing is written.
    6. Unit assembly (.gst/.g8son x3/.ork/.mg8) and execution with the
       real model answering each gate, in the three files' declared
       order; QSON audit trace written.
    7. Output handoff: output.mg8 + .gitson canon bundle.

First run: if no API key is configured you'll be asked for one and it is
saved to .env (git-ignored). Keys for Anthropic, OpenAI, or Gemini all
work.

The TOTE-loops database is built automatically from the sibling
T.O.T.E-loops checkout when present; without it the pipeline still runs
and honestly reports the lookup as a fallback.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

# Allow a sibling nych checkout without pip-installing it.
_sibling_nych = HERE.parent / "nych"
if _sibling_nych.is_dir():
    sys.path.insert(0, str(_sibling_nych))

from mg8_engine.llm import LLMClient, ensure_api_key  # noqa: E402
from mg8_engine.pipeline import (  # noqa: E402
    CongruenceNotPass, PipelineError, run_pipeline,
)


def find_tote_db() -> Path | None:
    """Locate (building if needed) the T.O.T.E-loops sqlite database."""
    repo = HERE.parent / "T.O.T.E-loops"
    db = repo / "data" / "tote_loops.sqlite3"
    if db.is_file():
        return db
    if (repo / "src" / "build_db.py").is_file():
        print("Building TOTE-loops database (one-time)...")
        subprocess.run([sys.executable, "-m", "src.build_db"],
                       cwd=repo, check=True)
        if db.is_file():
            return db
    return None


def main() -> int:
    sentence = " ".join(sys.argv[1:]) or "Re-ran both test suites after changes"

    print("=" * 72)
    print("NYCH -> MG8 pipeline demo (real LLM, end to end)")
    print("=" * 72)

    provider = ensure_api_key()
    client = LLMClient()
    print(f"Provider: {provider}  model: {client.model}")
    print(f"Input: {sentence!r}")
    print()

    # 1. deterministic NYCH side
    from nych.gst_export import build_gst
    db_path = find_tote_db()
    gst_payload = build_gst(sentence, db_path=db_path)
    pretext = gst_payload["nych_pretext"]
    roles = gst_payload["state"]["roles"]
    print("[1] Deterministic extraction (no LLM):")
    print(f"    action: {roles['action'] and roles['action']['word']!r}  "
          f"domain: {pretext['analysis']['domain']}  "
          f"tote_match: {bool(pretext['tote_match'])}")
    print(f"    words needing Gestalt mapping: "
          f"{[d['word'] for d in pretext['needs_mapping']]}")
    print()

    # 2-7. first LLM call -> validation -> second LLM call -> validation
    #      -> assembly -> gated execution
    out_dir = HERE / "demo_output"
    print("[2] First real LLM call (Gestalt mapping only, nych.bonit STEP 2)...")
    try:
        result = run_pipeline(gst_payload, client.mapping_llm,
                              client.congruence_llm, out_dir,
                              gate_llm=client.gate_llm)
    except CongruenceNotPass as exc:
        print(f"    CONGRUENCE {exc.result} (mg8.bonit STEP 3): {exc}")
        print("    (No .g8son was authored or written -- this is the "
              "engine refusing to proceed on an unconfirmed handoff, "
              "disclosed, not repaired.)")
        return 1
    except PipelineError as exc:
        print(f"    REJECTED by canon validation: {exc}")
        print("    (This is the engine refusing an invalid LLM plan/"
              "response -- disclosed, not repaired.)")
        return 1
    except json.JSONDecodeError as exc:
        print(f"    LLM did not return valid JSON: {exc}")
        return 1

    mapping_plan = result["mapping_plan"]
    congruence = result["congruence"]
    unit = result["unit"]
    print("[3] Mapping plan PASSED canon validation.")
    print(f"    mappings: {[(m['word'], m['symbol_id']) for m in mapping_plan.get('mappings', [])]}")
    print(f"[4] Second real LLM call (congruence assessment, mg8.bonit STEP 3)...")
    print(f"[5] Congruence result: {congruence['congruence_result']} -- "
          f"g8son files: {len(congruence['g8son_files'])}  "
          f"gates in flow: {congruence['flow']}")
    print(f"[6] Unit executed; QSON entries: {len(unit.qson.entries)}  "
          f"final state keys: {list(unit.gst.state) if isinstance(unit.gst.state, dict) else unit.gst.state}")
    print(f"[7] Outputs written under {out_dir}/")
    for name, path in result["paths"].items():
        print(f"    {name}: {path}")
    print()
    print(f"Token cost (provider-reported): "
          f"{client.total_input_tokens} in / {client.total_output_tokens} out "
          f"across {client.calls} calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
