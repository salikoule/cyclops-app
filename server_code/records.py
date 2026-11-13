"""Plant records to table rows and back.

No Anvil imports, so the mapping can be tested on its own. ``TABLES`` names every record table
in the order rows are written (a table only links to tables before it, except the links listed
in ``LATE``), with its columns as ``(column, key, kind)``:

- ``text``, ``num``, ``bool``: plain values; an empty number is None.
- ``date``: an ISO date string; ``moment``: an ISO UTC moment ``YYYY-MM-DDTHH:MM:SSZ``.
- ``json``: a dict kept as is.
- ``("link", table)`` and ``("links", table)``: the code, or list of codes, of the linked rows.

``CHILDREN`` are line tables that belong to one record and are written with it, as a list on
the record (a recipe's inputs, a run's scrap and consumed lots).

A recipe's machine settings are the press's own parameters, so they sit on the recipe as JSON
lists of ``{label, value}`` in the order written: ``temps`` holds the barrel zones the press
has, ``injection`` the injection page with cooling and screw speed, ``extra`` the remaining
setting-sheet boxes. Values that are plain numbers are numbers; anything else ("210/195",
"5,5") keeps the setter's text.
"""

import datetime

TEXT, NUM, BOOL, DATE, MOMENT, JSON = "text", "num", "bool", "date", "moment", "json"


def link(table):
    return ("link", table)


def links(table):
    return ("links", table)


TABLES = (
    ("item_categories", [("name", "name", TEXT), ("item_type", "type", TEXT), ("role", "role", TEXT)]),
    ("machine_types", [("name", "name", TEXT)]),
    ("units", [("name", "name", TEXT), ("status", "status", TEXT)]),
    ("variant_attributes", [("name", "name", TEXT), ("status", "status", TEXT)]),
    ("person_roles", [("name", "name", TEXT), ("runs_machines", "runsMachines", BOOL), ("status", "status", TEXT)]),
    ("shifts", [("name", "name", TEXT), ("start_time", "start", TEXT), ("end_time", "end", TEXT), ("status", "status", TEXT)]),
    ("stoppage_causes", [("name", "name", TEXT), ("category", "category", TEXT), ("planned", "planned", BOOL), ("changeover", "changeover", BOOL),
                         ("status", "status", TEXT)]),
    ("scrap_reasons", [("name", "name", TEXT), ("category", "category", TEXT), ("status", "status", TEXT)]),
    ("machines", [("name", "name", TEXT), ("alias", "alias", TEXT), ("machine_type", "typeId", link("machine_types")),
                  ("attached_to", "attachedToId", link("machines")), ("floor_number", "floor", NUM), ("serial", "serial", TEXT),
                  ("euromap", "euromap", TEXT), ("year", "year", TEXT), ("changeover_min", "changeoverMin", NUM),
                  ("location", "location", TEXT), ("status", "status", TEXT), ("notes", "notes", TEXT)]),
    ("personnel", [("name", "name", TEXT), ("role", "roleId", link("person_roles")), ("status", "status", TEXT), ("qualified_machines", "machineIds", links("machines"))]),
    ("items", [("name", "name", TEXT), ("item_type", "type", TEXT), ("category", "categoryId", link("item_categories")),
               ("unit", "uomId", link("units")), ("erp_code", "erpCode", TEXT), ("approved_machines", "approvedMachineIds", links("machines")),
               ("supplier", "supplier", TEXT), ("properties", "properties", JSON), ("status", "status", TEXT), ("notes", "notes", TEXT),
               ("parent", "parentId", link("items"))]),
    ("molds", [("name", "name", TEXT), ("cavities", "cavities", NUM), ("shot_weight_g", "shotWeight", NUM),
               ("location", "location", TEXT), ("status", "status", TEXT), ("notes", "notes", TEXT)]),
    ("recipes", [("item", "itemId", link("items")), ("mold", "moldId", link("molds")), ("machine", "machineId", link("machines")),
                 ("status", "status", TEXT), ("standard", "standard", BOOL), ("cycle_s", "cycle", NUM),
                 ("settings_note", "settingsNote", TEXT), ("comment", "comment", TEXT)]),
    ("production_orders", [("item", "itemId", link("items")), ("quantity", "quantity", NUM), ("due_date", "dueDate", DATE),
                           ("status", "status", TEXT), ("erp_order_no", "erpOrderNo", TEXT), ("notes", "notes", TEXT)]),
    ("production_runs", [("order", "orderId", link("production_orders")), ("recipe", "recipeId", link("recipes")),
                         ("shift", "shiftId", link("shifts")), ("operator", "operatorId", link("personnel")),
                         ("started_at", "startedAt", MOMENT), ("ended_at", "endedAt", MOMENT), ("good_qty", "good", NUM),
                         ("cavities_running", "cavities", NUM), ("cycle_s", "cycle", NUM), ("status", "status", TEXT),
                         ("notes", "notes", TEXT)]),
    ("lots", [("number", "number", TEXT), ("item", "itemId", link("items")), ("origin", "origin", TEXT),
              ("run", "runId", link("production_runs")), ("supplier_lot", "supplierLot", TEXT), ("received_at", "receivedAt", MOMENT),
              ("quantity", "quantity", NUM), ("status", "status", TEXT), ("notes", "notes", TEXT)]),
    ("stoppages", [("machine", "machineId", link("machines")), ("run", "runId", link("production_runs")),
                   ("started_at", "startedAt", MOMENT), ("ended_at", "endedAt", MOMENT), ("cause", "causeId", link("stoppage_causes")),
                   ("description", "description", TEXT), ("fix", "fix", TEXT), ("reported_by", "reportedById", link("personnel"))]),
    ("changeovers", [("machine", "machineId", link("machines")), ("from_run", "fromRunId", link("production_runs")),
                     ("to_run", "toRunId", link("production_runs")), ("from_item", "fromItemId", link("items")), ("to_item", "toItemId", link("items")),
                     ("kind", "kind", TEXT), ("started_at", "startedAt", MOMENT), ("ended_at", "endedAt", MOMENT), ("lost_h", "lostHours", NUM),
                     ("source", "source", TEXT), ("confidence", "confidence", TEXT), ("stoppage", "stoppageId", link("stoppages")),
                     ("basis", "basis", TEXT), ("notes", "notes", TEXT)]),
)
COLUMNS = dict(TABLES)
ORDER = tuple(name for name, _ in TABLES)
LATE = {"machines": ("attached_to",), "items": ("parent",)}

CHILDREN = (
    ("recipe_inputs", "recipes", "recipe", "inputs", [("item", "itemId", link("items")), ("share_pct", "share", NUM)]),
    ("run_scrap", "production_runs", "run", "scrap", [("reason", "reasonId", link("scrap_reasons")), ("quantity", "quantity", NUM)]),
    ("run_inputs", "production_runs", "run", "inputs", [("lot", "lotId", link("lots")), ("quantity", "quantity", NUM)]),
    ("item_attributes", "items", "item", "attributes", [("attribute", "attributeId", link("variant_attributes")), ("value", "value", TEXT)]),
)
CHILDREN_OF = {}
for _child in CHILDREN:
    CHILDREN_OF.setdefault(_child[1], []).append(_child)

TEMP_LABELS = (("nozzle", "Nozzle"), ("t6", "T6"), ("t5", "T5"), ("t4", "T4"), ("t3", "T3"), ("t2", "T2"), ("t1", "T1"))
RECIPE_INJECTION_FIELDS = (("cooling", "Cooling time (s)"), ("screwRpm", "Screw speed (rpm)"))
RECIPE_EXTRA_FIELDS = (("px", "ΠΧ"), ("py", "ΠΥ"), ("printPieces", "ΤΕΜ εκτύπωση"), ("printTotal", "TOT εκτύπωσης"))
RECIPE_FIELD_SETTINGS = tuple(label for _, label in RECIPE_INJECTION_FIELDS) + ("Cycle time (s)",)


def _text(value):
    return str(value if value is not None else "").strip()


def number(value):
    """A number from a cell or a typed box ("5,5" reads as 5.5), as an int when whole; None when empty or not a number."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number_value = float(value)
    else:
        try:
            number_value = float(str(value).strip().replace(",", "."))
        except ValueError:
            return None
    return int(number_value) if number_value.is_integer() else number_value


def number_text(value):
    value = number(value)
    if value is None:
        return ""
    return str(value) if isinstance(value, int) else ("%s" % value).rstrip("0").rstrip(".")


def parse_moment(text):
    """An ISO UTC moment as an aware datetime, or None."""
    text = _text(text)
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def moment_text(value):
    if not isinstance(value, datetime.datetime):
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_in(text):
    try:
        return datetime.datetime.strptime(_text(text)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_out(value):
    return value.isoformat() if isinstance(value, datetime.date) else ""


def _write(kind, value, ref):
    if kind == TEXT:
        return _text(value)
    if kind == NUM:
        return number(value)
    if kind == BOOL:
        return bool(value)
    if kind == DATE:
        return _date_in(value)
    if kind == MOMENT:
        return parse_moment(value)
    if kind == JSON:
        return dict(value or {}) or None
    if kind[0] == "link":
        return ref(kind[1], value) if value else None
    found = [ref(kind[1], code) for code in value or [] if code]
    return [row for row in found if row is not None]


def _read(kind, value, code_of):
    if kind == TEXT:
        return _text(value)
    if kind == NUM:
        return number(value)
    if kind == BOOL:
        return bool(value)
    if kind == DATE:
        return _date_out(value)
    if kind == MOMENT:
        return moment_text(value)
    if kind == JSON:
        return dict(value or {})
    if kind[0] == "link":
        return code_of(kind[1], value) if value is not None else ""
    return [code for code in (code_of(kind[1], linked) for linked in value or []) if code]


read_value = _read


def to_row(table, item, ref, skip=()):
    """The columns of ``table`` for ``item``; ``ref(table, code)`` resolves links, and columns in ``skip`` are left out."""
    columns = {"code": item["id"]}
    for column, key, kind in COLUMNS[table]:
        if column not in skip:
            columns[column] = _write(kind, item.get(key), ref)
    if table == "recipes":
        columns.update(_recipe_settings_row(item))
    return columns


def late_row(table, item, ref):
    keys = {column: (key, kind) for column, key, kind in COLUMNS[table]}
    return {column: _write(keys[column][1], item.get(keys[column][0]), ref) for column in LATE.get(table, ())}


def to_item(table, row, code_of):
    """The record for a row (or a dict with the same columns); ``code_of(table, linked_row)`` names a linked row."""
    item = {"id": row["code"]}
    for column, key, kind in COLUMNS[table]:
        item[key] = _read(kind, row[column], code_of)
    if table == "recipes":
        item.update(_recipe_settings_item(row))
    for child, _, _, list_key, _ in CHILDREN_OF.get(table, ()):
        item[list_key] = []
    return item


def child_rows(child, item, parent_row, ref):
    """The rows of line table ``child`` for ``item``."""
    _, _, parent_column, list_key, columns = next(spec for spec in CHILDREN if spec[0] == child)
    rows = []
    for entry in item.get(list_key) or []:
        row = {parent_column: parent_row}
        for column, key, kind in columns:
            row[column] = _write(kind, entry.get(key), ref)
        rows.append(row)
    return rows


def child_item(child, row, code_of):
    _, _, _, _, columns = next(spec for spec in CHILDREN if spec[0] == child)
    return {key: _read(kind, row[column], code_of) for column, key, kind in columns}


# Recipe machine settings --------------------------------------------------------------------

def _setting_in(text):
    value = number(text)
    return value if value is not None and number_text(value) == text else text


def _settings_in(settings):
    """The machine's parameters in the order written, as [{label, value}]; None when none are set."""
    kept = []
    for setting in settings or []:
        label, value = _text(setting.get("label")), _text(setting.get("value"))
        if label and value:
            kept.append({"label": label, "value": _setting_in(value)})
    return kept or None


def _setting_out(value):
    return number_text(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else _text(value)


def _recipe_settings_row(item):
    temps = item.get("temps") or {}
    injection = [setting for setting in item.get("settings") or [] if _text(setting.get("label")) not in RECIPE_FIELD_SETTINGS]
    injection += [{"label": label, "value": item.get(key)} for key, label in RECIPE_INJECTION_FIELDS]
    return {
        "temps": _settings_in({"label": label, "value": temps.get(key)} for key, label in TEMP_LABELS),
        "injection": _settings_in(injection),
        "extra": _settings_in({"label": label, "value": item.get(key)} for key, label in RECIPE_EXTRA_FIELDS),
    }


def _recipe_settings_item(row):
    temps = {setting["label"]: _setting_out(setting["value"]) for setting in row["temps"] or []}
    injection = [{"label": setting["label"], "value": _setting_out(setting["value"])} for setting in row["injection"] or []]
    extra = {setting["label"]: _setting_out(setting["value"]) for setting in row["extra"] or []}
    item = {"temps": {key: temps.get(label, "") for key, label in TEMP_LABELS}}
    by_label = {setting["label"]: setting["value"] for setting in injection}
    for key, label in RECIPE_INJECTION_FIELDS:
        item[key] = by_label.get(label, "")
    item["settings"] = [setting for setting in injection if setting["label"] not in RECIPE_FIELD_SETTINGS]
    for key, label in RECIPE_EXTRA_FIELDS:
        item[key] = extra.get(label, "")
    return item
