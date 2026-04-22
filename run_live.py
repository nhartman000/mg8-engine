from src.mg8_engine.core import run_mg8
from google import genai
import os

# === CONFIGURE YOUR GEMINI KEY HERE ===
if not os.getenv("GEMINI_API_KEY"):
    print("ERROR: Set your GEMINI_API_KEY first!")
    print('Example: $env:GEMINI_API_KEY = "AIzaSy..."')
    exit(1)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def gemini_llm(prompt: str) -> dict:
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",        # change to "gemini-1.5-flash" if needed
            contents=prompt,
            config={
                "temperature": 0.1,
                "max_output_tokens": 800,
                "response_mime_type": "application/json",
            }
        )
        
        text = response.text.strip()
        print(f"   [Gemini responded - {len(text)} chars]")

        import json
        try:
            return json.loads(text)
        except:
            return {"raw_output": text[:300], "transformed": True}
            
    except Exception as e:
        print(f"   [Gemini Error: {e}]")
        return {"transformed": True, "error": str(e)}


print("🚀 Running MG8 with real Gemini...\n")

result = run_mg8("examples/tote_example.mg8", gemini_llm)

print(f"\n✅ Execution complete. {len(result.qson.entries)} gates traced.")
print("Final state:", result.gst.state)

# Show summary of what happened
print("\nGate trace summary:")
for entry in result.qson.entries:
    modality = entry.modality or "none"
    output = str(entry.llm_output)[:100] + "..." if len(str(entry.llm_output)) > 100 else str(entry.llm_output)
    print(f"  {entry.step:2d}. {entry.gate_id} [{modality}] → {output}")