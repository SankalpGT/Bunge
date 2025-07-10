import google.generativeai as genai
import os
import json
import re
from datetime import datetime

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("models/gemini-1.5-flash-latest")


def extract_json(text):
    """Extract and parse JSON from Gemini output, even if it's embedded in natural language."""
    try:
        match = re.search(r"\{[\s\S]*?\}", text)
        if not match:
            raise ValueError("No JSON object found in response")
        json_str = match.group(0)
        return json.loads(json_str)
    except Exception as e:
        print("❌ Failed to parse Gemini output as JSON:", e)
        print("📄 Full Gemini response:")
        print(text)
        return {
            "deduct": False,
            "reason": f"Gemini returned invalid response: {e}",
            "deducted_from": None,
            "deducted_to": None,
            "total_hours": 0
        }


def ask_gemini_if_deduct(clause: str, event: dict):
    """
    Determines if laytime should be deducted for a given event based on a clause.

    event: {
      "reason": "Rain caused discharge to halt",
      "start_time": "2025-07-03T10:00:00",
      "end_time": "2025-07-03T14:00:00"
    }
    """
    prompt = f"""
You are a laytime calculation assistant.

You are given:
- A clause from a charter party contract.
- An event from the Statement of Facts (SoF), with start and end time, and a short description.

Your task:
1. Determine if this event caused a **disruption** to operations (loading/discharging).
2. Refer to the clause and decide if such a disruption should **deduct from laytime**.
3. Return the result in **this strict JSON format**:

{{
  "deduct": true or false,
  "reason": "a short explanation (e.g. Discharging suspended due to heavy rain)",
  "deducted_from": "YYYY-MM-DD HH:MM",
  "deducted_to": "YYYY-MM-DD HH:MM",
  "total_hours": (number of hours to deduct, float)
}}

Clause: {clause}

Event:
- Description: {event['reason']}
- Start Time: {event['start_time']}
- End Time: {event['end_time']}
"""

    try:
        response = model.generate_content(prompt)
        return extract_json(response.text)  
    except Exception as e:
        return {
            "deduct": False,
            "reason": f"Gemini failed: {e}",
            "deducted_from": event.get("start_time"),
            "deducted_to": event.get("end_time"),
            "total_hours": 0
        }



def calculate_deduction_from_event(clause: str, event: dict):
    """
    Computes deduction using clause and enriched remark + time info.
    Expects event to include 'reason', 'start_time', 'end_time'
    """
    # Ensure required keys exist
    event_structured = {
        "reason": event.get("reason") or event.get("event", "No reason provided"),
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time")
    }

    return ask_gemini_if_deduct(clause, event_structured)


