import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
import re

def generate_excel_from_extracted_data(metadata: dict, nor_df: pd.DataFrame, deductions: list[dict], net_laytime_used_hours: float, deduc: float):
    wb = Workbook()
    ws = wb.active
    ws.title = "LAY TIME CALCULATIONS"

    # --- Calculate Laytime Allowed ---
    time_allowed = ""
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
            time_allowed = f"{quantity / disrate:.2f}"
        else:
            time_allowed = "N/A (Discharge Rate is zero)"
    except Exception as e:
        time_allowed = f"Error calculating Laytime Allowed: {e}"

    laytime_allowed_value = deductions[0].get('deducted_to', 'N/A Discharge rate is 0')

    # -- Top: Metadata Header Rows --
    header_rows = [
        ["Vessel Name :", metadata.get("Vessel Name", ""), "", "", "PORT :", metadata.get("Port", "")],
        ["A/C :", metadata.get("A/C", ""), "", "", "QUANTITY :", metadata.get("Quantity", "")],
        ["TERMS :", metadata.get("TERMS", ""), "DISRATE :", metadata.get("DISRATE", ""), "NOR TENDERED :", metadata.get("NOR TENDERED", "")], 
        ["PRODUCT :", metadata.get("PRODUCT", "")],
        ["LTC  AT :", metadata.get("LTC AT", "")],
        ["VESSEL ARRIVED :", metadata.get("Vessel Arrival", ""), "", "", "VESSEL BERTHED :", metadata.get("Vessel Berthed", "")],
        ["DEMMURAGE :", metadata.get("DEMMURAGE", ""), "", "", "COMMENCED CARGO :", metadata.get("Commenced Cargo", "")],
        ["DESPATCH :", metadata.get("DESPATCH", ""), "", "", "COMPLETED CARGO :", metadata.get("Completed Cargo", "")],
        ["LAYTIME TO START COUNTING :", laytime_allowed_value],
        ["TIME ALLOWED :", time_allowed]
    ]

    for row in header_rows:
        ws.append(row)

    ws.append([])  # Spacer row

    # -- Combined Chronological Event and Deduction Table --
    # Adjusted headers to reflect that these are *deducted* events
    ws.append(["Date", "Day", "From", "To", "Deducted Hours", "Deduction Reason"])
    
    # Apply bold font to header
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    total_deducted_hours = deduc

    for d in deductions:

        raw_hours = d.get('total_hours')
        try:
            hours = float(raw_hours)
        except (TypeError, ValueError):
            hours = 0.0

        ws.append([
            d.get("Date", ""),
            d.get("Day", ""),
            d.get("deducted_from", ""),
            d.get("deducted_to", ""),
            hours,
            d.get("reason", "")
    ])
        
    ws.append([])

    ws.append(["", "", "", "", "Total", f"{total_deducted_hours:.2f}", ""])

    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.append(["TIME USED", f"{net_laytime_used_hours:.2f}"])

    for cell in ws[ws.max_row]:
        cell.alignment = Alignment(horizontal="left", vertical="top") # Ensure alignment for this row too
        cell.font = Font(bold=True)

    # -- Align all cells left --
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="top")

    return wb
