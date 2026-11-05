"""Plant records to table rows and back.

No Anvil imports, so the mapping can be tested on its own. Writers take ``ref(table, code)``
and return the row's columns with links resolved through it. Readers take a row (or a dict
with the same columns) whose links have already been turned into codes.

Numbers are stored as numbers. A value the setter wrote as something other than a plain
number ("210/195", "10+22", "-") keeps its text in the row's ``as_written`` column, keyed by
column name, so nothing on the original sheet is lost.
"""

import datetime

import domain

TEMP_COLUMNS = (("nozzle", "temp_nozzle"), ("t1", "temp_1"), ("t2", "temp_2"), ("t3", "temp_3"),
                ("t4", "temp_4"), ("t5", "temp_5"), ("t6", "temp_6"))
RECIPE_NUMBERS = (("cycle", "cycle_s"), ("cooling", "cooling_s"), ("screwRpm", "screw_rpm"), ("px", "px"), ("py", "py"),
                  ("printPieces", "print_pieces"), ("printTotal", "print_total"))
SETTING_COLUMNS = (
    ("Injection speed u1", "inj_speed_1"),
    ("Switch position 1→2", "switch_pos_1_2"),
    ("Injection speed u2", "inj_speed_2"),
    ("Switch position 2→3", "switch_pos_2_3"),
    ("Injection speed u3", "inj_speed_3"),
    ("Injection pressure max P1", "inj_pressure_max_1"),
    ("Position 1→2", "position_1_2"),
    ("Injection pressure max P2", "inj_pressure_max_2"),
    ("Position 2→3", "position_2_3"),
    ("Injection pressure max P3", "inj_pressure_max_3"),
    ("Hold switch position", "hold_switch_pos"),
    ("Hold pressure", "hold_pressure"),
    ("Hold time (s)", "hold_time_s"),
    ("Hold speed", "hold_speed"),
    ("Dosing stroke", "dosing_stroke"),
    ("Decompression after dosing", "decompression"),
    ("Back pressure P1", "back_pressure_1"),
    ("Back pressure switch 1→2", "back_pressure_switch_1_2"),
    ("Back pressure P2", "back_pressure_2"),
)
SETTING_COLUMN = dict(SETTING_COLUMNS)


def _text(value):
    return str(value if value is not None else "").strip()


def _number_in(value, column, written):
    """The number to store; ``written`` gets the original text when it is not exactly that number."""
    text = _text(value)
    if not text:
        return None
    number = domain.num(text)
    if number is None or domain.trim_num(number) != text:
        written[column] = text
    return domain.whole(number) if number is not None else None


def _number_out(row, column, written):
    if column in written:
        return written[column]
    return domain.trim_num(row[column])


def _written(row):
    return dict(row["as_written"] or {})


def _date_in(text):
    text = _text(text)
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_out(value):
    return value.isoformat() if value else ""


def _ref(ref, table, code):
    return ref(table, code) if code else None


# Writers ----------------------------------------------------------------------------------

def worker_row(name):
    return {"name": _text(name)}


def press_row(item, ref):
    """The mounted product is set later by ``press_board_row``: products link back to presses."""
    board = item.get("board") or {}
    return {
        "code": item["id"],
        "name": _text(item.get("name")),
        "alias": _text(item.get("alias")),
        "floor_number": domain.whole(item.get("aa")),
        "serial": _text(item.get("serial")),
        "robot": _text(item.get("robot")),
        "robot_serial": _text(item.get("robotSerial")),
        "robot_year": _text(item.get("robotYear")),
        "euromap": _text(item.get("euromap")),
        "changeover_min": domain.whole(item.get("changeoverMin")),
        "lifecycle": item.get("lifecycle") or "active",
        "board_location": _text(board.get("location")),
        "board_note": _text(board.get("note")),
    }


def press_board_row(item, ref):
    board = item.get("board") or {}
    return {"mounted_product": _ref(ref, "products", board.get("mountedId"))}


def material_row(item, ref):
    return {
        "code": item["id"],
        "grade": _text(item.get("text")),
        "kind": item.get("kind") or "resin",
        "supplier": _text(item.get("supplier")),
        "family": _text(item.get("family")),
        "mfi": domain.whole(item.get("mfi")),
        "account": _text(item.get("account")),
        "invoice_code": _text(item.get("invoiceCode")),
        "description": _text(item.get("description")),
        "notes": _text(item.get("notes")),
        "datasheet_link": _text(item.get("link")),
        "in_catalog": bool(item.get("catalog")),
    }


def color_row(item, ref):
    return {
        "code": item["id"],
        "label_code": _text(item.get("code")),
        "name": _text(item.get("name")),
        "label": _text(item.get("label")),
        "shade": _text(item.get("shade")),
        "account": _text(item.get("account")),
        "notes": _text(item.get("notes")),
        "datasheet_link": _text(item.get("link")),
        "in_catalog": bool(item.get("catalog")),
    }


def product_row(item, ref):
    return {
        "code": item["id"],
        "name": _text(item.get("name")),
        "sheet_id": domain.whole(item.get("legacyId")),
        "erp_code": _text(item.get("erpCode")),
        "item_type": item.get("type") or "part",
        "lifecycle": item.get("lifecycle") or "active",
        "only_on_cards": bool(item.get("onlyOnCards")),
        "notes": _text(item.get("notes")),
        "approved_presses": [row for row in (_ref(ref, "presses", code) for code in item.get("approvedPressIds") or []) if row is not None],
    }


def product_link_row(item, ref):
    return {
        "lid": _ref(ref, "products", item.get("lidId")),
        "part": _ref(ref, "products", item.get("partId")),
        "basis": _text(item.get("basis")),
    }


def mold_row(item, ref):
    return {
        "code": item["id"],
        "name": _text(item.get("name")),
        "product": _ref(ref, "products", item.get("productId")),
        "cavities": domain.whole(item.get("cavities")),
        "shot_weight_g": domain.whole(item.get("shotWeight")),
        "location": _text(item.get("location")),
        "status": item.get("status") or "in use",
    }


def recipe_row(item, ref):
    """The product is the mold's product, so it is not stored twice."""
    written = {}
    temps = item.get("temps") or {}
    fields = {
        "code": item["id"],
        "sheet_row": domain.whole(item.get("legacyId")),
        "mold": _ref(ref, "molds", item.get("moldId")),
        "press": _ref(ref, "presses", item.get("pressId")),
        "trial": bool(item.get("trial")),
        "standard": bool(item.get("standard")),
        "product_lot": _text(item.get("productLot")),
        "status_note": _text(item.get("status")),
        "comment": _text(item.get("comment")),
        "settings_note": _text(item.get("settingsNote")),
    }
    for key, column in TEMP_COLUMNS:
        fields[column] = _number_in(temps.get(key), column, written)
    for key, column in RECIPE_NUMBERS:
        fields[column] = _number_in(item.get(key), column, written)
    fields["as_written"] = written or None
    return fields


def injection_row(item, recipe):
    """None when the recipe has no injection settings written."""
    written = {}
    fields = dict({column: None for _, column in SETTING_COLUMNS}, recipe=recipe)
    filled = False
    for setting in item.get("settings") or []:
        column = SETTING_COLUMN.get(_text(setting.get("label")))
        if column is None:
            continue
        fields[column] = _number_in(setting.get("value"), column, written)
        filled = filled or bool(_text(setting.get("value")))
    if not filled:
        return None
    fields["as_written"] = written or None
    return fields


def material_slot_rows(item, recipe, ref):
    return [{
        "recipe": recipe,
        "material": _ref(ref, "materials", slot.get("materialId")),
        "slot": domain.whole(slot.get("slot")) or position + 1,
        "lot": _text(slot.get("lot")),
    } for position, slot in enumerate(item.get("materialSlots") or [])]


def color_slot_rows(item, recipe, ref):
    return [{
        "recipe": recipe,
        "color": _ref(ref, "colors", slot.get("colorId")),
        "slot": domain.whole(slot.get("slot")) or position + 1,
        "lot": _text(slot.get("lot")),
    } for position, slot in enumerate(item.get("colorSlots") or [])]


def stoppage_rows(item, recipe, ref):
    return [{
        "recipe": recipe,
        "worker": _ref(ref, "workers", _text(issue.get("worker"))),
        "position": position,
        "start_date": _date_in(issue.get("startDate")),
        "start_time": _text(issue.get("startTime")),
        "end_date": _date_in(issue.get("endDate")),
        "end_time": _text(issue.get("endTime")),
        "cause": _text(issue.get("cause")),
        "fix": _text(issue.get("fix")),
    } for position, issue in enumerate(item.get("issues") or [])]


def run_rows(item, recipe, ref):
    return [{
        "recipe": recipe,
        "operator": _ref(ref, "workers", _text(run.get("operator"))),
        "position": position,
        "start_date": _date_in(run.get("startDate")),
        "start_time": _text(run.get("startTime")),
        "end_date": _date_in(run.get("endDate")),
        "end_time": _text(run.get("endTime")),
        "shift": _text(run.get("shift")),
        "good": domain.whole(run.get("good")),
        "scrap": domain.whole(run.get("scrap")),
        "scrap_reason": _text(run.get("scrapReason")),
        "cycle_s": domain.whole(run.get("cycle")),
        "cavities": domain.whole(run.get("cavities")),
        "lot": _text(run.get("lot")),
        "order_no": _text(run.get("order")),
        "notes": _text(run.get("notes")),
        "sample": bool(run.get("sample")),
    } for position, run in enumerate(item.get("runs") or [])]


# Readers ----------------------------------------------------------------------------------

def press_item(row, mounted_code, product_names):
    return {
        "id": row["code"],
        "name": row["name"] or "",
        "alias": row["alias"] or "",
        "aa": domain.whole(row["floor_number"]),
        "serial": row["serial"] or "",
        "robot": row["robot"] or "",
        "robotSerial": row["robot_serial"] or "",
        "robotYear": row["robot_year"] or "",
        "euromap": row["euromap"] or "",
        "changeoverMin": domain.whole(row["changeover_min"]),
        "lifecycle": row["lifecycle"] or "active",
        "board": {
            "mountedId": mounted_code or "",
            "mounted": product_names.get(mounted_code, "") if mounted_code else "",
            "location": row["board_location"] or "",
            "note": row["board_note"] or "",
        },
    }


def material_item(row):
    return {
        "id": row["code"],
        "text": row["grade"] or "",
        "kind": row["kind"] or "resin",
        "supplier": row["supplier"] or "",
        "family": row["family"] or "",
        "mfi": domain.trim_num(row["mfi"]),
        "account": row["account"] or "",
        "invoiceCode": row["invoice_code"] or "",
        "description": row["description"] or "",
        "notes": row["notes"] or "",
        "link": row["datasheet_link"] or "",
        "catalog": bool(row["in_catalog"]),
    }


def color_item(row):
    return {
        "id": row["code"],
        "code": row["label_code"] or "",
        "name": row["name"] or "",
        "label": row["label"] or "",
        "shade": row["shade"] or "",
        "account": row["account"] or "",
        "notes": row["notes"] or "",
        "link": row["datasheet_link"] or "",
        "catalog": bool(row["in_catalog"]),
    }


def product_item(row, approved_codes):
    return {
        "id": row["code"],
        "name": row["name"] or "",
        "legacyId": domain.trim_num(row["sheet_id"]),
        "erpCode": row["erp_code"] or "",
        "type": row["item_type"] or "part",
        "lifecycle": row["lifecycle"] or "active",
        "onlyOnCards": bool(row["only_on_cards"]),
        "notes": row["notes"] or "",
        "approvedPressIds": list(approved_codes),
    }


def product_link_item(row, lid_code, part_code):
    return {"lidId": lid_code or "", "partId": part_code or "", "basis": row["basis"] or ""}


def mold_item(row, product_code):
    return {
        "id": row["code"],
        "name": row["name"] or "",
        "productId": product_code or "",
        "cavities": domain.whole(row["cavities"]),
        "shotWeight": domain.whole(row["shot_weight_g"]),
        "location": row["location"] or "",
        "status": row["status"] or "in use",
    }


def recipe_item(row, mold_code, product_code, press_code):
    written = _written(row)
    item = {
        "id": row["code"],
        "legacyId": domain.whole(row["sheet_row"]),
        "productId": product_code or "",
        "moldId": mold_code or "",
        "pressId": press_code or "",
        "trial": bool(row["trial"]),
        "standard": bool(row["standard"]),
        "productLot": row["product_lot"] or "",
        "status": row["status_note"] or "",
        "comment": row["comment"] or "",
        "settingsNote": row["settings_note"] or "",
        "temps": {key: _number_out(row, column, written) for key, column in TEMP_COLUMNS},
        "settings": [],
        "materialSlots": [],
        "colorSlots": [],
        "issues": [],
        "runs": [],
    }
    for key, column in RECIPE_NUMBERS:
        item[key] = _number_out(row, column, written)
    return item


def settings_items(row):
    written = _written(row)
    settings = []
    for label, column in SETTING_COLUMNS:
        value = _number_out(row, column, written)
        if value:
            settings.append({"label": label, "value": value})
    return settings


def material_slot_item(row, material_code):
    return {"slot": domain.whole(row["slot"]), "lot": row["lot"] or "", "materialId": material_code or ""}


def color_slot_item(row, color_code):
    return {"slot": domain.whole(row["slot"]), "lot": row["lot"] or "", "colorId": color_code or ""}


def stoppage_item(row, worker_name):
    return {
        "startDate": _date_out(row["start_date"]),
        "startTime": row["start_time"] or "",
        "cause": row["cause"] or "",
        "worker": worker_name or "",
        "fix": row["fix"] or "",
        "endDate": _date_out(row["end_date"]),
        "endTime": row["end_time"] or "",
    }


def run_item(row, operator_name):
    return {
        "startDate": _date_out(row["start_date"]),
        "startTime": row["start_time"] or "",
        "endDate": _date_out(row["end_date"]),
        "endTime": row["end_time"] or "",
        "shift": row["shift"] or "",
        "operator": operator_name or "",
        "good": domain.trim_num(row["good"]),
        "scrap": domain.trim_num(row["scrap"]),
        "scrapReason": row["scrap_reason"] or "",
        "cycle": domain.trim_num(row["cycle_s"]),
        "cavities": domain.trim_num(row["cavities"]),
        "lot": row["lot"] or "",
        "order": row["order_no"] or "",
        "notes": row["notes"] or "",
        "sample": bool(row["sample"]),
    }
