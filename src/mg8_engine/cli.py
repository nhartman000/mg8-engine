import json
import os
from pathlib import Path

import click
from .core import run_mg8

_gemini_client = None


def get_gemini_llm():
    global _gemini_client
    if _gemini_client is None:
        try:
            from google import genai
        except ImportError as exc:
            raise click.ClickException(
                "Gemini support is not installed. Run: pip install 'mg8-engine[gemini]'"
            ) from exc
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise click.ClickException("GEMINI_API_KEY environment variable is not set.")
        _gemini_client = genai.Client(api_key=api_key)

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def llm_call(prompt: str) -> dict:
        try:
            response = _gemini_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 1000,
                    "response_mime_type": "application/json",
                },
            )
            text = (response.text or "").strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {
                    "raw_output": text[:500],
                    "transformed": False,
                    "gate_result": "INTERMEDIATE",
                }
        except Exception as exc:
            raise click.ClickException(f"Gemini execution failed: {exc}") from exc

    return llm_call


def _default_trace_path(mg8_file: str, result) -> Path:
    source = Path(mg8_file)
    if result.manifest is not None:
        trace_ref = Path(result.manifest.trace)
        if trace_ref.is_absolute():
            raise click.ClickException("Manifest trace path must be relative")

        base = source.parent.resolve()
        resolved = (base / trace_ref).resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise click.ClickException(
                "Manifest trace path must remain inside the MG8 unit directory"
            ) from exc
        return resolved

    return source.with_name(f"{source.stem}_trace.qson")


@click.command()
@click.argument("mg8_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default=None, help="Override QSON trace output path")
@click.option("--provider", type=click.Choice(["none", "gemini"]), default="none", show_default=True, help="Optional state-proposal provider; gates remain authoritative")
def cli(mg8_file, output, provider):
    """Run an MG8 unit locally or with an optional state proposer."""
    click.echo(f"Loading MG8 unit: {mg8_file}")

    callback = get_gemini_llm() if provider == "gemini" else None
    result = run_mg8(mg8_file, callback)

    out_path = Path(output) if output else _default_trace_path(mg8_file, result)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.qson.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Execution complete. QSON trace saved to: {out_path}")
    click.echo(f"Gate attempts traced: {len(result.qson.events)}")
    click.echo(f"Final state: {result.gst.state}")


if __name__ == "__main__":
    cli()
