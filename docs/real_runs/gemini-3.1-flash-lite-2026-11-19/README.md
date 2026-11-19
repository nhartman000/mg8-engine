# Real end-to-end runs of `demo.py` (2026-11-19)

Provider: Google Gemini, model `gemini-3.1-flash-lite-preview` (a small, cheap model), `NYCH_LLM_PROVIDER=gemini`.
Run: `NYCH_LLM_PROVIDER=gemini GEMINI_MODEL=gemini-3.1-flash-lite-preview python demo.py "<sentence>"`.
These are not OpenAI runs: the OpenAI key available on the box was valid but the account had no credits
(`credit_balance_exhausted`), so no OpenAI completions were possible. The engine already supports OpenAI
(`NYCH_LLM_PROVIDER=openai OPENAI_MODEL=<model>`); it was not exercised.

| Run | Input | Outcome |
| --- | --- | --- |
| run1 | Re-ran both test suites after changes | Stopped by canon validation: the model wrote a gate whose `outcomes` was a string. Before this PR that crashed in unit assembly with a traceback; now it is a clean `PipelineError` (see `validate_congruence_response`). |
| run2 | Run the unit tests before tagging a release | Completed. Gates 01/02/03 = PASS/PASS/PASS. 5 model calls, 3756 tokens in / 823 out. |
| run3 | Verify the backup and confirm no errors were reported | Completed. Gates = PASS/INTERMEDIATE/INTERMEDIATE. 5 calls, 3698 in / 852 out. |

Read this before quoting the gate results: in this engine profile **the model itself answers each gate**
(`gate_llm`). In run2, `gate_01_run_unit_tests` is PASS although no tests were run. These PASS values are the
model's judgement, not evidence. The evidence-based gating (tool evidence, single-use permits, hash-chained log)
is what `mg8-runtime` implements. There are no permits in `mg8-engine`; its audit artefact is `trace.qson`
(entries, not a hash chain). Do not describe these runs as verified execution.
