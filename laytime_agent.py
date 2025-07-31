import json
import os
import re
import pandas as pd
from google.cloud import aiplatform
import google.generativeai as genai
from datetime import datetime
import numbers
from typing import List, Dict

# ---------- CONFIG ----------
PROJECT_ID = "laytimecalculation"
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
- A/C. It can be present Charterer
- TERMS
- PRODUCT
- DISCHARGE RATE/DISRATE. Check the document to find the quantity of goods which are to be discharged per day.
- LTC AT
- DEMURRAGE
- DESPATCH

### 📄 From SoF:
- Port
- Charterers
- Quantity
- NOR TENDERED (if present)
- NOR VALID (if present)
- Vessel Arrival Date & Time. It is the start time of the first event entry.
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
  "Completed Cargo": "..."
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

class LaytimeCalculator:
    def __init__(self, records: list[dict], deductions: list[dict]):
        """
        records:    List of {"start_time": str|float|datetime, "end_time": str|float|datetime, ...}
        deductions: List of {"deduct": bool, "total_hours": float, ...}
        """
        self.blocks = records
        self.deductions = deductions

    def _parse_dt(self, s) -> datetime:
        # 1) Already a datetime? return it.
        if isinstance(s, datetime):
            return s

        # 2) Numeric? Treat as UNIX timestamp (seconds since epoch).
        if isinstance(s, numbers.Number):
            try:
                return datetime.fromtimestamp(s)
            except (OSError, ValueError) as e:
                raise ValueError(f"Invalid timestamp {s!r}") from e

        # 3) String? Try your format, then ISO.
        if isinstance(s, str):
            s = s.strip()
            if not s:
                raise ValueError("Empty time string")
            try:
                return datetime.strptime(s, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    return datetime.fromisoformat(s)
                except ValueError as e:
                    raise ValueError(f"Couldn’t parse time string {s!r}") from e

        # 4) Anything else is unrecognized.
        raise ValueError(f"Cannot parse timestamp from {s!r}")

    def total_block_hours(self) -> float:
        total = 0.0
        try:
            st = self._parse_dt(self.blocks[0]["start_time"])
            et = self._parse_dt(self.blocks[-1]["end_time"])
        except:
            st = self._parse_dt(self.blocks[0]["start_time"])
            et = self._parse_dt(self.blocks[-1]["start_time"])

        total = (et - st).total_seconds() / 3600.0
        return total

    def total_deduction_hours(self) -> float:
        return sum( 
            float(d.get("total_hours"))
            for d in self.deductions
            if d.get("deduct", False)
            and isinstance(d.get("total_hours", None), (int, float, str))
            and str(d["total_hours"]).replace('.', '', 1).isdigit()
        )

    def net_laytime_hours(self) -> float:
        return self.total_block_hours() - self.total_deduction_hours()

