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
- **DISCHARGE RATE: Extract ONLY the numerical value for the discharge rate. Ignore any units (like "MT/day", "tons per day", "TPD", "Metric Tons per Day") or descriptive text. Map this clean numerical string to the key "Discharge Rate".
  Examples:
  - If text is "Discharge Rate: 15,000 MT/day", extract "15000".
  - If text is "Rate of discharge is 12,500 TPD", extract "12500".
  - If text is "500 tons/day", extract "500".
  - If text is "Discharging at 20,000 Metric Tons per Day", extract "20000".**
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
- Chronological Events: as a list of objects with the following fields extracted from the SoF's chronological logs:
  - Date (e.g., "DD/MM/YYYY")
  - Day (e.g., "Monday")
  - start_time (e.g., "HH:MM")
  - end_time (e.g., "HH:MM")
  - Event (description of the event/phase)
  - Remarks (any additional comments)

⚠️ STRICTLY return the data in the following JSON format:

```json
{
  "Vessel Name": "...",
  "A/C": "...",
  "TERMS": "...",
  "PRODUCT": "...",
  "Discharge Rate": "...", // Changed key from DISRATE to Discharge Rate
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
    {
      "Date": "...",
      "Day": "...",
      "start_time": "...",
      "end_time": "...",
      "Event": "...",
      "Remarks": "..."
    }
  ]
}
```
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
        
        extracted_json = json.loads(match.group(0))

        # Post-processing for Discharge Rate to ensure it's a clean numerical string
        if "Discharge Rate" in extracted_json and extracted_json["Discharge Rate"] is not None:
            disrate_value = str(extracted_json["Discharge Rate"])
            # Use regex to find the first sequence of digits and optional decimal point
            # This regex is made more robust to handle commas, spaces, and common units
            disrate_num_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)', disrate_value.replace(" ", ""))
            if disrate_num_match:
                extracted_json["Discharge Rate"] = disrate_num_match.group(1).replace(",", "") # Remove commas after extraction
            else:
                extracted_json["Discharge Rate"] = "" # Set to empty string if no number found

        return extracted_json, raw
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
        for b in self.blocks:
            try:
                st = self._parse_dt(b["start_time"])
                et = self._parse_dt(b["end_time"])
            except (KeyError, ValueError, TypeError) as err:
                # log or print(b) here if you need to debug
                continue
            total += (et - st).total_seconds() / 3600.0
            print(f"total:{total}")
        return total

    def total_deduction_hours(self) -> float:
        # Ensure total_hours is converted to float before summing
        deducted_sum = sum(
            float(d.get("total_hours", 0.0)) # Explicitly cast to float
            for d in self.deductions
            if d.get("deduct", False)
        )
        print(f'sum:{deducted_sum}')
        return deducted_sum

    def net_laytime_hours(self) -> float:
        print(f"records:{self.blocks}")
        print(f"deductions:{self.deductions}")
        return self.total_block_hours() - self.total_deduction_hours()
