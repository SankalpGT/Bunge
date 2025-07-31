# extractor.py

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

# ---------- Extractor ----------
def extract_with_gemini(pdf_path):
    model = genai.GenerativeModel(MODEL)

    prompt = """
    You are an intelligent document understanding agent. You will receive a raw PDF document. It may be any of the following:

    - Contract
    - Statement of Facts (SoF)
    - Pumping Log
    - Notice of Readiness (NOR)
    - Letter of Protest (LoP)
    - Email (in PDF form)

    Your task is to:
    1. Identify and return `document_type` as one of exactly: Contract, SoF, LoP, NOR, PumpingLog.
    2. Extract all meaningful structured information from the document, regardless of layout or template.

    ## Output Requirements

    Return a **single, clean JSON object** with:

    - A top-level key called `"document_type"`  
    - Key-value pairs (e.g., Vessel Name, Date of Arrival, Port, Quantity, Charterer, etc.)
    - Other keys should follow the logical structure of the content, using headings, timestamps, sections, and semantic clues  
    - Format key information using nested objects or arrays where appropriate  
    - Include events, clauses, reasons, remarks, participants, etc., as available
    - Hierarchical sections and legal clauses
    - Tabular data
    - Lists and event logs
    - Named entities such as dates, companies, ports, locations, products

    ## Examples of Structuring (For Guidance Only)

    - If it's a **Statement of Facts**:
        - Extract chronological events with timestamps, event descriptions, and remarks.
        - **For any time range in “HH:MM/HH:MM” format, do NOT use a single “from_to” field.
                Instead split it into two fields:  
                "start_time": "HH:MM",  
                "end_time":   "HH:MM"
                Make sure the names for 'from' is 'start_time and 'to' is 'end_time'**
        - **If an event occurs at a single point in time (e.g., '14:20'), do not create a single field:
                Instead split it into two fields: 
                "start_time": "HH:MM"
                "end_time": None 
                Make sure the names for 'from' is 'start_time and 'to' is 'end_time'.Do not make the key as 'time'.**
        - Ensure all events mentioned in the chronological log are included. 
        - For time in "Date & Time" format keep it the same heading instead of splitting it.
        - Rename the heading of the log table to 'Chronological Events' irrespective of what is given in the document.
    - If it's a **Contract**:
        - If clause numbers like 4.1 or 4.2 are present, retain them in titles, but do not rely on them.
        - Parse section titles from visual layout, headings, or all-caps formatting.
        - Maintain seperate key value for all clause and subclause. Name the keys as "heading" or "title" and values as "body" or "content".
        - Group related content under its section and preserve paragraph or bullet structure inside each.
        - Include all information relevant to terms, risks, prices, parties, dates, weather & holiday exemptions and procedures.
        - Do NOT summarize. Do NOT infer. Just extract and preserve structure from the contract as written.
        - The clauses should be inside "sections" key.
        - The working hours should be framed like "'Monday to Friday' : 'HH:MM to HH:MM'" and "'Saturday' : 'HH:MM to HH:MM'" if provided. Add it to the start of the extracted json file.
        - Add "laytime_commencement":"Time Unit" for the time of laytime commencement after working hours in the start as a key value pair.
        - Add the Demurrage cost as "demurrage", Despatch Cost as "despatch", Discharge rate "disrate", TERMS of contract as "terms" as seperate key value pairs after "laytime_commencement". Keep only the values of them without units.
    - If it's a **Letter of Protest**:
        - Extract protest reason, submitted by/to, timestamps, signatures
    - If NOR
        - Give all the details related to berth, port, pratique and customs.
    - If it's a **Pumping Log**:
        - Extract time entries, flow rates, volumes, comments. Basically all valid headings in the chronological table.
    - If it's an **Email PDF**:
        - Extract sender, recipient, date, subject, and body

    ## Rules

    - Be flexible — documents may not follow templates. Use layout, headings, dates, formatting, and content to infer structure.
    - Do not omit any key sections or tables. Include as much structure as can be reliably extracted.
    - Output must be valid JSON only.
    - Do not include any commentary or explanation.
    """

    try:
        # Upload PDF and generate content
        response = model.generate_content([prompt, genai.upload_file(pdf_path)])
        raw = response.text.strip()

        # Extract only JSON part
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        json_clean = raw[json_start:json_end]

        return json.loads(json_clean), raw
    except Exception as e:
        return {"error": str(e)}, response.text if 'response' in locals() else ""