#!/usr/bin/env python3
"""Offline regression checks over the published live observations (explicit checks; valid under python -O)."""
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path


def check(condition, description):
    """Explicit check (not `assert`) so the verifier still rejects tampering under `python -O`."""
    if not condition:
        raise SystemExit("FAIL: evidence check did not hold: " + description)


ROOT = Path(__file__).resolve().parent
ids = set()
total = 0
for case in ("original", "revised"):
    folder = ROOT / "evidence" / case
    data = json.loads((folder / "observations.json").read_text())
    records = data["records"]
    ledger = [json.loads(line) for line in (folder / "audit.qson").read_text().splitlines()]
    check(len(records) == len(ledger) == 9, 'len(records) == len(ledger) == 9')
    check(data["provider_reported_cached_input_tokens"] == 0, 'data["provider_reported_cached_input_tokens"] == 0')
    for record, event in zip(records, ledger):
        check(event["observation"] == record, 'event["observation"] == record')
        payload = json.loads((folder / "requests" / (record["group"] + ".json")).read_text())
        check("temperature" not in payload and "seed" not in payload, '"temperature" not in payload and "seed" not in payload')
        check("prompt_cache_key" not in payload, '"prompt_cache_key" not in payload')
        request_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        check(request_hash == record["request_sha256"], 'request_hash == record["request_sha256"]')
        raw = record["response"].encode("utf-8")
        check("".join(record["output_text_deltas"]).encode("utf-8") == raw, '"".join(record["output_text_deltas"]).encode("utf-8") == raw')
        check(len(raw) == record["response_bytes"], 'len(raw) == record["response_bytes"]')
        check(hashlib.sha256(raw).hexdigest() == record["response_sha256"], 'hashlib.sha256(raw).hexdigest() == record["response_sha256"]')
        check(record["provider_model"] == "gpt-6.1-sol", 'record["provider_model"] == "gpt-6.1-sol"')
        check(record["provider_response_id"] not in ids, 'record["provider_response_id"] not in ids')
        ids.add(record["provider_response_id"])
    check(Counter(record["group"] for record in records) == {group: 3 for group in data["groups"]}, 'Counter(record["group"] for record in records) == {group: 3 for group in data["groups"]}')
    for group, expected in data["groups"].items():
        rows = [row for row in records if row["group"] == group]
        hashes = [row["response_sha256"] for row in rows]
        pairs = list(itertools.combinations(hashes, 2))
        check(len(set(hashes)) == expected["distinct_responses"], 'len(set(hashes)) == expected["distinct_responses"]')
        check(sum(a == b for a, b in pairs) == expected["identical_pairs"], 'sum(a == b for a, b in pairs) == expected["identical_pairs"]')
        check(len(pairs) == expected["total_pairs"], 'len(pairs) == expected["total_pairs"]')
        check(len({row["request_sha256"] for row in rows}) == 1, 'len({row["request_sha256"] for row in rows}) == 1')
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        check(sum(row["usage"][field] for row in records) == data["total_usage"][field], 'sum(row["usage"][field] for row in records) == data["total_usage"][field]')
    total += len(records)
    print(case + ": verified 9 live observations, raw content, request hashes and declared group results")
check(total == len(ids) == 18, 'total == len(ids) == 18')
print("PASS: 18 distinct live completions; original divergence and revised exact matches preserved")
