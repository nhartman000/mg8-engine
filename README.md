# mg8-engine

**Minimal deterministic execution engine** powered by **Nych symbolic protocol** and **ADSR gating**.

Designed to be concise, traceable, and easy for developers to adopt.

## Core Idea

- **Nych**: Symbolic determinism using fixed modalities + emoji gestalt + compressed metadata
- **MG8**: Lightweight container that executes gates with rich ADSR control (Attack, Decay, Sustain, Release + Pan)
- **TOTE**: Simple Test → Operate → Test → Exit pattern

## Installation

```bash
pip install -e .
Set your Gemini API key:
PowerShell$env:GEMINI_API_KEY = "your_gemini_key"
Usage
Bashmg8-run examples/tote_example.mg8
This runs a hammer/nail example demonstrating:

Visual test (👀)
Kinesthetic operate (👏👏)
Final confirmation test (👀)

Key Features

ADSR gating as primary control mechanism (not binary)
Nych symbolic tokenization in every prompt
Immutable QSON trace for every execution
Easy to extend with other LLMs

Project Layout
textsrc/mg8_engine/
├── nych/core.py      # Nych protocol
├── models.py         # Data models (G8Gate with ADSR)
├── ork.py            # Execution engine + TOTE
├── core.py           # Load & run
└── cli.py            # mg8-run command

This runs a classic hammer/nail TOTE example using visual and kinesthetic modalities.
Interesting Anecdotal Observation
During development, once the TOTE loop stabilized and consistently reached "status": "nailed_down", both Gemini and the AI assistant (me) fell into a highly repetitive response pattern — even though the prompts varied slightly each time.
This was unexpected. LLMs are generally expected to show variability, yet both models entered a strong "attractor" state and began repeating similar structure and phrasing.
This phenomenon illustrates exactly why deterministic gating (ADSR + Nych) and strict tracing are valuable: they can help break or control these natural repetition loops in LLM reasoning.
It’s a nice real-world example of the kind of behavior mg8 is designed to study and manage.
Core Concepts

G8Gate: Uses ADSR (Attack, Decay, Sustain, Release) + Pan instead of simple binary logic
Nych: Fixed modality operators and symbolic tokenization
QSON: Full immutable trace of every gate execution


License

MIT