# extractor.py

import os, json
import time
from google.cloud import aiplatform
import google.generativeai as genai

# ---------- CONFIG ----------
PROJECT_ID = "pdf-extraction-464009"
LOCATION = "global"
MODEL = "models/gemini-1.5-flash-latest"

# ---------- INIT ----------
aiplatform.init(project=PROJECT_ID, location=LOCATION)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ---------- Extractor ----------
def extract_with_gemini(pdf_path):
    model = genai.GenerativeModel(MODEL)

    prompt = """
    You are an intelligent document understanding and extraction agent. You will receive a raw PDF document such as a Statement of Facts (SOF), Letter of Protest (LOP), Pumping Log, Contract, Charter Party, or any other maritime, legal, or operational document.

    Your task is to extract all relevant structured information from the PDF, including but not limited to:
    - Key-value pairs (e.g., Vessel Name, Date of Arrival, Port, Quantity, Charterer, etc.)
    - Hierarchical sections and legal clauses
    - Tabular data
    - Lists and event logs
    - Named entities such as dates, companies, ports, locations, products

    Output a valid JSON object with clean nested structure. Also include a top-level field called "document_type" to classify the document.
    Do not include any explanation or commentary.
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
