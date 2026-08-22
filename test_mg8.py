"""Manual no-network smoke runner for the legacy embedded TOTE fixture."""

from mg8_engine.core import run_mg8


def dummy_llm(_prompt):
    return {
        "transformed": True,
        "gate_result": "PASS",
        "status": "processed",
    }


def main():
    result = run_mg8("examples/tote_example.mg8", dummy_llm)
    print(f"Execution complete. {len(result.qson.entries)} gate attempts traced.")
    print("Final state:", result.gst.state)


if __name__ == "__main__":
    main()
