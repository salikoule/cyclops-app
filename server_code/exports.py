"""CSV and Excel bytes for a list of records. No Anvil imports."""

import csv
import io

# Column titles and row keys for the main record lists. Lists join as comma-separated text.
COLUMNS = {
    "item": (("ID", "id"), ("Name", "name"), ("Status", "status"), ("Type", "typeLabel"), ("Category", "category"),
             ("SKU", "erp"), ("Product", "parent"), ("Supplier", "supplier")),
    "mold": (("ID", "id"), ("Name", "name"), ("Status", "status"), ("Cavities", "cavities"), ("Shot (g)", "shot"), ("Location", "location")),
    "machine": (("ID", "id"), ("Name", "name"), ("Status", "status"), ("Type", "type"), ("Location", "location"), ("Running now", "current")),
    "recipe": (("ID", "id"), ("Item", "item"), ("Machine", "machine"), ("Mold", "mold"), ("Status", "status"), ("Cycle (s)", "cycle"), ("Pieces per hour", "pph")),
    "order": (("ID", "id"), ("Item", "item"), ("Quantity", "quantity"), ("Made", "made"), ("Due", "due"), ("ERP order no.", "erp"), ("Status", "status")),
    "run": (("ID", "id"), ("Order", "order"), ("Item", "item"), ("Machine", "machine"), ("Started", "start"), ("Ended", "end"),
            ("Good", "good"), ("Operator", "operator"), ("Shift", "shift"), ("Status", "status")),
    "stoppage": (("Machine", "machine"), ("Run", "run"), ("Started", "start"), ("Ended", "end"), ("Hours", "hours"),
                 ("Cause", "cause"), ("Category", "category"), ("Description", "description"), ("Status", "status")),
    "lot": (("ID", "id"), ("Number", "number"), ("Item", "item"), ("Origin", "origin"), ("Quantity", "quantity"), ("Received", "received"), ("Status", "status")),
    "changeover": (("ID", "id"), ("Machine", "machine"), ("From", "from"), ("To", "to"), ("Kind", "kind"), ("Started", "start"), ("Hours", "hours"), ("Source", "source")),
}


def cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(cell(item) for item in value)
    return value


def table(kind, records):
    columns = COLUMNS.get(kind) or ()
    headers = [title for title, _ in columns]
    body = [[cell(row.get(key)) for _, key in columns] for row in records or []]
    return headers, body


def csv_bytes(kind, records):
    headers, body = table(kind, records)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(body)
    return buffer.getvalue().encode("utf-8")


def xlsx_bytes(kind, records):
    from openpyxl import Workbook

    headers, body = table(kind, records)
    book = Workbook()
    sheet = book.active
    sheet.title = (kind or "records")[:31]
    sheet.append(headers)
    for line in body:
        sheet.append(list(line))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
