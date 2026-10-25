# Response-contract repeatability experiment

This publishes a finite live-generation result, not a claim of universal deterministic inference.

## Observed result

Model returned by the provider: `gpt-6.1-sol`, through OpenAI Codex OAuth. Each condition used three fresh calls with identical request content within that condition. Calls were interleaved. No temperature or seed was supplied, no answer was reused, and no divergent output was repaired or normalized. Both batches reported zero cached input tokens.

| Batch | Condition | Calls | Distinct UTF-8 responses | Identical pairs |
|---|---|---:|---:|---:|
| Original | Plain prompt | 3 | 3 | 0/3 |
| Original | Original gates/GST, flat | 3 | 3 | 0/3 |
| Original | Original gates/GST, structured | 3 | 3 | 0/3 |
| Revised | Simple prose and globals | 3 | 1 | 3/3 |
| Revised | Fixed terms and clause order | 3 | 1 | 3/3 |
| Revised | Single-production grammar | 3 | 1 | 3/3 |

All 18 generated responses are retained in the evidence, including the unsuccessful original conditions. The simple revised condition repeatedly produced this 108-byte response:

> Photosynthesis uses energy from sunlight to turn carbon dioxide and water into glucose and oxygen in plants.

SHA-256: `deace3951b7af2c7698f1fd2495a361159ba147f803e8afd4c86828268cc29a8`

The sentence above is an observed result, not an answer supplied to the generation requests.

## Contract changes

- Removed the original syllabic-verse requirement rather than combining verse with a prose contract.
- Used ninth-grade plain-language intent, active voice and simple-present tense.
- Required one subject–predicate sentence, exact whitespace and one final period.
- Supplied the process, energy source, inputs, outputs and organism as GST facts.
- Tested progressively narrower wording: relatively open prose, ordered scientific terms, and a single-production grammar.

The [example contracts](../../examples/response-contracts/) retain the demonstrated GST and G8SON bytes. Only example manifest routing metadata was adapted: a valid `.qson` trace reference and explicit `response-contract-v1` profile. The natural-language `atomic_requirements` remain an explicitly named prompt profile, not a schema migration or a claim of generic runtime predicate enforcement.

## Evidence and reproduction

- `evidence/original/observations.json`: all original responses, output-text deltas, hashes, provider IDs/model and token usage.
- `evidence/revised/observations.json`: the same evidence for all revised conditions.
- Each evidence directory has one complete `requests/<condition>.json` per repeated payload.
- `audit.qson` in each directory is a derived append-only experimental JSONL observation ledger, not a certified canonical-QSON serialization.
- `verify_evidence.py`: offline assertions for exact bytes, unique provider IDs, request identity, token totals and all declared counts.

From the repository root:

```sh
python experiments/response-contracts/verify_evidence.py
```

Published response strings are unchanged. Public evidence omits local machine paths and full reasoning/private transport events; it retains output-text deltas and the SHA-256 of each original raw event file. This curation is explicit and does not turn the publication into independently authenticated provider receipts.

Source baselines: NYCH `cee3610723ffe4877c424591711fed29717ab655`, mg8-engine `c44ca2fac1849d973b65c9996a7d39ed586ea6e6`. The archived source was `mgate-keeper99.zip`, SHA-256 `9c974a63579143e0e904daa4b84be6206a4ebed91f1100c7e6b1cbbac5329481`. Originals were not modified. New code in this publication is a portable integration of the model-facing contract, not a claim that the earlier experiment ran this later implementation.

## Limits

These are short responses for one supplied-fact task. Three matching calls are observed repeatability, not a universal guarantee. Several gates/globals changed together, so the experiment does not isolate a causal factor. The single-production grammar essentially predetermines wording; the simple variant permits alternatives and its observed match must be distinguished from that serialization case. Ninth-grade readability and scientific accuracy were not independently certified. Runtime comparison of bytes is not evaluation of every authored semantic gate. No backend fingerprint was returned, and backend input caching is not under host control.
