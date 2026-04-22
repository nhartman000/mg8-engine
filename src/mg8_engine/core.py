import json
from pathlib import Path
from .models import Mg8Unit
from .ork import execute_ork

def load_mg8(path: str | Path) -> Mg8Unit:
    """Load a .mg8 unit from file."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Mg8Unit.model_validate(data)

def run_mg8(path: str | Path, llm_callback=None):
    """Load and execute an MG8 unit."""
    unit = load_mg8(path)
    result = execute_ork(unit, llm_callback)
    return result