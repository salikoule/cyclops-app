"""Plant records to table rows and back.

No Anvil imports, so the mapping can be tested on its own. Writers take ``ref(table, code)``
and return the row's columns with links resolved through it. Readers take a row (or a dict
with the same columns) whose links have already been turned into codes.

Numbers are stored as numbers. A recipe's machine settings are the press's own parameters, so
they sit on the recipe as JSON lists of ``{label, value}`` in the order written: ``temps`` holds
the barrel zones the press has, ``injection`` the injection page with cooling and screw speed,
``extra`` the remaining setting-sheet boxes. Values that are plain numbers are numbers; anything
else ("210/195", "5,5") keeps the setter's text. A "-" for a zone means the press has none.
"""

import datetime

import domain

RECIPE_INJECTION_FIELDS = (("cooling", "Cooling time (s)"), ("screwRpm", "Screw speed (rpm)"))
RECIPE_EXTRA_FIELDS = (("px", "ΠΧ"), ("py", "ΠΥ"), ("printPieces", "ΤΕΜ εκτύπωση"), ("printTotal", "TOT εκτύπωσης"))
PRESS_COLUMNS = ("code", "name", "alias", "floor_number", "serial", "robot", "robot_serial", "robot_year", "euromap",
                 "changeover_min", "lifecycle", "board_location", "board_note")
PRODUCT_COLUMNS = ("code", "name", "erp_code", "item_type", "lifecycle", "only_on_cards", "notes",
                   "approved_presses", "lid_basis")


def _text(value):
    return str(value if value is not None else "").strip()


def _setting_in(text):
    number = domain.num(text)
    return domain.whole(number) if number is not None and domain.trim_num(number) == text else text


def _settings_in(settings):
    """The machine's parameters in the order written, as [{label, value}]; None when none are set."""
    kept = []
    for setting in settings or []:
        label, value = _text(setting.get("label")), _text(setting.get("value"))
        if label and value:
            kept.append({"label": label, "value": _setting_in(value)})
    return kept or None


def _setting_out(value):
    return domain.trim_num(value) if isinstance(value, (int, float)) else _text(value)


def _settings_out(stored):
    return [{"label": setting["label"], "value": _setting_out(setting["value"])} for setting in stored or []]


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
        "erp_code": _text(item.get("erpCode")),
        "item_type": item.get("type") or "part",
        "lifecycle": item.get("lifecycle") or "active",
        "only_on_cards": bool(item.get("onlyOnCards")),
        "notes": _text(item.get("notes")),
        "approved_presses": [row for row in (_ref(ref, "presses", code) for code in item.get("approvedPressIds") or []) if row is not None],
        "lid_basis": _text(item.get("lidBasis")) if item.get("lidId") else "",
    }


def product_lid_row(item, ref):
    """Set after the products exist: the lid is another product."""
    return {"lid": _ref(ref, "products", item.get("lidId"))}


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
    temps = item.get("temps") or {}
    return {
        "code": item["id"],
        "mold": _ref(ref, "molds", item.get("moldId")),
        "press": _ref(ref, "presses", item.get("pressId")),
        "trial": bool(item.get("trial")),
        "standard": bool(item.get("standard")),
        "cycle_s": domain.whole(item.get("cycle")),
        "product_lot": _text(item.get("productLot")),
        "status_note": _text(item.get("status")),
        "comment": _text(item.get("comment")),
        "settings_note": _text(item.get("settingsNote")),
        "temps": _settings_in([{"label": label, "value": temps.get(key)} for key, label in domain.TEMP_LABELS
                               if _text(temps.get(key)) != "-"]),
        "injection": _settings_in(list(item.get("settings") or [])
                                  + [{"label": label, "value": item.get(key)} for key, label in RECIPE_INJECTION_FIELDS]),
        "extra": _settings_in([{"label": label, "value": item.get(key)} for key, label in RECIPE_EXTRA_FIELDS]),
    }


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


def product_item(row, approved_codes, lid_code):
    return {
        "id": row["code"],
        "name": row["name"] or "",
        "erpCode": row["erp_code"] or "",
        "type": row["item_type"] or "part",
        "lifecycle": row["lifecycle"] or "active",
        "onlyOnCards": bool(row["only_on_cards"]),
        "notes": row["notes"] or "",
        "approvedPressIds": list(approved_codes),
        "lidId": lid_code or "",
        "lidBasis": (row["lid_basis"] or "") if lid_code else "",
    }


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
    temps = {setting["label"]: setting["value"] for setting in _settings_out(row["temps"])}
    injection = _settings_out(row["injection"])
    fields = {setting["label"]: setting["value"] for setting in injection}
    extra = {setting["label"]: setting["value"] for setting in _settings_out(row["extra"])}
    item = {
        "id": row["code"],
        "productId": product_code or "",
        "moldId": mold_code or "",
        "pressId": press_code or "",
        "trial": bool(row["trial"]),
        "standard": bool(row["standard"]),
        "cycle": domain.trim_num(row["cycle_s"]),
        "productLot": row["product_lot"] or "",
        "status": row["status_note"] or "",
        "comment": row["comment"] or "",
        "settingsNote": row["settings_note"] or "",
        "temps": {key: temps.get(label, "") for key, label in domain.TEMP_LABELS},
        "settings": [setting for setting in injection if setting["label"] not in domain.RECIPE_FIELD_SETTINGS],
        "materialSlots": [],
        "colorSlots": [],
        "issues": [],
        "runs": [],
    }
    for key, label in RECIPE_INJECTION_FIELDS:
        item[key] = fields.get(label, "")
    for key, label in RECIPE_EXTRA_FIELDS:
        item[key] = extra.get(label, "")
    return item


def material_slot_item(row, material_code):
    return {"slot": domain.whole(row["slot"]), "lot": row["lot"] or "", "materialId": material_code or ""}


def color_slot_item(row, color_code):
    return {"slot": domain.whole(row["slot"]), "lot": row["lot"] or "", "colorId": color_code or ""}


def stop_times(row):
    return {"startDate": _date_out(row["start_date"]), "startTime": row["start_time"] or "",
            "endDate": _date_out(row["end_date"]), "endTime": row["end_time"] or ""}


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
