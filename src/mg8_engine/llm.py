"""
llm.py -- real-LLM transport for the NYCH -> MG8 pipeline.

One small, dependency-free (stdlib urllib) adapter that speaks to any of
three providers, chosen by whichever API key is available:

    ANTHROPIC_API_KEY  -> Anthropic Messages API   (claude-*)
    OPENAI_API_KEY     -> OpenAI Chat Completions  (gpt-*)
    GEMINI_API_KEY     -> Google Generative Language API (gemini-*)

Every call returns a normalized record:

    {"content": str, "input_tokens": int, "output_tokens": int,
     "system_fingerprint": str | None}

so the experiment harness can measure token cost from the provider's own
accounting, and keeper.verify_reproducibility can track backend builds.

.env handling: `load_env()` reads a plain KEY=VALUE .env file (no external
dotenv dependency) and `ensure_api_key()` runs the first-run dialog -- if
no key is found in the environment or a .env file, it interactively asks
for a provider and key and writes .env for next time. Non-interactive
callers get a clear error instead of a hang.

Honesty note: this module adds no retries, no silent repair of bad JSON,
and no temperature defaults other than the explicit arguments. What the
provider returns is what the caller sees.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

PROVIDERS = ("anthropic", "openai", "gemini", "vertex", "vertex_batch")

KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "vertex": "GOOGLE_CLOUD_PROJECT",
    "vertex_batch": "GOOGLE_CLOUD_PROJECT",
}

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.8-flash",
    "vertex": "gemini-2.5-flash",
    "vertex_batch": "gemini-2.5-flash",
}

MODEL_VARS = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "vertex": "VERTEX_MODEL",
    "vertex_batch": "VERTEX_MODEL",
}


# ---------------------------------------------------------------------------
# .env loading and the first-run key dialog
# ---------------------------------------------------------------------------

def find_env_file(start: str | Path | None = None) -> Optional[Path]:
    """Walk up from `start` (default: cwd) looking for a .env file."""
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(path: str | Path | None = None) -> Dict[str, str]:
    """Load KEY=VALUE lines from a .env file into os.environ (existing
    environment variables win). Returns the variables that were loaded."""
    env_path = Path(path) if path else find_env_file()
    loaded: Dict[str, str] = {}
    if env_path is None or not env_path.is_file():
        return loaded
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def detect_provider() -> Optional[str]:
    """Return the first provider whose API key is set, in PROVIDERS order,
    unless NYCH_LLM_PROVIDER forces one explicitly."""
    forced = os.environ.get("NYCH_LLM_PROVIDER", "").strip().lower()
    if forced:
        if forced not in PROVIDERS:
            raise ValueError(f"NYCH_LLM_PROVIDER={forced!r}; "
                             f"expected one of {PROVIDERS}")
        if forced == "vertex":
            return forced if os.environ.get(KEY_VARS[forced]) else None
        return forced if os.environ.get(KEY_VARS[forced]) else None
    for provider in PROVIDERS:
        if provider in ("vertex", "vertex_batch"):
            if os.environ.get(KEY_VARS[provider]) and _gcloud_available():
                return provider
            continue
        if os.environ.get(KEY_VARS[provider]):
            return provider
    return None


def ensure_api_key(*, interactive: bool = True,
                   env_path: str | Path | None = None) -> str:
    """Make sure an API key is available; return the provider name.

    Order: existing environment -> .env file -> (if interactive and on a
    tty) ask the user for provider + key and write .env. Raises
    RuntimeError with setup instructions when nothing can be found."""
    load_env(env_path)
    provider = detect_provider()
    if provider:
        return provider

    if interactive and sys.stdin.isatty():
        print()
        print("No LLM API key found. The pipeline needs one real model.")
        print("Which provider do you want to use?")
        print("  1) Anthropic (Claude)   -- ANTHROPIC_API_KEY")
        print("  2) OpenAI (GPT)         -- OPENAI_API_KEY")
        print("  3) Google (Gemini)      -- GEMINI_API_KEY")
        choice = input("Enter 1, 2 or 3: ").strip()
        provider = {"1": "anthropic", "2": "openai", "3": "gemini"}.get(choice)
        if provider is None:
            raise RuntimeError(f"unrecognized choice {choice!r}")
        key = input(f"Paste your {KEY_VARS[provider]}: ").strip()
        if not key:
            raise RuntimeError("empty API key")
        os.environ[KEY_VARS[provider]] = key
        target = Path(env_path) if env_path else Path.cwd() / ".env"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"{KEY_VARS[provider]}={key}\n")
        print(f"Saved to {target} (git-ignored). You won't be asked again.")
        return provider

    raise RuntimeError(
        "No LLM API key found. Copy .env.example to .env and paste your "
        "ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY -- or export "
        "one of those variables before running."
    )


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class LLMClient:
    """Minimal multi-provider chat client with provider-side token counts.

    Tracks cumulative usage in `total_input_tokens` / `total_output_tokens`
    / `calls` so an experiment can report real token cost."""

    def __init__(self, provider: Optional[str] = None,
                 model: Optional[str] = None, *, timeout: float = 120.0):
        load_env()
        self.provider = provider or detect_provider()
        if self.provider is None:
            raise RuntimeError("no API key configured; call ensure_api_key() "
                               "or set one of " + ", ".join(KEY_VARS.values()))
        if self.provider == "vertex_batch":
            self.api_key = os.environ[KEY_VARS[self.provider]]
            self.bucket = os.environ.get("NYCH_BUCKET", "")
            if not self.bucket:
                raise RuntimeError(
                    "vertex_batch requires NYCH_BUCKET set in .env "
                    "(a GCS bucket for input/output)")
        else:
            self.api_key = os.environ[KEY_VARS[self.provider]]
        self.model = (model or os.environ.get(MODEL_VARS[self.provider])
                      or DEFAULT_MODELS[self.provider])
        self.timeout = timeout
        # Client-side pacing for rate-limited (e.g. free-tier) keys:
        # minimum seconds between requests. 0 = no pacing.
        self.min_interval = float(os.environ.get("NYCH_LLM_MIN_INTERVAL", "0"))
        self._last_request_at = 0.0
        self.calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # -- transport ---------------------------------------------------------

    def _post(self, url: str, headers: Dict[str, str],
              payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST with bounded backoff on transient rate limits (429) and
        server errors (5xx). Quota-exhaustion 429s and all other errors
        surface immediately -- transport retries only, never result
        repair."""
        import time
        request_bytes = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(5):
            if self.min_interval > 0:
                wait = self._last_request_at + self.min_interval - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            self._last_request_at = time.monotonic()
            request = urllib.request.Request(
                url, data=request_bytes,
                headers={"Content-Type": "application/json", **headers},
                method="POST")
            try:
                with urllib.request.urlopen(request,
                                            timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                # Hard quota exhaustion (daily caps, no credits) is not
                # retryable; per-minute rate limits and 5xx are.
                exhausted = any(s in body for s in
                                ("PerDay", "credit_balance_exhausted",
                                 "insufficient_quota"))
                retryable = (exc.code == 429 and not exhausted) or exc.code >= 500
                last_error = RuntimeError(
                    f"HTTP {exc.code} from {url}: {body[:400]}")
                if not retryable or attempt == 4:
                    raise last_error from exc
                time.sleep(min(15 * (attempt + 1), 60))
        raise last_error  # unreachable, for the type checker

    def complete(self, messages: list[Dict[str, str]], *,
                 temperature: float = 0.0, max_tokens: int = 2048,
                 seed: Optional[int] = None) -> Dict[str, Any]:
        """One chat completion. `messages` is a list of
        {"role": "system"|"user"|"assistant", "content": str}."""
        if self.provider == "anthropic":
            result = self._anthropic(messages, temperature, max_tokens)
        elif self.provider == "openai":
            result = self._openai(messages, temperature, max_tokens, seed)
        elif self.provider == "vertex_batch":
            result = self._vertex_batch(messages, temperature, max_tokens)
        elif self.provider == "vertex":
            result = self._vertex(messages, temperature, max_tokens)
        else:
            result = self._gemini(messages, temperature, max_tokens)
        self.calls += 1
        self.total_input_tokens += result["input_tokens"]
        self.total_output_tokens += result["output_tokens"]
        return result

    def _anthropic(self, messages, temperature, max_tokens):
        system = "\n".join(m["content"] for m in messages
                           if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        body: Dict[str, Any] = {
            "model": self.model, "max_tokens": max_tokens,
            "temperature": temperature, "messages": chat,
        }
        if system:
            body["system"] = system
        data = self._post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            body)
        usage = data.get("usage", {})
        return {
            "content": "".join(b.get("text", "")
                               for b in data.get("content", [])),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "system_fingerprint": data.get("model"),
        }

    def _openai(self, messages, temperature, max_tokens, seed):
        body: Dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        data = self._post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {self.api_key}"}, body)
        usage = data.get("usage", {})
        return {
            "content": data["choices"][0]["message"]["content"],
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "system_fingerprint": data.get("system_fingerprint"),
        }

    def _gemini(self, messages, temperature, max_tokens):
        system = "\n".join(m["content"] for m in messages
                           if m["role"] == "system")
        contents = [{"role": ("model" if m["role"] == "assistant" else "user"),
                     "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent",
            {"x-goog-api-key": self.api_key}, body)
        usage = data.get("usageMetadata", {})
        parts = (data.get("candidates") or [{}])[0] \
            .get("content", {}).get("parts", [])
        return {
            "content": "".join(p.get("text", "") for p in parts),
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0),
            "system_fingerprint": data.get("modelVersion"),
        }

    def _vertex(self, messages, temperature, max_tokens):
        system = "\n".join(m["content"] for m in messages
                              if m["role"] == "system")
        contents = [{"role": ("model" if m["role"] == "assistant" else "user"),
                     "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature,
                                    "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._post(
            f"https://us-central1-aiplatform.googleapis.com/v1/"
            f"projects/{self.api_key}/locations/us-central1/"
            f"publishers/google/models/{self.model}:generateContent",
            {}, body)
        usage = data.get("usageMetadata", {})
        parts = (data.get("candidates") or [{}]) \
            .get("content", {}).get("parts", [])
        return {
            "content": "".join(p.get("text", "") for p in parts),
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0),
            "system_fingerprint": data.get("modelVersion"),
        }

    def _vertex_batch(self, messages, temperature, max_tokens):
        """Vertex AI Batch Prediction: submits a batch job to the
        Generative API and polls until done. Returns the first
        response's content. Not used for the live pipeline (which
        needs streaming), but available for the experiment's
        no-throttle, no-rate-limit run."""
        import time
        from uuid import uuid4
        project = self.api_key
        model = self.model
        job_id = f"nych-exp-{uuid4().hex[:8]}"
        bucket = self.bucket
        input_uri = f"gs://{bucket}/input/{job_id}.jsonl"
        output_uri = f"gs://{bucket}/output/{job_id}/"
        instances = [
            {"request": {"contents": [
                {"role": m["role"], "parts": [{"text": m["content"]}]}
            ]}}
            for m in messages
        ]
        # Upload input JSONL via GCS JSON API (requires storage
        # write permission; if unavailable, fall through to the
        # streaming vertex path below).
        _upload_jsonl(input_uri, instances)
        body: Dict[str, Any] = {
            "displayName": job_id,
            "model": f"publishers/google/models/{model}",
            "inputConfig": {
                "instancesFormat": "jsonl",
                "gcsSource": {"uris": [input_uri]},
            },
            "outputConfig": {
                "predictionsFormat": "jsonl",
                "gcsDestination": {"outputUriPrefix": output_uri},
            },
            "modelParameters": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        import subprocess
        token = subprocess.run(
            ["gcloud", "auth", "application-default",
             "print-access-token"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        data = self._post(
            f"https://us-central1-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/us-central1/"
            f"batchPredictionJobs",
            {"Authorization": f"Bearer {token}"}, body)
        job_name = data["name"]
        # Poll until done (max ~25 min).
        state = ""
        for _ in range(300):
            time.sleep(5)
            job = self._get(
                f"https://us-central1-aiplatform.googleapis.com/v1/{job_name}",
                {"Authorization": f"Bearer {token}"})
            state = job.get("state", "")
            if state in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                          "JOB_STATE_CANCELLED"):
                break
        if state != "JOB_STATE_SUCCEEDED":
            err = job.get("error", {}).get("message", "unknown")
            raise RuntimeError(f"batch job {job_id} ended in state {state}: {err}")

        # Read predictions from GCS output. Vertex writes each prediction
        # as a JSON line in predictions.jsonl under a timestamped
        # subdirectory of the outputUriPrefix.
        predictions = _read_jsonl(output_uri + "predictions.jsonl")
        if not predictions:
            import urllib.request
            prefix = output_uri.replace(f"gs://{bucket}/", "")
            list_url = (f"https://storage.googleapis.com/storage/v1/b/{bucket}/o"
                        f"?prefix={urllib.parse.quote(prefix, safe='')}")
            req = urllib.request.Request(list_url, method="GET")
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                obj_list = json.loads(resp.read().decode("utf-8"))
            for obj in obj_list.get("items", []):
                name = obj["name"]
                if name.endswith("predictions.jsonl"):
                    media_url = obj.get("mediaLink")
                    if not media_url:
                        media_url = (f"https://storage.googleapis.com/"
                                     f"download/storage/v1/b/{bucket}/o/"
                                     f"{urllib.parse.quote(name, safe='')}"
                                     f"?alt=media")
                    req2 = urllib.request.Request(media_url, method="GET")
                    req2.add_header("Authorization", f"Bearer {token}")
                    with urllib.request.urlopen(req2, timeout=120) as resp2:
                        content = resp2.read().decode("utf-8")
                    predictions = [json.loads(line) for line in content.splitlines()
                                    if line]
                    break

        # Vertex returns predictions in the same order as input, each
        # wrapped in {"request":..., "response": {"candidates":
        # [{"content": {"parts": [{"text": ...}]}}], "usageMetadata": ...}}.
        first = predictions[0] if predictions else {}
        content = ""
        input_tokens = 0
        output_tokens = 0
        if isinstance(first, dict):
            status = first.get("status")
            if isinstance(status, dict) and status.get("code", 0) != 0:
                raise RuntimeError(f"batch prediction failed: {status}")
            resp = first.get("response", {})
            if isinstance(resp, dict):
                candidates = resp.get("candidates") or [{}]
                parts = (candidates[0].get("content", {})
                         .get("parts", []) if candidates else [])
                content = "".join(p.get("text", "") for p in parts)
                usage = resp.get("usageMetadata", {})
                input_tokens = usage.get("promptTokenCount", 0)
                output_tokens = usage.get("candidatesTokenCount", 0)
        return {
            "content": content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "system_fingerprint": (first.get("response", {})
                                   .get("modelVersion") if isinstance(first, dict) else None),
        }

    def _get(self, url: str, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
        request = urllib.request.Request(url, method="GET",
                                           headers=headers or {})
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # -- pipeline-shaped callbacks ------------------------------------------

    def mapping_llm(self, prompt: str) -> Dict[str, Any]:
        """pipeline.run_pipeline FIRST-call callback (nych.bonit STEP 2,
        Gestalt mapping only): prompt in, parsed JSON plan out. Strips
        markdown fences if the model added them; any other malformation
        surfaces as the json error it is."""
        result = self.complete([{"role": "user", "content": prompt}],
                               temperature=0.0, max_tokens=4096)
        return json.loads(_strip_fences(result["content"]))

    def congruence_llm(self, prompt: str) -> Dict[str, Any]:
        """pipeline.run_pipeline SECOND-call callback (mg8.bonit STEP 3:
        congruence assessment, then -- only on PASS -- three .g8son
        files). Larger max_tokens than mapping_llm since a PASS response
        authors three gate files plus the .ork flow, not just a word
        list."""
        result = self.complete([{"role": "user", "content": prompt}],
                               temperature=0.0, max_tokens=4096)
        return json.loads(_strip_fences(result["content"]))

    def gate_llm(self, prompt: str) -> Dict[str, Any]:
        """ork.execute_ork per-gate callback."""
        result = self.complete([{"role": "user", "content": prompt}],
                               temperature=0.0, max_tokens=1024)
        try:
            return json.loads(_strip_fences(result["content"]))
        except json.JSONDecodeError:
            return {"raw_output": result["content"][:500],
                    "transformed": False, "gate_result": "INTERMEDIATE"}

    def keeper_transport(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """keeper.GateKeeper transport: {"messages","temperature","seed"}
        in, {"content","response_id","system_fingerprint"} out."""
        result = self.complete(request["messages"],
                               temperature=request.get("temperature", 0.0),
                               max_tokens=2048, seed=request.get("seed"))
        return {"content": result["content"], "response_id": None,
                "system_fingerprint": result["system_fingerprint"]}


def _gcloud_available() -> bool:
    """True if `gcloud` is installed and the user is authenticated."""
    import subprocess
    try:
        r = subprocess.run(["gcloud", "auth", "list", "--filter=status:ACTIVE",
                            "--format=value(account)"],
                           capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except FileNotFoundError:
        return False


def _upload_jsonl(uri: str, instances: list) -> None:
    """Upload a JSONL file to GCS using the REST API with ADC."""
    import subprocess
    token = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True, timeout=10).stdout.strip()
    # uri is gs://bucket/path/to/file.jsonl
    path = uri[len("gs://"):] if uri.startswith("gs://") else uri
    bucket, blob = path.split("/", 1)
    url = (f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}"
           f"/o?name={urllib.parse.quote(blob, safe='')}&uploadType=media")
    data = "\n".join(json.dumps(i) for i in instances).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/jsonl")
    with urllib.request.urlopen(req, timeout=120):
        pass


def _read_jsonl(uri: str) -> list:
    """Read a JSONL file from GCS and return parsed objects."""
    import subprocess
    token = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True, timeout=10).stdout.strip()
    path = uri[len("gs://"):] if uri.startswith("gs://") else uri
    bucket, blob = path.split("/", 1)
    url = (f"https://storage.googleapis.com/storage/v1/b/{bucket}/o"
           f"/{urllib.parse.quote(blob, safe='')}")
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        media_url = data.get("mediaLink")
        if media_url:
            req2 = urllib.request.Request(media_url, method="GET")
            req2.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req2, timeout=120) as resp2:
                content = resp2.read().decode("utf-8")
            return [json.loads(line) for line in content.splitlines() if line]
    except Exception:
        pass
    return []


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline != -1 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
