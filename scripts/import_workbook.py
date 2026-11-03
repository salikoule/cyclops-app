#!/usr/bin/env python3
"""Import the Cyclops workbook into the app's plant record.

    python3 scripts/import_workbook.py                       # rewrite server_code/seed_data.py
    python3 scripts/import_workbook.py --json /tmp/plant.json
    python3 scripts/import_workbook.py --uplink-key KEY      # replace the data in a running app
    python3 scripts/import_workbook.py --uplink-key KEY --url ws://localhost:3032/_/uplink

IDs follow the sheet order (PRD-0001, MLD-0001, PRS-01, REC-<sheet row id>, MAT-001,
COL-001), the same scheme as cyclops/sketch/build_data.py, so a re-import keeps
every link and bookmark. Nothing is written back to the workbook.

Needs openpyxl. The --uplink-key mode also needs anvil-uplink.
"""

import argparse
import base64
import datetime
import json
import re
import sys
import zlib
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = Path.home() / "Downloads" / "CLONE- Cyclops παραγωγη.xlsx"
SEED_MODULE = ROOT / "server_code" / "seed_data.py"

GREEK_ACCENTS = str.maketrans("ΆΈΉΊΌΎΏΪΫάέήίόύώϊϋΐΰ", "ΑΕΗΙΟΥΩΙΥΑΕΗΙΟΥΩΙΥΙΥ")

SETTING_COLUMNS = (
    (1, "Injection speed u1"), (2, "Switch position 1→2"), (3, "Injection speed u2"), (4, "Switch position 2→3"),
    (5, "Injection speed u3"), (6, "Injection pressure max P1"), (7, "Position 1→2"), (8, "Injection pressure max P2"),
    (9, "Position 2→3"), (10, "Injection pressure max P3"), (11, "Hold switch position"), (12, "Hold pressure"),
    (13, "Hold time (s)"), (14, "Hold speed"), (15, "Dosing stroke"), (16, "Decompression after dosing"),
    (17, "Back pressure P1"), (18, "Back pressure switch 1→2"), (19, "Back pressure P2"), (20, "Screw speed (rpm)"),
    (21, "Cooling time (s)"), (22, "Cycle time (s)"),
)

# Issues sheet: up to three stoppages per recipe row, seven columns each.
ISSUE_GROUPS = (1, 8, 15)


def norm(value):
    text = str(value or "").strip().upper().translate(GREEK_ACCENTS)
    return re.sub(r"\s+", " ", text)


def cell(row, index):
    if row is None or index >= len(row) or row[index] in (None, ""):
        return ""
    value = row[index]
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    return str(value).strip()


def blank(text):
    return "" if text in ("", "-") else text


def date_text(value):
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return blank(str(value or "").strip())


def time_text(value):
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M")
    if isinstance(value, datetime.datetime):
        return value.strftime("%H:%M")
    return blank(str(value or "").strip())


def year_text(value):
    if isinstance(value, datetime.datetime):
        return str(value.year) if value.month == 1 else value.strftime("%m/%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return blank(str(value or "").strip())


def sheet(wb, name):
    if name not in wb.sheetnames:
        return []
    return [list(r) for r in wb[name].iter_rows(values_only=True)]


def parse(path):
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    data, injection, product_sheet = sheet(wb, "Data"), sheet(wb, "Injection"), sheet(wb, "Product")
    material_sheet, colour_sheet, machines = sheet(wb, "Material"), sheet(wb, "Colour"), sheet(wb, "Machines")
    current, issues_sheet, personnel = sheet(wb, "CurrentP"), sheet(wb, "Issues"), sheet(wb, "Personnel")
    wb.close()
    report = OrderedDict()

    presses = []
    for row in machines[1:]:
        name = cell(row, 0)
        if not name:
            continue
        aa = cell(row, 2)
        presses.append({
            "name": name, "alias": cell(row, 1), "aa": int(float(aa)) if aa else 99,
            "serial": blank(cell(row, 3)), "robot": blank(cell(row, 4)), "robotSerial": blank(cell(row, 5)),
            "robotYear": year_text(row[6] if len(row) > 6 else None),
            "euromap": blank(cell(row, 8)), "board": {"mounted": "", "location": "", "note": ""},
        })
    presses.sort(key=lambda p: (p["aa"], p["name"]))
    for index, press in enumerate(presses, start=1):
        press["id"] = f"PRS-{index:02d}"
    press_by_name = {p["name"]: p for p in presses}
    press_by_norm = {norm(p["name"]): p for p in presses}

    for row in current:
        left_press, left_loc, left_product = cell(row, 0), cell(row, 3), cell(row, 5)
        right_press, right_product = cell(row, 2), cell(row, 7)
        if left_press in press_by_name:
            press_by_name[left_press]["board"] = {"mounted": left_product, "location": left_loc, "note": ""}
        if right_press in press_by_name:
            press_by_name[right_press]["board"] = {"mounted": right_product, "location": "", "note": ""}

    # Product sheet: one name per row, then a 1 under each press the product may run on.
    matrix = []
    header = product_sheet[0] if product_sheet else []
    for col in range(3, len(header)):
        press = press_by_norm.get(norm(header[col]))
        if press:
            matrix.append((col, press["id"]))
    products = []
    approvals = 0
    for row in product_sheet[1:]:
        name = cell(row, 0)
        if not name or name == "-":
            continue
        approved = [press_id for col, press_id in matrix if cell(row, col) == "1"]
        approvals += len(approved)
        products.append({"name": name, "legacyId": cell(row, 1), "moldId": None, "erpCode": "", "approvedPressIds": approved})
    for index, product in enumerate(products, start=1):
        product["id"] = f"PRD-{index:04d}"
    product_by_norm = {norm(p["name"]): p for p in products}
    report["press approvals"] = approvals

    materials = []
    for row in material_sheet[2:]:
        grade = cell(row, 1)
        if not grade or grade == "-":
            continue
        materials.append({
            "text": grade, "supplier": blank(cell(row, 0)), "mfi": blank(cell(row, 2)), "family": blank(cell(row, 3)),
            "account": blank(cell(row, 4)), "invoiceCode": blank(cell(row, 5)), "description": blank(cell(row, 6)),
            "notes": blank(cell(row, 7)), "link": cell(row, 8) if cell(row, 8).startswith("http") else "", "catalog": True,
        })
    material_by_norm = OrderedDict((norm(m["text"]), m) for m in materials)

    colors = []
    seen_codes = set()
    for row in colour_sheet[2:]:
        code = cell(row, 2)
        if not code or code == "-" or norm(code) in seen_codes:
            continue
        seen_codes.add(norm(code))
        link = cell(row, 5) if cell(row, 5).startswith("http") else ""
        extras = [cell(row, col) for col in range(5, 11)]
        notes = " · ".join(text for text in extras if text and not text.startswith("http"))
        colors.append({
            "code": code, "name": blank(cell(row, 3)), "label": blank(cell(row, 0)), "account": blank(cell(row, 1)),
            "shade": blank(cell(row, 4)), "link": link, "notes": notes, "catalog": True,
        })
    color_by_norm = OrderedDict((norm(c["code"]), c) for c in colors)

    injection_by_id = {}
    for row in injection[1:]:
        rid = cell(row, 0)
        if rid:
            injection_by_id[rid] = row

    issues_by_id = {}
    issue_count = 0
    for row in issues_sheet[1:]:
        rid = cell(row, 0)
        if not rid:
            continue
        found = []
        for start in ISSUE_GROUPS:
            group = (row[start:start + 7] + [None] * 7)[:7]
            cause = blank(str(group[2] or "").strip())
            if not cause:
                continue
            found.append({
                "startDate": date_text(group[1]), "startTime": time_text(group[0]),
                "cause": cause, "worker": blank(str(group[3] or "").strip()), "fix": blank(str(group[4] or "").strip()),
                "endDate": date_text(group[6]), "endTime": time_text(group[5]),
            })
        if found:
            issues_by_id[rid] = found
            issue_count += len(found)
    report["stoppages"] = issue_count

    workers = []
    for row in personnel[1:]:
        for col in (2, 5, 6):
            name = blank(cell(row, col))
            if name and name not in workers and not name.isdigit():
                workers.append(name)
    report["workers"] = len(workers)

    recipes = []
    molds = []
    mold_by_product = {}
    notes = 0
    for row in data[1:]:
        press_name, mold_text, legacy = cell(row, 0), cell(row, 1), cell(row, 2)
        if not press_name or not mold_text or press_name not in press_by_name:
            continue
        try:
            legacy_num = int(float(legacy))
        except ValueError:
            continue
        product = product_by_norm.get(norm(mold_text))
        if product is None:
            product = {"name": mold_text, "legacyId": "", "moldId": None, "erpCode": "", "approvedPressIds": [],
                       "id": f"PRD-{len(products) + 1:04d}", "onlyOnCards": True}
            products.append(product)
            product_by_norm[norm(mold_text)] = product
        if product["id"] not in mold_by_product:
            mold = {"id": f"MLD-{len(molds) + 1:04d}", "name": mold_text, "productId": product["id"]}
            molds.append(mold)
            mold_by_product[product["id"]] = mold
            product["moldId"] = mold["id"]
        mold = mold_by_product[product["id"]]
        press = press_by_name[press_name]

        material_slots = []
        for slot, (text_col, lot_col) in enumerate(((20, 21), (22, 23), (24, 25)), start=1):
            text = cell(row, text_col)
            if not text or text == "-":
                continue
            key = norm(text)
            if key not in material_by_norm:
                material = {"text": text, "supplier": "", "mfi": "", "family": "", "account": "", "invoiceCode": "",
                            "description": "", "notes": "", "link": "", "catalog": False}
                materials.append(material)
                material_by_norm[key] = material
            material_slots.append({"slot": slot, "materialKey": key, "lot": blank(cell(row, lot_col))})

        color_slots = []
        for slot, (code_col, lot_col) in enumerate(((11, 12), (13, 14), (15, 16), (17, 18)), start=1):
            code = cell(row, code_col)
            if not code or code == "-":
                continue
            key = norm(code)
            if key not in color_by_norm:
                color = {"code": code, "name": "", "label": "", "account": "", "shade": "", "link": "", "notes": "", "catalog": False}
                colors.append(color)
                color_by_norm[key] = color
            color_slots.append({"slot": slot, "colorKey": key, "lot": blank(cell(row, lot_col))})

        inj = injection_by_id.get(legacy)
        settings = []
        for col, label in SETTING_COLUMNS:
            value = cell(inj, col) if inj else ""
            if value:
                settings.append({"label": label, "value": value})
        settings_note = cell(inj, 23) if inj else ""
        comment = " · ".join(text for text in (cell(row, 29), cell(row, 30)) if text)
        if settings_note:
            notes += 1
        recipes.append({
            "id": f"REC-{legacy_num:04d}", "legacyId": legacy_num, "productId": product["id"], "moldId": mold["id"],
            "pressId": press["id"],
            "temps": {"nozzle": cell(row, 3), "t6": cell(row, 4), "t5": cell(row, 5), "t4": cell(row, 6),
                      "t3": cell(row, 7), "t2": cell(row, 8), "t1": cell(row, 9)},
            "cycle": cell(inj, 22) if inj else "", "cooling": cell(inj, 21) if inj else "",
            "screwRpm": cell(inj, 20) if inj else "", "settings": settings, "settingsNote": settings_note,
            "px": cell(row, 10), "py": cell(row, 19), "productLot": cell(row, 26),
            "printPieces": cell(row, 27), "printTotal": cell(row, 28), "comment": comment,
            "status": cell(inj, 24) if inj else "", "trial": legacy_num <= 16,
            "materialSlots": material_slots, "colorSlots": color_slots,
            "issues": issues_by_id.get(legacy) or [],
        })
    report["setting notes"] = notes

    for index, material in enumerate(materials, start=1):
        material["id"] = f"MAT-{index:03d}"
    for index, color in enumerate(colors, start=1):
        color["id"] = f"COL-{index:03d}"
    for recipe in recipes:
        for slot in recipe["materialSlots"]:
            slot["materialId"] = material_by_norm[slot.pop("materialKey")]["id"]
        for slot in recipe["colorSlots"]:
            slot["colorId"] = color_by_norm[slot.pop("colorKey")]["id"]

    # Lid-to-part links by name only. Exact: "ΚΑΠΑΚΙ (ΓΙΑ) X" where X is a product.
    # Family: "ΚΑΠΑΚΙ X 11 & 17 lt" expands to "X 11 lt" and "X 17 lt".
    links = []
    for product in products:
        name = norm(product["name"])
        rest = None
        for prefix in ("ΚΑΠΑΚΙ ΓΙΑ ", "ΚΑΠΑΚΙ "):
            if name.startswith(prefix):
                rest = name[len(prefix):].strip()
                break
        if rest is None:
            continue
        candidates = []
        basis = "exact"
        if rest in product_by_norm and product_by_norm[rest] is not product:
            candidates = [rest]
        else:
            match = re.search(r"^(.*?)(\d[\d,.]*(?:\s*(?:&|,)\s*\d[\d,.]*)+)\s*(LT|ML|L)$", rest)
            if match:
                family, numbers, unit = match.group(1).strip(), match.group(2), match.group(3)
                parts = [p.strip() for p in re.split(r"\s*&\s*|,(?!\d)", numbers) if p.strip()]
                expanded = [f"{family} {p} {unit}".strip() for p in parts]
                candidates = [e for e in expanded if e in product_by_norm and product_by_norm[e] is not product]
                basis = "family"
        for candidate in candidates:
            links.append({"lidId": product["id"], "partId": product_by_norm[candidate]["id"], "basis": basis})

    graph = {
        "products": products, "molds": molds, "presses": presses, "materials": materials,
        "colors": colors, "recipes": recipes, "links": links, "workers": workers,
        "meta": {"source": Path(path).name, "imported": datetime.date.today().isoformat()},
    }
    counted = OrderedDict((key, len(graph[key])) for key in ("products", "molds", "presses", "recipes", "materials", "colors", "links"))
    counted.update(report)
    return graph, counted


def encode(graph):
    raw = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw, 9)


def write_seed_module(graph, counted, target=SEED_MODULE):
    packed = base64.b64encode(encode(graph)).decode("ascii")
    lines = ['    "%s"' % packed[i:i + 96] for i in range(0, len(packed), 96)]
    body = (
        '"""Workbook import, generated by scripts/import_workbook.py. Regenerate instead of editing."""\n\n'
        "import base64\nimport json\nimport zlib\n\n"
        "SOURCE = %r\n"
        "COUNTS = %r\n\n"
        "_PAYLOAD = (\n%s\n)\n\n\n"
        "def load():\n"
        '    return json.loads(zlib.decompress(base64.b64decode(_PAYLOAD)).decode("utf-8"))\n'
    ) % (graph["meta"]["source"], dict(counted), "\n".join(lines))
    target.write_text(body, encoding="utf-8")
    return target


def push_uplink(graph, key, url=None):
    import anvil.server
    from anvil import BlobMedia

    if url:
        anvil.server.connect(key, url=url)
    else:
        anvil.server.connect(key)
    try:
        media = BlobMedia("application/zlib", encode(graph), name="plant.json.z")
        return anvil.server.call("cyclops_import_plant", media)
    finally:
        anvil.server.disconnect()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook", default=str(WORKBOOK), help="path to the .xlsx (default: %(default)s)")
    parser.add_argument("--json", help="also write the parsed graph to this JSON file")
    parser.add_argument("--no-seed", action="store_true", help="do not rewrite server_code/seed_data.py")
    parser.add_argument("--uplink-key", help="server Uplink key; replaces the data in that app")
    parser.add_argument("--url", help="Uplink URL for a local App Server, e.g. ws://localhost:3032/_/uplink")
    args = parser.parse_args(argv)

    path = Path(args.workbook).expanduser()
    if not path.exists():
        sys.exit("workbook not found: %s" % path)
    graph, counted = parse(path)
    print(" · ".join("%s %s" % (value, key) for key, value in counted.items()))
    if args.json:
        Path(args.json).write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote %s" % args.json)
    if not args.no_seed:
        target = write_seed_module(graph, counted)
        print("wrote %s (%s KB)" % (target.relative_to(ROOT), target.stat().st_size // 1024))
    if args.uplink_key:
        result = push_uplink(graph, args.uplink_key, args.url)
        print("app now holds: %s" % result)


if __name__ == "__main__":
    main()
