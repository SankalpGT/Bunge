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
        disrate_raw = metadata.get("DISRATE", "") 

        # Use regex to find numbers (integers or floats)
        quantity_match = re.search(r'(\d+\.?\d*)', str(quantity_raw))
        disrate_match = re.search(r'(\d+\.?\d*)', str(disrate_raw))

        quantity = float(quantity_match.group(1)) if quantity_match else 0.0
        disrate = float(disrate_match.group(1)) if disrate_match else 0.0

        if disrate != 0:
            time_allowed = f"{quantity / disrate:.4f}"
        else:
            time_allowed = "N/A (Discharge Rate is zero)"
    except Exception as e:
        time_allowed = f"Error calculating Laytime Allowed: {e}"

    laytime_allowed_value = deductions[0].get('deducted_to', 'N/A Discharge rate is 0')

    a_c = ""
    if metadata.get("A/C", ""):
        a_c = metadata.get("A/C", "")
    else:
        a_c = metadata.get("Charterer", "")

    # -- Top: Metadata Header Rows --
    header_rows = [
        ["Vessel Name :", metadata.get("Vessel Name", ""), "", "", "PORT :", metadata.get("Port", "")],
        ["A/C :", a_c, "", "", "QUANTITY :", metadata.get("Quantity", "")],
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
    ws.append(["Date", "Day", "From", "To", "Deduction", "To Count", "Deduction Reason"])
    
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
        if d.get("deduct"):
            ws.append([
                d.get("Date", ""),
                d.get("Day", ""),
                d.get("deducted_from", ""),
                d.get("deducted_to", ""),
                hours,
                "",
                d.get("Remark", "")
        ])
        else:
            ws.append([
                d.get("Date", ""),
                d.get("Day", ""),
                d.get("deducted_from", ""),
                d.get("deducted_to", ""),
                "",
                hours,
                ""
        ])

    ws.append(["TIME ALLOWED :", time_allowed, "", "Total", f"{total_deducted_hours:.2f}", ""])

    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    time_used = f"{net_laytime_used_hours/24.0:.4f}"
    ws.append(["TIME USED", time_used])

    for cell in ws[ws.max_row]:
        cell.alignment = Alignment(horizontal="left", vertical="top") # Ensure alignment for this row too
        cell.font = Font(bold=True)

    print(f"time_used: {time_used}")
    print(f"type time_used: {type(time_used)}")
    print(f"time_allowed: {time_allowed}")
    print(f"type time_allowed: {type(time_allowed)}")
    difference = round(float(time_used) - float(time_allowed), 4)
    if difference > 0:
        rate = float(metadata.get("DEMMURAGE", 0))
        cost = difference * rate
        ws.append(["DEMMURAGE", f"{difference:.4f}"])
        ws.append(["Rate US$", rate, f"{cost:.2f}"])
    elif difference < 0:
        des_pull = abs(difference)
        rate = float(metadata.get("DESPATCH", 0))
        credit = des_pull * rate
        ws.append(["DESPATCH", f"{des_pull:.4f}"])
        ws.append(["Rate US$", rate, f"{credit:.2f}"])
    else:
        ws.append(["NO DEMURRAGE OR DESPATCH APPLICABLE", "0"])

    # Bold all the last few rows
    for row in ws.iter_rows(min_row=ws.max_row - 3, max_row=ws.max_row):
        for cell in row:
            cell.font = Font(bold=True)

    # -- Align all cells left --
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="top")

    return wb
