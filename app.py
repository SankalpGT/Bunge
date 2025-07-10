import streamlit as st
import os
import json
import tempfile
from extractor import extract_with_gemini
from embedding_matcher import match_clause_remark_pairs
from deduction_engine import calculate_deduction_from_event
#from embedding_matcher import get_embedding
#from deduction_engine import get_deduction
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


        # Step 3: Clause–Remark Matching
        st.header("Step 3: Clause–Remark Matching")

        remark_texts = [b["reason"] or b["event_phase"] for b in blocks]
        pairs = []

        if clause_texts and remark_texts:
            pairs = match_clause_remark_pairs(
                clause_texts,
                remark_texts,
                top_k=3,  # fallback to hybrid scoring
            )

            # Print all matches
            for p in pairs:
                st.markdown(f"**Clause:** {p['clause']}")
                st.markdown(f"**Remark:** {p['remark']}")
                st.markdown(f"• Score: `{p['score']}`")
                st.divider()

  
        # Step 4: Deduction Engine (Gemini-powered)
        st.header("Step 4: Laytime Deductions (via Gemini)")

        deductions = []

        for p in pairs:
            clause = p["clause"]
            remark = p["remark"]

            # Find block loosely matching this remark
            match = next((b for b in blocks if remark in (b["reason"] or "") or remark in (b["event_phase"] or "")), None)
            if not match:
                continue

            event_obj = {
                "reason": match.get("reason") or match.get("event_phase") or "No reason provided",
                "start_time": match["start_time"],
                "end_time": match["end_time"]
                }

            deduction = calculate_deduction_from_event(clause, event_obj)

                # Add metadata for display
            deduction.update({
                "clause": clause,
                "event": match.get("event_phase"),
                "remarks": match.get("reason")
                })

            deductions.append(deduction)

        # ✅ Display deductions
        st.subheader("🔎 Final Deductions")

        if not deductions:
            st.warning("⚠️ No deductions were made.")
        else:
            for i, d in enumerate(deductions):
               with st.expander(f"Clause: {(d.get('clause') or '')[:60]}... | Event: {(d.get('event') or '')[:30]}"):
                    st.markdown(f"**Event:** {d['event']}")
                    st.text_area(
                        "Remarks", 
                        d["remarks"], 
                        height=80, 
                        key=f"remarks_{i}"
                    )
                    st.markdown(f"**Deduction Reason:** {d['reason']}")
                    st.markdown(f"**From:** {d['deducted_from']}")
                    st.markdown(f"**To:** {d['deducted_to']}")
                    st.markdown(f"**Hours Deducted:** `{d['total_hours']}`")



            upload_to_s3(
                json.dumps(deductions, indent=2),
                f"deductions/final_deductions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            st.success("✅ Deductions saved to S3.")




else:
    st.info("📎 Please upload required documents and click 'Extract and Analyze' to continue.")
