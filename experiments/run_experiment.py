#!/usr/bin/env python3
"""
run_experiment.py -- the measured comparison the unveiling needs.

50 real commit-message sentences (experiments/sentences.json, collected
verbatim from this project's own repositories) are run through:

    A. NYCH condition -- deterministic nych extraction -> .gst pretext ->
       the real first-LLM-call mapping prompt -> engine-side canon
       validation (validate_plan).
    B. Plain condition -- the bare sentence plus a minimal instruction to
       produce the same JSON plan shape, no pretext, no rules.

Measured, per condition:

    - plan validity: canon validation for A; structural validation
      (1-3 gates per file, every gate has an exit, flow references
      declared gates, valid JSON) for BOTH A and B so there is one
      like-for-like number. (B cannot be held to the canon mapping rules
      -- it is never shown the skeletons or pins; that asymmetry is the
      design being tested, and is disclosed, not hidden.)
    - token cost: provider-reported input/output tokens per call.
    - task accuracy (proxy, disclosed as such): fraction of the
      sentence's content words that appear anywhere in the returned plan
      -- a plan that drops the subject matter scores low.

Determinism sub-experiment (first --determinism-n sentences):

    - gated: a GateKeeper prompt built from the sentence's .gst context
      plus requirement gates, sent twice bit-identically at temperature 0;
      verbatim match verified in engine code (verify_reproducibility).
    - control (the no-gates run the keeper's own docs ask for): the same
      user prompt with a bare system line, also sent twice identically.

If gated matches and control also matches, the gates are NOT what made it
deterministic -- that result is reported exactly as it falls.

Also reported: deterministic-side coverage on the 50 sentences (action
found, domain resolved, TOTE loop matched) so the known heuristic gaps
stay visible.

Usage:
    python3 experiments/run_experiment.py            # full run
    python3 experiments/run_experiment.py --limit 5  # cheap smoke run
    python3 experiments/run_experiment.py --skip-llm # coverage stats only

Results land in experiments/results.json and experiments/RESULTS.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
_sibling_nych = ROOT.parent / "nych"
if _sibling_nych.is_dir():
    sys.path.insert(0, str(_sibling_nych))

from mg8_engine.llm import LLMClient, ensure_api_key  # noqa: E402
from mg8_engine.models import G8Gate, Gst  # noqa: E402
from mg8_engine.keeper import GateKeeper, build_gated_prompt  # noqa: E402
from mg8_engine.pipeline import (  # noqa: E402
    PipelineError, build_mapping_prompt, validate_plan,
)

STOPWORDS = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "with",
             "as", "so", "that", "its", "it", "is", "are", "was", "were",
             "this", "no", "not", "by", "on", "at", "all", "both"}

PLAIN_PROMPT = """Convert this sentence into an execution plan.

Sentence: {sentence}

Return ONLY one valid JSON object:
{{
  "mappings": [{{"word": ..., "symbol_id": ..., "glyph": ...}}],
  "g8son_files": [{{"file_id": ..., "gates": [1-3 gate objects, each with
      "id", "type", "condition" or "conditions", "outcomes"]}}],
  "flow": ["gate ids in execution order"]
}}"""


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def structural_validity(plan: Any) -> tuple[bool, str]:
    """The like-for-like validity check both conditions are held to."""
    if not isinstance(plan, dict):
        return False, "not a JSON object"
    files = plan.get("g8son_files")
    if not files or not isinstance(files, list):
        return False, "no g8son_files"
    gate_ids = []
    for f in files:
        gates = f.get("gates", []) if isinstance(f, dict) else []
        if not 1 <= len(gates) <= 3:
            return False, f"file has {len(gates)} gates (must be 1-3)"
        for g in gates:
            gid = g.get("id") or g.get("gate_id")
            if not gid:
                return False, "gate without id"
            if not (g.get("outcomes") or g.get("condition")
                    or g.get("conditions") or g.get("then")):
                return False, f"gate {gid!r} has no exit condition"
            gate_ids.append(gid)
    flow = plan.get("flow") or []
    if not flow:
        return False, "no flow"
    unknown = [g for g in flow if g not in gate_ids]
    if unknown:
        return False, f"flow references unknown gates {unknown}"
    return True, ""


def content_words(sentence: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", sentence.lower())
            if w not in STOPWORDS and len(w) > 2}


def accuracy_proxy(sentence: str, plan: Any) -> float:
    words = content_words(sentence)
    if not words:
        return 0.0
    blob = json.dumps(plan, ensure_ascii=False).lower()
    return sum(1 for w in words if w in blob) / len(words)


# ---------------------------------------------------------------------------
# experiment
# ---------------------------------------------------------------------------

def find_tote_db() -> Path | None:
    repo = ROOT.parent / "T.O.T.E-loops"
    db = repo / "data" / "tote_loops.sqlite3"
    if db.is_file():
        return db
    if (repo / "src" / "build_db.py").is_file():
        subprocess.run([sys.executable, "-m", "src.build_db"],
                       cwd=repo, check=True)
        if db.is_file():
            return db
    return None


def run(limit: int | None, determinism_n: int, skip_llm: bool) -> Dict[str, Any]:
    from nych.gst_export import build_gst

    sentences: List[str] = json.loads(
        (HERE / "sentences.json").read_text(encoding="utf-8"))["sentences"]
    if limit:
        sentences = sentences[:limit]
    db_path = find_tote_db()

    client = None
    if not skip_llm:
        ensure_api_key()
        client = LLMClient()
        print(f"Provider: {client.provider}  model: {client.model}")
    print(f"Sentences: {len(sentences)}  TOTE db: {db_path or 'MISSING'}")

    rows: List[Dict[str, Any]] = []
    for i, sentence in enumerate(sentences, 1):
        gst_payload = build_gst(sentence, db_path=db_path)
        pretext = gst_payload["nych_pretext"]
        roles = gst_payload["state"]["roles"]
        row: Dict[str, Any] = {
            "sentence": sentence,
            "coverage": {
                "action_found": roles["action"] is not None,
                "domain_resolved": pretext["analysis"]["domain"] != "UNRESOLVED",
                "tote_matched": pretext["tote_match"] is not None,
            },
        }

        if client is not None:
            nych_prompt = build_mapping_prompt(gst_payload)
            row["nych"] = _llm_condition(
                client, nych_prompt, sentence,
                canon_payload=gst_payload)
            row["plain"] = _llm_condition(
                client, PLAIN_PROMPT.format(sentence=sentence), sentence,
                canon_payload=None)
            print(f"[{i:2}/{len(sentences)}] "
                  f"nych={'OK' if row['nych']['structural_valid'] else 'FAIL'}"
                  f"/canon={'OK' if row['nych'].get('canon_valid') else 'FAIL'} "
                  f"plain={'OK' if row['plain']['structural_valid'] else 'FAIL'} "
                  f" {sentence[:50]!r}")
        rows.append(row)

    determinism = []
    if client is not None and determinism_n > 0:
        print(f"\nDeterminism sub-experiment "
              f"(n={determinism_n}, 2 runs each, gated vs no-gates control):")
        for sentence in sentences[:determinism_n]:
            determinism.append(_determinism_trial(client, sentence,
                                                  build_gst, db_path))
            d = determinism[-1]
            print(f"  gated={'match' if d['gated_deterministic'] else 'DIVERGE'} "
                  f"control={'match' if d['control_deterministic'] else 'DIVERGE'} "
                  f" {sentence[:50]!r}")

    return _summarize(rows, determinism, client)


def _llm_condition(client: LLMClient, prompt: str, sentence: str,
                   canon_payload: Dict[str, Any] | None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"prompt_chars": len(prompt)}
    try:
        result = client.complete([{"role": "user", "content": prompt}],
                                 temperature=0.0, max_tokens=4096)
        out["input_tokens"] = result["input_tokens"]
        out["output_tokens"] = result["output_tokens"]
        from mg8_engine.llm import _strip_fences
        plan = json.loads(_strip_fences(result["content"]))
    except json.JSONDecodeError as exc:
        out.update(structural_valid=False, canon_valid=False,
                   error=f"invalid JSON: {exc}", accuracy=0.0)
        return out
    except Exception as exc:  # transport failure -- recorded, not retried
        out.update(structural_valid=False, canon_valid=False,
                   error=f"transport: {exc}", accuracy=0.0)
        return out

    ok, why = structural_validity(plan)
    out["structural_valid"] = ok
    if why:
        out["structural_error"] = why
    if canon_payload is not None:
        try:
            validate_plan(plan, canon_payload)
            out["canon_valid"] = True
        except PipelineError as exc:
            out["canon_valid"] = False
            out["canon_error"] = str(exc)
    out["accuracy"] = round(accuracy_proxy(sentence, plan), 3)
    return out


def _determinism_trial(client: LLMClient, sentence: str, build_gst,
                       db_path) -> Dict[str, Any]:
    gst_payload = build_gst(sentence, db_path=db_path)
    gst = Gst.model_validate({k: v for k, v in gst_payload.items()})
    gates = [G8Gate(
        id="exp.gate.1", type="requirement",
        conditions=[
            "Answer in exactly three sentences.",
            "Each sentence states one concrete step implied by the input.",
            "Do not add commentary outside the three sentences.",
        ],
        outcomes={"PASS": "exit", "FAIL": "repeat"},
    )]
    user_prompt = f"Describe how to carry out: {sentence}"

    keeper = GateKeeper(gst, gates)
    gated = keeper.verify_reproducibility(user_prompt,
                                          client.keeper_transport, runs=2)

    # No-gates control: identical bare request, twice.
    control_request = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
    }
    control = [client.keeper_transport(control_request) for _ in range(2)]
    control_match = control[0]["content"] == control[1]["content"]

    return {
        "sentence": sentence,
        "gated_deterministic": gated["deterministic"],
        "gated_evidence_level": gated["evidence_level"],
        "control_deterministic": control_match,
        "fingerprints": gated["fingerprints"],
    }


def _summarize(rows, determinism, client) -> Dict[str, Any]:
    n = len(rows)

    def rate(pred) -> float:
        return round(sum(1 for r in rows if pred(r)) / n, 3) if n else 0.0

    def mean(values) -> float:
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 1) if values else 0.0

    summary: Dict[str, Any] = {
        "n_sentences": n,
        "deterministic_coverage": {
            "action_found": rate(lambda r: r["coverage"]["action_found"]),
            "domain_resolved": rate(lambda r: r["coverage"]["domain_resolved"]),
            "tote_matched": rate(lambda r: r["coverage"]["tote_matched"]),
        },
    }
    if client is not None:
        for cond in ("nych", "plain"):
            got = [r[cond] for r in rows if cond in r]
            summary[cond] = {
                "structural_valid_rate": round(
                    sum(1 for g in got if g.get("structural_valid")) / len(got), 3),
                "mean_input_tokens": mean(g.get("input_tokens") for g in got),
                "mean_output_tokens": mean(g.get("output_tokens") for g in got),
                "mean_accuracy_proxy": round(
                    sum(g.get("accuracy", 0.0) for g in got) / len(got), 3),
            }
        summary["nych"]["canon_valid_rate"] = round(
            sum(1 for r in rows if r.get("nych", {}).get("canon_valid"))
            / len(rows), 3)
        if determinism:
            summary["determinism"] = {
                "n": len(determinism),
                "gated_match_rate": round(
                    sum(d["gated_deterministic"] for d in determinism)
                    / len(determinism), 3),
                "control_match_rate": round(
                    sum(d["control_deterministic"] for d in determinism)
                    / len(determinism), 3),
            }
        summary["total_tokens"] = {
            "input": client.total_input_tokens,
            "output": client.total_output_tokens,
            "calls": client.calls,
        }
        summary["provider"] = client.provider
        summary["model"] = client.model

    return {"summary": summary, "rows": rows, "determinism": determinism}


def write_markdown(result: Dict[str, Any], path: Path) -> None:
    s = result["summary"]
    lines = ["# Experiment results: NYCH pipeline vs plain prompting", ""]
    lines.append(f"Sentences: {s['n_sentences']} real commit messages "
                 "(experiments/sentences.json).")
    if "model" in s:
        lines.append(f"Model: `{s['model']}` ({s['provider']}), "
                     "temperature 0.")
    cov = s["deterministic_coverage"]
    lines += ["", "## Deterministic-side coverage (no LLM)", "",
              "| metric | rate |", "|---|---|",
              f"| action found | {cov['action_found']:.0%} |",
              f"| domain resolved | {cov['domain_resolved']:.0%} |",
              f"| TOTE loop matched | {cov['tote_matched']:.0%} |"]
    if "nych" in s:
        ny, pl = s["nych"], s["plain"]
        lines += ["", "## NYCH vs plain prompting", "",
                  "| metric | NYCH | plain |", "|---|---|---|",
                  f"| structural plan validity | {ny['structural_valid_rate']:.0%} | {pl['structural_valid_rate']:.0%} |",
                  f"| full canon validity | {ny['canon_valid_rate']:.0%} | n/a (no pretext) |",
                  f"| mean input tokens | {ny['mean_input_tokens']} | {pl['mean_input_tokens']} |",
                  f"| mean output tokens | {ny['mean_output_tokens']} | {pl['mean_output_tokens']} |",
                  f"| accuracy proxy (content-word retention) | {ny['mean_accuracy_proxy']:.0%} | {pl['mean_accuracy_proxy']:.0%} |"]
    if "determinism" in s:
        d = s["determinism"]
        lines += ["", "## Determinism (2 identical calls each, temperature 0)",
                  "",
                  "| condition | verbatim match rate |", "|---|---|",
                  f"| gated (GateKeeper) | {d['gated_match_rate']:.0%} |",
                  f"| no-gates control | {d['control_match_rate']:.0%} |",
                  "",
                  "If the control matches as often as the gated runs, the "
                  "gates are not the cause of the determinism -- that is "
                  "the honest reading, per the keeper's own docs."]
    if "total_tokens" in s:
        t = s["total_tokens"]
        lines += ["", f"Total spend: {t['input']} input / {t['output']} "
                  f"output tokens across {t['calls']} calls."]
    lines += ["", "## Caveats", "",
              "- Accuracy is a content-word-retention proxy, not graded "
              "task success.",
              "- The plain condition is never shown the canon rules, so it "
              "is only held to structural validity; the canon column is the "
              "pipeline's added constraint, not a handicap applied to the "
              "baseline.",
              "- One model, one day, 50 sentences: directional evidence, "
              "not proof."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N sentences")
    parser.add_argument("--determinism-n", type=int, default=10,
                        help="sentences in the determinism sub-experiment")
    parser.add_argument("--skip-llm", action="store_true",
                        help="deterministic coverage stats only, no API calls")
    args = parser.parse_args()

    result = run(args.limit, 0 if args.skip_llm else args.determinism_n,
                 args.skip_llm)

    (HERE / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    write_markdown(result, HERE / "RESULTS.md")
    print("\nSummary:")
    print(json.dumps(result["summary"], indent=2))
    print(f"\nWritten: {HERE / 'results.json'}  {HERE / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
