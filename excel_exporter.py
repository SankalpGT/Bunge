import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment
import tempfile

def generate_excel_from_extracted_data(metadata: dict):
    wb = Workbook()
    ws = wb.active
    ws.title = "LAY TIME CALCULATIONS"

    # -- Top: Metadata Header Rows --
    header_rows = [
        ["Vessel Name", metadata.get("Vessel Name", ""), "", "", "", "PORT", metadata.get("Port", "")],
        ["A/C", metadata.get("A/C", ""), "", "", "QUANTITY :", metadata.get("Quantity", "")],
        ["TERMS", metadata.get("TERMS", ""), "DISRATE", metadata.get("DISRATE", ""), "NOR TENDERED", metadata.get("NOR TENDERED", "")],
        ["PRODUCT", metadata.get("PRODUCT", ""), "NOR VALID", metadata.get("NOR VALID", "")],
        ["LTC  AT :", metadata.get("LTC AT", ""), "VESSEL ARRIVED", metadata.get("Vessel Arrival", "")],
        ["", "", "VESSEL BERTHED", metadata.get("Vessel Berthed", "")],
        ["DEMMURAGE", metadata.get("DEMMURAGE", ""), "COMMENCED CARGO", metadata.get("Commenced Cargo", "")],
        ["DESPATCH", metadata.get("DESPATCH", ""), "COMPLETED CARGO", metadata.get("Completed Cargo", "")],
    ]

    for row in header_rows:
        ws.append(row)

    ws.append([])  # Spacer row

    # -- Bottom: Chronological Event Table --
    ws.append(["Date & Time", "Event", "Remarks"])
    for event in metadata.get("Chronological Events", []):
        ws.append([
            event.get("Date & Time", ""),
            event.get("Event", ""),
            event.get("Remarks", "")
        ])

    # -- Align all cells left --
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="top")

    return wb
