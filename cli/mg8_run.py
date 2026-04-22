import click
from pathlib import Path
from engine.core import run_mg8

@click.command()
@click.argument("mg8_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output trace file")
def cli(mg8_file, output):
    click.echo(f"🚀 Loading MG8 unit: {mg8_file}")

    def simple_llm(prompt):
        click.echo("   [LLM called with strict Nych gate prompt]")
        return {"transformed": True}  # replace with real call

    result = run_mg8(mg8_file, simple_llm)

    out_path = Path(output or f"{Path(mg8_file).stem}_trace.qson")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))

    click.echo(f"✅ Execution complete. Trace saved to: {out_path}")
    click.echo(f"   {len(result.qson.entries)} gates traced.")

if __name__ == "__main__":
    cli()
