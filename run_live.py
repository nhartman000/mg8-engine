import json
import os

from google import genai

from mg8_engine.core import run_mg8

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: Set GEMINI_API_KEY in your environment first.")
    raise SystemExit(1)

model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client(api_key=api_key)


def gemini_llm(prompt: str) -> dict:
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "temperature": 0.1,
            "max_output_tokens": 800,
            "response_mime_type": "application/json",
        },
    )

    text = (response.text or "").strip()
    print(f"   [Gemini responded - {len(text)} chars]")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "raw_output": text[:300],
            "transformed": False,
            "gate_result": "INTERMEDIATE",
        }


print(f"Running MG8 reference profile with model: {model}\n")
result = run_mg8("examples/tote_example.mg8", gemini_llm)

print(f"\nExecution complete. {len(result.qson.entries)} gate attempts traced.")
print("Final state:", result.gst.state)

print("\nGate trace summary:")
for entry in result.qson.entries:
    modality = entry.modality or "none"
    output = str(entry.llm_output)
    if len(output) > 100:
        output = output[:100] + "..."
    print(
        f"  {entry.sequence:2d}. {entry.gate_id} [{modality}] "
        f"{entry.result or 'UNRESOLVED'} → {output}"
    )
