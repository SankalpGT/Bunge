import streamlit as st
import os
import json
import tempfile
from extractor import extract_with_gemini
from embedding_matcher import match_clause_remark_pairs
from embedding_matcher import get_embedding
from deduction_engine import get_deduction
from s3_handler import upload_to_s3

# from datetime import datetime

from datetime import datetime, timedelta
import re
import pandas as pd


st.set_page_config(page_title="Gemini Laytime Analyzer", layout="wide")
st.title("📄 Gemini Laytime Multi-Document Processor")

REQUIRED_DOCUMENTS = ["Contract", "SoF"]
OPTIONAL_DOCUMENTS = ["LoP", "NOR", "PumpingLog"]
ALL_EXPECTED = REQUIRED_DOCUMENTS + OPTIONAL_DOCUMENTS

def parse_working_hours(text):
    mon_fri_match = re.search(r"from\s*(\d{2}:\d{2})\s*to\s*(\d{2}:\d{2})\s*Hours on Monday to Friday", text)
    sat_match    = re.search(r"from\s*(\d{2}:\d{2})\s*to\s*(\d{2}:\d{2})\s*Hours on Saturdays?", text)
    if mon_fri_match and sat_match:
        return {
            "mon_fri": (mon_fri_match.group(1), mon_fri_match.group(2)),
            "sat":     (sat_match.group(1), sat_match.group(2))
        }
    return None

# Function to get working hours for a given datetime
def get_working_hours(dt):
    default = {"mon_fri": ("09:00", "20:00"), "sat": ("09:00", "12:00")}
    hours = st.session_state.get("working_hours", default)
    weekday = dt.weekday()
    if weekday < 5:
        start_str, end_str = hours["mon_fri"]
    elif weekday == 5:
        start_str, end_str = hours["sat"]
    else:
        return None, None
    start = datetime.combine(dt.date(), datetime.strptime(start_str, "%H:%M").time())
    end   = datetime.combine(dt.date(), datetime.strptime(end_str, "%H:%M").time())
    return start, end

# Upload section
st.header("Step 1: Upload Documents")
uploaded_files = st.file_uploader(
    "Upload Contract, SoF (required) and optionally LoP, NOR, PumpingLog",
    accept_multiple_files=True,
    type=["pdf", "docx"]
)

if st.button("Extract and Analyze") and uploaded_files:
    uploaded_doc_types = []
    clause_texts = []
    remark_texts = []
    extracted_data = {}
    all_events = []
    st.session_state.pop("working_hours", None)

    for uploaded_file in uploaded_files:
        file_name = uploaded_file.name

        # Save to temp path
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            temp_path = tmp.name

        # Run Gemini extraction
        try:
            structured_data, _ = extract_with_gemini(temp_path)

            if "error" in structured_data:
                st.error(f"❌ Gemini extraction failed for {file_name}: {structured_data['error']}")
                continue

        except Exception as e:
            st.error(f"❌ Failed to extract from {file_name}: {str(e)}")
            continue

        doc_type = structured_data.get("document_type")

        # Fallback: infer doc_type from filename
        if not doc_type:
            doc_type = next((d for d in ALL_EXPECTED if d.lower() in file_name.lower()), None)

        if not doc_type or doc_type not in ALL_EXPECTED:
            st.warning(f"⚠️ Skipping unknown or invalid document type for file: {file_name}")
            continue

        uploaded_doc_types.append(doc_type)
        extracted_data[doc_type] = structured_data
        

        st.markdown(f"**doctype**: {doc_type}")

        # # Clause extraction (Contract)
        # if doc_type == "Contract":
        #     st.markdown("1")
        #     sections = structured_data.get("Sections", [])

        #     for section in sections:
        #         if "Items" in section:
        #             clause_texts.extend([
        #                 f"{section.get('Section Title', '')}: {json.dumps(item)}"
        #                 for item in section["Items"]
        #             ])
        #         elif "Subsections" in section:
        #             clause_texts.extend([
        #                 f"{sub.get('Subsection Title', '')}: {sub.get('Content', '')}"
        #                 for sub in section["Subsections"]
        #             ])
        #         elif "Content" in section:
        #             clause_texts.append(
        #                 f"{section.get('Section Title', '')}: {section.get('Content', '')}"
        #             )

        # Remark extraction (SoF, LoP, etc.)
        # else:
        #     st.markdown("2")
        #     events = structured_data.get("Chronological Events", []) or structured_data.get("remarks", [])
        #     if isinstance(events, list):
        #         remark_texts.extend([
        #             e.get("Remarks", "") or e.get("Event", "") or str(e)
        #             for e in events if isinstance(e, dict)
        #         ])

        # Contract: extract clauses and working hours
        # if doc_type == "Contract":
        #     for section in structured_data.get("Sections", []):
        #         # parse working hours from section title and content
        #         for key in ("Section Title", "Content"): 
        #             text = section.get(key, "")
        #             wh = parse_working_hours(text)
        #             if wh:
        #                 st.session_state["working_hours"] = wh
        #         # clauses
        #         for item_key in ("Items", "Subsections"): 
        #             if item_key in section:
        #                 for elem in section[item_key]:
        #                     # for subsections parse wh and add clause text
        #                     if isinstance(elem, dict):
        #                         content = elem.get("Content", "")
        #                         wh = parse_working_hours(content)
        #                         if wh:
        #                             st.session_state["working_hours"] = wh
        #                         title = elem.get("Subsection Title") or elem.get("Clause Title", "")
        #                         clause_texts.append(f"{title}: {content}")

        if doc_type == "Contract":
            for section in structured_data.get("Sections", []):
                # parse working hours from section title and content
                for key in ("Section Title", "Content"):
                    text = section.get(key, "")
                    wh = parse_working_hours(text)
                    if wh:
                        st.session_state["working_hours"] = wh

                # clauses
                #  - Items: dicts like {"Product": "Wheat"}
                #  - Subsections: dicts with "Subsection Title" & "Content"
                # We treat them separately to avoid empty titles.
                # 1) Items
                if "Items" in section:
                    for item in section["Items"]:
                        if isinstance(item, dict):
                            for k, v in item.items():
                                clause_texts.append(f"{k}: {v}")

                # 2) Subsections
                if "Subsections" in section:
                    for elem in section["Subsections"]:
                        if not isinstance(elem, dict):
                            continue
                        content = elem.get("Content", "").strip()
                        title   = elem.get("Subsection Title", "").strip() or elem.get("Clause Title", "").strip()

                        # parse working hours if mentioned here too
                        wh = parse_working_hours(content)
                        if wh:
                            st.session_state["working_hours"] = wh

                        # only append non-empty entries
                        if title or content:
                            clause_texts.append(f"{title}: {content}")

            st.markdown(f"**Clause_texts**: {clause_texts}")
        
        # SoF and others: collect chronological events
        else:
            events = structured_data.get("Chronological Events", [])
            for e in events:
                try:
                    ts = datetime.strptime(e.get("Date & Time"), "%Y-%m-%d %H:%M")
                    all_events.append({
                        "timestamp": ts,
                        "event": e.get("Event"),
                        "remarks": e.get("Remarks")
                    })
                except:
                    continue
            st.markdown(f"**All events**: {all_events}")


        # Upload structured result to S3
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{doc_type}_{timestamp}.json"
        # filename = f"{doc_type}.json"
        upload_to_s3(json.dumps(structured_data, indent=2), f"structured/{filename}")

    # Step 2: Ensure required documents exist
    if not all(req in uploaded_doc_types for req in REQUIRED_DOCUMENTS):
        st.error("❌ Please upload both Contract and SoF files. They are required for clause–remark matching.")
    else:
        st.success("✅ Required documents uploaded and processed successfully.")

        # ### DEMO pupose
        # # Mocked clause & remark texts (replace with extracted data)
        # clauses = ["Time lost due to bad weather...", "Laytime shall commence at..."]
        # remarks = ["Operations stopped due to rain", "Berth unavailable due to congestion"]

        # st.title("Clause & Remark Embeddings Viewer")

        # st.header("Clause Embeddings")
        # for clause in clauses:
        #     emb = get_embedding(clause)
        #     st.markdown(f"**Clause**: {clause}")
        #     st.write(emb[:10])  # Display first 10 values

        # st.header("Remark Embeddings")
        # for remark in remarks:
        #     emb = get_embedding(remark)
        #     st.markdown(f"**Remark**: {remark}")
        #     st.write(emb[:10])

        ###########################################################
        # Step 2.5: Club Events by Working Hours
        st.header("🗓️ Chronological Events Clubbed by Working Hours")

        def build_event_blocks(events):
            blocks = []
            for a, b in zip(events, events[1:]):
                start, end = a["timestamp"], b["timestamp"]
                label, reason = a["event"], a["remarks"]
                curr = start
                while curr < end:
                    ws, we = get_working_hours(curr)
                    if ws and we:
                        seg_start = max(curr, ws)
                        seg_end   = min(end, we)
                        if seg_start < seg_end:
                            blocks.append({
                                "start_time": seg_start.strftime("%Y-%m-%d %H:%M"),
                                "end_time":   seg_end.strftime("%Y-%m-%d %H:%M"),
                                "event_phase": label,
                                "reason":      reason
                            })
                    curr = (curr + timedelta(days=1)).replace(hour=0, minute=0)
            return blocks

        blocks = build_event_blocks(all_events)
        if blocks:
            st.dataframe(pd.DataFrame(blocks))


        ###############################################
        # Step 3: Clause–Remark Matching
        # st.header("Step 2: Clause–Remark Matching")
        # if clause_texts and blocks:
        #     st.markdown("3")
        #     pairs = match_clause_remark_pairs(clause_texts, blocks['reason'])
        #     st.session_state["pairs"] = pairs

        #     for pair in pairs:
        #         st.markdown(f"**Clause:** {pair['clause']}")
        #         st.markdown(f"**Remark:** {pair['remark']}")
        #         st.markdown(f"**Similarity Score:** `{pair['score']}`")
        #         st.divider()
        # else:
        #     st.warning("⚠️ Not enough clauses or remarks available for matching.")

        # Step 3: Clause–Remark Matching
        # st.header("Step 3: Clause–Remark Matching")
        # remark_texts=[b['reason'] or b['event_phase'] for b in blocks]
        # if clause_texts and remark_texts:
        #     pairs = match_clause_remark_pairs(clause_texts, remark_texts, top_k=3, alpha=0.3)

        #     for p in pairs:
        #         clause = p['clause']
        #         remark = p['remark']
        #         combined = p.get('combined_score')          # hybrid score
        #         semantic = p.get('semantic_score')
        #         lexical  = p.get('lexical_score')

        #         st.markdown(f"**Clause:** {clause}")
        #         st.markdown(f"**Remark:** {remark}")
        #         st.markdown(f"• Combined Score: `{combined}`  ")
        #         st.markdown(f"• Semantic: `{semantic}` • Lexical: `{lexical}`")
        #         st.divider()

        # else:
        #     st.warning("⚠️ Not enough data for matching")

        # app.py  (excerpt)

        st.header("Step 3: Clause–Remark Matching")
        remark_texts = [b["reason"] or b["event_phase"] for b in blocks]
        if clause_texts and remark_texts:
            pairs = match_clause_remark_pairs(
                        clause_texts,
                        remark_texts,
                        top_k=3,
                        min_score=0.75
                    )

            for p in pairs:
                st.markdown(f"**Clause:** {p['clause']}")
                st.markdown(f"**Remark:** {p['remark']}")
                st.markdown(f"• Score: `{p['score']}`")
                st.divider()
        else:
            st.warning("⚠️ Not enough data for matching")

        # # Step 4: Deduction Engine
        # st.header("Step 3: Deduction Engine")
        # deductions = []
        # for pair in st.session_state.get("pairs", []):
        #     deduction = get_deduction(pair["clause"], pair["remark"])
        #     deduction.update(pair)
        #     deductions.append(deduction)

        # if deductions:
        #     st.subheader("🔎 Final Deductions")
        #     st.json(deductions)
        #     upload_to_s3(json.dumps(deductions, indent=2), f"deductions/final_deductions.json")
        #     st.success("✅ Deductions saved to S3.")

else:
    st.info("📎 Please upload required documents and click 'Extract and Analyze' to continue.")
