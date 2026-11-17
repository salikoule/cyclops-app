"""Plant rules and page data, on the plant graph the loader builds.

The graph holds one list per table, keyed by the table's name, each record a dict with its
code as ``id`` and its links as codes (see ``records``). A page's graph holds only what that
page reads; ``graph["codes"]`` lists every stored code of a table an edit may add to.

Times are ISO UTC moments (``2026-05-25T19:00:00Z``). The browser shows them in local time
and sends local entries back as UTC, so nothing here depends on a time zone.
"""

import copy
import datetime
import re
import unicodedata

import records

ITEM_TYPES = (("RAW", "Raw material"), ("PAK", "Packaging"), ("SFG", "Semi-finished"), ("FG", "Finished good"), ("TRD", "Trading good"))
TYPE_LABEL = dict(ITEM_TYPES)
ROLES = (("base", "Base material (resin, regrind)"), ("colorant", "Colorant (masterbatch)"), ("additive", "Additive"), ("", "None"))
ROLE_LABEL = {"base": "Base", "colorant": "Colorant", "additive": "Additive", "": ""}
STATUSES = ("active", "retired")
RECIPE_STATUSES = ("trial", "approved", "retired")
MOLD_STATUSES = ("in use", "in repair", "stored", "retired")
ORDER_STATUSES = ("planned", "released", "in progress", "done", "cancelled")
OPEN_ORDERS = ("planned", "released", "in progress")
LOT_STATUSES = ("released", "quarantined", "blocked")
FISHBONE = ("Man", "Machine", "Method", "Material", "Measurement", "Environment")
CHANGEOVER_KINDS = (("mold", "Mold change"), ("color", "Color change"), ("material", "Material change"),
                    ("other", "Same mold, other item"), ("unknown", "Mold not recorded"))
CHANGEOVER_SOURCES = (("stop", "Logged stop"), ("derived", "Derived from output"), ("entered", "Entered by hand"))
TEMP_LABELS = records.TEMP_LABELS
TEMP_KEYS = tuple(key for key, _ in TEMP_LABELS)
SETTING_LABELS = (
    "Injection speed u1", "Switch position 1→2", "Injection speed u2", "Switch position 2→3", "Injection speed u3",
    "Injection pressure max P1", "Position 1→2", "Injection pressure max P2",
    "Hold switch position", "Hold pressure", "Hold time (s)", "Hold speed",
    "Dosing stroke", "Decompression after dosing", "Back pressure P1",
)
SETTING_PREFIX = "setting::"
STATUS_TONE = {
    "Active": "ok", "Running": "ok", "Done": "ok", "Closed": "ok", "Released": "ok", "Standard": "std", "Approved": "ok",
    "Incomplete": "warn", "No code": "warn", "Open": "warn", "Trial": "warn", "Trial only": "warn", "No recipe": "warn",
    "Planned": "muted", "In progress": "ok", "Quarantined": "warn", "Stopped": "warn", "Idle": "muted",
    "Cannot produce": "bad", "Check dates": "bad", "No stop time": "bad", "Blocked": "bad",
}
PREFIX = {
    "items": ("ITM", 5), "molds": ("MLD", 4), "machines": ("MCH", 2), "recipes": ("REC", 4), "production_orders": ("PO", 5),
    "production_runs": ("RUN", 5), "lots": ("LOT", 6), "stoppages": ("STP", 5), "item_categories": ("CAT", 2),
    "machine_types": ("MTY", 2), "shifts": ("SHF", 2), "stoppage_causes": ("CAU", 2), "scrap_reasons": ("SCR", 2), "personnel": ("PER", 3),
    "person_roles": ("ROL", 2), "units": ("UNT", 2), "changeovers": ("CHG", 5), "variant_attributes": ("VAT", 2),
}
SETTING_TABLES = {
    "shift": "shifts", "cause": "stoppage_causes", "reason": "scrap_reasons", "category": "item_categories",
    "machineType": "machine_types", "person": "personnel", "role": "person_roles", "unit": "units",
    "attribute": "variant_attributes",
}
CREATES = {
    "new-item": ("items",), "clone-item": ("items", "recipes"), "new-mold": ("molds",), "new-machine": ("machines",),
    "add-recipe": ("recipes", "molds"), "clone-recipe": ("recipes",), "new-order": ("production_orders",),
    "add-run": ("production_runs",), "log-shift": ("production_runs",), "add-output-lot": ("lots",), "receive-lot": ("lots",),
    "add-stoppage": ("stoppages",), "save-setting": tuple(SETTING_TABLES.values()),
}
WHOLE_ACTIONS = {"new-item": ("items",), "edit-item": ("items",), "clone-item": ("items",)}
LOT_NUMBER_ACTIONS = ("receive-lot", "add-output-lot", "edit-lot")
KIND_TABLE = {
    "item": "items", "mold": "molds", "machine": "machines", "recipe": "recipes", "order": "production_orders",
    "run": "production_runs", "lot": "lots", "stoppage": "stoppages",
}
TABLE_KIND = {table: kind for kind, table in KIND_TABLE.items()}


# Values -------------------------------------------------------------------------------------

num = records.number
trim_num = records.number_text


def text(value):
    return str(value if value is not None else "").strip()


def uniq(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def group_by(entries, key):
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.get(key), []).append(entry)
    return grouped


def cap(value):
    value = value or ""
    return value[:1].upper() + value[1:]


def tone(status):
    return STATUS_TONE.get(status or "", "muted")


def plural(count, one, many=None):
    return "%s %s" % (count, one if count == 1 else (many or one + "s"))


def next_code(prefix, codes, width):
    highest = 0
    for code in codes:
        try:
            highest = max(highest, int(str(code).split("-")[-1]))
        except ValueError:
            continue
    return "%s-%s" % (prefix, str(highest + 1).zfill(width))


def new_code(graph, table):
    """The next free code of ``table``; ``graph["codes"]`` holds every stored code when only part of the plant is loaded."""
    prefix, width = PREFIX[table]
    known = [entry["id"] for entry in graph.get(table) or []] + list((graph.get("codes") or {}).get(table) or [])
    return next_code(prefix, known, width)


def span_hours(start, end):
    """Hours from ``start`` to ``end`` (ISO moments), or None when either is missing or they run backwards."""
    begin, finish = records.parse_moment(start), records.parse_moment(end)
    if begin is None or finish is None or finish < begin:
        return None
    return round((finish - begin).total_seconds() / 3600.0, 2)


def _overlap(start, end, spans):
    begin, finish = records.parse_moment(start), records.parse_moment(end)
    total = 0.0
    if begin is None or finish is None:
        return total
    for stop, restart in spans:
        low, high = max(begin, records.parse_moment(stop)), min(finish, records.parse_moment(restart))
        if high > low:
            total += (high - low).total_seconds() / 3600.0
    return total


_DEFAULTS = {
    "item_categories": {"name": "", "type": "RAW", "role": ""},
    "machine_types": {"name": ""},
    "shifts": {"name": "", "start": "", "end": "", "status": "active"},
    "stoppage_causes": {"name": "", "category": "Machine", "planned": False, "changeover": False, "status": "active"},
    "scrap_reasons": {"name": "", "category": "Method", "status": "active"},
    "machines": {"name": "", "alias": "", "typeId": "", "attachedToId": "", "floor": None, "serial": "", "euromap": "", "year": "",
                 "changeoverMin": None, "location": "", "status": "active", "notes": ""},
    "personnel": {"name": "", "roleId": "", "status": "active", "machineIds": []},
    "person_roles": {"name": "", "runsMachines": False, "status": "active"},
    "units": {"name": "", "status": "active"},
    "variant_attributes": {"name": "", "status": "active"},
    "items": {"name": "", "type": "SFG", "categoryId": "", "uomId": "", "erpCode": "", "approvedMachineIds": [], "supplier": "",
              "properties": {}, "status": "active", "notes": "", "parentId": "", "attributes": []},
    "molds": {"name": "", "cavities": None, "shotWeight": None, "location": "", "status": "in use", "notes": ""},
    "recipes": {"itemId": "", "moldId": "", "machineId": "", "status": "approved", "standard": False, "cycle": None,
                "cooling": "", "screwRpm": "", "temps": {}, "settings": [], "px": "", "py": "", "printPieces": "", "printTotal": "",
                "settingsNote": "", "comment": "", "inputs": []},
    "production_orders": {"itemId": "", "quantity": None, "dueDate": "", "status": "planned", "erpOrderNo": "", "notes": ""},
    "production_runs": {"orderId": "", "recipeId": "", "shiftId": "", "operatorId": "", "startedAt": "", "endedAt": "", "good": None,
                        "cavities": None, "cycle": None, "status": "running", "notes": "", "scrap": [], "inputs": []},
    "lots": {"number": "", "itemId": "", "origin": "received", "runId": "", "supplierLot": "", "receivedAt": "", "quantity": None,
             "status": "released", "notes": ""},
    "stoppages": {"machineId": "", "runId": "", "startedAt": "", "endedAt": "", "causeId": "", "description": "", "fix": "", "reportedById": ""},
    "changeovers": {"machineId": "", "fromRunId": "", "toRunId": "", "fromItemId": "", "toItemId": "", "kind": "unknown", "startedAt": "",
                    "endedAt": "", "lostHours": None, "source": "entered", "confidence": "", "stoppageId": "", "basis": "", "notes": ""},
}


def normalize(graph):
    """Fill every field a record may lack, as an imported or hand-written graph can."""
    for table, defaults in _DEFAULTS.items():
        for entry in graph.get(table) or []:
            for key, value in defaults.items():
                if entry.get(key) is None and value is not None:
                    entry[key] = copy.deepcopy(value)
                elif key not in entry:
                    entry[key] = None
        graph.setdefault(table, [])
    for recipe in graph["recipes"]:
        recipe["temps"] = {key: text((recipe.get("temps") or {}).get(key)) for key in TEMP_KEYS}
        recipe["cycle"] = num(recipe.get("cycle"))
    return graph


# Index ------------------------------------------------------------------------------------------

def reindex(graph):
    index = {table: {entry["id"]: entry for entry in graph.get(table) or []} for table in records.ORDER}
    recipes = graph.get("recipes") or []
    runs = graph.get("production_runs") or []
    index.update({
        "recipesByItem": group_by(recipes, "itemId"),
        "recipesByMold": group_by(recipes, "moldId"),
        "recipesByMachine": group_by(recipes, "machineId"),
        "recipesUsing": {},
        "runsByRecipe": group_by(runs, "recipeId"),
        "runsByOrder": group_by(runs, "orderId"),
        "stoppagesByRun": group_by(graph.get("stoppages") or [], "runId"),
        "stoppagesByMachine": group_by(graph.get("stoppages") or [], "machineId"),
        "lotsByItem": group_by(graph.get("lots") or [], "itemId"),
        "lotsByRun": group_by(graph.get("lots") or [], "runId"),
        "ordersByItem": group_by(graph.get("production_orders") or [], "itemId"),
        "itemsByParent": group_by(graph.get("items") or [], "parentId"),
        "attached": group_by(graph.get("machines") or [], "attachedToId"),
        "consumers": {},
        "changeoversByMachine": group_by(graph.get("changeovers") or [], "machineId"),
        "changeoversByToRun": group_by(graph.get("changeovers") or [], "toRunId"),
        "changeoversByFromRun": group_by(graph.get("changeovers") or [], "fromRunId"),
    })
    for recipe in recipes:
        for entry in recipe.get("inputs") or []:
            index["recipesUsing"].setdefault(entry.get("itemId"), []).append(recipe)
    for run in runs:
        for entry in run.get("inputs") or []:
            index["consumers"].setdefault(entry.get("lotId"), []).append((run, entry))
    graph["_ix"] = index
    return index


def _ix(graph):
    if "_ix" not in graph:
        reindex(graph)
    return graph["_ix"]


def name_of(index, table, code):
    entry = index[table].get(code)
    if entry is None:
        return code or ""
    if table == "lots":
        return entry.get("number") or code
    return entry.get("name") or code


def role_of(index, item_code):
    item = index["items"].get(item_code) or {}
    return (index["item_categories"].get(item.get("categoryId")) or {}).get("role") or ""


def unit_of(index, item_code):
    item = index["items"].get(item_code) or {}
    return name_of(index, "units", item["uomId"]) if item.get("uomId") else ""


def can_operate(index, person):
    """A role that runs machines. A person whose role is not set yet is still offered, so an imported list stays usable."""
    role = index["person_roles"].get(person.get("roleId"))
    return role is None or bool(role.get("runsMachines"))


def category_name(index, item):
    return (index["item_categories"].get(item.get("categoryId")) or {}).get("name") or ""


def machine_of_run(index, run):
    return (index["recipes"].get(run.get("recipeId")) or {}).get("machineId") or ""


def item_of_run(index, run):
    return (index["recipes"].get(run.get("recipeId")) or {}).get("itemId") or ""


# Recipes ----------------------------------------------------------------------------------------

def live(recipes):
    return [recipe for recipe in recipes or [] if recipe.get("status") == "approved"]


def inputs_with_role(index, recipe, role):
    return [entry["itemId"] for entry in recipe.get("inputs") or [] if role_of(index, entry.get("itemId")) == role]


def colorants(index, recipe):
    return inputs_with_role(index, recipe, "colorant")


def materials(index, recipe):
    return [entry["itemId"] for entry in recipe.get("inputs") or [] if role_of(index, entry.get("itemId")) != "colorant"]


def has_base(index, recipe):
    return bool(inputs_with_role(index, recipe, "base"))


def variant_key(index, recipe):
    return "|".join(sorted(colorants(index, recipe)))


def color_label(index, code):
    item = index["items"].get(code) or {}
    properties = item.get("properties") or {}
    return properties.get("colorName") or properties.get("labelCode") or item.get("name") or code


def variant_label(index, recipe):
    found = colorants(index, recipe)
    return " + ".join(color_label(index, code) for code in found) if found else "natural / no color"


def temps_count(recipe):
    return sum(1 for key in TEMP_KEYS if num((recipe.get("temps") or {}).get(key)) is not None)


def pieces_per_hour(index, recipe):
    mold = index["molds"].get(recipe.get("moldId")) or {}
    cycle = num(recipe.get("cycle"))
    if not mold.get("cavities") or not cycle:
        return None
    return int(round(3600.0 / cycle * float(mold["cavities"])))


def best_cycle(recipes):
    cycles = [cycle for cycle in (num(recipe.get("cycle")) for recipe in recipes) if cycle is not None]
    return min(cycles) if cycles else None


RECIPE_SHOWN = ("Active", "Cannot produce", "Incomplete", "Retired", "Standard", "Trial")


def recipe_status(graph, recipe):
    index = _ix(graph)
    if recipe.get("status") == "retired":
        return "Retired"
    if recipe.get("status") == "trial":
        return "Trial"
    if not has_base(index, recipe):
        return "Cannot produce"
    if not num(recipe.get("cycle")) or temps_count(recipe) < 3:
        return "Incomplete"
    if recipe.get("standard"):
        return "Standard"
    return "Active"


def missing_share(recipe):
    return any(entry.get("share") is None for entry in recipe.get("inputs") or [])


def injection_settings(recipe):
    """The standard injection block, filled or blank, then any other label this recipe carries."""
    values, extras = {}, []
    for entry in recipe.get("settings") or []:
        label = text(entry.get("label"))
        if not label or label in records.RECIPE_FIELD_SETTINGS or label in values:
            continue
        values[label] = entry.get("value") or ""
        if label not in SETTING_LABELS:
            extras.append(label)
    return [{"label": label, "value": values.get(label, "")} for label in SETTING_LABELS + tuple(extras)]


# Statuses ---------------------------------------------------------------------------------------

ITEM_SHOWN = ("Active", "Cannot produce", "Incomplete", "No code", "No recipe", "Retired", "Trial only", "Unused")


def item_status(graph, item):
    index = _ix(graph)
    if item.get("status") == "retired":
        return "Retired"
    if item.get("type") == "RAW":
        if not live(index["recipesUsing"].get(item["id"]) or []):
            return "Unused"
        if not item.get("erpCode"):
            return "No code"
        return "Active"
    if item.get("type") != "SFG":
        return "Active"
    every = index["recipesByItem"].get(item["id"]) or []
    running = live(every)
    if not every:
        return "No recipe"
    if not running:
        return "Trial only"
    statuses = [recipe_status(graph, recipe) for recipe in running]
    if all(status == "Cannot produce" for status in statuses):
        return "Cannot produce"
    if any(status in ("Cannot produce", "Incomplete") for status in statuses):
        return "Incomplete"
    return "Active"


MOLD_SHOWN = ("Active", "In repair", "Incomplete", "Retired", "Stored", "Unused")


def mold_status(graph, mold):
    if mold.get("status") and mold.get("status") != "in use":
        return cap(mold.get("status"))
    if not live(_ix(graph)["recipesByMold"].get(mold["id"]) or []):
        return "Unused"
    if not mold.get("cavities"):
        return "Incomplete"
    return "Active"


def open_run(graph, machine_code):
    """The run in progress on a machine: the latest one without an end."""
    index = _ix(graph)
    running = [run for recipe in index["recipesByMachine"].get(machine_code) or [] for run in index["runsByRecipe"].get(recipe["id"]) or []
               if run.get("startedAt") and not run.get("endedAt")]
    return max(running, key=lambda run: run["startedAt"]) if running else None


def open_stoppage(graph, machine_code):
    found = [stop for stop in _ix(graph)["stoppagesByMachine"].get(machine_code) or [] if stop.get("startedAt") and not stop.get("endedAt")]
    return max(found, key=lambda stop: stop["startedAt"]) if found else None


MACHINE_SHOWN = ("Attached", "Idle", "No recipes", "Retired", "Running")


def machine_status(graph, machine):
    index = _ix(graph)
    if machine.get("status") == "retired":
        return "Retired"
    if open_run(graph, machine["id"]):
        return "Running"
    if machine.get("attachedToId"):
        return "Attached"
    if not live(index["recipesByMachine"].get(machine["id"]) or []):
        return "No recipes"
    return "Idle"


def stoppage_state(stop):
    if not stop.get("startedAt"):
        return "no stop time"
    if not stop.get("endedAt"):
        return "open"
    if span_hours(stop.get("startedAt"), stop.get("endedAt")) is None:
        return "check dates"
    return "closed"


def run_state(run):
    if not run.get("endedAt"):
        return "running"
    if span_hours(run.get("startedAt"), run.get("endedAt")) is None:
        return "check dates"
    return "done"


def run_metrics(graph, run):
    index = _ix(graph)
    recipe = index["recipes"].get(run.get("recipeId")) or {}
    mold = index["molds"].get(recipe.get("moldId")) or {}
    hours = span_hours(run.get("startedAt"), run.get("endedAt"))
    spans = [(stop["startedAt"], stop["endedAt"]) for stop in index["stoppagesByRun"].get(run["id"]) or [] if stoppage_state(stop) == "closed"]
    down = _overlap(run.get("startedAt"), run.get("endedAt"), spans) if hours else 0.0
    good = num(run.get("good"))
    scrap = sum(num(entry.get("quantity")) or 0 for entry in run.get("scrap") or [])
    made = (good or 0) + scrap if good is not None else None
    running = hours - down if hours else None
    rate = made / running if made and running and running > 0 else None
    cycle = num(run.get("cycle")) or num(recipe.get("cycle"))
    cavities = num(run.get("cavities")) or num(mold.get("cavities"))
    target = 3600.0 / cycle * cavities if cycle and cavities else None
    return {
        "hours": round(hours, 1) if hours else None,
        "downHours": round(down, 1) if down else None,
        "scrap": scrap,
        "pph": int(round(rate)) if rate else None,
        "target": int(round(target)) if target else None,
        "performance": int(round(100.0 * rate / target)) if rate and target else None,
        "scrapPct": round(100.0 * scrap / made, 1) if made else None,
        "state": run_state(run),
    }


# Rows -------------------------------------------------------------------------------------------

def _status(status):
    return {"status": status, "tone": tone(status)}


def item_row(graph, item):
    index = _ix(graph)
    every = index["recipesByItem"].get(item["id"]) or []
    running = live(every)
    row = {
        "id": item["id"], "name": item.get("name") or "", "type": item.get("type") or "", "typeLabel": TYPE_LABEL.get(item.get("type"), ""),
        "category": category_name(index, item), "uom": unit_of(index, item["id"]), "erp": item.get("erpCode") or "",
        "machines": uniq([name_of(index, "machines", recipe.get("machineId")) for recipe in running]),
        "recipes": len(running), "trial": len([recipe for recipe in every if recipe.get("status") == "trial"]),
        "usedIn": len(live(index["recipesUsing"].get(item["id"]) or [])),
        "colors": uniq([color_label(index, code) for recipe in running for code in colorants(index, recipe)]),
        "supplier": item.get("supplier") or "",
        "parent": name_of(index, "items", item.get("parentId")) if item.get("parentId") else "",
        "parentId": item.get("parentId") or "",
    }
    row.update(_status(item_status(graph, item)))
    return row


def mold_row(graph, mold):
    index = _ix(graph)
    running = live(index["recipesByMold"].get(mold["id"]) or [])
    row = {
        "id": mold["id"], "name": mold.get("name") or "",
        "items": uniq([name_of(index, "items", recipe.get("itemId")) for recipe in running]),
        "machines": uniq([name_of(index, "machines", recipe.get("machineId")) for recipe in running]),
        "recipes": len(running), "cavities": mold.get("cavities"), "shot": mold.get("shotWeight"), "location": mold.get("location") or "",
    }
    row.update(_status(mold_status(graph, mold)))
    return row


def machine_row(graph, machine):
    index = _ix(graph)
    running = live(index["recipesByMachine"].get(machine["id"]) or [])
    current = open_run(graph, machine["id"])
    row = {
        "id": machine["id"], "name": machine.get("name") or "", "type": name_of(index, "machine_types", machine.get("typeId")),
        "attachedTo": name_of(index, "machines", machine.get("attachedToId")) if machine.get("attachedToId") else "",
        "euromap": machine.get("euromap") or "", "molds": len(uniq([recipe.get("moldId") for recipe in running])),
        "recipes": len(running), "changeover": machine.get("changeoverMin"), "location": machine.get("location") or "",
        "current": name_of(index, "items", item_of_run(index, current)) if current else "",
    }
    row.update(_status(machine_status(graph, machine)))
    return row


def recipe_row(graph, recipe):
    index = _ix(graph)
    row = {
        "id": recipe["id"], "item": name_of(index, "items", recipe.get("itemId")), "itemId": recipe.get("itemId") or "",
        "mold": recipe.get("moldId") or "", "machine": name_of(index, "machines", recipe.get("machineId")),
        "machineId": recipe.get("machineId") or "", "variant": variant_label(index, recipe), "cycle": num(recipe.get("cycle")),
        "pph": pieces_per_hour(index, recipe),
        "materials": [name_of(index, "items", code) for code in materials(index, recipe)],
        "colors": [color_label(index, code) for code in colorants(index, recipe)],
        "shares": "missing" if missing_share(recipe) else "set",
    }
    row.update(_status(recipe_status(graph, recipe)))
    return row


def summary_rows(graph, recipes):
    """One row per item made by ``recipes``."""
    index = _ix(graph)
    source = live(recipes) or list(recipes or [])
    rows = []
    for code in uniq([recipe.get("itemId") for recipe in source]):
        listed = [recipe for recipe in source if recipe.get("itemId") == code]
        item = index["items"].get(code)
        status = item_status(graph, item) if item else ""
        rows.append({
            "id": code, "name": name_of(index, "items", code), "molds": uniq([recipe.get("moldId") for recipe in listed]),
            "machines": uniq([name_of(index, "machines", recipe.get("machineId")) for recipe in listed]), "recipes": len(listed),
            "cycle": best_cycle(listed), "colors": uniq([color_label(index, c) for recipe in listed for c in colorants(index, recipe)]),
            "status": status, "tone": tone(status),
        })
    return rows


def order_row(graph, order):
    index = _ix(graph)
    runs = index["runsByOrder"].get(order["id"]) or []
    made = sum(num(run.get("good")) or 0 for run in runs)
    status = cap(order.get("status"))
    return {
        "id": order["id"], "item": name_of(index, "items", order.get("itemId")), "itemId": order.get("itemId") or "",
        "quantity": order.get("quantity"), "made": made, "progress": int(round(100.0 * made / order["quantity"])) if order.get("quantity") else None,
        "due": order.get("dueDate") or "", "erp": order.get("erpOrderNo") or "", "runs": len(runs), "status": status, "tone": tone(status),
    }


def run_row(graph, run):
    index = _ix(graph)
    metrics = run_metrics(graph, run)
    state = metrics["state"]
    row = dict(metrics)
    row.update({
        "id": run["id"], "order": run.get("orderId") or "", "item": name_of(index, "items", item_of_run(index, run)),
        "itemId": item_of_run(index, run), "recipe": run.get("recipeId") or "",
        "machine": name_of(index, "machines", machine_of_run(index, run)), "machineId": machine_of_run(index, run),
        "start": run.get("startedAt") or "", "end": run.get("endedAt") or "", "good": run.get("good"),
        "operator": name_of(index, "personnel", run.get("operatorId")) if run.get("operatorId") else "",
        "shift": name_of(index, "shifts", run.get("shiftId")) if run.get("shiftId") else "",
        "lots": [lot.get("number") for lot in index["lotsByRun"].get(run["id"]) or []],
        "status": cap(state), "tone": {"done": "ok", "check dates": "bad"}.get(state, "warn"),
    })
    return row


def stoppage_row(graph, stop):
    index = _ix(graph)
    run = index["production_runs"].get(stop.get("runId")) or {}
    cause = index["stoppage_causes"].get(stop.get("causeId")) or {}
    state = stoppage_state(stop)
    return {
        "id": stop["id"], "machine": name_of(index, "machines", stop.get("machineId")), "machineId": stop.get("machineId") or "",
        "run": stop.get("runId") or "", "item": name_of(index, "items", item_of_run(index, run)) if run else "",
        "start": stop.get("startedAt") or "", "end": stop.get("endedAt") or "", "hours": span_hours(stop.get("startedAt"), stop.get("endedAt")),
        "cause": cause.get("name") or "", "category": cause.get("category") or "", "planned": bool(cause.get("planned")),
        "description": stop.get("description") or "", "fix": stop.get("fix") or "",
        "reportedBy": name_of(index, "personnel", stop.get("reportedById")) if stop.get("reportedById") else "",
        "causeId": stop.get("causeId") or "", "runId": stop.get("runId") or "", "reportedById": stop.get("reportedById") or "",
        "startedAt": stop.get("startedAt") or "", "endedAt": stop.get("endedAt") or "",
        "state": state, "status": cap(state), "tone": {"closed": "ok", "open": "warn"}.get(state, "bad"),
    }


CHANGEOVER_KIND_LABEL = dict(CHANGEOVER_KINDS)
CHANGEOVER_SOURCE_LABEL = dict(CHANGEOVER_SOURCES)


def changeover_row(graph, change):
    index = _ix(graph)
    confidence = change.get("confidence") or ""
    return {
        "id": change["id"], "machine": name_of(index, "machines", change.get("machineId")), "machineId": change.get("machineId") or "",
        "from": name_of(index, "items", change.get("fromItemId")), "to": name_of(index, "items", change.get("toItemId")),
        "fromItemId": change.get("fromItemId") or "", "toItemId": change.get("toItemId") or "",
        "fromRun": change.get("fromRunId") or "", "toRun": change.get("toRunId") or "",
        "kind": CHANGEOVER_KIND_LABEL.get(change.get("kind"), cap(change.get("kind"))), "kindKey": change.get("kind") or "",
        "start": change.get("startedAt") or "", "end": change.get("endedAt") or "", "hours": num(change.get("lostHours")),
        "source": CHANGEOVER_SOURCE_LABEL.get(change.get("source"), cap(change.get("source"))), "stoppage": change.get("stoppageId") or "",
        "basis": change.get("basis") or "", "notes": change.get("notes") or "",
        "status": cap(confidence), "tone": {"high": "ok", "medium": "muted", "low": "warn"}.get(confidence, "muted"),
    }


def changeover_rows(graph, changes):
    return sorted((changeover_row(graph, change) for change in changes), key=lambda row: row["start"], reverse=True)


def lot_row(graph, lot):
    index = _ix(graph)
    status = cap(lot.get("status"))
    return {
        "id": lot["id"], "number": lot.get("number") or "", "item": name_of(index, "items", lot.get("itemId")), "itemId": lot.get("itemId") or "",
        "origin": cap(lot.get("origin")), "run": lot.get("runId") or "", "quantity": lot.get("quantity"),
        "uom": unit_of(index, lot.get("itemId")), "received": lot.get("receivedAt") or "",
        "supplierLot": lot.get("supplierLot") or "", "used": len(index["consumers"].get(lot["id"]) or []),
        "status": status, "tone": tone(status),
    }


def _newest(rows):
    return sorted(rows, key=lambda row: row.get("start") or "", reverse=True)


def stoppage_rows(graph, stops):
    return _newest([stoppage_row(graph, stop) for stop in stops])


def run_rows(graph, runs):
    return _newest([run_row(graph, run) for run in runs])


# Gaps -------------------------------------------------------------------------------------------

def gaps(graph):
    index = _ix(graph)
    items = graph.get("items") or []
    parts = [item for item in items if item.get("type") == "SFG" and item.get("status") != "retired"]
    raws = [item for item in items if item.get("type") == "RAW" and item.get("status") != "retired"]
    every = graph.get("recipes") or []
    running = live(every)
    presses = [machine for machine in graph.get("machines") or [] if not machine.get("attachedToId") and machine.get("status") != "retired"]
    duplicates = []
    for group in group_by([dict(recipe, _key="%s|%s|%s" % (recipe.get("itemId"), recipe.get("machineId"), variant_key(index, recipe)))
                           for recipe in running], "_key").values():
        if len(group) > 1 and not any(recipe.get("standard") for recipe in group):
            duplicates.extend(recipe["id"] for recipe in group)
    stops = graph.get("stoppages") or []
    entries = (
        ("no-erp", "item", ("manager", "planner"), "Semi-finished items without an ERP code",
         "Orders and stock can be matched to an item and its recipes. Until then the system cannot answer what is owed and whether it can be made.",
         [item["id"] for item in parts if not item.get("erpCode")]),
        ("no-recipe", "item", ("engineer", "planner"), "Semi-finished items with no recipe",
         "Each item either gets a mold and a recipe or is retired. The setter can then start any item from the record.",
         [item["id"] for item in parts if not live(index["recipesByItem"].get(item["id"]) or [])]),
        ("no-cavities", "mold", ("planner", "manager"), "Molds without a cavity count",
         "Pieces per hour per machine. It is the base of every schedule. Enter cavities on a mold and the number appears on all its recipes.",
         [mold["id"] for mold in graph.get("molds") or [] if not mold.get("cavities")]),
        ("no-shot", "mold", ("manager",), "Molds without a shot weight",
         "Material consumed per piece, so a run can be costed and resin ordered against a plan.",
         [mold["id"] for mold in graph.get("molds") or [] if not mold.get("shotWeight")]),
        ("no-share", "recipe", ("engineer", "manager"), "Recipes whose inputs have no share of the shot",
         "With the share of each resin, masterbatch, and additive, the kilograms needed for an order are a calculation.",
         [recipe["id"] for recipe in running if missing_share(recipe)]),
        ("no-cycle", "recipe", ("planner",), "Recipes without a cycle time", "Hours per order can be computed for these items.",
         [recipe["id"] for recipe in running if not num(recipe.get("cycle"))]),
        ("no-mold", "recipe", ("engineer", "planner"), "Recipes without a mold",
         "With the mold set, a mold change, which takes hours, can be told from a color change on the same mold, which takes far less. "
         "Changeover times and the order of jobs on a machine are planned from it.",
         [recipe["id"] for recipe in running if not recipe.get("moldId")]),
        ("dup-standard", "recipe", ("engineer",), "Same color on the same machine, more than one recipe, none marked standard",
         "The setter gets one answer instead of choosing between rows. Mark one recipe as standard on its page.", duplicates),
        ("trial", "recipe", ("engineer",), "Recipes still in trial (sheet rows 2–16)",
         "Approve or retire them. Temperatures there step by 10 °C; they distort which machines an item can run on.",
         [recipe["id"] for recipe in every if recipe.get("status") == "trial"]),
        ("no-base", "recipe", ("engineer",), "Recipes with no base material (colorants or additives only)",
         "Nothing can be produced from these records. The base material has to be written before the setter can start the job.",
         [recipe["id"] for recipe in running if not has_base(index, recipe)]),
        ("no-changeover", "machine", ("planner",), "Machines without a changeover time",
         "Mold and color changes can be sequenced with real durations. Without it a schedule is a wish list.",
         [machine["id"] for machine in presses if not machine.get("changeoverMin")]),
        ("machine-no-recipe", "machine", ("planner",), "Machines with no recipe at all",
         "Either the machine is retired from planning or what it can run is recorded.",
         [machine["id"] for machine in presses if not (index["recipesByMachine"].get(machine["id"]) or [])]),
        ("approved-no-recipe", "item", ("planner", "engineer"), "Approved on a machine, but no recipe there",
         "Every machine a planner may book has a setting sheet, so a job can move without a trial run.",
         [item["id"] for item in parts if approved_without_recipe(graph, item)]),
        ("raw-no-code", "item", ("manager",), "Raw materials without an ERP code",
         "Purchasing and stock reconcile with what production actually feeds.",
         [item["id"] for item in raws if not item.get("erpCode")]),
        ("raw-unused", "item", ("manager",), "Raw materials never used on a recipe",
         "The stock list matches what production uses; the rest is questioned.",
         [item["id"] for item in raws if not (index["recipesUsing"].get(item["id"]) or [])]),
        ("stop-open", "stoppage", ("engineer", "manager"), "Stoppages with no restart time",
         "Close them with the restart time, so downtime per machine and mold can be totalled.",
         [stop["id"] for stop in stops if stoppage_state(stop) == "open"]),
        ("stop-bad", "stoppage", ("engineer",), "Stoppages with no stop time, or a restart before the stop",
         "As written in the Issues sheet. Correct the times so the downtime is real.",
         [stop["id"] for stop in stops if stoppage_state(stop) in ("no stop time", "check dates")]),
        ("stop-no-cause", "stoppage", ("engineer", "manager"), "Stoppages without a cause from the list",
         "With a cause in a fishbone category, repeat faults per machine and mold show up and can be fixed at the root.",
         [stop["id"] for stop in stops if not stop.get("causeId")]),
        ("lot-no-run", "lot", ("manager", "engineer"), "Produced lots not linked to a run",
         "Lots from the workbook were written on recipe rows. A complaint can only be traced to its resin when the lot comes from a logged run.",
         [lot["id"] for lot in graph.get("lots") or [] if lot.get("origin") == "produced" and not lot.get("runId")]),
    )
    return [{"key": key, "kind": kind, "who": list(who), "title": title, "benefit": benefit, "count": len(ids), "ids": ids}
            for key, kind, who, title, benefit, ids in entries]


def approved_without_recipe(graph, item):
    index = _ix(graph)
    running = {recipe.get("machineId") for recipe in live(index["recipesByItem"].get(item["id"]) or [])}
    return [code for code in item.get("approvedMachineIds") or [] if code in index["machines"] and code not in running]


def counts(graph):
    index = _ix(graph)
    items = graph.get("items") or []
    stops = graph.get("stoppages") or []
    return {
        "items": len(items),
        "byType": {key: sum(1 for item in items if item.get("type") == key) for key, _ in ITEM_TYPES},
        "withRecipe": sum(1 for item in items if item.get("type") == "SFG" and live(index["recipesByItem"].get(item["id"]) or [])),
        "molds": len(graph.get("molds") or []),
        "machines": len(graph.get("machines") or []),
        "presses": sum(1 for machine in graph.get("machines") or [] if not machine.get("attachedToId")),
        "running": sum(1 for run in graph.get("production_runs") or [] if run.get("startedAt") and not run.get("endedAt")),
        "recipes": len(graph.get("recipes") or []),
        "liveRecipes": len(live(graph.get("recipes") or [])),
        "trialRecipes": sum(1 for recipe in graph.get("recipes") or [] if recipe.get("status") == "trial"),
        "orders": len(graph.get("production_orders") or []),
        "openOrders": sum(1 for order in graph.get("production_orders") or [] if order.get("status") in OPEN_ORDERS),
        "runs": len(graph.get("production_runs") or []),
        "stoppages": len(stops),
        "downtimeHours": round(sum(span_hours(stop.get("startedAt"), stop.get("endedAt")) or 0 for stop in stops), 1),
        "lots": len(graph.get("lots") or []),
        "personnel": len(graph.get("personnel") or []),
        "categories": len(graph.get("item_categories") or []),
    }


# Lists ------------------------------------------------------------------------------------------

_LISTS = {
    "item": lambda graph: [item_row(graph, item) for item in graph.get("items") or []],
    "mold": lambda graph: [mold_row(graph, mold) for mold in graph.get("molds") or []],
    "machine": lambda graph: [machine_row(graph, machine) for machine in graph.get("machines") or []],
    "recipe": lambda graph: [recipe_row(graph, recipe) for recipe in graph.get("recipes") or []],
    "order": lambda graph: [order_row(graph, order) for order in graph.get("production_orders") or []],
    "run": lambda graph: run_rows(graph, graph.get("production_runs") or []),
    "stoppage": lambda graph: stoppage_rows(graph, graph.get("stoppages") or []),
    "lot": lambda graph: [lot_row(graph, lot) for lot in graph.get("lots") or []],
    "changeover": lambda graph: changeover_rows(graph, graph.get("changeovers") or []),
}


def list_view(graph, kind, gap_key=None):
    if kind not in _LISTS:
        return {"error": "Unknown list."}
    rows = _LISTS[kind](graph)
    banner = None
    if gap_key:
        match = next((entry for entry in gaps(graph) if entry["key"] == gap_key and entry["kind"] == kind), None)
        if match:
            wanted = set(match["ids"])
            rows = [row for row in rows if row["id"] in wanted]
            banner = {"count": match["count"], "title": match["title"], "benefit": match["benefit"]}
    return {"kind": kind, "rows": rows, "banner": banner}


# Overview ---------------------------------------------------------------------------------------

def overview(graph, who="all"):
    index = _ix(graph)
    persona = who or "all"
    every = gaps(graph)
    shown = [entry for entry in every if entry["count"] and (persona == "all" or persona in entry["who"])]
    presses = [machine for machine in graph.get("machines") or [] if not machine.get("attachedToId")]
    cards = []
    for machine in presses:
        run = open_run(graph, machine["id"])
        stop = open_stoppage(graph, machine["id"])
        recipe = index["recipes"].get(run.get("recipeId")) if run else None
        cards.append({
            "id": machine["id"], "name": machine.get("name") or "", "euromap": machine.get("euromap") or "",
            "location": machine.get("location") or "", "changeover": machine.get("changeoverMin"),
            "running": bool(run), "item": name_of(index, "items", recipe.get("itemId")) if recipe else "",
            "run": run["id"] if run else "", "order": run.get("orderId") if run else "", "since": run.get("startedAt") if run else "",
            "pph": pieces_per_hour(index, recipe) if recipe else None,
            "stoppedSince": stop.get("startedAt") if stop else "",
            "recipes": len(live(index["recipesByMachine"].get(machine["id"]) or [])),
            "molds": len(uniq([entry.get("moldId") for entry in live(index["recipesByMachine"].get(machine["id"]) or [])])),
        })
    return {
        "who": persona,
        "machines": cards,
        "gaps": [{key: entry[key] for key in ("key", "kind", "who", "title", "benefit", "count")} for entry in shown],
        "done": [entry["title"] for entry in every if not entry["count"]],
        "counts": counts(graph),
        "chart": {
            "labels": [machine.get("name") or machine["id"] for machine in presses],
            "values": [len(live(index["recipesByMachine"].get(machine["id"]) or [])) for machine in presses],
            "downtime": [round(sum(span_hours(stop.get("startedAt"), stop.get("endedAt")) or 0
                                   for stop in index["stoppagesByMachine"].get(machine["id"]) or []), 1) for machine in presses],
        },
        "stoppages": stoppage_rows(graph, graph.get("stoppages") or [])[:6],
    }


def elapsed_text(start, now):
    """How long a run has been going, from two ISO UTC moments."""
    begin, finish = records.parse_moment(start), records.parse_moment(now)
    if begin is None or finish is None or finish < begin:
        return ""
    minutes = int((finish - begin).total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return "%sh %sm" % (hours, mins)
    if minutes:
        return "%sm" % minutes
    return "under a minute"


def floor_state(graph, machine):
    """Running, idle, or stopped. An open stoppage counts as stopped even when a run is still open."""
    if machine.get("status") == "retired":
        return "Retired"
    if open_stoppage(graph, machine["id"]):
        return "Stopped"
    if open_run(graph, machine["id"]):
        return "Running"
    return "Idle"


def run_gaps(run):
    """What a shift log can still fill in. Listed for the operator; none of these block a save."""
    gaps = []
    if not (run.get("inputs") or []):
        gaps.append("No consumed lot")
    if run.get("cavities") is None:
        gaps.append("No cavity count")
    if run.get("good") is None:
        gaps.append("No good-piece count yet")
    return gaps


def _due_soon(order, today):
    due = order.get("dueDate") or ""
    if not due or order.get("status") not in OPEN_ORDERS:
        return False
    try:
        day = datetime.date.fromisoformat(due[:10])
        start = datetime.date.fromisoformat((today or "")[:10])
    except ValueError:
        return False
    return day <= start + datetime.timedelta(days=7)


def floor_view(graph, now, today):
    """The live board: one card per machine that stands on its own, from the open runs and stoppages."""
    index = reindex(graph)
    presses = [machine for machine in graph.get("machines") or [] if not machine.get("attachedToId") and machine.get("status") != "retired"]
    presses.sort(key=lambda machine: (machine.get("name") or "").lower())
    cards = []
    for machine in presses:
        run = open_run(graph, machine["id"])
        stop = open_stoppage(graph, machine["id"])
        recipe = index["recipes"].get(run.get("recipeId")) if run else None
        order = index["production_orders"].get(run.get("orderId")) if run else None
        state = floor_state(graph, machine)
        cause = index["stoppage_causes"].get(stop.get("causeId")) if stop else None
        qty = (order or {}).get("quantity")
        good = run.get("good") if run else None
        progress = None
        if good is not None and qty:
            try:
                progress = min(100, int(100 * float(good) / float(qty)))
            except (TypeError, ValueError, ZeroDivisionError):
                progress = None
        cards.append({
            "id": machine["id"], "name": machine.get("name") or machine["id"], "location": machine.get("location") or "",
            "state": state, "tone": {"Running": "ok", "Stopped": "bad", "Idle": "muted"}.get(state, "muted"),
            "run": run["id"] if run else "", "order": run.get("orderId") if run else "", "orderLabel": (order or {}).get("erpOrderNo") or (run.get("orderId") if run else ""),
            "recipe": run.get("recipeId") if run else "", "item": name_of(index, "items", recipe.get("itemId")) if recipe else "",
            "itemId": (recipe or {}).get("itemId") or "",
            "mold": name_of(index, "molds", recipe.get("moldId")) if recipe else "",
            "cycleSec": num(recipe.get("cycle")) if recipe else None,
            "operator": name_of(index, "personnel", run.get("operatorId")) if run and run.get("operatorId") else "",
            "operatorId": run.get("operatorId") if run else "",
            "shift": name_of(index, "shifts", run.get("shiftId")) if run and run.get("shiftId") else "",
            "shiftId": run.get("shiftId") if run else "",
            "startedAt": run.get("startedAt") if run else "", "elapsed": elapsed_text(run.get("startedAt"), now) if run else "",
            "good": good, "orderQty": qty, "progress": progress,
            "pph": pieces_per_hour(index, recipe) if recipe else None,
            "stoppage": stop.get("id") if stop else "", "cause": (cause or {}).get("name") or "",
            "stoppedSince": stop.get("startedAt") if stop else "", "stoppedFor": elapsed_text(stop.get("startedAt"), now) if stop else "",
            "gaps": run_gaps(run) if run else [],
            "barrelTemp": 215 if state == "Running" else None,
        })
    due = sorted((order for order in graph.get("production_orders") or [] if _due_soon(order, today)), key=lambda order: order.get("dueDate") or "")
    no_good = [run for run in graph.get("production_runs") or [] if run.get("startedAt") and not run.get("endedAt") and run.get("good") is None]
    counts = {
        "running": sum(1 for card in cards if card["state"] == "Running"),
        "idle": sum(1 for card in cards if card["state"] == "Idle"),
        "stopped": sum(1 for card in cards if card["state"] == "Stopped"),
    }
    board = {
        "now": now or "", "today": today or "",
        "counts": counts,
        "machines": cards,
        "dueSoon": [{"id": order["id"], "item": name_of(index, "items", order.get("itemId")), "due": order.get("dueDate") or "",
                     "erp": order.get("erpOrderNo") or "", "status": cap(order.get("status"))} for order in due[:8]],
        "down": [{"id": card["id"], "name": card["name"], "cause": card["cause"], "since": card["stoppedSince"], "for": card["stoppedFor"]}
                 for card in cards if card["state"] == "Stopped"][:8],
        "noGood": [{"id": run["id"], "machine": name_of(index, "machines", machine_of_run(index, run)),
                    "item": name_of(index, "items", item_of_run(index, run)), "elapsed": elapsed_text(run.get("startedAt"), now)}
                   for run in no_good[:8]],
        "demo": False,
    }
    return floor_with_demo(board)


_DEMO_SCENES = (
    {"state": "Running", "tone": "ok", "item": "Closure 38 mm", "mold": "MLD-1204", "recipe": "REC-DEMO-1", "orderLabel": "SO-24018",
     "operator": "Nikos P.", "shift": "Morning", "elapsed": "4h 12m", "good": 18400, "orderQty": 36000, "progress": 51, "pph": 720,
     "cycleSec": 9.8, "barrelTemp": 218, "gaps": []},
    {"state": "Stopped", "tone": "bad", "item": "Jar 250 ml", "mold": "MLD-0881", "recipe": "REC-DEMO-2", "orderLabel": "SO-24002",
     "operator": "Elena K.", "shift": "Morning", "elapsed": "1h 05m", "cause": "Heater band", "stoppedFor": "22m", "good": 4200, "orderQty": 24000,
     "progress": 18, "pph": 540, "cycleSec": 11.2, "barrelTemp": 205, "gaps": ["No good-piece count yet"]},
    {"state": "Running", "tone": "ok", "item": "Measuring cup", "mold": "MLD-0402", "recipe": "REC-DEMO-3", "orderLabel": "SO-24031",
     "operator": "Ada L.", "shift": "Morning", "elapsed": "2h 40m", "good": 9600, "orderQty": 12000, "progress": 80, "pph": 1080,
     "cycleSec": 7.4, "barrelTemp": 232, "gaps": []},
    {"state": "Idle", "tone": "muted", "item": "", "mold": "", "recipe": "", "orderLabel": "", "operator": "", "shift": "", "elapsed": "",
     "good": None, "orderQty": None, "progress": None, "pph": None, "cycleSec": None, "barrelTemp": None, "gaps": []},
)


def floor_with_demo(board):
    """When nothing is running on the real plant, show a realistic preview board for walkthroughs."""
    counts = board.get("counts") or {}
    live = (counts.get("running") or 0) + (counts.get("stopped") or 0)
    if live:
        board["demo"] = False
        good = sum(card.get("good") or 0 for card in board.get("machines") or [] if card.get("state") == "Running")
        board["kpis"] = {
            "goodToday": good or "—",
            "downtime": sum(1 for card in board.get("machines") or [] if card.get("state") == "Stopped"),
            "ordersDue": len(board.get("dueSoon") or []),
            "utilization": int(round(100 * (counts.get("running") or 0) / max(1, len(board.get("machines") or [])))),
        }
        return board
    machines = list(board.get("machines") or [])
    if not machines:
        return board
    painted = []
    for index, card in enumerate(machines):
        scene = dict(_DEMO_SCENES[index % len(_DEMO_SCENES)])
        painted.append({**card, **scene, "demoSlot": True})
    board = dict(board)
    board["machines"] = painted
    board["demo"] = True
    board["counts"] = {
        "running": sum(1 for card in painted if card.get("state") == "Running"),
        "idle": sum(1 for card in painted if card.get("state") == "Idle"),
        "stopped": sum(1 for card in painted if card.get("state") == "Stopped"),
    }
    board["timeline"] = [
        {"at": "10:42", "text": "Press 2 stopped · Heater band", "tone": "bad"},
        {"at": "10:18", "text": "Press 1 started order SO-24018", "tone": "ok"},
        {"at": "09:55", "text": "Press 3 changeover finished", "tone": "muted"},
        {"at": "09:12", "text": "Lot LOT-8821 received", "tone": "muted"},
    ]
    board["dueSoon"] = board.get("dueSoon") or [
        {"id": "PO-DEMO-1", "item": "Closure 38 mm", "due": board.get("today") or "", "erp": "SO-24018", "status": "Released"},
        {"id": "PO-DEMO-2", "item": "Jar 250 ml", "due": board.get("today") or "", "erp": "SO-24002", "status": "Released"},
    ]
    board["down"] = [{"id": card["id"], "name": card["name"], "cause": card.get("cause") or "", "since": "", "for": card.get("stoppedFor") or ""}
                     for card in painted if card.get("state") == "Stopped"][:4]
    board["kpis"] = {"goodToday": "32,200", "downtime": "0.6 h", "ordersDue": len(board["dueSoon"]), "utilization": 68}
    return board


# Details ----------------------------------------------------------------------------------------

def _flow_recipe(graph, recipe):
    index = _ix(graph)
    return {
        "id": recipe["id"], "trial": recipe.get("status") == "trial", "standard": bool(recipe.get("standard")),
        "cycle": num(recipe.get("cycle")), "label": variant_label(index, recipe), "pph": pieces_per_hour(index, recipe),
        "inputs": [{"id": entry["itemId"], "label": name_of(index, "items", entry["itemId"]), "role": role_of(index, entry["itemId"]),
                    "share": entry.get("share")} for entry in recipe.get("inputs") or []],
    }


def _flow(graph, item):
    index = _ix(graph)
    every = index["recipesByItem"].get(item["id"]) or []
    molds = []
    for mold_code in uniq([recipe.get("moldId") for recipe in every]):
        mold = index["molds"].get(mold_code) or {"id": mold_code}
        by_machine = group_by([recipe for recipe in every if recipe.get("moldId") == mold_code], "machineId")
        molds.append({
            "id": mold_code, "name": mold.get("name") or mold_code, "cavities": mold.get("cavities"),
            "groups": [{"machineId": code, "machineName": name_of(index, "machines", code),
                        "recipes": [_flow_recipe(graph, recipe) for recipe in listed]} for code, listed in sorted(by_machine.items())],
        })
    return {"itemId": item["id"], "itemName": item.get("name") or "", "erpCode": item.get("erpCode") or "", "molds": molds,
            "liveCount": len(live(every))}


def _machine_groups(graph, item):
    """The item's live recipes per machine, each a way to mold it: its colorants, materials, and cycle."""
    index = _ix(graph)
    groups = []
    for code, listed in sorted(group_by(live(index["recipesByItem"].get(item["id"]) or []), "machineId").items()):
        cycles = [cycle for cycle in (num(recipe.get("cycle")) for recipe in listed) if cycle is not None]
        same = bool(cycles) and all(cycle == cycles[0] for cycle in cycles)
        label = "cycle not written" if not cycles else ("%s s" % trim_num(cycles[0]) if same else "best %s s" % trim_num(min(cycles)))
        by_color = group_by([{"key": variant_key(index, recipe), "recipe": recipe} for recipe in listed], "key")
        current = open_run(graph, code)
        groups.append({
            "machineId": code, "machineName": name_of(index, "machines", code), "molds": uniq([recipe.get("moldId") for recipe in listed]),
            "cycleLabel": label, "colorWays": len(by_color),
            "needsStandard": any(len(ways) > 1 and not any(way["recipe"].get("standard") for way in ways) for ways in by_color.values()),
            "runningNow": bool(current and item_of_run(index, current) == item["id"]),
            "ways": [{
                "id": recipe["id"],
                "colors": [{"id": c, "label": color_label(index, c)} for c in colorants(index, recipe)],
                "materials": [{"id": m, "label": name_of(index, "items", m)} for m in materials(index, recipe)],
                "standard": bool(recipe.get("standard")), "canProduce": has_base(index, recipe), "cycle": num(recipe.get("cycle")),
                "showCycle": not same,
            } for recipe in listed],
        })
    return groups


def _approved(graph, item):
    index = _ix(graph)
    running = {recipe.get("machineId") for recipe in live(index["recipesByItem"].get(item["id"]) or [])}
    approved = set(item.get("approvedMachineIds") or [])
    return [{"id": machine["id"], "name": machine.get("name") or machine["id"], "approved": machine["id"] in approved,
             "hasRecipe": machine["id"] in running}
            for machine in graph.get("machines") or [] if machine["id"] in approved or machine["id"] in running]


def _item_missing(graph, item):
    index = _ix(graph)
    every = index["recipesByItem"].get(item["id"]) or []
    running = live(every)
    missing = []
    if item.get("type") == "RAW":
        if not item.get("erpCode"):
            missing.append({"what": "ERP code", "why": "Purchasing and stock cannot be matched to this material.", "action": "edit-item"})
        return missing
    if item.get("type") != "SFG":
        if not item.get("erpCode"):
            missing.append({"what": "ERP code", "why": "Orders and stock cannot be matched to this item.", "action": "edit-item"})
        return missing
    no_base = [recipe for recipe in running if not has_base(index, recipe)]
    if no_base:
        missing.append({"what": "Base material on %s" % plural(len(no_base), "recipe"), "why": "Colorants or additives only; nothing can be produced from that record.", "action": ""})
    if not item.get("erpCode"):
        missing.append({"what": "ERP code", "why": "Orders and stock cannot be matched to this item.", "action": "edit-item"})
    for mold_code in uniq([recipe.get("moldId") for recipe in running]):
        mold = index["molds"].get(mold_code) or {}
        if not mold.get("cavities"):
            missing.append({"what": "Cavities on %s" % mold_code, "why": "Pieces per hour cannot be computed.", "action": ""})
        if not mold.get("shotWeight"):
            missing.append({"what": "Shot weight on %s" % mold_code, "why": "Material per piece and cost are unknown.", "action": ""})
    unbooked = approved_without_recipe(graph, item)
    if unbooked:
        missing.append({"what": "Recipe on %s" % ", ".join(name_of(index, "machines", code) for code in unbooked),
                        "why": "The item is approved there, but there is no setting sheet for it.", "action": "add-recipe"})
    no_cycle = [recipe for recipe in running if not num(recipe.get("cycle"))]
    if no_cycle:
        missing.append({"what": "Cycle time on %s" % plural(len(no_cycle), "recipe"), "why": "Hours per order cannot be computed.", "action": ""})
    no_share = [recipe for recipe in running if missing_share(recipe)]
    if no_share:
        missing.append({"what": "Input shares on %s" % plural(len(no_share), "recipe"), "why": "Kilograms of resin and masterbatch per order cannot be computed.", "action": ""})
    for ways in group_by([dict(recipe, _key="%s|%s" % (recipe.get("machineId"), variant_key(index, recipe))) for recipe in running], "_key").values():
        if len(ways) > 1 and not any(recipe.get("standard") for recipe in ways):
            missing.append({"what": "Standard recipe", "why": "Several recipes for the same color on the same machine; the setter has to choose.", "action": ""})
            break
    trial = [recipe for recipe in every if recipe.get("status") == "trial"]
    if trial:
        missing.append({"what": plural(len(trial), "trial recipe").capitalize(), "why": "Approve or retire them so the machine list is true.", "action": ""})
    return missing


def _properties(item, role):
    properties = item.get("properties") or {}
    if role == "colorant":
        keys = (("labelCode", "Label code"), ("colorName", "Color"), ("label", "Label text"), ("shade", "Shade / supplier ref."),
                ("standard", "Color standard (RAL, Pantone)"), ("swatch", "Swatch"), ("link", "Sample link"))
    elif item.get("type") == "RAW":
        keys = (("family", "Family"), ("mfi", "MFI (g/10 min)"),
                ("description", "Description"), ("link", "Datasheet link"))
    else:
        keys = (("link", "Datasheet link"),)
    return [{"key": key, "label": label, "value": properties.get(key) or ""} for key, label in keys]


def detail_item(graph, code):
    index = _ix(graph)
    item = index["items"].get(code)
    if item is None:
        return {"missing": True, "kind": "item", "id": code}
    every = index["recipesByItem"].get(code) or []
    using = index["recipesUsing"].get(code) or []
    role = role_of(index, code)
    status = item_status(graph, item)
    runs = [run for recipe in every for run in index["runsByRecipe"].get(recipe["id"]) or []]
    properties = item.get("properties") or {}
    link = properties.get("link") or ""
    return {
        "kind": "item", "missing": False, "id": item["id"], "name": item.get("name") or "", "status": status, "tone": tone(status),
        "type": item.get("type") or "", "typeLabel": TYPE_LABEL.get(item.get("type"), ""), "categoryId": item.get("categoryId") or "",
        "category": category_name(index, item), "role": role, "uom": unit_of(index, item["id"]), "uomId": item.get("uomId") or "", "erpCode": item.get("erpCode") or "",
        "parentId": item.get("parentId") or "", "parentName": name_of(index, "items", item.get("parentId")) if item.get("parentId") else "",
        "attributes": [{"id": entry.get("attributeId") or "", "name": name_of(index, "variant_attributes", entry.get("attributeId")),
                        "value": entry.get("value") or ""} for entry in item.get("attributes") or []],
        "variants": [item_row(graph, child) for child in index["itemsByParent"].get(code) or []],
        "supplier": item.get("supplier") or "", "itemStatus": item.get("status") or "active", "notes": item.get("notes") or "",
        "catalog": properties.get("catalog", True), "properties": _properties(item, role),
        "link": link if link.startswith(("https://", "http://")) else "",
        "flow": _flow(graph, item), "machines": _machine_groups(graph, item), "approvedMachines": _approved(graph, item),
        "approvedMachineIds": list(item.get("approvedMachineIds") or []), "missingBits": _item_missing(graph, item),
        "recipes": [recipe_row(graph, recipe) for recipe in every],
        "usedIn": [recipe_row(graph, recipe) for recipe in using], "madeFrom": summary_rows(graph, using),
        "production": run_rows(graph, runs), "lots": [lot_row(graph, lot) for lot in index["lotsByItem"].get(code) or []],
        "orders": [order_row(graph, order) for order in index["ordersByItem"].get(code) or []],
        "trialCount": len([recipe for recipe in every if recipe.get("status") == "trial"]),
        "liveRecipes": [{"value": recipe["id"], "label": "%s · %s · %s" % (recipe["id"], name_of(index, "machines", recipe.get("machineId")),
                                                                            variant_label(index, recipe))} for recipe in live(every)],
        "molds": uniq([recipe.get("moldId") for recipe in every]),
    }


def detail_mold(graph, code):
    index = _ix(graph)
    mold = index["molds"].get(code)
    if mold is None:
        return {"missing": True, "kind": "mold", "id": code}
    status = mold_status(graph, mold)
    recipes = index["recipesByMold"].get(code) or []
    return {
        "kind": "mold", "missing": False, "id": mold["id"], "name": mold.get("name") or "", "status": status, "tone": tone(status),
        "cavities": mold.get("cavities"), "shotWeight": mold.get("shotWeight"), "location": mold.get("location") or "",
        "moldStatus": mold.get("status") or "in use", "notes": mold.get("notes") or "",
        "items": summary_rows(graph, recipes), "recipes": [recipe_row(graph, recipe) for recipe in recipes],
    }


def detail_machine(graph, code):
    index = _ix(graph)
    machine = index["machines"].get(code)
    if machine is None:
        return {"missing": True, "kind": "machine", "id": code}
    recipes = index["recipesByMachine"].get(code) or []
    runs = [run for recipe in recipes for run in index["runsByRecipe"].get(recipe["id"]) or []]
    current = open_run(graph, code)
    status = machine_status(graph, machine)
    return {
        "kind": "machine", "missing": False, "id": machine["id"], "name": machine.get("name") or "", "status": status, "tone": tone(status),
        "alias": machine.get("alias") or "", "typeId": machine.get("typeId") or "", "type": name_of(index, "machine_types", machine.get("typeId")),
        "attachedToId": machine.get("attachedToId") or "", "attachedTo": name_of(index, "machines", machine.get("attachedToId")) if machine.get("attachedToId") else "",
        "attached": [{"id": other["id"], "name": other.get("name") or "", "type": name_of(index, "machine_types", other.get("typeId"))}
                     for other in index["attached"].get(code) or []],
        "floor": machine.get("floor"), "serial": machine.get("serial") or "", "euromap": machine.get("euromap") or "", "year": machine.get("year") or "",
        "changeoverMin": machine.get("changeoverMin"), "location": machine.get("location") or "", "machineStatus": machine.get("status") or "active",
        "notes": machine.get("notes") or "",
        "current": run_row(graph, current) if current else None,
        "items": summary_rows(graph, recipes),
        "approved": [item_row(graph, item) for item in graph.get("items") or [] if code in (item.get("approvedMachineIds") or [])],
        "recipes": [recipe_row(graph, recipe) for recipe in recipes],
        "production": run_rows(graph, runs),
        "stoppages": stoppage_rows(graph, index["stoppagesByMachine"].get(code) or []),
        "changeovers": changeover_rows(graph, index["changeoversByMachine"].get(code) or []),
    }


def detail_recipe(graph, code):
    index = _ix(graph)
    recipe = index["recipes"].get(code)
    if recipe is None:
        return {"missing": True, "kind": "recipe", "id": code}
    status = recipe_status(graph, recipe)
    siblings = [other["id"] for other in live(index["recipesByItem"].get(recipe.get("itemId")) or [])
                if other.get("machineId") == recipe.get("machineId") and variant_key(index, other) == variant_key(index, recipe) and other["id"] != code]
    pph = pieces_per_hour(index, recipe)
    runs = index["runsByRecipe"].get(code) or []
    mold = index["molds"].get(recipe.get("moldId")) or {}
    inputs = []
    for position, entry in enumerate(recipe.get("inputs") or []):
        item = index["items"].get(entry.get("itemId")) or {}
        share = num(entry.get("share"))
        per_piece = None
        if share is not None and mold.get("shotWeight") and mold.get("cavities"):
            per_piece = round(float(mold["shotWeight"]) / float(mold["cavities"]) * share / 100.0, 2)
        inputs.append({
            "index": position, "id": entry.get("itemId") or "", "name": name_of(index, "items", entry.get("itemId")),
            "role": role_of(index, entry.get("itemId")), "roleLabel": ROLE_LABEL.get(role_of(index, entry.get("itemId")), ""),
            "category": category_name(index, item), "erp": item.get("erpCode") or "",
            "share": share, "perPiece": per_piece,
        })
    inputs.sort(key=lambda entry: ({"base": 0, "additive": 1, "colorant": 2}.get(entry["role"], 3), entry["name"]))
    total = sum(entry["share"] for entry in inputs if entry["share"] is not None)
    return {
        "kind": "recipe", "missing": False, "id": recipe["id"], "status": status, "tone": tone(status),
        "recipeStatus": recipe.get("status") or "approved", "standard": bool(recipe.get("standard")),
        "itemId": recipe.get("itemId") or "", "itemName": name_of(index, "items", recipe.get("itemId")),
        "machineId": recipe.get("machineId") or "", "machineName": name_of(index, "machines", recipe.get("machineId")),
        "moldId": recipe.get("moldId") or "", "moldName": mold.get("name") or "",
        "cycle": trim_num(recipe.get("cycle")), "cooling": recipe.get("cooling") or "", "screwRpm": recipe.get("screwRpm") or "",
        "pph": pph, "pphHint": "" if pph else ("needs cavities" if num(recipe.get("cycle")) else "needs cycle"),
        "siblings": siblings,
        "zones": [{"key": key, "label": label, "value": (recipe.get("temps") or {}).get(key) or ""} for key, label in TEMP_LABELS],
        "temps": {key: (recipe.get("temps") or {}).get(key) or "" for key in TEMP_KEYS},
        "inputs": inputs, "shareTotal": total if any(entry["share"] is not None for entry in inputs) else None,
        "settings": injection_settings(recipe),
        "px": recipe.get("px") or "", "py": recipe.get("py") or "", "printPieces": recipe.get("printPieces") or "",
        "printTotal": recipe.get("printTotal") or "", "comment": recipe.get("comment") or "", "settingsNote": recipe.get("settingsNote") or "",
        "production": run_rows(graph, runs),
        "stoppages": stoppage_rows(graph, [stop for run in runs for stop in index["stoppagesByRun"].get(run["id"]) or []]),
    }


def detail_order(graph, code):
    index = _ix(graph)
    order = index["production_orders"].get(code)
    if order is None:
        return {"missing": True, "kind": "order", "id": code}
    runs = index["runsByOrder"].get(code) or []
    row = order_row(graph, order)
    row.update({
        "kind": "order", "missing": False, "orderStatus": order.get("status") or "planned", "notes": order.get("notes") or "",
        "dueDate": order.get("dueDate") or "", "erpOrderNo": order.get("erpOrderNo") or "",
        "uom": unit_of(index, order.get("itemId")),
        "production": run_rows(graph, runs),
        "lots": [lot_row(graph, lot) for run in runs for lot in index["lotsByRun"].get(run["id"]) or []],
        "recipes": [{"value": recipe["id"], "label": "%s · %s · %s" % (recipe["id"], name_of(index, "machines", recipe.get("machineId")),
                                                                       variant_label(index, recipe))}
                    for recipe in live(index["recipesByItem"].get(order.get("itemId")) or [])],
    })
    return row


def detail_run(graph, code):
    index = _ix(graph)
    run = index["production_runs"].get(code)
    if run is None:
        return {"missing": True, "kind": "run", "id": code}
    recipe = index["recipes"].get(run.get("recipeId")) or {}
    row = run_row(graph, run)
    fed = {entry.get("itemId") for entry in recipe.get("inputs") or []}
    row.update({
        "kind": "run", "missing": False, "orderId": run.get("orderId") or "", "recipeId": run.get("recipeId") or "",
        "shiftId": run.get("shiftId") or "", "operatorId": run.get("operatorId") or "", "startedAt": run.get("startedAt") or "",
        "endedAt": run.get("endedAt") or "", "cavities": run.get("cavities"), "cycle": run.get("cycle"), "notes": run.get("notes") or "",
        "uom": unit_of(index, recipe.get("itemId")),
        "scrapLines": [{"index": position, "reason": name_of(index, "scrap_reasons", entry.get("reasonId")),
                        "category": (index["scrap_reasons"].get(entry.get("reasonId")) or {}).get("category") or "",
                        "quantity": entry.get("quantity")} for position, entry in enumerate(run.get("scrap") or [])],
        "inputLines": [{"index": position, "lotId": entry.get("lotId") or "", "lot": name_of(index, "lots", entry.get("lotId")),
                        "item": name_of(index, "items", (index["lots"].get(entry.get("lotId")) or {}).get("itemId")),
                        "itemId": (index["lots"].get(entry.get("lotId")) or {}).get("itemId") or "",
                        "quantity": entry.get("quantity"),
                        "uom": unit_of(index, (index["lots"].get(entry.get("lotId")) or {}).get("itemId"))}
                       for position, entry in enumerate(run.get("inputs") or [])],
        "outputLots": [lot_row(graph, lot) for lot in index["lotsByRun"].get(code) or []],
        "stoppages": stoppage_rows(graph, index["stoppagesByRun"].get(code) or []),
        "changeovers": changeover_rows(graph, (index["changeoversByToRun"].get(code) or []) + (index["changeoversByFromRun"].get(code) or [])),
        "candidateLots": [{"value": lot["id"], "label": "%s · %s%s" % (lot.get("number"), name_of(index, "items", lot.get("itemId")),
                                                                        "" if lot.get("status") == "released" else " (%s)" % lot.get("status"))}
                          for lot in graph.get("lots") or [] if lot.get("itemId") in fed and lot.get("status") != "blocked"],
        "fedItems": [{"value": code_, "label": name_of(index, "items", code_)} for code_ in uniq([entry.get("itemId") for entry in recipe.get("inputs") or []])],
    })
    return row


def _trace_back(graph, lot, depth=0):
    index = _ix(graph)
    run = index["production_runs"].get(lot.get("runId")) if lot.get("runId") else None
    node = {"lot": lot_row(graph, lot), "run": run_row(graph, run) if run else None, "inputs": []}
    if run and depth < 8:
        for entry in run.get("inputs") or []:
            fed = index["lots"].get(entry.get("lotId"))
            if fed:
                child = _trace_back(graph, fed, depth + 1)
                child["quantity"] = entry.get("quantity")
                node["inputs"].append(child)
    return node


def _trace_forward(graph, lot, depth=0):
    index = _ix(graph)
    node = {"lot": lot_row(graph, lot), "runs": []}
    if depth < 8:
        for run, entry in index["consumers"].get(lot["id"]) or []:
            node["runs"].append({"run": run_row(graph, run), "quantity": entry.get("quantity"),
                                 "outputs": [_trace_forward(graph, made, depth + 1) for made in index["lotsByRun"].get(run["id"]) or []]})
    return node


def detail_lot(graph, code):
    index = _ix(graph)
    lot = index["lots"].get(code)
    if lot is None:
        return {"missing": True, "kind": "lot", "id": code}
    row = lot_row(graph, lot)
    row.update({
        "kind": "lot", "missing": False, "lotStatus": lot.get("status") or "released", "notes": lot.get("notes") or "",
        "receivedAt": lot.get("receivedAt") or "", "back": _trace_back(graph, lot), "forward": _trace_forward(graph, lot),
    })
    return row


_DETAILS = {
    "item": detail_item, "mold": detail_mold, "machine": detail_machine, "recipe": detail_recipe,
    "order": detail_order, "run": detail_run, "lot": detail_lot,
}


def detail(graph, kind, code):
    builder = _DETAILS.get(kind)
    if builder is None:
        return {"missing": True, "kind": kind, "id": code}
    return builder(graph, code)


def settings_view(graph):
    index = _ix(graph)
    return {
        "kind": "settings",
        "shifts": [dict(entry) for entry in graph.get("shifts") or []],
        "causes": [dict(entry) for entry in graph.get("stoppage_causes") or []],
        "reasons": [dict(entry) for entry in graph.get("scrap_reasons") or []],
        "categories": [dict(entry, typeLabel=TYPE_LABEL.get(entry.get("type"), ""), roleLabel=ROLE_LABEL.get(entry.get("role") or "", ""))
                       for entry in graph.get("item_categories") or []],
        "machineTypes": [dict(entry) for entry in graph.get("machine_types") or []],
        "roles": [dict(entry) for entry in graph.get("person_roles") or []],
        "units": [dict(entry) for entry in graph.get("units") or []],
        "variantAttributes": [dict(entry) for entry in graph.get("variant_attributes") or []],
        "personnel": [dict(entry, roleLabel=name_of(index, "person_roles", entry["roleId"]) if entry.get("roleId") else "",
                           machines=[name_of(index, "machines", code) for code in entry.get("machineIds") or []])
                      for entry in graph.get("personnel") or []],
    }


# Search and choices -------------------------------------------------------------------------

_LOOKALIKE = str.maketrans("αβεζηικμνορτυχς", "abezhikmnoptyxσ")


def fold(value):
    """Lower case without accents, with Greek capitals that look Latin read as Latin (Α100 = A100)."""
    plain = unicodedata.normalize("NFD", str(value or "").lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return plain.translate(_LOOKALIKE)


def search(graph, term, limit=16):
    query = fold(term).strip()
    if len(query) < 2:
        return []
    index = _ix(graph)
    found = []

    def hit(*parts):
        return query in fold(" ".join(text(part) for part in parts))

    def push(kind, code, label):
        if len(found) < limit:
            found.append({"kind": kind, "id": code, "label": label})

    for item in graph.get("items") or []:
        properties = item.get("properties") or {}
        if hit(item.get("name"), item["id"], item.get("erpCode"), properties.get("labelCode")):
            push("item", item["id"], item.get("name") or item["id"])
    for mold in graph.get("molds") or []:
        if hit(mold["id"], mold.get("name")):
            push("mold", mold["id"], mold.get("name") or mold["id"])
    for machine in graph.get("machines") or []:
        if hit(machine.get("name"), machine["id"], machine.get("alias")):
            push("machine", machine["id"], machine.get("name") or machine["id"])
    for recipe in graph.get("recipes") or []:
        item, machine = name_of(index, "items", recipe.get("itemId")), name_of(index, "machines", recipe.get("machineId"))
        if hit(recipe["id"], item, machine):
            push("recipe", recipe["id"], "%s on %s" % (item, machine))
    for order in graph.get("production_orders") or []:
        if hit(order["id"], order.get("erpOrderNo"), name_of(index, "items", order.get("itemId"))):
            push("order", order["id"], "%s · %s" % (order["id"], name_of(index, "items", order.get("itemId"))))
    for run in graph.get("production_runs") or []:
        if hit(run["id"]):
            push("run", run["id"], run["id"])
    for lot in graph.get("lots") or []:
        if hit(lot.get("number"), lot["id"], lot.get("supplierLot")):
            push("lot", lot["id"], "%s · %s" % (lot.get("number"), name_of(index, "items", lot.get("itemId"))))
    return found


def _options(entries, label=lambda entry: entry.get("name") or entry["id"], keep=lambda entry: True):
    return [{"value": entry["id"], "label": label(entry)} for entry in entries if keep(entry)]


def _active(entry):
    return entry.get("status", "active") != "retired"




def choices(graph):
    index = _ix(graph)
    items = graph.get("items") or []
    presses = [machine for machine in graph.get("machines") or [] if not machine.get("attachedToId")]
    recipes_by_machine = {}
    for recipe in live(graph.get("recipes") or []):
        recipes_by_machine.setdefault(recipe.get("machineId") or "", []).append({
            "value": recipe["id"], "label": "%s · %s · %s" % (name_of(index, "items", recipe.get("itemId")), variant_label(index, recipe), recipe["id"])})
    open_orders = [order for order in graph.get("production_orders") or [] if order.get("status") in OPEN_ORDERS]
    recipes_by_order = {order["id"]: [{"value": recipe["id"], "label": "%s · %s · %s" % (recipe["id"], name_of(index, "machines", recipe.get("machineId")),
                                                                                          variant_label(index, recipe))}
                                      for recipe in live(index["recipesByItem"].get(order.get("itemId")) or [])] for order in open_orders}
    runs_by_machine = {}
    for run in sorted(graph.get("production_runs") or [], key=lambda entry: entry.get("startedAt") or "", reverse=True):
        runs_by_machine.setdefault(machine_of_run(index, run), []).append({
            "value": run["id"], "label": "%s · %s%s" % (run["id"], name_of(index, "items", item_of_run(index, run)), "" if run.get("endedAt") else " · running")})
    return {
        "machines": _options(graph.get("machines") or []),
        "presses": _options(presses),
        "items": _options(items, lambda entry: "%s (%s)" % (entry.get("name") or entry["id"], entry["id"])),
        "made": _options(items, lambda entry: "%s (%s)" % (entry.get("name") or entry["id"], entry["id"]),
                         lambda entry: entry.get("type") in ("SFG", "FG") and _active(entry)),
        "raw": _options(items, lambda entry: "%s · %s" % (entry.get("name") or entry["id"], category_name(index, entry)),
                        lambda entry: entry.get("type") == "RAW" and _active(entry)),
        "colorants": _options(items, lambda entry: entry.get("name") or entry["id"], lambda entry: role_of(index, entry["id"]) == "colorant"),
        "received": _options(items, lambda entry: "%s (%s)" % (entry.get("name") or entry["id"], TYPE_LABEL.get(entry.get("type"), "")),
                             lambda entry: entry.get("type") in ("RAW", "PAK", "TRD") and _active(entry)),
        "molds": _options(graph.get("molds") or [], lambda entry: "%s · %s" % (entry["id"], entry.get("name") or "")),
        "categories": [{"value": entry["id"], "label": entry.get("name") or entry["id"], "type": entry.get("type") or ""}
                       for entry in graph.get("item_categories") or []],
        "categoriesByType": {key: _options([entry for entry in graph.get("item_categories") or [] if entry.get("type") == key])
                             for key, _ in ITEM_TYPES},
        "machineTypes": _options(graph.get("machine_types") or []),
        "types": [{"value": key, "label": label} for key, label in ITEM_TYPES],
        "roles": [{"value": key, "label": label} for key, label in ROLES],
        "uoms": _options(graph.get("units") or [], keep=_active),
        "products": _options(items, lambda entry: "%s (%s)" % (entry.get("name") or entry["id"], entry["id"]), _active),
        "variantAttributes": _options(graph.get("variant_attributes") or [], keep=_active),
        "statuses": [{"value": value, "label": cap(value)} for value in STATUSES],
        "recipeStatuses": [{"value": value, "label": cap(value)} for value in RECIPE_STATUSES],
        "moldStatuses": [{"value": value, "label": cap(value)} for value in MOLD_STATUSES],
        "orderStatuses": [{"value": value, "label": cap(value)} for value in ORDER_STATUSES],
        "lotStatuses": [{"value": value, "label": cap(value)} for value in LOT_STATUSES],
        "fishbone": [{"value": value, "label": value} for value in FISHBONE],
        "people": _options(graph.get("personnel") or [], keep=_active),
        "operators": _options(graph.get("personnel") or [], keep=lambda entry: _active(entry) and can_operate(index, entry)),
        "personRoles": _options(graph.get("person_roles") or [], keep=_active),
        "productionRoles": [entry["id"] for entry in graph.get("person_roles") or [] if entry.get("runsMachines")],
        "shifts": [{"value": entry["id"], "label": "%s %s–%s" % (entry.get("name"), entry.get("start"), entry.get("end")),
                    "start": entry.get("start") or "", "end": entry.get("end") or ""} for entry in graph.get("shifts") or [] if _active(entry)],
        "causes": _options(graph.get("stoppage_causes") or [], lambda entry: "%s · %s" % (entry.get("name"), entry.get("category")), _active),
        "reasons": _options(graph.get("scrap_reasons") or [], lambda entry: "%s · %s" % (entry.get("name"), entry.get("category")), _active),
        "openOrders": _options(open_orders, lambda entry: "%s · %s" % (entry["id"], name_of(index, "items", entry.get("itemId")))),
        "recipesByMachine": recipes_by_machine,
        "recipesByOrder": recipes_by_order,
        "runsByMachine": runs_by_machine,
    }


# Actions ----------------------------------------------------------------------------------------

def _redirect(kind, code, dirty):
    return {"redirect": {"kind": kind, "code": code}, "dirty": dirty}


def _refresh(dirty):
    return {"refresh": True, "dirty": dirty}


def _get(graph, table, code):
    return _ix(graph)[table].get(code or "")


def _context(graph, payload, kind):
    return _get(graph, KIND_TABLE[kind], payload.get("contextId")) if payload.get("contextKind") == kind else None


def _number_error(payload, checks):
    """Name the first field that is not a number."""
    for key, label in checks:
        value = text(payload.get(key))
        if value and num(value) is None:
            return "%s has to be a number." % label
    return None


def _choice(value, allowed, fallback):
    return value if value in allowed else fallback


def _moment_error(payload, start_key, end_key, start_label, end_label, required=True):
    start, end = text(payload.get(start_key)), text(payload.get(end_key))
    if not start:
        return "Give the %s." % start_label if required else None
    if records.parse_moment(start) is None:
        return "The %s is not a date and time." % start_label
    if end:
        if records.parse_moment(end) is None:
            return "The %s is not a date and time." % end_label
        if records.parse_moment(end) < records.parse_moment(start):
            return "The %s is before the %s." % (end_label, start_label)
    return None


def _parent_error(graph, item, parent_id):
    if not parent_id:
        return None
    if parent_id == item.get("id"):
        return "A product cannot be its own variant."
    seen = set()
    cursor = parent_id
    while cursor:
        if cursor == item.get("id") or cursor in seen:
            return "That parent would make a loop."
        seen.add(cursor)
        parent = _get(graph, "items", cursor)
        if parent is None:
            return "Choose the shared product from the list."
        cursor = parent.get("parentId") or ""
    return None


def _attribute_values(graph, payload):
    active = {entry["id"]: entry for entry in graph.get("variant_attributes") or [] if entry.get("status") != "retired"}
    values = []
    for key, value in payload.items():
        if not str(key).startswith("attr::"):
            continue
        code = str(key)[6:]
        if code not in active:
            return None, "Choose a variant attribute from the list."
        written = text(value)
        if written:
            values.append({"attributeId": code, "value": written})
    return values, None


def ensure_variant_attributes(graph):
    """The starting attribute names, only when the plant has none yet. Existing items are left alone."""
    if graph.get("variant_attributes"):
        return []
    made = []
    graph["variant_attributes"] = []
    for name in ("Customer", "Pack size", "Color"):
        entry = {"id": new_code(graph, "variant_attributes"), "name": name, "status": "active"}
        graph["variant_attributes"].append(entry)
        made.append(entry["id"])
    return made


def _item_fields(graph, item, payload):
    name = text(payload.get("name"))
    if not name:
        return "Name is required."
    kind = _choice(payload.get("type") or item.get("type"), TYPE_LABEL, "SFG")
    category = _get(graph, "item_categories", payload.get("categoryId") or item.get("categoryId"))
    if category is None or category.get("type") != kind:
        return "Choose a category for this item type."
    error = _number_error(payload, [("mfi", "MFI")])
    if error:
        return error
    unit = _get(graph, "units", payload.get("uomId") or item.get("uomId"))
    if unit is None:
        return "Choose the unit."
    swatch = text(payload.get("prop::swatch"))
    if swatch and not re.match(r"^#[0-9a-fA-F]{6}$", swatch):
        return "The swatch must be a color like #1E3A8A."
    item.update({"name": name, "type": kind, "categoryId": category["id"], "uomId": unit["id"]})
    for key in ("erpCode", "supplier", "notes"):
        if key in payload:
            item[key] = text(payload.get(key))
    if "status" in payload:
        item["status"] = _choice(payload.get("status"), STATUSES, "active")
    properties = dict(item.get("properties") or {})
    for key, value in payload.items():
        if key.startswith("prop::"):
            value = text(value)
            if value:
                properties[key[6:]] = value
            else:
                properties.pop(key[6:], None)
    if properties.get("catalog") is False:
        properties["catalog"] = True
    item["properties"] = properties
    if "parentId" in payload:
        parent_id = text(payload.get("parentId"))
        error = _parent_error(graph, item, parent_id)
        if error:
            return error
        item["parentId"] = parent_id
    if any(str(key).startswith("attr::") for key in payload):
        values, error = _attribute_values(graph, payload)
        if error:
            return error
        item["attributes"] = values
    return None


def action_new_item(graph, payload):
    item = copy.deepcopy(_DEFAULTS["items"])
    item["id"] = new_code(graph, "items")
    error = _item_fields(graph, item, payload)
    if error:
        return {"error": error}
    graph["items"].append(item)
    return _redirect("item", item["id"], {"items": [item["id"]]})


def action_edit_item(graph, payload):
    item = _context(graph, payload, "item")
    if item is None:
        return {"error": "Item was not found."}
    error = _item_fields(graph, item, payload)
    if error:
        return {"error": error}
    return _refresh({"items": [item["id"]]})


def action_set_approved(graph, payload):
    item = _context(graph, payload, "item")
    if item is None:
        return {"error": "Item was not found."}
    wanted = payload.get("machines") or []
    if isinstance(wanted, str):
        wanted = [code.strip() for code in wanted.split(",")]
    item["approvedMachineIds"] = [machine["id"] for machine in graph.get("machines") or [] if machine["id"] in wanted]
    return _refresh({"items": [item["id"]]})


def _copy_recipe(graph, source, item_id):
    recipe = copy.deepcopy(source)
    recipe.update({"id": new_code(graph, "recipes"), "itemId": item_id, "standard": False, "comment": "copy of %s" % source["id"]})
    if recipe.get("status") == "retired":
        recipe["status"] = "trial"
    graph["recipes"].append(recipe)
    return recipe


def action_clone_item(graph, payload):
    source = _context(graph, payload, "item")
    if source is None:
        return {"error": "Item was not found."}
    item = copy.deepcopy(source)
    item.update({"id": new_code(graph, "items"), "name": (source.get("name") or "Item") + " (copy)", "erpCode": ""})
    graph["items"].append(item)
    copies = [_copy_recipe(graph, recipe, item["id"]) for recipe in list(_ix(graph)["recipesByItem"].get(source["id"]) or [])]
    return _redirect("item", item["id"], {"items": [item["id"]], "recipes": [recipe["id"] for recipe in copies]})


def action_new_mold(graph, payload):
    name = text(payload.get("name"))
    if not name:
        return {"error": "Mold name is required."}
    error = _number_error(payload, [("cavities", "Cavities"), ("shotWeight", "Shot weight")])
    if error:
        return {"error": error}
    mold = dict(copy.deepcopy(_DEFAULTS["molds"]), id=new_code(graph, "molds"), name=name,
                cavities=num(payload.get("cavities")), shotWeight=num(payload.get("shotWeight")), location=text(payload.get("location")))
    graph["molds"].append(mold)
    return _redirect("mold", mold["id"], {"molds": [mold["id"]]})


def action_edit_mold(graph, payload):
    mold = _context(graph, payload, "mold")
    if mold is None:
        return {"error": "Mold was not found."}
    name = text(payload.get("name")) or mold.get("name")
    error = _number_error(payload, [("cavities", "Cavities"), ("shotWeight", "Shot weight")])
    if error:
        return {"error": error}
    mold.update({"name": name, "cavities": num(payload.get("cavities")), "shotWeight": num(payload.get("shotWeight")),
                 "location": text(payload.get("location")), "status": _choice(payload.get("status"), MOLD_STATUSES, "in use"),
                 "notes": text(payload.get("notes"))})
    return _refresh({"molds": [mold["id"]]})


def _machine_fields(graph, machine, payload):
    name = text(payload.get("name"))
    if not name:
        return "Name is required."
    if _get(graph, "machine_types", payload.get("typeId")) is None:
        return "Choose the machine type."
    attached = text(payload.get("attachedToId"))
    if attached and (attached == machine.get("id") or _get(graph, "machines", attached) is None):
        return "Choose another machine to attach it to."
    error = _number_error(payload, [("changeoverMin", "Changeover time"), ("floor", "Floor number")])
    if error:
        return error
    machine.update({"name": name, "typeId": payload["typeId"], "attachedToId": attached, "changeoverMin": num(payload.get("changeoverMin")),
                    "floor": num(payload.get("floor")), "status": _choice(payload.get("status"), STATUSES, "active")})
    for key in ("alias", "serial", "euromap", "year", "location", "notes"):
        if key in payload:
            machine[key] = text(payload.get(key))
    return None


def action_new_machine(graph, payload):
    machine = dict(copy.deepcopy(_DEFAULTS["machines"]), id=new_code(graph, "machines"))
    error = _machine_fields(graph, machine, payload)
    if error:
        return {"error": error}
    graph["machines"].append(machine)
    return _redirect("machine", machine["id"], {"machines": [machine["id"]]})


def action_edit_machine(graph, payload):
    machine = _context(graph, payload, "machine")
    if machine is None:
        return {"error": "Machine was not found."}
    error = _machine_fields(graph, machine, payload)
    if error:
        return {"error": error}
    return _refresh({"machines": [machine["id"]]})


def action_add_recipe(graph, payload):
    item = _context(graph, payload, "item")
    if item is None:
        return {"error": "Item was not found."}
    if _get(graph, "machines", payload.get("machine")) is None:
        return {"error": "Choose a machine."}
    dirty = {"recipes": [], "molds": []}
    mold = _get(graph, "molds", payload.get("mold"))
    if mold is None:
        if payload.get("mold"):
            return {"error": "Choose a mold from the list."}
        mold = dict(copy.deepcopy(_DEFAULTS["molds"]), id=new_code(graph, "molds"), name=item.get("name") or "Mold")
        graph["molds"].append(mold)
        dirty["molds"].append(mold["id"])
    source = _get(graph, "recipes", payload.get("from"))
    recipe = copy.deepcopy(source) if source else copy.deepcopy(_DEFAULTS["recipes"])
    recipe.update({"id": new_code(graph, "recipes"), "itemId": item["id"], "moldId": mold["id"], "machineId": payload["machine"],
                   "status": "approved", "standard": False, "comment": ("copy of %s" % source["id"]) if source else "created in Cyclops"})
    recipe["temps"] = {key: text((recipe.get("temps") or {}).get(key)) for key in TEMP_KEYS}
    colorant = _get(graph, "items", payload.get("color"))
    if colorant is not None:
        recipe["inputs"] = [entry for entry in recipe.get("inputs") or [] if role_of(_ix(graph), entry.get("itemId")) != "colorant"]
        recipe["inputs"].append({"itemId": colorant["id"], "share": None})
    graph["recipes"].append(recipe)
    dirty["recipes"].append(recipe["id"])
    return _redirect("recipe", recipe["id"], dirty)


def action_edit_recipe(graph, payload):
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    checks = [("temp_" + key, "%s temperature" % label) for key, label in TEMP_LABELS]
    checks += [("cycle", "Cycle"), ("cooling", "Cooling"), ("screwRpm", "Screw speed")]
    error = _number_error(payload, checks)
    if error:
        return {"error": error}
    recipe["temps"] = {key: text(payload.get("temp_" + key)) for key in TEMP_KEYS}
    recipe["cycle"] = num(payload.get("cycle"))
    recipe["cooling"] = text(payload.get("cooling"))
    recipe["screwRpm"] = text(payload.get("screwRpm"))
    recipe["status"] = _choice(payload.get("status") or recipe.get("status"), RECIPE_STATUSES, "approved")
    if recipe["status"] != "approved":
        recipe["standard"] = False
    for key in ("comment", "settingsNote", "px", "py", "printPieces", "printTotal"):
        if key in payload:
            recipe[key] = text(payload.get(key))
    return _refresh({"recipes": [recipe["id"]]})


def action_edit_injection(graph, payload):
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    written = []
    for entry in injection_settings(recipe):
        value = text(payload.get(SETTING_PREFIX + entry["label"], entry["value"]))
        if value:
            written.append({"label": entry["label"], "value": value})
    recipe["settings"] = written
    return _refresh({"recipes": [recipe["id"]]})


def action_set_standard(graph, payload):
    index = _ix(graph)
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    if recipe.get("status") != "approved":
        return {"error": "Only an approved recipe can be the standard."}
    dirty = []
    for other in live(index["recipesByItem"].get(recipe.get("itemId")) or []):
        if other["id"] != recipe["id"] and other.get("machineId") == recipe.get("machineId") and variant_key(index, other) == variant_key(index, recipe) and other.get("standard"):
            other["standard"] = False
            dirty.append(other["id"])
    recipe["standard"] = True
    return _refresh({"recipes": dirty + [recipe["id"]]})


def action_clone_recipe(graph, payload):
    source = _context(graph, payload, "recipe")
    if source is None:
        return {"error": "Recipe was not found."}
    recipe = _copy_recipe(graph, source, source.get("itemId"))
    return _redirect("recipe", recipe["id"], {"recipes": [recipe["id"]]})


def action_delete_recipe(graph, payload):
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    if _ix(graph)["runsByRecipe"].get(recipe["id"]):
        return {"error": "Runs were logged on this recipe. Retire it instead, so the production history keeps its settings."}
    graph["recipes"] = [entry for entry in graph["recipes"] if entry["id"] != recipe["id"]]
    return _redirect("item", recipe.get("itemId"), {"recipes": [recipe["id"]]})


def _share(payload):
    value = text(payload.get("share"))
    if not value:
        return None, None
    share = num(value)
    if share is None or share < 0 or share > 100:
        return None, "The share is a percentage between 0 and 100."
    return share, None


def action_add_input(graph, payload):
    index = _ix(graph)
    item = _get(graph, "items", payload.get("item"))
    if item is None or item.get("type") != "RAW":
        return {"error": "Choose a raw material."}
    share, error = _share(payload)
    if error:
        return {"error": error}
    recipe = _context(graph, payload, "recipe")
    if recipe is not None:
        targets = [recipe]
    else:
        parent = _context(graph, payload, "item")
        if parent is None:
            return {"error": "Item was not found."}
        running = live(index["recipesByItem"].get(parent["id"]) or [])
        chosen = payload.get("recipe") or "all"
        targets = running if chosen == "all" else [entry for entry in running if entry["id"] == chosen]
    if not targets:
        return {"error": "There is no approved recipe to add this input to."}
    dirty = []
    for target in targets:
        if any(entry.get("itemId") == item["id"] for entry in target.get("inputs") or []):
            continue
        target.setdefault("inputs", []).append({"itemId": item["id"], "share": share})
        dirty.append(target["id"])
    if not dirty:
        return {"error": "That material is already an input."}
    return _refresh({"recipes": dirty})


def _line(entries, payload):
    try:
        position = int(payload.get("index"))
    except (TypeError, ValueError):
        return None
    return position if 0 <= position < len(entries or []) else None


def _input_position(recipe, payload):
    """Inputs are shown sorted, so the page names the input by its item."""
    for position, entry in enumerate(recipe.get("inputs") or []):
        if entry.get("itemId") == payload.get("item"):
            return position
    return None


def action_edit_input(graph, payload):
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    position = _input_position(recipe, payload)
    if position is None:
        return {"error": "That input is no longer on the recipe."}
    share, error = _share(payload)
    if error:
        return {"error": error}
    recipe["inputs"][position]["share"] = share
    return _refresh({"recipes": [recipe["id"]]})


def action_remove_input(graph, payload):
    recipe = _context(graph, payload, "recipe")
    if recipe is None:
        return {"error": "Recipe was not found."}
    position = _input_position(recipe, payload)
    if position is None:
        return {"error": "That input is no longer on the recipe."}
    del recipe["inputs"][position]
    return _refresh({"recipes": [recipe["id"]]})


def _order_fields(graph, order, payload):
    item = _get(graph, "items", payload.get("item") or order.get("itemId"))
    if item is None or item.get("type") not in ("SFG", "FG"):
        return "Choose the item to make."
    quantity = num(payload.get("quantity"))
    if quantity is None or quantity <= 0:
        return "Give the quantity to make."
    due = text(payload.get("dueDate"))
    if due and records._date_in(due) is None:
        return "The due date is not a date."
    order.update({"itemId": item["id"], "quantity": quantity, "dueDate": due, "status": _choice(payload.get("status") or order.get("status"), ORDER_STATUSES, "planned"),
                  "erpOrderNo": text(payload.get("erpOrderNo")), "notes": text(payload.get("notes"))})
    return None


def action_new_order(graph, payload):
    order = dict(copy.deepcopy(_DEFAULTS["production_orders"]), id=new_code(graph, "production_orders"))
    if payload.get("contextKind") == "item" and not payload.get("item"):
        payload = dict(payload, item=payload.get("contextId"))
    error = _order_fields(graph, order, payload)
    if error:
        return {"error": error}
    graph["production_orders"].append(order)
    return _redirect("order", order["id"], {"production_orders": [order["id"]]})


def action_edit_order(graph, payload):
    order = _context(graph, payload, "order")
    if order is None:
        return {"error": "Order was not found."}
    if payload.get("item") and payload.get("item") != order.get("itemId") and _ix(graph)["runsByOrder"].get(order["id"]):
        return {"error": "Runs were logged on this order, so its item stays."}
    error = _order_fields(graph, order, payload)
    if error:
        return {"error": error}
    return _refresh({"production_orders": [order["id"]]})


def action_delete_order(graph, payload):
    order = _context(graph, payload, "order")
    if order is None:
        return {"error": "Order was not found."}
    if _ix(graph)["runsByOrder"].get(order["id"]):
        return {"error": "Runs were logged on this order. Cancel it instead."}
    graph["production_orders"] = [entry for entry in graph["production_orders"] if entry["id"] != order["id"]]
    return _redirect("order", None, {"production_orders": [order["id"]]})


def _run_fields(graph, run, payload):
    index = _ix(graph)
    order = _get(graph, "production_orders", payload.get("order") or run.get("orderId"))
    if order is None:
        return "Choose the production order."
    recipe = _get(graph, "recipes", payload.get("recipe") or run.get("recipeId"))
    if recipe is None:
        return "Choose the recipe that ran."
    if recipe.get("itemId") != order.get("itemId"):
        return "The recipe makes %s, but the order is for %s." % (name_of(index, "items", recipe.get("itemId")), name_of(index, "items", order.get("itemId")))
    if _get(graph, "shifts", payload.get("shiftId")) is None:
        return "Choose the shift."
    operator = _get(graph, "personnel", payload.get("operatorId"))
    if operator is None:
        return "Choose the operator."
    if not can_operate(index, operator) and operator["id"] != run.get("operatorId"):
        return "%s's role (%s) does not run machines." % (operator.get("name"), name_of(index, "person_roles", operator.get("roleId")))
    error = _moment_error(payload, "startedAt", "endedAt", "start", "end")
    if error:
        return error
    error = _number_error(payload, [("good", "Good pieces"), ("cavities", "Cavities running"), ("cycle", "Actual cycle")])
    if error:
        return error
    if text(payload.get("endedAt")) and num(payload.get("good")) is None:
        return "Give the good pieces to close the run."
    if text(payload.get("endedAt")) and any(stoppage_state(stop) == "open" for stop in index["stoppagesByRun"].get(run.get("id")) or []):
        return "A stoppage on this run is still open. Give its restart time first."
    for key in ("good", "cavities", "cycle"):
        if num(payload.get(key)) is not None and num(payload.get(key)) < 0:
            return "Numbers cannot be negative."
    run.update({"orderId": order["id"], "recipeId": recipe["id"], "shiftId": payload["shiftId"], "operatorId": payload["operatorId"],
                "startedAt": text(payload.get("startedAt")), "endedAt": text(payload.get("endedAt")), "good": num(payload.get("good")),
                "cavities": num(payload.get("cavities")), "cycle": num(payload.get("cycle")), "notes": text(payload.get("notes"))})
    run["status"] = "done" if run["endedAt"] else "running"
    return None


def _order_progress(graph, order_code, dirty):
    order = _get(graph, "production_orders", order_code)
    if order is not None and order.get("status") in ("planned", "released"):
        order["status"] = "in progress"
        dirty.setdefault("production_orders", []).append(order["id"])


def action_add_run(graph, payload):
    run = dict(copy.deepcopy(_DEFAULTS["production_runs"]), id=new_code(graph, "production_runs"))
    if payload.get("contextKind") == "order" and not payload.get("order"):
        payload = dict(payload, order=payload.get("contextId"))
    if payload.get("contextKind") == "recipe" and not payload.get("recipe"):
        payload = dict(payload, recipe=payload.get("contextId"))
    error = _run_fields(graph, run, payload)
    if error:
        return {"error": error}
    graph["production_runs"].append(run)
    dirty = {"production_runs": [run["id"]]}
    _order_progress(graph, run["orderId"], dirty)
    result = _redirect("run", run["id"], dirty)
    result["gaps"] = run_gaps(run)
    return result


def action_edit_run(graph, payload):
    run = _context(graph, payload, "run")
    if run is None:
        return {"error": "Run was not found."}
    error = _run_fields(graph, run, payload)
    if error:
        return {"error": error}
    return _refresh({"production_runs": [run["id"]]})


def _shift_payload(run, payload, closing):
    """Order, recipe, shift, and start stay as they are on an open run. The clock fills a new run."""
    merged = dict(payload)
    if run.get("id"):
        for key, field in (("order", "orderId"), ("recipe", "recipeId"), ("shiftId", "shiftId"), ("operatorId", "operatorId")):
            if not text(merged.get(key)):
                merged[key] = run.get(field) or ""
        if not text(merged.get("startedAt")):
            merged["startedAt"] = run.get("startedAt") or ""
        if not text(merged.get("good")) and not closing:
            merged["good"] = "" if run.get("good") is None else run.get("good")
        if "cavities" not in payload:
            merged["cavities"] = "" if run.get("cavities") is None else run.get("cavities")
        if "cycle" not in payload:
            merged["cycle"] = "" if run.get("cycle") is None else run.get("cycle")
        if "notes" not in payload:
            merged["notes"] = run.get("notes") or ""
    if closing:
        merged["endedAt"] = text(merged.get("endedAt"))
    else:
        merged["endedAt"] = ""
    return merged


def _apply_scrap(graph, run, payload):
    reason, quantity = text(payload.get("scrapReason")), text(payload.get("scrapQty"))
    if not reason and not quantity:
        return None
    if _get(graph, "scrap_reasons", reason) is None:
        return "Choose the scrap reason."
    amount = num(quantity)
    if amount is None or amount <= 0:
        return "Give the scrapped quantity."
    run.setdefault("scrap", []).append({"reasonId": reason, "quantity": amount})
    return None


def action_log_shift(graph, payload):
    """Good pieces, scrap, and who was on the machine. A missing lot or cavity count is listed, not refused."""
    index = _ix(graph)
    machine_code = text(payload.get("machine")) or (text(payload.get("contextId")) if payload.get("contextKind") == "floor" else "")
    if _get(graph, "machines", machine_code) is None and payload.get("contextKind") != "run":
        return {"error": "Choose the machine."}
    closing = text(payload.get("close")) in ("yes", "true", "1")
    run = None
    if payload.get("contextKind") == "run":
        run = _get(graph, "production_runs", payload.get("contextId"))
    if run is None and machine_code:
        run = open_run(graph, machine_code)
    dirty = {"production_runs": []}
    if run is None:
        run = dict(copy.deepcopy(_DEFAULTS["production_runs"]), id=new_code(graph, "production_runs"))
        graph["production_runs"].append(run)
        fresh = True
    else:
        fresh = False
    error = _run_fields(graph, run, _shift_payload(run, payload, closing))
    if error:
        if fresh:
            graph["production_runs"] = [entry for entry in graph["production_runs"] if entry["id"] != run["id"]]
        return {"error": error}
    error = _apply_scrap(graph, run, payload)
    if error:
        if fresh:
            graph["production_runs"] = [entry for entry in graph["production_runs"] if entry["id"] != run["id"]]
        return {"error": error}
    dirty["production_runs"].append(run["id"])
    _order_progress(graph, run["orderId"], dirty)
    result = _refresh(dirty)
    result["gaps"] = run_gaps(run)
    return result


def action_delete_run(graph, payload):
    index = _ix(graph)
    run = _context(graph, payload, "run")
    if run is None:
        return {"error": "Run was not found."}
    made = index["lotsByRun"].get(run["id"]) or []
    if any(index["consumers"].get(lot["id"]) for lot in made):
        return {"error": "Lots from this run were used by later runs. Correct the run instead of deleting it."}
    dirty = {"production_runs": [run["id"]], "lots": [lot["id"] for lot in made], "stoppages": []}
    for stop in index["stoppagesByRun"].get(run["id"]) or []:
        stop["runId"] = ""
        dirty["stoppages"].append(stop["id"])
    graph["lots"] = [lot for lot in graph["lots"] if lot.get("runId") != run["id"]]
    graph["production_runs"] = [entry for entry in graph["production_runs"] if entry["id"] != run["id"]]
    return _redirect("order", run.get("orderId"), dirty)


def action_add_scrap(graph, payload):
    run = _context(graph, payload, "run")
    if run is None:
        return {"error": "Run was not found."}
    if _get(graph, "scrap_reasons", payload.get("reason")) is None:
        return {"error": "Choose the scrap reason."}
    quantity = num(payload.get("quantity"))
    if quantity is None or quantity <= 0:
        return {"error": "Give the scrapped quantity."}
    run.setdefault("scrap", []).append({"reasonId": payload["reason"], "quantity": quantity})
    return _refresh({"production_runs": [run["id"]]})


def action_remove_scrap(graph, payload):
    run = _context(graph, payload, "run")
    position = _line(run.get("scrap") if run else None, payload)
    if run is None or position is None:
        return {"error": "That scrap line is no longer on the run."}
    del run["scrap"][position]
    return _refresh({"production_runs": [run["id"]]})


def action_add_run_input(graph, payload):
    index = _ix(graph)
    run = _context(graph, payload, "run")
    if run is None:
        return {"error": "Run was not found."}
    lot = _get(graph, "lots", payload.get("lot"))
    if lot is None:
        return {"error": "Choose the lot that was fed."}
    if lot.get("status") == "blocked":
        return {"error": "Lot %s is blocked and cannot be used." % lot.get("number")}
    fed = {entry.get("itemId") for entry in (index["recipes"].get(run.get("recipeId")) or {}).get("inputs") or []}
    if lot.get("itemId") not in fed:
        return {"error": "%s is not an input of this run's recipe." % name_of(index, "items", lot.get("itemId"))}
    quantity = num(payload.get("quantity"))
    if quantity is None or quantity <= 0:
        return {"error": "Give the quantity used."}
    run.setdefault("inputs", []).append({"lotId": lot["id"], "quantity": quantity})
    return _refresh({"production_runs": [run["id"]]})


def action_remove_run_input(graph, payload):
    run = _context(graph, payload, "run")
    position = _line(run.get("inputs") if run else None, payload)
    if run is None or position is None:
        return {"error": "That input lot is no longer on the run."}
    del run["inputs"][position]
    return _refresh({"production_runs": [run["id"]]})


def _lot_number_taken(graph, item_code, number, keep=""):
    return any(lot.get("itemId") == item_code and lot.get("number") == number and lot["id"] != keep for lot in graph.get("lots") or [])


def action_add_output_lot(graph, payload):
    index = _ix(graph)
    run = _context(graph, payload, "run")
    if run is None:
        return {"error": "Run was not found."}
    number = text(payload.get("number"))
    quantity = num(payload.get("quantity"))
    if not number:
        return {"error": "Give the lot printed on the boxes."}
    if quantity is None or quantity <= 0:
        return {"error": "Give the quantity in the lot."}
    item_code = item_of_run(index, run)
    if _lot_number_taken(graph, item_code, number):
        return {"error": "Lot %s already exists for this item." % number}
    lot = dict(copy.deepcopy(_DEFAULTS["lots"]), id=new_code(graph, "lots"), number=number, itemId=item_code, origin="produced",
               runId=run["id"], quantity=quantity, notes=text(payload.get("notes")))
    graph["lots"].append(lot)
    return _refresh({"lots": [lot["id"]]})


def action_receive_lot(graph, payload):
    item = _get(graph, "items", payload.get("item"))
    if item is None or item.get("type") not in ("RAW", "PAK", "TRD"):
        return {"error": "Choose the material or packaging received."}
    number = text(payload.get("number"))
    if not number:
        return {"error": "Give the lot number on the bag or box."}
    if _lot_number_taken(graph, item["id"], number):
        return {"error": "Lot %s already exists for this item." % number}
    if records.parse_moment(payload.get("receivedAt")) is None:
        return {"error": "Give the date and time it was received."}
    quantity = num(payload.get("quantity"))
    if quantity is None or quantity <= 0:
        return {"error": "Give the quantity received."}
    lot = dict(copy.deepcopy(_DEFAULTS["lots"]), id=new_code(graph, "lots"), number=number, itemId=item["id"], origin="received",
               supplierLot=text(payload.get("supplierLot")), receivedAt=text(payload.get("receivedAt")), quantity=quantity,
               status=_choice(payload.get("status"), LOT_STATUSES, "released"), notes=text(payload.get("notes")))
    graph["lots"].append(lot)
    return _redirect("lot", lot["id"], {"lots": [lot["id"]]})


def action_edit_lot(graph, payload):
    lot = _context(graph, payload, "lot")
    if lot is None:
        return {"error": "Lot was not found."}
    number = text(payload.get("number")) or lot.get("number")
    if _lot_number_taken(graph, lot.get("itemId"), number, keep=lot["id"]):
        return {"error": "Lot %s already exists for this item." % number}
    error = _number_error(payload, [("quantity", "Quantity")])
    if error:
        return {"error": error}
    if text(payload.get("receivedAt")) and records.parse_moment(payload.get("receivedAt")) is None:
        return {"error": "The received time is not a date and time."}
    lot.update({"number": number, "quantity": num(payload.get("quantity")), "status": _choice(payload.get("status"), LOT_STATUSES, "released"),
                "supplierLot": text(payload.get("supplierLot")), "notes": text(payload.get("notes"))})
    if lot.get("origin") == "received" and "receivedAt" in payload:
        lot["receivedAt"] = text(payload.get("receivedAt"))
    return _refresh({"lots": [lot["id"]]})


def action_delete_lot(graph, payload):
    lot = _context(graph, payload, "lot")
    if lot is None:
        return {"error": "Lot was not found."}
    if _ix(graph)["consumers"].get(lot["id"]):
        return {"error": "Runs used this lot. Block it instead, so the trace stays."}
    graph["lots"] = [entry for entry in graph["lots"] if entry["id"] != lot["id"]]
    return _redirect("lot", None, {"lots": [lot["id"]]})


def _stoppage_fields(graph, stop, payload):
    index = _ix(graph)
    machine = _get(graph, "machines", payload.get("machine") or stop.get("machineId"))
    if machine is None:
        return "Choose the machine that stopped."
    run_code = text(payload.get("run")) if "run" in payload else stop.get("runId") or ""
    run = _get(graph, "production_runs", run_code) if run_code else None
    if run_code and run is None:
        return "Choose the run from the list."
    if run is not None and machine_of_run(index, run) != machine["id"]:
        return "That run was on another machine."
    error = _moment_error(payload, "startedAt", "endedAt", "stop time", "restart time")
    if error:
        return error
    cause = text(payload.get("cause"))
    if cause and _get(graph, "stoppage_causes", cause) is None:
        return "Choose the cause from the list."
    if text(payload.get("endedAt")) and not cause:
        return "Choose the cause to close the stoppage."
    if not cause and not text(payload.get("description")):
        return "Choose the cause or write what was seen."
    reporter = text(payload.get("reportedBy"))
    if reporter and _get(graph, "personnel", reporter) is None:
        return "Choose who reported it from the list."
    stop.update({"machineId": machine["id"], "runId": run["id"] if run else "", "startedAt": text(payload.get("startedAt")),
                 "endedAt": text(payload.get("endedAt")), "causeId": cause, "description": text(payload.get("description")),
                 "fix": text(payload.get("fix")), "reportedById": reporter})
    return None


def action_add_stoppage(graph, payload):
    index = _ix(graph)
    stop = dict(copy.deepcopy(_DEFAULTS["stoppages"]), id=new_code(graph, "stoppages"))
    if payload.get("contextKind") == "machine" and not payload.get("machine"):
        payload = dict(payload, machine=payload.get("contextId"))
    if payload.get("contextKind") == "run":
        run = _get(graph, "production_runs", payload.get("contextId"))
        if run is not None:
            payload = dict(payload, run=run["id"], machine=machine_of_run(index, run))
    error = _stoppage_fields(graph, stop, payload)
    if error:
        return {"error": error}
    graph["stoppages"].append(stop)
    return _refresh({"stoppages": [stop["id"]]})


def action_edit_stoppage(graph, payload):
    stop = _get(graph, "stoppages", payload.get("stoppage"))
    if stop is None:
        return {"error": "That stoppage was not found."}
    error = _stoppage_fields(graph, stop, payload)
    if error:
        return {"error": error}
    return _refresh({"stoppages": [stop["id"]]})


def action_delete_stoppage(graph, payload):
    stop = _get(graph, "stoppages", payload.get("stoppage"))
    if stop is None:
        return {"error": "That stoppage was not found."}
    graph["stoppages"] = [entry for entry in graph["stoppages"] if entry["id"] != stop["id"]]
    return _refresh({"stoppages": [stop["id"]]})


def _time_text(value):
    value = text(value).replace(".", ":")
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value):
        return None
    return value


def action_save_setting(graph, payload):
    kind = payload.get("settingKind") or ""
    table = SETTING_TABLES.get(kind)
    if table is None:
        return {"error": "Unknown setting."}
    name = text(payload.get("name"))
    if not name:
        return {"error": "Name is required."}
    entry = _get(graph, table, payload.get("code"))
    if any(other.get("name", "").lower() == name.lower() and other["id"] != (entry or {}).get("id") for other in graph[table]):
        return {"error": "%s is already on the list." % name}
    if entry is None:
        entry = dict(copy.deepcopy(_DEFAULTS[table]), id=new_code(graph, table))
        graph[table].append(entry)
    entry["name"] = name
    if table == "shifts":
        start, end = _time_text(payload.get("start")), _time_text(payload.get("end"))
        if not start or not end:
            return {"error": "Give the start and end as HH:MM."}
        entry.update({"start": start, "end": end})
    if table in ("stoppage_causes", "scrap_reasons"):
        entry["category"] = _choice(payload.get("category"), FISHBONE, "Machine")
    if table == "person_roles":
        entry["runsMachines"] = text(payload.get("runsMachines")) in ("yes", "true", "1")
    if table == "stoppage_causes":
        entry["planned"] = text(payload.get("planned")) in ("yes", "true", "1")
        entry["changeover"] = text(payload.get("changeover")) in ("yes", "true", "1")
    if table == "item_categories":
        entry["type"] = _choice(payload.get("type"), TYPE_LABEL, "RAW")
        entry["role"] = _choice(payload.get("role") or "", [key for key, _ in ROLES], "") if entry["type"] == "RAW" else ""
    if table == "personnel":
        role = _get(graph, "person_roles", payload.get("roleId"))
        entry["roleId"] = role["id"] if role else ""
        wanted = payload.get("machines") or []
        if isinstance(wanted, str):
            wanted = [code.strip() for code in wanted.split(",") if code.strip()]
        if role is None or not role.get("runsMachines"):
            wanted = []
        entry["machineIds"] = [machine["id"] for machine in graph.get("machines") or [] if machine["id"] in wanted]
    if "status" in entry and payload.get("status"):
        entry["status"] = _choice(payload.get("status"), STATUSES, "active")
    return _refresh({table: [entry["id"]]})


ACTIONS = {
    "new-item": action_new_item, "edit-item": action_edit_item, "set-approved": action_set_approved, "clone-item": action_clone_item,
    "new-mold": action_new_mold, "edit-mold": action_edit_mold, "new-machine": action_new_machine, "edit-machine": action_edit_machine,
    "add-recipe": action_add_recipe, "edit-recipe": action_edit_recipe, "edit-injection": action_edit_injection,
    "set-standard": action_set_standard, "clone-recipe": action_clone_recipe, "delete-recipe": action_delete_recipe,
    "add-input": action_add_input, "edit-input": action_edit_input, "remove-input": action_remove_input,
    "new-order": action_new_order, "edit-order": action_edit_order, "delete-order": action_delete_order,
    "add-run": action_add_run, "edit-run": action_edit_run, "log-shift": action_log_shift, "delete-run": action_delete_run,
    "add-scrap": action_add_scrap, "remove-scrap": action_remove_scrap,
    "add-run-input": action_add_run_input, "remove-run-input": action_remove_run_input, "add-output-lot": action_add_output_lot,
    "receive-lot": action_receive_lot, "edit-lot": action_edit_lot, "delete-lot": action_delete_lot,
    "add-stoppage": action_add_stoppage, "edit-stoppage": action_edit_stoppage, "delete-stoppage": action_delete_stoppage,
    "save-setting": action_save_setting,
}


def dispatch(graph, action, payload):
    handler = ACTIONS.get(action)
    if handler is None:
        return {"error": "Unknown action."}
    reindex(graph)
    result = handler(graph, payload or {})
    if not result.get("error"):
        reindex(graph)
    return result
