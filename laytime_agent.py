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

# ---------- AGENT PROMPT ----------
def extract_laytime_from_docs(contract_data, sof_data):
    model = genai.GenerativeModel(MODEL)

    prompt = """
You are a laytime calculation agent for maritime contracts.

You will receive two structured JSON documents:

1. A **Contract JSON** – includes:
   - Vessel Name
   - A/C
   - LTC AT
   - Port
   - Charterer
   - Arrival Date
   - Cargo Quantity
   - Discharge Rate
   - Working Hours (Weekday): "HH:MM–HH:MM"
   - Working Hours (Saturday): "HH:MM–HH:MM"

2. A **Statement of Facts (SoF) JSON** – includes:
   - A list of events, each with:
     - Event: one of ["Commenced Discharging", "Discharging Suspended", "Discharging Resumed", "Completed Discharging"]
     - Timestamp: in format "YYYY-MM-DD HH:MM"

---

### ⛔ ABSOLUTE RULES — DO NOT:

- ❌ DO NOT estimate time
- ❌ DO NOT assume full working days
- ❌ DO NOT infer durations or events
- ❌ DO NOT count Sundays or hours outside declared working hours
- ❌ DO NOT skip suspended periods — they ARE counted
- ❌ DO NOT summarize or describe — only compute and return structured output

---

### ✅ WHAT TO DO:

You must strictly compute **Laytime Used (Hours)** as follows:

1. Extract:
   - First `"Commenced Discharging"` timestamp = `start_time`
   - Final `"Completed Discharging"` timestamp = `end_time`

2. Loop hour-by-hour from `start_time` to `end_time` (example: from 2023-08-01 17:00 to 2023-08-03 11:00)

3. For each hour:
   - If the day is **Sunday**, skip
   - If the day is **Saturday**, count the hour only if it falls **within Saturday working hours**
   - If the day is **Monday to Friday**, count the hour only if it falls **within weekday working hours**
   - ⚠️ DO NOT assume full blocks — validate every individual hour by clock time
   - Count even if that hour overlaps with a "Suspended" period

4. After looping:
   - `Laytime Used (Hours)` = total valid working hours in that range
   - `Laytime Used (Days)` = Laytime Used (Hours) ÷ Weekday working hours per day

5. Compute:
   - `Laytime Allowed (Days)` = Cargo Quantity ÷ Discharge Rate
   - `Laytime Allowed (Hours)` = Laytime Allowed (Days) × weekday hours/day
   - `Laytime Remaining (Days)` = Laytime Allowed (Days) – Laytime Used (Days)

---

### 💡 You MUST use only what is explicitly provided.
- No guessing.
- No assumptions.
- If a timestamp is missing — return 0 hours used.

---

### 🔢 Example:

Working Hours:
- Weekdays: 09:00–18:00 (9 hours)
- Saturday: 09:00–12:00 (3 hours)
- Sunday: zero

SoF Events:
- 2023-08-01 17:00 — Commenced Discharging
- 2023-08-02 11:00 — Discharging Suspended
- 2023-08-02 14:00 — Discharging Resumed
- 2023-08-03 11:00 — Completed Discharging

Count only valid hours:
- Aug 1: 17:00–18:00 → 1 hr
- Aug 2: 09:00–11:00 → 2 hrs, 14:00–18:00 → 4 hrs = 6 hrs
- Aug 3: 09:00–11:00 → 2 hrs
- Total Laytime Used = **9 hours**

---

### ✅ FINAL OUTPUT FORMAT (STRICTLY JSON ONLY):

```json
{
  "Vessel Name": "MV Grain Carrier",
  "A/C": "...",
  "LTC AT": "...",
  "Port": "Vancouver Grain Terminal",
  "Charterer": "Global Grain Traders Ltd.",
  "Arrival Date": "2023-08-01 09:00",
  "Cargo Quantity": "50,000",
  "Discharge Rate": "5,000",
  "Time allowed for laytime (Qty/Disrate)": "50000 / 5000",
  "Laytime Allowed (Days)": 10,
  "Laytime Allowed (Hours)": 90,
  "Laytime Used (Hours)": 9,
  "Laytime Used (Days)": 1.0,
  "Laytime Remaining (Days)": 9.0,
  "Working Hours (Weekday)": "09:00–18:00",
  "Working Hours (Saturday)": "09:00–12:00",
  "Calculation Notes": "Laytime used is calculated hour-by-hour. Includes suspended time. Sunday and off-hour time excluded. All timestamps strictly respected."
}

"""

    try:
        response = model.generate_content(
            [prompt, f"\n\nContract:\n{json.dumps(contract_data)}\n\nSoF:\n{json.dumps(sof_data)}"],
            generation_config={"response_mime_type": "application/json"}
        )
        raw = response.text.strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("❌ No JSON object found in Gemini response")
        return json.loads(match.group(0)), raw
    except Exception as e:
        return {"error": str(e)}, raw if 'raw' in locals() else ""

# ---------- EXCEL EXPORT ----------
def extract_excel_data_from_docs(laytime_agent_response: dict):
    meta = laytime_agent_response.get("metadata", laytime_agent_response)

    return pd.DataFrame([{
        "Vessel Name": meta.get("Vessel Name", ""),
        "A/C": meta.get("A/C", ""),
        "LTC AT": meta.get("LTC AT", ""),
        "Time allowed for laytime (Qty/Disrate)": meta.get("Time allowed for laytime (Qty/Disrate)", ""),
        "Laytime Allowed (Days)": meta.get("Laytime Allowed (Days)", ""),
        "Laytime Allowed (Hours)": meta.get("Laytime Allowed (Hours)", ""),
        "Port": meta.get("Port", ""),
        "Charterer": meta.get("Charterer", ""),
        "Arrival Date": meta.get("Arrival Date", ""),
        "Cargo Quantity": meta.get("Cargo Quantity", ""),
        "Discharge Rate": meta.get("Discharge Rate", ""),
        "Laytime Used (Hours)": meta.get("Laytime Used (Hours)", ""),
        "Laytime Used (Days)": meta.get("Laytime Used (Days)", ""),
        "Laytime Remaining (Days)": meta.get("Laytime Remaining (Days)", ""),
        "Working Hours (Weekday)": meta.get("Working Hours (Weekday)", ""),
        "Working Hours (Saturday)": meta.get("Working Hours (Saturday)", ""),
        "Calculation Notes": meta.get("Calculation Notes", "")
    }])
