import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment, Font
import tempfile
import re
from datetime import datetime, timedelta

def parse_time_string(time_str, date_str):
    """Parses time string (HH:MM) with a given date string (DD/MM/YYYY) into a datetime object."""
    if not time_str or not date_str:
        return None
    try:
        # Try parsing with year assumed from current date if only DD/MM is present
        # This is a robust attempt, but actual year from context is best
        return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
    except ValueError:
        try:
            # Fallback for "YYYY-MM-DD HH:MM" if that format is somehow present
            return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None # Return None if parsing fails

def generate_excel_from_extracted_data(metadata: dict, nor_df: pd.DataFrame, deductions: list[dict], net_laytime_used_hours: float):
    wb = Workbook()
    ws = wb.active
    ws.title = "LAY TIME CALCULATIONS"

    # --- Calculate Laytime Allowed ---
    laytime_allowed_value = ""
    try:
        quantity_raw = metadata.get("Quantity", "")
        disrate_raw = metadata.get("Discharge Rate", "") 

        quantity_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)', str(quantity_raw).replace(" ", ""))
        disrate_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)', str(disrate_raw).replace(" ", ""))

        quantity = float(quantity_match.group(1).replace(",", "")) if quantity_match else 0.0
        disrate = float(disrate_match.group(1).replace(",", "")) if disrate_match else 0.0

        if disrate != 0:
            laytime_allowed_value = f"{quantity / disrate:.2f}"
        else:
            laytime_allowed_value = "N/A (Discharge Rate is zero)"
    except Exception as e:
        laytime_allowed_value = f"Error calculating Laytime Allowed: {e}"

    # -- Top: Metadata Header Rows --
    header_rows = [
        ["Vessel Name", metadata.get("Vessel Name", "")],
        ["A/C", metadata.get("A/C", "")],
        ["TERMS", metadata.get("TERMS", "")],
        ["PRODUCT", metadata.get("PRODUCT", "")],
        ["DEMMURAGE", metadata.get("DEMMURAGE", "")],
        ["DESPATCH", metadata.get("DESPATCH", "")],
        ["Discharge Rate", metadata.get("Discharge Rate", "")],
        ["NOR TENDERED", metadata.get("NOR TENDERED", "")],
        ["LAYTIME ALLOWED", laytime_allowed_value],
        ["VESSEL ARRIVED", metadata.get("Vessel Arrival", "")],
        ["VESSEL BERTHED", metadata.get("Vessel Berthed", "")],
        ["COMMENCED CARGO", metadata.get("Commenced Cargo", "")],
        ["COMPLETED CARGO", metadata.get("Completed Cargo", "")],
        ["QUANTITY", metadata.get("Quantity", "")],
    ]

    for row in header_rows:
        ws.append(row)

    ws.append([])  # Spacer row
    ws.append([])  # Another spacer row for better separation

    # --- Prepare data for Chronological Events and Deductions ---
    # Create a map for quick lookup of deductions
    deduction_map = {}
    for d in deductions:
        # Use a combination of remark and start time to link deductions
        remark_str = str(d.get("Remark", "")).strip()
        deducted_from_str = str(d.get("deducted_from", "")).strip()
        deduction_map[(remark_str, deducted_from_str)] = d

    # Group nor_df by date
    nor_df['date_only'] = pd.to_datetime(nor_df['start_time']).dt.date
    grouped_events = nor_df.groupby('date_only')

    # -- Chronological Events Table Header --
    ws.append(["Date", "Day", "FROM", "TO", "Count (hrs min sec)", "Deductible (hrs min sec)", "Deduction Reason"])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    total_deducted_hours_overall = 0.0 # To keep track of the sum for the final row
    
    for date_group, events_for_date in grouped_events:
        daily_counted_hours = 0.0
        deducted_events_details_for_day = [] # To store details of deducted events for this specific day
        
        # Determine the day name for the date group
        day_name = events_for_date['day'].iloc[0] if not events_for_date.empty else ""

        for index, event_row in events_for_date.iterrows():
            event_start_str = event_row.get("start_time", "")
            event_end_str = event_row.get("end_time", "")
            event_description = event_row.get("reason", "") or event_row.get("event_phase", "")
            event_date_str = event_row.get("date", "") # Get date string from nor_df

            # Check if this event corresponds to a deduction
            deduction_key = (event_description.strip(), event_start_str.strip())
            
            if deduction_key in deduction_map:
                deduction_data = deduction_map[deduction_key]
                # If it's a deducted event, store its details
                deducted_hours_val = float(deduction_data.get('total_hours', 0.0))
                total_deducted_hours_overall += deducted_hours_val
                
                # Format deducted hours as hrs min sec
                hours = int(deducted_hours_val)
                minutes = int((deducted_hours_val * 60) % 60)
                seconds = int((deducted_hours_val * 3600) % 60)
                deducted_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                deduction_reason = deduction_data.get("reason", "")
                
                deducted_events_details_for_day.append([
                    "", # Date column blank
                    "", # Day column blank
                    event_start_str,
                    event_end_str,
                    "", # Counted time column blank for deducted events
                    deducted_time_str,
                    deduction_reason
                ])
            else:
                # If not deducted, calculate counted time
                start_dt = parse_time_string(event_start_str, event_date_str)
                end_dt = parse_time_string(event_end_str, event_date_str)

                if start_dt and end_dt:
                    duration_seconds = (end_dt - start_dt).total_seconds()
                    duration_hours = duration_seconds / 3600.0
                    daily_counted_hours += duration_hours
                # No individual rows for non-deducted events, only sum to daily_counted_hours

        # Add the date and day row (only once per date group)
        ws.append([date_group.strftime("%d-%b-%y"), day_name, "", "", "", "", ""])

        # Add the daily total row for counted time (if any counted hours)
        if daily_counted_hours > 0:
            hours = int(daily_counted_hours)
            minutes = int((daily_counted_hours * 60) % 60)
            seconds = int((daily_counted_hours * 3600) % 60)
            daily_total_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            ws.append(["", "", "", "Total", daily_total_time_str, "", ""])
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
        
        # Append all individual deducted event rows for this day
        for row_data in deducted_events_details_for_day:
            ws.append(row_data)

        ws.append([]) # Spacer after each date group (including its deducted events)


    # Add overall total deducted hours
    ws.append(["", "", "", "", "Total Deducted Hours", f"{total_deducted_hours_overall:.2f}", ""])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    ws.append([]) # Spacer

    # Add net laytime used
    ws.append(["Total Laytime Used", f"{net_laytime_used_hours:.2f}"])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    # -- Align all cells left --
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="top")

    return wb
