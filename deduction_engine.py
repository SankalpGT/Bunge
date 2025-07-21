import google.generativeai as genai
import os
import json
import re
from datetime import datetime

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("models/gemini-1.5-flash-latest")


def extract_json(text: str) -> dict:
    """
    Extracts and parses a JSON object from a string, which may contain other text.
    """
    try:
        # Use a regex to find the JSON block
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("No JSON object found in the response text.")
        json_str = match.group(0)
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"❌ Error parsing JSON from response: {e}")
        print(f"📄 Full response text:\n{text}")
        return {
            "error": f"Failed to parse JSON response: {e}",
            "deduct": False,
            "reason": "Invalid response format from the model."
        }


def analyze_event_against_clauses(event: dict, clause_texts: list[str]) -> dict:
    """
    For a single event, this function asks the Gemini model to find the most relevant
    clause, score the match, and determine if laytime should be deducted.

    Args:
        event (dict): An object with 'reason', 'start_time', and 'end_time'.
        clause_texts (list[str]): A list of all clauses from the contract.

    Returns:
        dict: A JSON object with the analysis result.
    """
    clauses_formatted = "\n".join([f"- {c}" for c in clause_texts])

    prompt = f"""
        You are an expert laytime calculation agent.

        Your task is to analyze a single operational event from a Statement of Facts (SoF) against a list of clauses from a charter party contract.

        Follow these steps precisely:
        1.  **Analyze the Event:** Review the event's description, start time, and end time.
        2.  **Find the Best Match:** From the list of all available `Contract Clauses`, identify the single most relevant clause that applies to this event.
        3.  **Calculate Confidence:** Assign a confidence score between 0.0 (no match) and 1.0 (perfect match) for how well the chosen clause applies to the event.
        4.  **Decide on Deduction:** Based on the event and the matched clause, determine if this event caused a disruption that should be deducted from laytime.
        5.  **Calculate Duration:** Compute the total duration of the event in hours.

        Return a **single, clean JSON object** in the following strict format. Do not include any other text or explanations outside the JSON block. Every remark should return corresponding clause and deduction block.

        {{
        "Remark": "{event.get('reason')}",
        "Clause": "The full text of the best matching clause you identified",
        "confidence_score": <float, e.g., 0.85>,
        "deduct": <true or false>,
        "reason": "A short explanation for your deduction decision (e.g., 'Suspension of pumping due to rain as per weather clause')",
        "deducted_from": "{event.get('start_time')}",
        "deducted_to": "{event.get('end_time')}",
        "total_hours": <float, formatted to 4 decimal places>
        }}

        ---
        **Event Details:**
        - **Description:** {event.get('reason')}
        - **Start Time:** {event.get('start_time')}
        - **End Time:** {event.get('end_time')}

        ---
        **Contract Clauses (Find the best match from this list):**
        {clauses_formatted}
        ---
        """

    try:
        response = model.generate_content(prompt)
        return extract_json(response.text)
    except Exception as e:
        print(f"❌ Gemini API call failed: {e}")
        return {
            "Remark": event.get('reason'),
            "Clause": "Error during processing",
            "confidence_score": 0.0,
            "deduct": False,
            "reason": f"Model failed to generate a response: {e}",
            "deducted_from": event.get("start_time"),
            "deducted_to": event.get("end_time"),
            "total_hours": 0.0
        }



