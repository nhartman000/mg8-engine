# Response contracts in mg8-engine

The opt-in `response-contract-v1` integration uses the demonstrated GST globals and G8SON atomic requirements as actual model-facing instructions. It does not change the existing generic gate executor, legacy keeper defaults, file-family identities or canonical schemas.

## What it does

1. Process the natural-language user prompt through canonical NYCH intake.
2. Bind the selected `.mg8` unit's complete GST and G8SON resources.
3. Preserve globals, facts, requirement IDs and authored wording in the model-facing request.
4. Generate fresh responses without supplying temperature or seed, reusing an answer, or silently repairing output.
5. Preserve requests, exact response content, provider metadata and reference-engine QSON evidence; compare UTF-8 bytes separately from semantic gate satisfaction.

Use one of [the three complete example units](../examples/response-contracts/): `simple`, `ordered` or `grammar`. Their small `flow.ork` declares one generation per trial, with no repair and no answer reuse. Repetition means separate bounded trials, not an unbounded loop.

The grammar variant essentially predetermines the rendering of supplied facts. The simple variant retains more wording freedom. The [published experiment](../experiments/response-contracts/README.md) reports the finite results and all failures as well as matches; it does not prove deterministic inference for arbitrary prompts.

## Installation boundary

Install the engine normally. The inspected NYCH revision's wheel omits its `schemas` subpackage, so use that dependency's complete editable source until its own packaging is corrected. This is an existing dependency packaging issue, not a reason to replace or silently fork NYCH.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m pip install --no-deps -e 'git+https://github.com/nhartman000/nych.git@cee3610723ffe4877c424591711fed29717ab655#egg=nych'
```

CI uses the same pinned editable-source dependency. The engine does not depend on Hermes, local source paths, or a particular agent host. Custom inference providers can use the Python callback boundary; any supplied transport must make a fresh call and preserve exact returned content.

## Python API and command line

Prepare the exact request offline, without credentials or a model call:

```sh
mg8-response examples/response-contracts/simple/response.mg8 \
  --prompt 'What is photosynthesis? Explain simply.' --request-only
```

The module form works without reinstalling the console entry point:

```sh
python -m mg8_engine.response_contract examples/response-contracts/simple/response.mg8 \
  --prompt 'What is photosynthesis? Explain simply.' --request-only
```

For live OpenAI Responses calls, configure `OPENAI_API_KEY` in your environment or secret manager, choose an available model explicitly, and use a new evidence directory:

```sh
mg8-response examples/response-contracts/simple/response.mg8 \
  --prompt 'What is photosynthesis? Explain simply.' \
  --model YOUR_AVAILABLE_MODEL --runs 3 --output-dir runs/photo-001
```

The bundled HTTP adapter makes fresh calls to OpenAI's Responses endpoint with no retries, temperature, seed or answer cache. It is distinct from the Codex OAuth transport used in the published experiment. No particular model is silently chosen. Exit codes are 0 for `MATCH`, 1 for `DIVERGENT`, and 2 for `ERROR` or invalid invocation. An existing evidence directory is refused.

Use another inference provider through the Python callback boundary:

```python
from mg8_engine.response_contract import ResponseContract

contract = ResponseContract.from_unit('examples/response-contracts/simple/response.mg8')
request = contract.request('What is photosynthesis? Explain simply.')
# send_to_provider must make a fresh call and return exact content, not a cached answer.
result = contract.verify(
    'What is photosynthesis? Explain simply.', send_to_provider,
    runs=3, output_dir='runs/photo-custom-001',
)
```

A callback accepts `{'messages': [...]}` and returns a nonempty string, or a dictionary containing `content` with optional `response_id`, `model`, `usage` and `system_fingerprint`. Each repetition receives an independent request copy. Missing/invalid responses and provider exceptions are retained as errors and never counted as a successful match. Output includes the request and contract snapshots, per-attempt content/metadata, `summary.json` and the manifest-selected QSON path underneath the new evidence directory. `MATCH` means observed byte equality, not semantic gate approval; QSON observation events retain `UNKNOWN` as their gate result rather than certifying the authored semantic requirements.

## Evidence and limits

Run the published-evidence regression checks without a provider or credentials:

```sh
python experiments/response-contracts/verify_evidence.py
```

The original and revised experiment evidence contains 18 distinct live completions. The later portable engine implementation is a separately tested integration of that contract; publishing it does not retrospectively claim that the earlier observations ran this later code.

Byte-repeatability checks do not certify scientific correctness, ninth-grade readability or all semantic G8SON requirements. A matching pair or triple is a result under the recorded conditions, not a universal guarantee. Model-declared success is not runtime authorization. Reference-engine QSON serialization and explicitly experimental published observation ledgers are identified separately; independent canonical-QSON certification is not claimed.
