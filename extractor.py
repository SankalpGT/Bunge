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
    You are an intelligent document understanding agent. You will receive a raw PDF document. It may be any of the following:

    - Contract
    - Statement of Facts (SoF)
    - Pumping Log
    - Notice of Readiness (NOR)
    - Letter of Protest (LoP)
    - Email (in PDF form)

    Your task is to:
    1. Identify the document_type (e.g., SoF, Contract, LoP, etc.)
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
        - Extract chronological events with timestamps, event descriptions, and remarks
    - If it's a **Contract**:
        - If clause numbers like 4.1 or 4.2 are present, retain them in titles, but do not rely on them.
        - Parse section titles from visual layout, headings, or all-caps formatting.
        - Group related content under its section and preserve paragraph or bullet structure inside each.
        - Include all information relevant to terms, risks, prices, parties, dates, weather & holiday exemptions and procedures.
        - Do NOT summarize. Do NOT infer. Just extract and preserve structure from the contract as written.
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

    # prompt = """
    #     You are a modular AI document extraction agent operating on maritime, legal, and operational documents.
    #     You will perform this task in 4 structured stages, each handled by a specific sub-role:

    #     STAGES:
    #     1. document_type identification
    #     2. structured key-value extraction
    #     3. clause/event/table parsing
    #     4. output validation (final JSON only)

    #     You will receive a document in PDF format. Your job is to produce clean, structured JSON output with no commentary or explanation.

    #     Each sub-agent plays a specific role. Perform all roles in sequence, or retry only the failing stage if necessary.
    #     Role: Classifier
    #     Task: Identify the document_type

    #     Document types include:
    #     - Statement of Facts (SoF)
    #     - Contract
    #     - Pumping Log
    #     - NOR (Notice of Readiness)
    #     - Letter of Protest (LoP)
    #     - Email PDF

    #     Return a top-level field:
    #     {
    #     "document_type": "Contract"
    #     }
    #     Role: Structural Extractor  
    #     Task: Extract flat and hierarchical information from the document, such as:

    #     - Key-value fields: Vessel Name, Port, Charterer, etc.
    #     - Paragraph sections with headings
    #     - Bullet points or numbered lists
    #     - Date, product, location, and party names

    #     Use nested objects/arrays where needed.

    #     Do not skip any section even if titles/labels are unconventional.
    #     Role: Clause and Table Extractor  
    #     Task: Parse advanced structured content:

    #     If legal/contract:
    #     - Extract clauses, even if not numbered.
    #     - Preserve clause hierarchy (4, 4.1, 4.1.a)
    #     - Keep clause titles and their full text
    #     - Use arrays for lists inside clauses

    #     If event log or table:
    #     - Extract table rows with headers and logical types (e.g., timestamp, description, quantity)
    #     - Extract multiple tables if available
    #     - Convert scanned table images using OCR or format-aware logic if required

    #     Use:
    #     {
    #     "clauses": [...],
    #     "tables": [...]
    #     }

    #     Role: Output Validator  
    #     Task: Ensure the final output is:
    #     - JSON-only
    #     - No commentary or explanations
    #     - Well-formed and parsable
    #     - All sections embedded under a single top-level JSON object

    #     Example layout:
    #     {
    #     "document_type": "SoF",
    #     "metadata": { ... },
    #     "clauses": [ ... ],
    #     "tables": [ ... ],
    #     "events": [ ... ]
    #     }
    #     """
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