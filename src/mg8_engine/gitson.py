"""
gitson.py -- .gitson canon-bundle splitter/reassembler (reference
implementation of gitson- spec/gitson_v1.md).

Purpose: when an .mg8 output is handed off to another LLM, it travels with
a .gitson bundle carrying the NYCH + MG8 canon (full rules/spec text, or
pointers to the canonical GitHub repositories) so a receiver with no prior
context can ingest the rules needed to interpret the output.

Size limits are a configurable parameter (`max_bytes`), never hard-coded:
platform limits are external constraints that change independently of the
format. Bundles split into numbered parts 1.1, 1.2, 1.3, ... and a block
too large to fit alone in one part is demoted to a repository reference --
disclosed in the part's "demoted" list -- never truncated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

GITSON_VERSION = "1.0"

# Canonical rule-source repositories for NYCH + MG8 canon ingestion.
CANON_REPOS = [
    "https://github.com/nhartman000/nych",
    "https://github.com/nhartman000/mg8",
    "https://github.com/nhartman000/mg8-engine",
    "https://github.com/nhartman000/gst",
    "https://github.com/nhartman000/g8son",
    "https://github.com/nhartman000/qson",
    "https://github.com/nhartman000/TCTA",
    "https://github.com/nhartman000/T.O.T.E-loops",
]


class GitsonError(ValueError):
    """Raised for malformed blocks or incomplete/inconsistent bundles."""


def make_block(block_id: str, title: str, source: str, content: str) -> Dict[str, str]:
    return {"block_id": block_id, "title": title, "source": source,
            "content": content}


def _envelope(bundle_id: str, created: str, references: Sequence[str]) -> Dict[str, Any]:
    return {
        "gitson_version": GITSON_VERSION,
        "bundle_id": bundle_id,
        "part": "1.1",
        "parts_total": 1,
        "created": created,
        "purpose": "canon-ingestion",
        "blocks": [],
        "references": list(references),
        "demoted": [],
    }


def _part_size(part: Dict[str, Any]) -> int:
    return len(json.dumps(part, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def split_canon_bundle(
    blocks: Sequence[Dict[str, str]],
    *,
    bundle_id: str,
    max_bytes: int,
    references: Optional[Sequence[str]] = None,
    bundle_seq: int = 1,
    created: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Pack `blocks` into one or more .gitson part payloads, each whose
    serialized size stays within caller-supplied `max_bytes`.

    Blocks are packed in input order. A block that cannot fit alone in an
    empty part is demoted: content dropped, its source appended to that
    part's references, and its block_id recorded under "demoted"."""
    if max_bytes <= 0:
        raise GitsonError("max_bytes must be positive")
    for b in blocks:
        missing = {"block_id", "title", "source", "content"} - set(b)
        if missing:
            raise GitsonError(f"block missing fields: {sorted(missing)}")

    refs = list(references if references is not None else CANON_REPOS)
    created = created or datetime.now(timezone.utc).isoformat()

    parts: List[Dict[str, Any]] = []
    current = _envelope(bundle_id, created, refs)

    def close_current() -> None:
        nonlocal current
        parts.append(current)
        current = _envelope(bundle_id, created, refs)

    for block in blocks:
        trial = {**current, "blocks": current["blocks"] + [dict(block)]}
        if _part_size(trial) <= max_bytes:
            current = trial
            continue
        if current["blocks"]:
            close_current()
            trial = {**current, "blocks": [dict(block)]}
            if _part_size(trial) <= max_bytes:
                current = trial
                continue
        # Block cannot fit alone under the limit: demote to reference.
        demoted_refs = current["references"] + (
            [block["source"]] if block["source"] not in current["references"] else [])
        current = {**current,
                   "references": demoted_refs,
                   "demoted": current["demoted"] + [block["block_id"]]}
        if _part_size(current) > max_bytes:
            raise GitsonError(
                f"max_bytes={max_bytes} too small even for the envelope of "
                f"demoted block {block['block_id']!r}"
            )

    parts.append(current)

    total = len(parts)
    for index, part in enumerate(parts, start=1):
        part["part"] = f"{bundle_seq}.{index}"
        part["parts_total"] = total
    return parts


def build_canon_bundle(blocks: Sequence[Dict[str, str]], *, bundle_id: str,
                       max_bytes: int, **kwargs: Any) -> List[Dict[str, Any]]:
    """Alias of split_canon_bundle with the same disclosed behavior."""
    return split_canon_bundle(blocks, bundle_id=bundle_id,
                              max_bytes=max_bytes, **kwargs)


def write_parts(parts: Sequence[Dict[str, Any]], directory: str | Path,
                stem: str = "canon") -> List[Path]:
    """Write parts as <stem>.<part>.gitson files, e.g. canon.1.1.gitson."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for part in parts:
        path = directory / f"{stem}.{part['part']}.gitson"
        path.write_text(
            json.dumps(part, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def load_bundle(paths: Sequence[str | Path]) -> Dict[str, Any]:
    """Reassemble a bundle from its part files. Raises GitsonError on a
    missing/duplicate part or inconsistent bundle metadata -- a partial
    bundle is never silently presented as complete."""
    if not paths:
        raise GitsonError("no part files given")
    parts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]

    bundle_ids = {p["bundle_id"] for p in parts}
    if len(bundle_ids) != 1:
        raise GitsonError(f"mixed bundle_ids: {sorted(bundle_ids)}")
    totals = {p["parts_total"] for p in parts}
    if len(totals) != 1:
        raise GitsonError(f"inconsistent parts_total: {sorted(totals)}")
    total = totals.pop()

    indexed: Dict[int, Dict[str, Any]] = {}
    for p in parts:
        seq, _, idx = p["part"].partition(".")
        index = int(idx)
        if index in indexed:
            raise GitsonError(f"duplicate part {p['part']!r}")
        indexed[index] = p
    missing = sorted(set(range(1, total + 1)) - set(indexed))
    if missing:
        raise GitsonError(f"missing part index(es): {missing}")

    blocks: List[Dict[str, str]] = []
    references: List[str] = []
    demoted: List[str] = []
    for index in range(1, total + 1):
        part = indexed[index]
        blocks.extend(part["blocks"])
        for ref in part["references"]:
            if ref not in references:
                references.append(ref)
        for d in part["demoted"]:
            if d not in demoted:
                demoted.append(d)

    first = indexed[1]
    return {
        "gitson_version": first["gitson_version"],
        "bundle_id": first["bundle_id"],
        "parts_total": total,
        "created": first["created"],
        "purpose": first["purpose"],
        "blocks": blocks,
        "references": references,
        "demoted": demoted,
    }
