import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment, Font
import tempfile
import re # Import re for robust numerical extraction

def generate_excel_from_extracted_data(metadata: dict, nor_df: pd.DataFrame, deductions: list[dict], net_laytime_used_hours: float):
    wb = Workbook()
    ws = wb.active
    ws.title = "LAY TIME CALCULATIONS"

    # --- Calculate Laytime Allowed ---
    laytime_allowed_value = ""
    try:
        # Robustly extract numerical part from Quantity and Discharge Rate
        quantity_raw = metadata.get("Quantity", "")
        # Changed key from DISRATE to Discharge Rate
        disrate_raw = metadata.get("Discharge Rate", "") 

        # Use regex to find numbers (integers or floats)
        quantity_match = re.search(r'(\d+\.?\d*)', str(quantity_raw))
        disrate_match = re.search(r'(\d+\.?\d*)', str(disrate_raw))

        quantity = float(quantity_match.group(1)) if quantity_match else 0.0
        disrate = float(disrate_match.group(1)) if disrate_match else 0.0

        if disrate != 0:
            laytime_allowed_value = f"{quantity / disrate:.2f}"
        else:
            laytime_allowed_value = "N/A (Discharge Rate is zero)"
    except Exception as e:
        laytime_allowed_value = f"Error calculating Laytime Allowed: {e}"


    # -- Top: Metadata Header Rows --
    # User requested order: Vessel Name, A/C, Terms, Products, Demmurrage, Despatch, Discharge Rate,
    # Vessel Arrive, Vessel Berthed, Commenced Cargo, Completed Cargo, Quantity and Nor Tendered.
    header_rows = [
        ["Vessel Name", metadata.get("Vessel Name", "")],
        ["A/C", metadata.get("A/C", "")],
        ["TERMS", metadata.get("TERMS", "")],
        ["PRODUCT", metadata.get("PRODUCT", "")],
        ["DEMMURAGE", metadata.get("DEMMURAGE", "")],
        ["DESPATCH", metadata.get("DESPATCH", "")],
        ["Discharge Rate", metadata.get("Discharge Rate", "")], # Changed label and key
        ["NOR TENDERED", metadata.get("NOR TENDERED", "")], # Moved up as requested
        ["LAYTIME ALLOWED", laytime_allowed_value], # New row for Laytime Allowed
        ["VESSEL ARRIVED", metadata.get("Vessel Arrival", "")],
        ["VESSEL BERTHED", metadata.get("Vessel Berthed", "")],
        ["COMMENCED CARGO", metadata.get("Commenced Cargo", "")],
        ["COMPLETED CARGO", metadata.get("Completed Cargo", "")],
        ["QUANTITY", metadata.get("Quantity", "")], # Keep this row for display
    ]

    for row in header_rows:
        ws.append(row)

    ws.append([])  # Spacer row
    ws.append([])  # Another spacer row for better separation

    # -- Combined Chronological Event and Deduction Table --
    # Adjusted headers to reflect that these are *deducted* events
    ws.append(["Date", "Day", "Event Start (From)", "Event End (To)", "Event Description",
               "Deducted Hours", "Deduction Reason"])
    
    # Apply bold font to header
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    total_deducted_hours = 0.0
    # Iterate directly over the filtered deductions list
    for d in deductions:
        # Extract event details from the deduction object (now containing date/day)
        event_date = d.get("event_date", "")
        event_day = d.get("event_day", "")
        event_start = d.get("deducted_from", "")
        event_end = d.get("deducted_to", "")
        event_description = d.get("Remark", "") # The original event reason/remark

        deducted_hours_val = float(d.get('total_hours', 0.0)) # Ensure it's a float
        total_deducted_hours += deducted_hours_val
        deducted_hours_str = f"{deducted_hours_val:.2f}"
        deduction_reason = d.get("reason", "")
        
        ws.append([
            event_date,
            event_day,
            event_start,
            event_end,
            event_description,
            deducted_hours_str,
            deduction_reason
        ])

    # Add a blank row for spacing
    ws.append([])

    # Add the "Total Deducted Hours" row
    ws.append(["", "", "", "", "Total Deducted Hours", f"{total_deducted_hours:.2f}", ""])
    # Apply bold font to the "Total Deducted Hours" row
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    # Add another blank row for spacing before the total laytime used
    ws.append([])

    # Add the "Total Laytime Used" row
    ws.append(["Total Laytime Used", f"{net_laytime_used_hours:.2f}"])
    
    # Apply bold font to the "Total Laytime Used" row
    for cell in ws[ws.max_row]:
        cell.alignment = Alignment(horizontal="left", vertical="top") # Ensure alignment for this row too
        cell.font = Font(bold=True)

    # -- Align all cells left (re-apply to ensure consistency for all rows) --
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="top")

    return wb
