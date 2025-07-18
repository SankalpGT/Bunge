import streamlit as st
import os
import json
import tempfile
from extractor import extract_with_gemini
from embedding_matcher import match_clause_remark_pairs
from deduction_engine import calculate_deduction_from_event
from s3_handler import upload_to_s3
from laytime_agent import extract_metadata_from_docs
from laytime_agent import LaytimeCalculator
from excel_exporter import generate_excel_from_extracted_data

from datetime import datetime, timedelta
from dateutil import parser

import re
import pandas as pd


st.set_page_config(page_title="Gemini Laytime Analyzer", layout="wide")
st.title("📄 Gemini Laytime Multi-Document Processor")

REQUIRED_DOCUMENTS = ["Contract", "SoF"]
OPTIONAL_DOCUMENTS = ["LoP", "NOR", "PumpingLog"]
ALL_EXPECTED = REQUIRED_DOCUMENTS + OPTIONAL_DOCUMENTS

def extract_nor_delay_hours(clause_text: str) -> int:
    """
    Parse “<N> hours after” from the NOR clause text.
    """
    pattern = r'(\d+)(?:\s*\([^)]*\))?\s*hours?\s+after'
    m = re.search(pattern, clause_text, re.IGNORECASE)
    return int(m.group(1)) if m else 0

def split_nor_period(df: pd.DataFrame, nor_clause_text: str) -> pd.DataFrame:
    d = df.copy()
    d['start_time'] = pd.to_datetime(d['start_time'])
    d['end_time']   = pd.to_datetime(d['end_time'])
    d = d.sort_values('start_time').reset_index(drop=True)

    if 'event_phase' in d.columns:
        mask_nor = (
            d['event_phase']
             .str
             .contains(r'\bNOR tendered\b|\bNotice of Readiness tendered\b', 
                       case=False, na=False)
        )
    else:
        mask_nor = (
            d['reason']
             .str
             .contains(r'\bNOR tendered\b|\bNotice of Readiness tendered\b', 
                       case=False, na=False)
        )

    if mask_nor.any():
        nor_tender = d.loc[mask_nor, 'start_time'].min()
    else:
        # fallback to first timestamp if no explicit NOR found
        nor_tender = d.loc[0, 'start_time']

    delay_h      = extract_nor_delay_hours(nor_clause_text)
    default_cut  = nor_tender + timedelta(hours=delay_h)

    # —— new: see if any "Commenced Discharging" happens earlier
    if "event_phase" in d.columns:
        mask_commence = (
            d['event_phase']
            .str
            .contains('commenced discharging', case=False, na=False)
        )
    else:
    # no event_phase column → look in 'reason' instead
        mask_commence = (
            d["reason"]
            .str
            .contains("commenced discharging", case=False, na=False)
        )
    if mask_commence.any():
        first_commence = d.loc[mask_commence, 'start_time'].min()
        # pick the earlier of (NOR+delay) vs first commencement
        laytime_start = min(default_cut, first_commence)
    else:
        laytime_start = default_cut
    
    # synthetic NOR row now spans from tender → actual laytime_start
    nor_row = {
        'start_time': nor_tender,
        'end_time':   laytime_start,
        'reason':     f'Notice of Readiness period ({delay_h} h)'
    }

    if 'event_phase' in d.columns:
        nor_row['event_phase'] = 'NOR'

    # clip any row that straddles the new laytime_start
    mask = (d['start_time'] < laytime_start) & (d['end_time'] > laytime_start)
    d.loc[mask, 'start_time'] = laytime_start

    # drop everything before laytime_start, then prepend the NOR row
    d_after = d[d['start_time'] >= laytime_start].reset_index(drop=True)
    out     = pd.concat([pd.DataFrame([nor_row]), d_after], ignore_index=True)

    # format for display
    out['start_time'] = out['start_time'].dt.strftime("%Y-%m-%d %H:%M")
    out['end_time']   = out['end_time'].dt.strftime("%Y-%m-%d %H:%M")
    return out

def parse_working_hours(text):
    """
    Extract working hours for Mon-Fri and Sat from text strings like:
    'Monday to Friday: 09:00 to 18:00' and 'Saturday: 09:00 to 13:00'.
    Returns a dict with keys 'mon_fri' and/or 'sat' if found, else None.
    """
    mon_fri_pattern = re.compile(
        r"(\')*(?:Monday|Mon)\s*(?:to|-|To)\s*(?:Friday|Fri)(\')*[:\s]*?(\')*(\d{2}:\d{2})\s*(?:to|-)\s*(\d{2}:\d{2})(\')*",
        re.IGNORECASE
    )
    sat_pattern = re.compile(
        r"(\')*(?:Saturday|Sat|saturday|sat)(\')*[:\s]*?(\')*(\d{2}:\d{2})\s*(?:to|-)\s*(\d{2}:\d{2})(\')*",
        re.IGNORECASE
    )
    wh = {}
    mf_match = mon_fri_pattern.search(text)
    sat_match = sat_pattern.search(text)
    if mf_match:
        wh["mon_fri"] = (mf_match.group(1), mf_match.group(2))
    if sat_match:
        wh["sat"] = (sat_match.group(1), sat_match.group(2))
    return wh if wh else None

# # Helper to flatten nested dicts/lists into a list of strings
def collect_strings(value):
    if isinstance(value, str):
        return [value]
    elif isinstance(value, dict):
        texts = []
        for k, v in value.items():
            texts.append(str(k))
            texts.extend(collect_strings(v))
        return texts
    elif isinstance(value, list):
        texts = []
        for item in value:
            texts.extend(collect_strings(item))
        return texts
    else:
        return []

# Generic function to find any nested time dict without relying on key name
def find_time_dict(d):
    if isinstance(d, dict):
        # check if this dict contains time-like keys
        for k in d.keys():
            if re.search(r"(Monday to Friday|mon_fri|norHours|workingHours|Saturday)", k, re.IGNORECASE):
                return d
        for k,v in d.items():
            if re.search(r"(Monday to Friday|mon_fri|norHours|workingHours|Saturday)", k, re.IGNORECASE):
                return d
        # recurse
        for v in d.values():
            found = find_time_dict(v)
            if found:
                return found
    elif isinstance(d, list):
        for item in d:
            found = find_time_dict(item)
            if found:
                return found
    return None

# Function to get working hours for a given datetime
def get_working_hours(dt):
    default = {"mon_fri": ("09:00", "17:00"), "sat": ("09:00", "13:00")}
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
    clause_texts1 = []
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
        if str(doc_type).strip().lower() == "contract":

            default_wh_text = "Monday to Friday: 09:00 to 17:00; Saturday: 09:00 to 13:00"
            default_wh = parse_working_hours(default_wh_text)
            work_hours = default_wh.copy() if default_wh else {"mon_fri": None, "sat": None}
            found_mf = False
            found_sat = False

            working_hour = structured_data.get("working_hours")
            time_dict = find_time_dict(working_hour)
            if time_dict:
                # parse all entries in that dict
                for k, v in time_dict.items():
                    if isinstance(v, str):
                        times = re.findall(r"(\d{2}:\d{2})", v)
                        if len(times) == 2:
                            if re.search(r"(Monday to Friday|mon_fri)", k, re.IGNORECASE):
                                work_hours["mon_fri"] = (times[0], times[1])
                                found_mf = True
                            elif re.search(r"(saturday|sat)", k, re.IGNORECASE):
                                work_hours["sat"] = (times[0], times[1])
                                found_sat = True

            raw_secs = (
                structured_data.get("Sections")
                or structured_data.get("sections")
                or structured_data.get("Agreement", {}).get("sections", [])
            )

            if isinstance(raw_secs, dict):
                sections = [
                    {"heading": sec_title, "body": sec_body} for sec_title, sec_body in raw_secs.items()
                ]
            else:
                sections = raw_secs

            for section in sections:

                heading = section.get("heading", "") or section.get("title", "")
                body    = section.get("body", {}) or section.get("content", "")

                all_texts = [heading] + collect_strings(body)
                clause_texts1.extend(all_texts)

                norm_heading = re.sub(r'[^a-zA-Z0-9]+', '_', heading.lower()).strip('_')

                if isinstance(body, dict):
                    for key, val in body.items():
                        # normalize sub-key
                        entry_key = re.sub(r'[^a-zA-Z0-9]+', '_', key.lower()).strip('_')
                        
                        # append each subclause as a separate dict-string
                        if isinstance(val, dict):
                            clause_texts.append(f"{entry_key}: {val}")
                        elif isinstance(val, list):
                            for item in val:
                                clause_texts.append(f"{entry_key}: {item}")
                        else:
                            clause_texts.append(f"{entry_key}: {val}")
                elif isinstance(body, list):
                    # body is a list of items
                    for idx, item in enumerate(body, start=1):
                        entry_key = f"{idx}"
                        clause_texts.append(f"{entry_key}: {item}")
                else:
                    # single non-dict, non-list value
                    clause_texts.append(f"{norm_heading}: {body}")
            
            st.session_state["working_hours"] = work_hours
            
        # SoF and others: collect chronological events
        else:
            events = structured_data.get("Chronological Events", [])
            for e in events:
                if e.get("Date & Time"):
                    try:
                        ts = datetime.strptime(e.get("Date & Time"), "%Y-%m-%d %H:%M")
                        all_events.append({
                            "timestamp": ts,
                            "event": e.get("Event"),
                            "remarks": e.get("Remarks")
                        })
                    except:
                        continue

                # Case 2: split fields (date, day, start_time, end_time)
                elif e.get("Date") or e.get("date"):
                    date_val   = e.get("Date") or e.get("date")
                    day_val    = e.get("Day")  or e.get("day")
                    start_val  = e.get("start_time") or e.get("Start_Time")
                    end_val    = e.get("end_time")   or e.get("End_Time")
                    remarks_val= e.get("Remarks")    or e.get("remarks")

                    ev = {
                        "date":       date_val,
                        "day":        day_val,
                        "start_time": start_val,
                        "end_time":   end_val,
                        "remarks":    remarks_val
                    }

                else:
                    # neither format recognized
                    continue

                all_events.append(ev)
                
            if any("timestamp" in ev for ev in all_events):
                all_events.sort(key=lambda x: x["timestamp"])


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
            ranges = []
            # 1) Turn each raw event into a (start, end, label, reason) tuple
            for idx, e in enumerate(events):
                # Case A: split-fields event
                if e.get("date") and e.get("start_time"):
                    # parse with dayfirst=True for “DD/MM/YYYY”
                    end_dt = None
                    date_str = e["date"]
                    day_str  = e.get("day", "")
                    start_dt = parser.parse(f"{date_str} {e['start_time']}", dayfirst=True)
                    if e.get("end_time"):
                        end_dt = parser.parse(f"{date_str} {e['end_time']}", dayfirst=True)
                    label  = e.get("Event", "")
                    reason = e.get("Remarks") or e.get("remarks") or ""
                    ranges.append((date_str, day_str, start_dt, end_dt, label, reason))

                # Case B: timestamped events to be paired
                elif e.get("timestamp") and idx + 1 < len(events) and events[idx+1].get("timestamp"):
                    start_dt = e["timestamp"]
                    end_dt   = events[idx+1]["timestamp"]
                    label    = e.get("event", "")
                    reason   = e.get("remarks", "")
                    ranges.append(("", "", start_dt, end_dt, label, reason))

            # 2) For each (start, end), slice into working-hour blocks
            for date_str, day_str, start_dt, end_dt, label, reason in ranges:
                if end_dt is None:
                    blk = {
                        "date":        date_str,
                        "day":         day_str,
                        "start_time":  start_dt.strftime("%Y-%m-%d %H:%M"),
                        "end_time":    None,
                        "reason":      reason
                    }
                    if label:
                        blk["event_phase"] = label
                    blocks.append(blk)
                    continue

                curr = start_dt
                while curr < end_dt:
                    ws, we = get_working_hours(curr)
                    if ws and we:
                        seg_start = max(curr, ws)
                        seg_end   = min(end_dt, we)
                        if seg_start < seg_end:
                            blk = {
                                "date" : date_str,
                                "day" : day_str,
                                "start_time": seg_start.strftime("%Y-%m-%d %H:%M"),
                                "end_time":   seg_end.strftime("%Y-%m-%d %H:%M"),
                                "reason":     reason
                            }
                            if label:
                                blk["event_phase"] = label
                            blocks.append(blk)
                    else:
                        blk = {
                                "date" : date_str,
                                "day" : day_str,
                                "start_time": curr.strftime("%Y-%m-%d %H:%M"),
                                "end_time":   end_dt.strftime("%Y-%m-%d %H:%M"),
                                "reason":     reason
                            }
                        if label:
                            blk["event_phase"] = label
                        blocks.append(blk)
                    # bump to next calendar day midnight
                    curr = (curr + timedelta(days=1)).replace(hour=0, minute=0)

            return blocks

        # …later…
        blocks = build_event_blocks(all_events)

        if blocks:
            st.dataframe(pd.DataFrame(blocks))


        # ─ Step 2.5: Insert NOR split ─────────────────────────────────────────────────
        st.header("⏱ Insert NOR Period & Clip Logs")
        # grab the NOR clause content from your flat clause_texts
        nor_clause_text = ""
        for ct in clause_texts1:
            lower = ct.lower()
            if ("notice of readiness" in lower or "nor" in lower) and "laytime" in lower:
                nor_clause_text = ct.split(":",1)[1].strip() if ":" in ct else ct
                break

        nor_df = split_nor_period(pd.DataFrame(blocks), nor_clause_text)
        st.dataframe(nor_df)

        # Step 3: Clause–Remark Matching
        st.header("Step 3: Clause–Remark Matching")
        records = nor_df.to_dict("records")
        remark_texts = [b["reason"] or b["event_phase"] for b in records[1:]]
        pairs = []

        if clause_texts and remark_texts:
            pairs = match_clause_remark_pairs(
                clause_texts,
                remark_texts
            )

            # Print all matches
            for p in pairs:
                st.markdown(f"**Clause:** {p['clause']}")
                st.markdown(f"**Remark:** {p['remark']}")
                st.markdown(f"• Score: `{p['score']}`")
                st.divider()

  
        # # Step 4: Deduction Engine (Gemini-powered)
        st.header("Step 4: Laytime Deductions (via Gemini)")

        deductions = []

        for p in pairs:
            clause = p["clause"]
            remark = p["remark"]

            # Find block loosely matching this remark
            match = next(
                (
                    b for b in records
                    if remark in (b.get("reason") or "")
                    or remark in (b.get("event_phase") or "")
                ),
                None,
            )
            if not match:
                continue

            event_obj = {
                "reason": match.get("reason") or match.get("event_phase") or "No reason provided",
                "start_time": match["start_time"],
                "end_time": match["end_time"]
                }

            deduction = calculate_deduction_from_event(clause, event_obj)

                # Add metadata for display
            metadata = {
                "clause": clause,
                "remarks": match.get("reason") or "",
            }
            if match.get("event_phase"):
                metadata["event"] = match["event_phase"]

            deduction.update(metadata)
            deductions.append(deduction)

        # ✅ Display deductions
        st.subheader("🔎 Final Deductions")

        if not deductions:
            st.warning("⚠️ No deductions were made.")
        else:
            for i, d in enumerate(deductions):
                title = f"Clause: {(d.get('clause') or '')[:60]}..."
                if d.get("event"):
                    title += f" | Event: {d['event'][:30]}"
                
                with st.expander(title):
                    # Only render Event if present
                    if d.get("event"):
                        st.markdown(f"**Event:** {d['event']}")
                    
                    st.text_area(
                        "Remarks",
                        d.get("remarks", ""),
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

        # Step 5: Final Laytime Summary
        if records and deductions:
            calc = LaytimeCalculator(records, deductions)
            total = calc.total_block_hours()
            deduc = calc.total_deduction_hours()
            net   = calc.net_laytime_hours()

            st.header("🧮 Laytime Calculation Summary")
            st.markdown(f"- **Total Working-Hour Blocks:** {total:.2f} hrs")
            st.markdown(f"- **Total Deductions:**          {deduc:.2f} hrs")
            st.markdown(f"- **Net Laytime Used:**         {net:.2f} hrs")

        # Final block: generate Excel if both Contract and SoF were extracted
        if "Contract" in extracted_data and "SoF" in extracted_data:
            contract_raw = extracted_data["Contract"]
            sof_raw = extracted_data["SoF"]

            # 🔄 Extract structured metadata + events using Gemini
            metadata_response, raw_response = extract_metadata_from_docs(contract_raw, sof_raw)

            # 🧾 Display keys (optional)
            st.subheader("✅ Populating Excel with extracted metadata + events")
            st.markdown("### 🔑 Contract Keys")
            st.json(list(contract_raw.keys()))
            st.markdown("### 🔑 SoF Keys")
            st.json(list(sof_raw.keys()))

            st.markdown("### 🧾 Metadata Preview")
            st.json(metadata_response)

            # ✅ Build Excel workbook using new format
            excel_wb = generate_excel_from_extracted_data(metadata_response)
            excel_filename = f"Laytime_Metadata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

            # ✅ Save Excel to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_xlsx:
                excel_wb.save(tmp_xlsx.name)
                tmp_xlsx.seek(0)
                with open(tmp_xlsx.name, "rb") as f:
                    st.download_button(
                        label="📥 Download Laytime Metadata Report",
                        data=f.read(),
                        file_name=excel_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

else:
    st.info("📎 Please upload required documents and click 'Extract and Analyze' to continue.")

