import json
import os
import re
import pandas as pd
from google.cloud import aiplatform
import google.generativeai as genai

# ---------- CONFIG ----------
PROJECT_ID = "pdf-extraction-464009"
LOCATION = "global"
MODEL = "models/gemini-1.5-flash-latest"

# ---------- INIT ----------
aiplatform.init(project=PROJECT_ID, location=LOCATION)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def flatten_contract(contract_data):
    flattened = {}
    for section in contract_data.get("Sections", []):
        for item in section.get("Items", []):
            if isinstance(item, dict):
                flattened.update(item)
        for sub in section.get("Subsections", []):
            if isinstance(sub, dict):
                title = sub.get("Subsection Title") or sub.get("Clause Title")
                content = sub.get("Content", "")
                if title and content:
                    flattened[title] = content
    return flattened

# ---------- GEMINI EXTRACTION PROMPT ----------
def extract_metadata_from_docs(contract_data, sof_data):
    model = genai.GenerativeModel(MODEL)

    prompt = """
You are a maritime document extraction assistant.

You will receive:
1. A structured Contract JSON (with sections and subsections)
2. A Statement of Facts (SoF) JSON containing vessel operations and events.

---

🎯 YOUR TASK: Extract and return a structured JSON object with the following keys:

### 📘 From Contract:
- Vessel Name
- A/C
- TERMS
- PRODUCT
- DISCHARGE RATE = DISRATE
- LTC AT
- DEMURRAGE
- DESPATCH

### 📄 From SoF:
- Port
- Charterer
- Quantity
- NOR TENDERED (if present)
- NOR VALID (if present)
- Vessel Arrival Date & Time
- Vessel Berthed Date & Time
- Commenced Cargo Date & Time
- Completed Cargo Date & Time
- Chronological Events: as a list of objects with:
  - Date & Time
  - Event
  - Remarks (if present)

⚠️ STRICTLY return the data in the following JSON format:

```json
{
  "Vessel Name": "...",
  "A/C": "...",
  "TERMS": "...",
  "PRODUCT": "...",
  "DISRATE": "...",
  "LTC AT": "...",
  "DEMMURAGE": "...",
  "DESPATCH": "...",
  "Port": "...",
  "Charterer": "...",
  "Quantity": "...",
  "NOR TENDERED": "...",
  "NOR VALID": "...",
  "Vessel Arrival": "...",
  "Vessel Berthed": "...",
  "Commenced Cargo": "...",
  "Completed Cargo": "...",
  "Chronological Events": [
    { "Date & Time": "...", "Event": "...", "Remarks": "..." },
    ...
  ]
}
"""
    try:
        flattened_contract = flatten_contract(contract_data)
        response = model.generate_content(
            [prompt, f"\n\nContract:\n{json.dumps(flattened_contract)}\n\nSoF:\n{json.dumps(sof_data)}"],
            generation_config={"response_mime_type": "application/json"}
        )
        raw = response.text.strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("❌ No JSON object found in Gemini response")
        return json.loads(match.group(0)), raw
    except Exception as e:
        return {"error": str(e)}, raw if 'raw' in locals() else ""
