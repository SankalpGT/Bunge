import os, json
import time
from google.cloud import aiplatform
import google.generativeai as genai

# ---------- CONFIG ----------
PROJECT_ID = "laytimecalculation"
LOCATION = "global"
MODEL = "models/gemini-1.5-flash-latest"

# ---------- INIT ----------
aiplatform.init(project=PROJECT_ID, location=LOCATION)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def chronological_events(events_json_string, blocks):
    model = genai.GenerativeModel(MODEL)

    prompt = f"""
        You are an expert maritime assistant.

        Given the following chronological list of time blocks (events), your task is to identify and fill any temporal gaps between consecutive events. For each gap identified, you must insert a new event block with an inferred reason, from the "events_json_string" of corresponding date and time.

            Input Events (JSON array):
            ```json
            events_json_string: {events_json_string}
            ```

            Rules for Gap Filling and Reason Assignment:
            1.  **Iterate Chronologically**: Process the events in the order they appear.
            2.  **Identify 
                *If the end_time of block x does not match the start_time of block x+1 in 'events_json_string', insert a new row to fill this gap.
                    The new row should use:
                    start_time = end_time of block x
                    end_time = start_time of block x+1
                    reason = Find the appropiate reason based on the previous and the next block, don't repeat and dont hallucinate.
                *If end_time of block x is null, assume it equals the start_time of the next available block with start_time different from the end time of block x.
                    Keep the reason as that of the block x.
                *If the end_time is empty for the last event of the last day then fill it with start time of that event
                *Ensure that data is grouped by date, and for every new date, a new block of rows should begin, the last event of that particular date should have the end_time as 23:59.
            3. **Effective `end_time` of `event_X`**:
                * If `event_X` has `start_time` equal to `end_time` (instantaneous event), or if `end_time` is null/empty, find the *next event* (`event_Y`) in the chronological list that has a `start_time` *different* from `event_X`'s `start_time`. The `effective_end_time` of `event_X` for gap calculation purposes will be the `start_time` of this `event_Y`. If no such `event_Y` exists (i.e., `event_X` is the last event or all subsequent events are instantaneous at the same time), then `event_X`'s original `end_time` (even if null) should be preserved in the output.
                * Make sure to clip all events happening in between that time unless its an event related to a disruption of discharging(i.e. discharging is stopped). There should be single event/reason happening at a single timeframe.
            4.  **Output Format**: Return a single JSON array containing *all* original events which have start time and end time and both and for others adjust according the prompt, sorted strictly chronologically by their `start_time`. Each object in the output array must have the following keys: `date` (DD/MM/YYYY), `day` (Full weekday name), `start_time` (HH:MM), `end_time` (HH:MM), `reason`. Ensure all date/time strings are correctly formatted.
            5. **If event_json_string['Reason'] is a 'National Holiday'/'Holiday' then club all the events happening on that day to a single row with date, day, start_time as 00:00 , end_time as 23:59 and Reason as 'National Holiday'.
            6. **If day is 'Sunday' then club all the events happening on that day to a single row with date, day, start_time as 00:00 , end_time as 23:59 and Reason as 'Sunday'.
            7. **Make sure there is start_time and end_time for every row. 
            8. **The last entry should be of when the discharging has completed at a particular berth. Remove all the events after that. Eg: Completed discharging operations at Vicentin Berth. The end_time of this event should be the same the start_time if the end_time is originally empty.
            Ensure the output is *only* the JSON array, with no additional text or commentary.
    s"""

    try:
      
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Extract only JSON part
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        json_clean = raw[json_start:json_end]

        return json.loads(json_clean), raw

    except Exception as e:
        return {"error": str(e)}, response.text if 'response' in locals() else ""
