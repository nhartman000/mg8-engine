import json
import os
from pathlib import Path

import click
from google import genai

from .core import run_mg8

_gemini_client = None


def get_gemini_llm():
    global _gemini_client
    if _gemini_client is None:
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
        return source.parent / trace_ref
    return source.with_name(f"{source.stem}_trace.qson")


@click.command()
@click.argument("mg8_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default=None, help="Override QSON trace output path")
def cli(mg8_file, output):
    """Run an MG8 unit with the reference Gemini adapter."""
    click.echo(f"Loading MG8 unit: {mg8_file}")

    result = run_mg8(mg8_file, get_gemini_llm())

    out_path = Path(output) if output else _default_trace_path(mg8_file, result)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.qson.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Execution complete. QSON trace saved to: {out_path}")
    click.echo(f"Gate attempts traced: {len(result.qson.entries)}")
    click.echo(f"Final state: {result.gst.state}")


if __name__ == "__main__":
    cli()
