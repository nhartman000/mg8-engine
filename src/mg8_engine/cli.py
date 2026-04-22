import click
from pathlib import Path
from .core import run_mg8
from google import genai
import os
import json

_gemini_client = None

def get_gemini_llm():
    global _gemini_client
    if _gemini_client is None:
        if not os.getenv("GEMINI_API_KEY"):
            raise click.ClickException("GEMINI_API_KEY environment variable is not set.")
        _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def llm_call(prompt: str) -> dict:
        try:
            response = _gemini_client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 1000,
                    "response_mime_type": "application/json",
                }
            )
            text = response.text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_output": text[:500], "transformed": True}
        except Exception as e:
            click.echo(f"   [Gemini Error: {e}]")
            return {"transformed": True, "error": str(e)}

    return llm_call


@click.command()
@click.argument("mg8_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output trace file")
def cli(mg8_file, output):
    """Run an MG8 unit with Gemini."""
    click.echo(f"🚀 Loading MG8 unit: {mg8_file}")

    llm_callback = get_gemini_llm()

    result = run_mg8(mg8_file, llm_callback)

    out_path = Path(output or f"{Path(mg8_file).stem}_trace.qson")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))

    click.echo(f"✅ Execution complete. Trace saved to: {out_path}")
    click.echo(f"   {len(result.qson.entries)} gates traced.")
    click.echo(f"   Final state: {result.gst.state}")


if __name__ == "__main__":
    cli()