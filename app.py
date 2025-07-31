import streamlit as st
import json
import tempfile
from extractor import extract_with_gemini
from chronological_event import chronological_events
from deduction_engine import analyze_event_against_clauses
from laytime_agent import extract_metadata_from_docs
from laytime_agent import LaytimeCalculator
from excel_exporter import generate_excel_from_extracted_data

from datetime import datetime, timedelta, time
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
    pattern = r'(\d+)(?:\s*\([^)]*\))?\s*hours?(\s+after|later)?'
    m = re.search(pattern, clause_text, re.IGNORECASE)
    return int(m.group(1)) if m else 0

def split_nor_period(df: pd.DataFrame, laytime_commencement: str) -> pd.DataFrame:
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

    delay_h      = extract_nor_delay_hours(laytime_commencement)
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


# Generic function to find any nested time dict without relying on key name
# def find_time_dict(d):
#     if isinstance(d, dict):
#         # check if this dict contains time-like keys
#         for k in d.keys():
#             if re.search(r"(Monday to Friday|mon_fri|norHours|workingHours|Saturday)", k, re.IGNORECASE):
#                 return d
#         for k,v in d.items():
#             if re.search(r"(Monday to Friday|mon_fri|norHours|workingHours|Saturday)", k, re.IGNORECASE):
#                 return d
#         # recurse
#         for v in d.values():
#             found = find_time_dict(v)
#             if found:
#                 return found
#     elif isinstance(d, list):
#         for item in d:
#             found = find_time_dict(item)
#             if found:
#                 return found
#     return None

# Function to get working hours for a given datetime
# def get_working_hours(dt):
#     default = {"mon_fri": ("09:00", "17:00"), "sat": ("09:00", "13:00")}
#     hours = st.session_state.get("working_hours", default)
#     weekday = dt.weekday()
#     if weekday < 5:
#         start_str, end_str = hours["mon_fri"]
#     elif weekday == 5:
#         start_str, end_str = hours["sat"]
#     else:
#         return None, None
    
#     start = datetime.combine(dt.date(), datetime.strptime(start_str, "%H:%M").time())
#     end   = datetime.combine(dt.date(), datetime.strptime(end_str, "%H:%M").time())
#     return start, end

# Upload section
st.header("Upload Documents")
uploaded_files = st.file_uploader(
    "Upload Contract, SoF (required) and optionally LoP, NOR, PumpingLog",
    accept_multiple_files=True,
    type=["pdf", "docx"]
)

if st.button("Extract and Analyze") and uploaded_files:
    uploaded_doc_types = []
    clause_texts = []
    metadata = {}
    laytime_commencement = ""
    extracted_data = {}
    all_events = []
    # st.session_state.pop("working_hours", None)

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
            st.markdown(f"Struc : {structured_data}")
            laytime_commencement = structured_data.get("laytime_commencement")
            metadata["LTC AT"] = structured_data.get("laytime_commencement")
            metadata["DEMMURAGE"] = structured_data.get("demurrage")
            metadata["DESPATCH"] = structured_data.get("despatch")
            metadata["DISRATE"] = structured_data.get("disrate")
            metadata["TERMS"] = structured_data.get("terms")
         
            # work_hours = {"mon_fri": None, "sat": None}
         
            # working_hour = structured_data.get("working_hours")
            # time_dict = find_time_dict(working_hour)
            # if time_dict:
            #     # parse all entries in that dict
            #     for k, v in time_dict.items():
            #         if isinstance(v, str):
            #             times = re.findall(r"(\d{2}:\d{2})", v)
            #             if len(times) == 2:
            #                 if re.search(r"(Monday to Friday|mon_fri)", k, re.IGNORECASE):
            #                     work_hours["mon_fri"] = (times[0], times[1])
            #                     found_mf = True
            #                 elif re.search(r"(saturday|sat)", k, re.IGNORECASE):
            #                     work_hours["sat"] = (times[0], times[1])
            #                     found_sat = True

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
            
            # st.session_state["working_hours"] = work_hours
            
        # SoF and others: collect chronological events
        else:
            st.markdown(f"Struc : {structured_data}")
            events = structured_data.get("Chronological Events", []) or structured_data.get("chronological_events", [])
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

    # Step 2: Ensure required documents exist
    if not all(req in uploaded_doc_types for req in REQUIRED_DOCUMENTS):
        st.error("❌ Please upload both Contract and SoF files. They are required for clause–remark matching.")
    else:
        st.success("✅ Required documents uploaded and processed successfully.")
       
        # Step 2.5: Club Events by Working Hours
        st.header("🗓️ Chronological Events")

        def build_event_blocks(events):
            blocks = []
            ranges = []
            # 1) Turn each raw event into a (start, end, label, reason) tuple
            for idx, e in enumerate(events):
                # Case A: split-fields event
                if e.get("date") and (e.get("start_time") or e.get("time")):
                    # parse with dayfirst=True for “DD/MM/YYYY”
                    start_time = e.get("start_time") or e.get("time")
                    end_dt = None
                    date_str = e["date"]
                    day_str  = e.get("day", "")
                    start_dt = parser.parse(f"{date_str} {start_time}", dayfirst=True)
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

            # # 2) For each (start, end), slice into working-hour blocks
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
                else:
                    blk = {
                        "date":        date_str,
                        "day":         day_str,
                        "start_time":  start_dt.strftime("%Y-%m-%d %H:%M"),
                        "end_time":    end_dt.strftime("%Y-%m-%d %H:%M"),
                        "reason":      reason
                    }
                    if label:
                        blk["event_phase"] = label
                    blocks.append(blk)

            return blocks
                # curr = start_dt
                # while curr < end_dt:
            #         ws, we = get_working_hours(curr)
            #         if ws and we:
            #             seg_start = max(curr, ws)
            #             seg_end   = min(end_dt, we)
            #             if seg_start < seg_end:
            #                 blk = {
            #                     "date" : date_str,
            #                     "day" : day_str,
            #                     "start_time": seg_start.strftime("%Y-%m-%d %H:%M"),
            #                     "end_time":   seg_end.strftime("%Y-%m-%d %H:%M"),
            #                     "reason":     reason
            #                 }
            #                 if label:
            #                     blk["event_phase"] = label
            #                 blocks.append(blk)
            #         else:
            #             blk = {
            #                     "date" : date_str,
            #                     "day" : day_str,
            #                     "start_time": curr.strftime("%Y-%m-%d %H:%M"),
            #                     "end_time":   end_dt.strftime("%Y-%m-%d %H:%M"),
            #                     "reason":     reason
            #                 }
            #             if label:
            #                 blk["event_phase"] = label
            #             blocks.append(blk)
            #         # bump to next calendar day midnight
            #         curr = (curr + timedelta(days=1)).replace(hour=0, minute=0)
            # return ranges
            
            

        # …later…
        blocks = build_event_blocks(all_events)

        # Step 2.5: Insert NOR split 

        nor_df = split_nor_period(pd.DataFrame(blocks), metadata["LTC AT"])

        # adjusted_nor_df = nor_df.copy()

        # # Ensure 'date' is a proper date (not datetime) for grouping
        # adjusted_nor_df['date'] = pd.to_datetime(
        #     adjusted_nor_df['date'],
        #     dayfirst=True
        # ).dt.date

        # # 1) NATIONAL HOLIDAYS
        # # Identify dates where reason mentions 'holiday'
        # holiday_dates = adjusted_nor_df[
        #     adjusted_nor_df['reason'].str.contains('holiday', case=False, na=False)
        # ]['date'].unique()

        # # Build one full-day row per holiday date
        # holiday_rows = pd.DataFrame({
        #     'date':    holiday_dates,
        #     'day':     [pd.to_datetime(d).day_name() for d in holiday_dates],
        #     'start_time': ['00:00'] * len(holiday_dates),
        #     'end_time':   ['23:59'] * len(holiday_dates),
        #     'reason': ['National Holiday'] * len(holiday_dates)
        # })

        # # 2) SUNDAYS
        # # Identify all Sundays in the data
        # sunday_mask = pd.to_datetime(adjusted_nor_df['date']).dt.dayofweek == 6  # Monday=0 … Sunday=6
        # sunday_dates = adjusted_nor_df[sunday_mask]['date'].unique()

        # # Build one full-day row per Sunday
        # sunday_rows = pd.DataFrame({
        #     'date':    sunday_dates,
        #     'day':     ['Sunday'] * len(sunday_dates),
        #     'start_time': ['00:00'] * len(sunday_dates),
        #     'end_time':   ['23:59'] * len(sunday_dates),
        #     'reason': ['Sunday'] * len(sunday_dates)
        # })

        # # 3) FILTER OUT original holiday/Sunday events
        # filtered = adjusted_nor_df[
        #     ~(
        #         adjusted_nor_df['date'].isin(holiday_dates) |
        #         pd.to_datetime(adjusted_nor_df['date']).dt.dayofweek.eq(6)
        #     )
        # ]

        # # 4) CONCATENATE & SORT
        # adjusted_nor_df = pd.concat([filtered, holiday_rows, sunday_rows], ignore_index=True)
        # adjusted_nor_df = adjusted_nor_df.sort_values(['date', 'start_time']).reset_index(drop=True)

        # # 5) Reorder columns
        # cols = ['date', 'day', 'start_time', 'end_time', 'reason']
        # adjusted_nor_df = adjusted_nor_df[cols]

        # # 6) Move Notice of Readiness row(s) to the very top
        # nor_mask = adjusted_nor_df['reason'].str.contains('notice of readiness period', case=False, na=False)
        # nor_rows   = adjusted_nor_df[nor_mask]
        # other_rows = adjusted_nor_df[~nor_mask]

        # adjusted_nor_df = pd.concat([nor_rows, other_rows], ignore_index=True)

        # # 7) Display
        # st.dataframe(adjusted_nor_df)

        # --- NEW LOGIC FOR GAP FILLING AND FINAL RECORDS using Gemini ---
        # st.header("✨ Refining Chronological Events with Gemini (Gap Filling)")
        st.dataframe(nor_df)
        # Prepare data for Gemini prompt
        # Ensure date, start_time, end_time columns are strings before sending to Gemini
        nor_df['date'] = nor_df['date'].astype(str)
        nor_df['start_time'] = nor_df['start_time'].astype(str)
        nor_df['end_time'] = nor_df['end_time'].astype(str) # Convert to string, NaNs become "nan"

        events_for_gemini = nor_df.to_dict(orient='records')
        events_json_string = json.dumps(events_for_gemini, indent=2)

        final_records, _ = chronological_events(events_json_string, blocks)
        st.markdown(f"final_records:{final_records}")

        # Convert date/time strings in final_records to proper Python objects for sorting
        # This step is crucial for robust sorting and avoiding ParserErrors.
        for record in final_records:
            # Ensure date and time strings are not empty or "nan" or "None" before parsing
            date_str = str(record.get('date', '')).strip()
            if date_str.lower() in ['none', 'nan']: date_str = ''

            start_time_str = str(record.get('start_time', '')).strip()
            if start_time_str.lower() in ['none', 'nan']: start_time_str = ''

            end_time_str = str(record.get('end_time', '')).strip()
            if end_time_str.lower() in ['none', 'nan']: end_time_str = ''

            record['start_dt_obj'] = None
            if date_str and start_time_str:
                try:
                    # Combine date and time to create full datetime objects for accurate parsing and sorting
                    record['start_dt_obj'] = parser.parse(f"{date_str} {start_time_str}", dayfirst=True)
                except Exception as e:
                    st.warning(f"Could not parse start_datetime for sorting: '{date_str} {start_time_str}'. Error: {e}")
                    record['start_dt_obj'] = datetime.min # Fallback for sorting

            record['end_dt_obj'] = None
            if date_str and end_time_str: # This condition is now more reliable
                try:
                    record['end_dt_obj'] = parser.parse(f"{date_str} {end_time_str}", dayfirst=True)
                except Exception as e:
                    st.warning(f"Could not parse end_datetime for sorting: '{date_str} {end_time_str}'. Error: {e}")
                    record['end_dt_obj'] = record['start_dt_obj'] if record['start_dt_obj'] else datetime.min # Fallback
            else: # If end_time_str is empty, default end_dt_obj to start_dt_obj
                record['end_dt_obj'] = record['start_dt_obj'] if record['start_dt_obj'] else datetime.min

            # If start_dt_obj is still None, assign datetime.min for sorting
            if record['start_dt_obj'] is None:
                record['start_dt_obj'] = datetime.min

            # Ensure end_dt_obj is not None for sorting
            if record['end_dt_obj'] is None:
                record['end_dt_obj'] = record['start_dt_obj'] # Default to start time if still None


        # Sort the final_records by the datetime objects
        final_records.sort(key=lambda x: x['start_dt_obj'])
        
        # Clean up temporary datetime objects and ensure string formats are consistent
        for record in final_records:
            record['start_time'] = record['start_dt_obj'].strftime("%Y-%m-%d %H:%M")
            record['end_time'] = record['end_dt_obj'].strftime("%Y-%m-%d %H:%M")
            record['date'] = record['start_dt_obj'].strftime("%d/%m/%Y")
            record['day'] = record['start_dt_obj'].strftime("%A")
            del record['start_dt_obj']
            del record['end_dt_obj']

        st.dataframe(final_records)
  
        # # Step 4: Deduction Engine (Gemini-powered)
        st.header("Laytime Deductions (via Gemini)")
        
        #records = final_records.to_dict("records")
        records = final_records
        deductions = []
        if 'clause_texts' in locals() and 'records' in locals() and clause_texts and records:
            st.info(f"Analyzing {len(records)} events against {len(clause_texts)} clauses...")

            for event_record in records:
                # Prepare the event object for the deduction engine
                event_obj = {
                    "date": event_record.get("date"),
                    "day": event_record.get("day"),
                    "start_time": event_record.get("start_time"),
                    "end_time": event_record.get("end_time"),
                    "reason": event_record.get("reason") or event_record.get("event_phase") or "No reason provided",
                }

                # Skip events without a clear reason or time range
                if not event_obj["reason"] or not event_obj["start_time"] or not event_obj["end_time"]:
                    continue

                # Call the new deduction engine function
                deduction_result = analyze_event_against_clauses(event_obj, clause_texts)

                # Append result for display and further calculation
                deductions.append(deduction_result)

            # ✅ Display deductions
            # st.subheader("🔎 Final Deductions")

            if not deductions:
                st.warning("⚠️ No valid deductions could be analyzed.")
            else:
                for i, d in enumerate(deductions):
                    is_deducted = d.get("deduct", False)
                    confidence = d.get("confidence_score", 0.0)
                    color = "green" if is_deducted else "orange"
                
                    title = f"Event: {d.get('Remark', 'N/A')[:70]}..."

                    with st.expander(title):
                        st.markdown(f"**Matched Clause:** {d.get('Clause', 'N/A')}")
                        st.markdown(f"**Confidence Score:** `{confidence:.2f}`")
                        st.markdown(f"**Deduct from Laytime:** :{color}[{'Yes' if is_deducted else 'No'}]")
                        st.markdown(f"**Reason:** {d.get('reason', 'N/A')}")
                        st.markdown(f"**From:** `{d.get('deducted_from', 'N/A')}` | **To:** `{d.get('deducted_to', 'N/A')}`")
                        st.markdown(f"**Hours:** `{d.get('total_hours', 0.0)}`")

        else:
            st.warning("⚠️ Cannot run deduction engine. Clause texts or event records are missing.")

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

            for k, v in metadata.items():
                if v is not None: 
                    metadata_response[k] = v

            # ✅ Build Excel workbook using new format
            net_laytime_used_hours = net if 'net' in locals() else 0.0
            excel_wb = generate_excel_from_extracted_data(metadata_response, deductions, net_laytime_used_hours)
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