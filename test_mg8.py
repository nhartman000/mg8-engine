from src.mg8_engine.core import run_mg8

def dummy_llm(prompt):
    print("   [LLM called with ADSR + Nych prompt]")
    return {"transformed": True, "status": "processed"}

result = run_mg8("examples/tote_example.mg8", dummy_llm)

print(f"Execution complete. {len(result.qson.entries)} gates traced.")
print("Final state:", result.gst.state)