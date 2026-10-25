#!/usr/bin/env python3
"""Offline regression assertions over the published live observations."""
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ids = set()
total = 0
for case in ("original", "revised"):
    folder = ROOT / "evidence" / case
    data = json.loads((folder / "observations.json").read_text())
    records = data["records"]
    ledger = [json.loads(line) for line in (folder / "audit.qson").read_text().splitlines()]
    assert len(records) == len(ledger) == 9
    assert data["provider_reported_cached_input_tokens"] == 0
    for record, event in zip(records, ledger):
        assert event["observation"] == record
        payload = json.loads((folder / "requests" / (record["group"] + ".json")).read_text())
        assert "temperature" not in payload and "seed" not in payload
        assert "prompt_cache_key" not in payload
        request_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        assert request_hash == record["request_sha256"]
        raw = record["response"].encode("utf-8")
        assert "".join(record["output_text_deltas"]).encode("utf-8") == raw
        assert len(raw) == record["response_bytes"]
        assert hashlib.sha256(raw).hexdigest() == record["response_sha256"]
        assert record["provider_model"] == "gpt-6.1-sol"
        assert record["provider_response_id"] not in ids
        ids.add(record["provider_response_id"])
    assert Counter(record["group"] for record in records) == {group: 3 for group in data["groups"]}
    for group, expected in data["groups"].items():
        rows = [row for row in records if row["group"] == group]
        hashes = [row["response_sha256"] for row in rows]
        pairs = list(itertools.combinations(hashes, 2))
        assert len(set(hashes)) == expected["distinct_responses"]
        assert sum(a == b for a, b in pairs) == expected["identical_pairs"]
        assert len(pairs) == expected["total_pairs"]
        assert len({row["request_sha256"] for row in rows}) == 1
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        assert sum(row["usage"][field] for row in records) == data["total_usage"][field]
    total += len(records)
    print(case + ": verified 9 live observations, raw content, request hashes and declared group results")
assert total == len(ids) == 18
print("PASS: 18 distinct live completions; original divergence and revised exact matches preserved")
