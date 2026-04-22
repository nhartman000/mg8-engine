
import click
from pathlib import Path
from engine.models import Mg8Unit
from engine.ork import execute_ork
import json

@click.command()
@click.argument("mg8_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output qson file")
def cli(mg8_file, output):
    """Run an MG8 unit."""
    path = Path(mg8_file)
    with open(path, "r") as f:
        data = json.load(f)

    unit = Mg8Unit.model_validate(data)

    click.echo(f"Executing {path.name} ...")
    result = execute_ork(unit)

    out_path = Path(output or f"{path.stem}_trace.qson")
    with open(out_path, "w") as f:
        f.write(result.model_dump_json(indent=2))

    click.echo(f"Trace written to {out_path}")

if __name__ == "__main__":
    cli()
