"""Cyclops production records.

Pure Python port of the sketch in cyclops/sketch/template.html. No Anvil imports,
so the status rules, gaps, and edits can be tested on their own.
"""

import copy
import datetime
import re
import unicodedata

TYPES = {
    "part": "Molded part",
    "lid": "Lid",
    "set": "Set (sold together)",
    "other": "Other",
}
MATERIAL_KINDS = {"resin": "Resin", "regrind": "Regrind", "additive": "Additive"}
KIND_ROUTE = {
    "product": "products",
    "mold": "molds",
    "press": "presses",
    "recipe": "recipes",
    "material": "materials",
    "color": "colors",
}
ROUTE_KIND = {route: kind for kind, route in KIND_ROUTE.items()}
TEMP_KEYS = ("nozzle", "t6", "t5", "t4", "t3", "t2", "t1")
TEMP_LABELS = (
    ("nozzle", "Nozzle"),
    ("t6", "T6"),
    ("t5", "T5"),
    ("t4", "T4"),
    ("t3", "T3"),
    ("t2", "T2"),
    ("t1", "T1"),
)
STATUS_TONE = {
    "Active": "ok",
    "Mounted": "ok",
    "Standard": "std",
    "Incomplete": "warn",
    "No code": "warn",
    "Cannot produce": "bad",
}
ADDITIVE_TEXT = {"ροή", "διόγκωση", "αντιστατικό", "αντηλιακό"}
MOLD_STATUSES = ("in use", "in repair", "stored", "retired")
LIFECYCLES = ("active", "retired")


def num(value):
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def whole(value):
    number = num(value)
    if number is None:
        return None
    if number.is_integer():
        return int(number)
    return number


def trim_num(value):
    number = num(value)
    if number is None:
        return ""
    if number.is_integer():
        return str(int(number))
    return ("%s" % number).rstrip("0").rstrip(".")


def uniq(items):
    seen = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def group_by(items, key):
    grouped = {}
    for item in items:
        grouped.setdefault(item.get(key), []).append(item)
    return grouped


def by_id(items):
    return {item["id"]: item for item in items}


def live(recipes):
    return [recipe for recipe in (recipes or []) if not recipe.get("trial")]


def tone(status):
    return STATUS_TONE.get(status or "", "muted")


def cap(text):
    text = text or ""
    if not text:
        return ""
    return text[0].upper() + text[1:]


def next_id(prefix, items, width):
    highest = 0
    for item in items:
        part = str(item.get("id") or "").split("-")[-1]
        try:
            highest = max(highest, int(part))
        except ValueError:
            continue
    return "%s-%s" % (prefix, str(highest + 1).zfill(width))


def derive_material_kind(material):
    text = (material.get("text") or "").strip().lower()
    family = (material.get("family") or "").upper()
    if text in ADDITIVE_TEXT or family == "ΠΡΟΣΘΕΤΑ":
        return "additive"
    if re.search(r"κ[όο]κκος|σπασμ[έε]νο|^mix$|μιξ", text) or family == "RECYCLE" or re.match(r"^9199", material.get("account") or ""):
        return "regrind"
    return "resin"


def default_product_type(name):
    if re.match(r"^ΚΑΠΑΚΙ", name or "", re.IGNORECASE):
        return "lid"
    return "part"


def normalize(graph):
    for product in graph.get("products") or []:
        product["erpCode"] = product.get("erpCode") or ""
        product["notes"] = product.get("notes") or ""
        product["legacyId"] = product.get("legacyId") or ""
        if not product.get("type"):
            product["type"] = default_product_type(product.get("name"))
        if not product.get("lifecycle"):
            product["lifecycle"] = "active"
        product["onlyOnCards"] = bool(product.get("onlyOnCards"))
        product["approvedPressIds"] = uniq(list(product.get("approvedPressIds") or []))
    for mold in graph.get("molds") or []:
        if "cavities" not in mold or mold.get("cavities") == "":
            mold["cavities"] = None
        else:
            mold["cavities"] = whole(mold.get("cavities"))
        if "shotWeight" not in mold or mold.get("shotWeight") == "":
            mold["shotWeight"] = None
        else:
            mold["shotWeight"] = whole(mold.get("shotWeight"))
        mold["location"] = mold.get("location") or ""
        if not mold.get("status"):
            mold["status"] = "in use"
    for press in graph.get("presses") or []:
        if "changeoverMin" not in press or press.get("changeoverMin") == "":
            press["changeoverMin"] = None
        else:
            press["changeoverMin"] = whole(press.get("changeoverMin"))
        if not press.get("lifecycle"):
            press["lifecycle"] = "active"
        board = press.get("board") or {}
        press["board"] = {
            "mounted": board.get("mounted") or "",
            "location": board.get("location") or "",
            "note": board.get("note") or "",
        }
        press["alias"] = press.get("alias") or ""
        press["serial"] = press.get("serial") or ""
        press["robot"] = press.get("robot") or ""
        press["robotSerial"] = press.get("robotSerial") or ""
        press["robotYear"] = press.get("robotYear") or ""
        press["euromap"] = press.get("euromap") or ""
    for recipe in graph.get("recipes") or []:
        temps = recipe.get("temps") or {}
        recipe["temps"] = {key: temps.get(key) or "" for key in TEMP_KEYS}
        recipe["settings"] = list(recipe.get("settings") or [])
        recipe["materialSlots"] = list(recipe.get("materialSlots") or [])
        recipe["colorSlots"] = list(recipe.get("colorSlots") or [])
        for key in ("cycle", "cooling", "screwRpm", "px", "py", "productLot", "printPieces", "printTotal", "comment", "status", "settingsNote"):
            recipe[key] = recipe.get(key) or ""
        recipe["trial"] = bool(recipe.get("trial"))
        recipe["standard"] = bool(recipe.get("standard"))
        recipe["issues"] = [_issue(item) for item in recipe.get("issues") or [] if item]
    for material in graph.get("materials") or []:
        if not material.get("kind"):
            material["kind"] = derive_material_kind(material)
        for key in ("supplier", "mfi", "family", "account", "invoiceCode", "description", "link", "notes"):
            material[key] = material.get(key) or ""
        material["catalog"] = bool(material.get("catalog"))
    for color in graph.get("colors") or []:
        for key in ("code", "name", "label", "account", "shade", "link", "notes"):
            color[key] = color.get(key) or ""
        color["catalog"] = bool(color.get("catalog"))
    graph["links"] = list(graph.get("links") or [])
    graph["workers"] = uniq([str(name).strip() for name in graph.get("workers") or [] if str(name or "").strip()])
    return graph


ISSUE_KEYS = ("startDate", "startTime", "cause", "worker", "fix", "endDate", "endTime")


def _issue(item):
    return {key: str(item.get(key) or "").strip() for key in ISSUE_KEYS}


def _moment(date_text, time_text):
    try:
        return datetime.datetime.strptime("%s %s" % (date_text, (time_text or "").replace(".", ":")), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def downtime_hours(issue):
    """Hours from stop to restart, or None when a time is missing or the dates run backwards."""
    start = _moment(issue.get("startDate"), issue.get("startTime"))
    end = _moment(issue.get("endDate"), issue.get("endTime"))
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds() / 3600.0, 1)


def issue_state(issue):
    if not issue.get("endDate") and not issue.get("endTime"):
        return "open"
    start = _moment(issue.get("startDate"), issue.get("startTime"))
    end = _moment(issue.get("endDate"), issue.get("endTime"))
    if start is None or end is None:
        return "no restart time"
    if end < start:
        return "check dates"
    return "closed"


def reindex(graph):
    products = graph.get("products") or []
    molds = graph.get("molds") or []
    presses = graph.get("presses") or []
    recipes = graph.get("recipes") or []
    materials = graph.get("materials") or []
    colors = graph.get("colors") or []
    index = {
        "product": by_id(products),
        "mold": by_id(molds),
        "press": by_id(presses),
        "recipe": by_id(recipes),
        "material": by_id(materials),
        "color": by_id(colors),
        "recipesByProduct": group_by(recipes, "productId"),
        "recipesByMold": group_by(recipes, "moldId"),
        "recipesByPress": group_by(recipes, "pressId"),
        "recipesByMaterial": {},
        "recipesByColor": {},
        "linksByLid": group_by(graph.get("links") or [], "lidId"),
        "linksByPart": group_by(graph.get("links") or [], "partId"),
        "moldsByProduct": group_by(molds, "productId"),
    }
    for recipe in recipes:
        for slot in recipe.get("materialSlots") or []:
            index["recipesByMaterial"].setdefault(slot.get("materialId"), []).append(recipe)
        for slot in recipe.get("colorSlots") or []:
            index["recipesByColor"].setdefault(slot.get("colorId"), []).append(recipe)
    for product in products:
        owned = index["moldsByProduct"].get(product["id"]) or []
        product["moldId"] = owned[0]["id"] if owned else None
    graph["_ix"] = index
    return index


def _ix(graph):
    if "_ix" not in graph:
        reindex(graph)
    return graph["_ix"]


def product_name(index, code):
    item = index["product"].get(code)
    return item["name"] if item else (code or "")


def press_name(index, code):
    item = index["press"].get(code)
    return item["name"] if item else (code or "")


def material_name(index, code):
    item = index["material"].get(code)
    return item["text"] if item else (code or "")


def color_name(index, code):
    item = index["color"].get(code)
    if not item:
        return code or ""
    return " ".join(part for part in (item.get("name"), item.get("code")) if part)


def color_short(index, code):
    item = index["color"].get(code)
    if not item:
        return code or ""
    return item.get("name") or item.get("code") or code


def material_ids(recipe):
    return uniq([slot.get("materialId") for slot in recipe.get("materialSlots") or []])


def color_ids(recipe):
    return uniq([slot.get("colorId") for slot in recipe.get("colorSlots") or []])


def variant_key(recipe):
    return "|".join(sorted(color_ids(recipe)))


def variant_label(index, recipe):
    colors = color_ids(recipe)
    if not colors:
        return "natural / no color"
    return " + ".join(color_short(index, code) for code in colors)


def variants_of(graph, product):
    index = _ix(graph)
    all_recipes = index["recipesByProduct"].get(product["id"]) or []
    base = live(all_recipes) or list(all_recipes)
    groups = {}
    order = []
    for recipe in base:
        key = variant_key(recipe) or "natural"
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(recipe)
    variants = []
    for position, key in enumerate(order, start=1):
        recipes = groups[key]
        variants.append({
            "id": "%s-V%s" % (product["id"], position),
            "key": key,
            "label": variant_label(index, recipes[0]),
            "colorIds": color_ids(recipes[0]),
            "recipes": recipes,
            "pressIds": uniq([recipe.get("pressId") for recipe in recipes]),
            "trialOnly": all(recipe.get("trial") for recipe in recipes),
        })
    return variants


def pieces_per_hour(index, recipe):
    mold = index["mold"].get(recipe.get("moldId"))
    cycle = num(recipe.get("cycle"))
    if not mold or not mold.get("cavities") or not cycle:
        return None
    return int(round((3600.0 / cycle) * float(mold["cavities"])))


def best_cycle(recipes):
    cycles = [cycle for cycle in (num(recipe.get("cycle")) for recipe in recipes) if cycle is not None]
    if not cycles:
        return None
    return min(cycles)


def has_base(index, recipe):
    for slot in recipe.get("materialSlots") or []:
        material = index["material"].get(slot.get("materialId"))
        if material and material.get("kind") in ("resin", "regrind"):
            return True
    return False


def temps_count(recipe):
    temps = recipe.get("temps") or {}
    return sum(1 for key in TEMP_KEYS if num(temps.get(key)) is not None)


def setup_status(graph, recipe):
    index = _ix(graph)
    if recipe.get("trial"):
        return "Trial row"
    if not has_base(index, recipe):
        return "Cannot produce"
    if not num(recipe.get("cycle")) or temps_count(recipe) < 3:
        return "Incomplete"
    if recipe.get("standard"):
        return "Standard"
    return "Active"


def product_status(graph, product):
    if product.get("lifecycle") == "retired":
        return "Retired"
    index = _ix(graph)
    all_recipes = index["recipesByProduct"].get(product["id"]) or []
    live_recipes = live(all_recipes)
    if not all_recipes:
        return "Name only"
    if not live_recipes:
        return "Trial only"
    statuses = [setup_status(graph, recipe) for recipe in live_recipes]
    if all(status == "Cannot produce" for status in statuses):
        return "Cannot produce"
    if any(status in ("Cannot produce", "Incomplete") for status in statuses):
        return "Incomplete"
    return "Active"


def mold_status(graph, mold):
    if mold.get("status") and mold.get("status") != "in use":
        return cap(mold.get("status"))
    index = _ix(graph)
    if not live(index["recipesByMold"].get(mold["id"]) or []):
        return "Unused"
    if not mold.get("cavities"):
        return "Incomplete"
    return "Active"


def press_status(graph, press):
    if press.get("lifecycle") == "retired":
        return "Retired"
    index = _ix(graph)
    if not live(index["recipesByPress"].get(press["id"]) or []):
        return "No setups"
    if (press.get("board") or {}).get("mounted"):
        return "Mounted"
    return "No board entry"


def material_status(graph, material):
    if not material.get("catalog"):
        return "Not in catalog"
    index = _ix(graph)
    if not live(index["recipesByMaterial"].get(material["id"]) or []):
        return "Unused"
    if not material.get("account"):
        return "No code"
    return "Active"


def color_status(graph, color):
    index = _ix(graph)
    if not live(index["recipesByColor"].get(color["id"]) or []):
        return "Unused"
    if not color.get("account"):
        return "No code"
    return "Active"


def product_links(graph, product):
    index = _ix(graph)
    linked = []
    for link in index["linksByLid"].get(product["id"]) or []:
        other = index["product"].get(link.get("partId"))
        if other:
            linked.append({"otherId": other["id"], "otherName": other["name"], "text": "fits onto", "lidId": link.get("lidId"), "partId": link.get("partId"), "basis": link.get("basis") or ""})
    for link in index["linksByPart"].get(product["id"]) or []:
        other = index["product"].get(link.get("lidId"))
        if other:
            linked.append({"otherId": other["id"], "otherName": other["name"], "text": "lid that fits", "lidId": link.get("lidId"), "partId": link.get("partId"), "basis": link.get("basis") or ""})
    return linked


def gaps(graph):
    index = _ix(graph)
    live_all = live(graph.get("recipes") or [])
    duplicates = []
    for product in graph.get("products") or []:
        for variant in variants_of(graph, product):
            by_press = group_by([recipe for recipe in variant["recipes"] if not recipe.get("trial")], "pressId")
            for listed in by_press.values():
                if len(listed) > 1 and not any(recipe.get("standard") for recipe in listed):
                    duplicates.extend(listed)
    board_mismatch = []
    for press in graph.get("presses") or []:
        mounted = (press.get("board") or {}).get("mounted") or ""
        if not mounted:
            continue
        product = None
        for candidate in graph.get("products") or []:
            if candidate["name"].strip().upper() == mounted.strip().upper():
                product = candidate
                break
        matched = product and any(
            recipe.get("productId") == product["id"] and recipe.get("pressId") == press["id"]
            for recipe in live_all
        )
        if not matched:
            board_mismatch.append(press)
    items = [
        {"key": "no-erp", "route": "products", "who": ["manager", "planner"], "title": "Products without an ERP code", "benefit": "Orders and stock can be matched to a product and its recipes. Until then the system cannot answer what is owed and whether it can be made.", "ids": [product["id"] for product in graph["products"] if not product.get("erpCode")]},
        {"key": "no-recipe", "route": "products", "who": ["engineer", "planner"], "title": "Products with no recipe", "benefit": "Each name either gets a mold and a recipe or is retired. The setter can then start any product from the record.", "ids": [product["id"] for product in graph["products"] if not live(index["recipesByProduct"].get(product["id"]) or [])]},
        {"key": "no-cavities", "route": "molds", "who": ["planner", "manager"], "title": "Molds without a cavity count", "benefit": "Pieces per hour per press. It is the base of every schedule and every capacity answer. Enter cavities on a mold and the number appears on all its recipes.", "ids": [mold["id"] for mold in graph["molds"] if not mold.get("cavities")]},
        {"key": "no-shot", "route": "molds", "who": ["manager"], "title": "Molds without a shot weight", "benefit": "Material consumed per piece, so a run can be costed and resin ordered against a plan.", "ids": [mold["id"] for mold in graph["molds"] if not mold.get("shotWeight")]},
        {"key": "no-cycle", "route": "recipes", "who": ["planner"], "title": "Recipes without a cycle time", "benefit": "Hours per order can be computed for these products.", "ids": [recipe["id"] for recipe in live_all if not num(recipe.get("cycle"))]},
        {"key": "dup-standard", "route": "recipes", "who": ["engineer"], "title": "Same color on the same press, more than one recipe, none marked standard", "benefit": "The setter gets one answer instead of choosing between rows. Mark one recipe as standard on its page.", "ids": [recipe["id"] for recipe in duplicates]},
        {"key": "trial", "route": "recipes", "who": ["engineer"], "title": "Recipes in the trial block (sheet rows 2–16)", "benefit": "Confirm or delete. Temperatures there step by 10 °C; they distort which presses a product can run on.", "ids": [recipe["id"] for recipe in graph["recipes"] if recipe.get("trial")]},
        {"key": "no-base", "route": "recipes", "who": ["engineer"], "title": "Setups with no resin or regrind (colors or additives only)", "benefit": "Nothing can be produced from these records. The base material has to be written before the setter can start the job.", "ids": [recipe["id"] for recipe in live_all if not has_base(index, recipe)]},
        {"key": "no-changeover", "route": "presses", "who": ["planner"], "title": "Presses without a changeover time", "benefit": "Mold and color changes can be sequenced with real durations. Without it a schedule is a wish list.", "ids": [press["id"] for press in graph["presses"] if not press.get("changeoverMin")]},
        {"key": "links-open", "route": "products", "who": ["manager"], "title": "Lid–body links with the sold item unknown", "benefit": "Set bills of materials and packing lists. Today these are name matches only.", "ids": uniq([code for link in graph["links"] for code in (link.get("lidId"), link.get("partId"))])},
        {"key": "mat-no-code", "route": "materials", "who": ["manager"], "title": "Raw materials without an accounting code", "benefit": "Purchasing and stock reconcile with what production actually feeds.", "ids": [material["id"] for material in graph["materials"] if not material.get("account")]},
        {"key": "mat-unused", "route": "materials", "who": ["manager"], "title": "Catalog materials never used on a recipe", "benefit": "The stock list matches what production uses; the rest is questioned.", "ids": [material["id"] for material in graph["materials"] if not (index["recipesByMaterial"].get(material["id"]) or [])]},
        {"key": "board-mismatch", "route": "presses", "who": ["engineer", "planner"], "title": "Board shows a product with no recipe on that press", "benefit": "The floor board and the recipes agree; a mounted mold always has its setting sheet.", "ids": [press["id"] for press in board_mismatch]},
        {"key": "press-no-recipe", "route": "presses", "who": ["planner"], "title": "Presses with no recipe at all", "benefit": "Either the press is retired from planning or its capabilities are recorded.", "ids": [press["id"] for press in graph["presses"] if not (index["recipesByPress"].get(press["id"]) or [])]},
        {"key": "approved-no-recipe", "route": "products", "who": ["planner", "engineer"], "title": "Approved on a press in the product sheet, but no recipe there", "benefit": "Every press a planner may book has a setting sheet, so a job can move presses without a trial run.", "ids": [product["id"] for product in graph["products"] if approved_without_recipe(graph, product)]},
        {"key": "stoppage-open", "route": "recipes", "who": ["engineer", "manager"], "title": "Recipes with a stoppage that has no usable restart time", "benefit": "Downtime per press and per mold can be totalled, and repeat faults show up by hours lost.", "ids": uniq([recipe["id"] for recipe in graph["recipes"] if any(issue_state(issue) != "closed" for issue in recipe.get("issues") or [])])},
    ]
    published = []
    for item in items:
        published.append({
            "key": item["key"],
            "route": item["route"],
            "kind": ROUTE_KIND[item["route"]],
            "who": item["who"],
            "title": item["title"],
            "benefit": item["benefit"],
            "count": len(item["ids"]),
            "ids": item["ids"],
        })
    return published


def counts(graph):
    index = _ix(graph)
    return {
        "products": len(graph.get("products") or []),
        "withRecipe": sum(1 for product in graph.get("products") or [] if live(index["recipesByProduct"].get(product["id"]) or [])),
        "molds": len(graph.get("molds") or []),
        "presses": len(graph.get("presses") or []),
        "onBoard": sum(1 for press in graph.get("presses") or [] if (press.get("board") or {}).get("mounted")),
        "recipes": len(graph.get("recipes") or []),
        "liveRecipes": len(live(graph.get("recipes") or [])),
        "trialRecipes": sum(1 for recipe in graph.get("recipes") or [] if recipe.get("trial")),
        "variants": sum(len(variants_of(graph, product)) for product in graph.get("products") or []),
        "materials": len(graph.get("materials") or []),
        "colors": len(graph.get("colors") or []),
        "links": len(graph.get("links") or []),
        "stoppages": sum(len(recipe.get("issues") or []) for recipe in graph.get("recipes") or []),
        "downtimeHours": round(sum(downtime_hours(issue) or 0 for recipe in graph.get("recipes") or [] for issue in recipe.get("issues") or []), 1),
    }


def approved_without_recipe(graph, product):
    index = _ix(graph)
    running = set(recipe.get("pressId") for recipe in live(index["recipesByProduct"].get(product["id"]) or []))
    return [code for code in product.get("approvedPressIds") or [] if code in index["press"] and code not in running]


def approved_presses(graph, product):
    index = _ix(graph)
    running = set(recipe.get("pressId") for recipe in live(index["recipesByProduct"].get(product["id"]) or []))
    approved = set(product.get("approvedPressIds") or [])
    rows = []
    for press in graph.get("presses") or []:
        if press["id"] in approved or press["id"] in running:
            rows.append({
                "id": press["id"],
                "name": press.get("name") or press["id"],
                "approved": press["id"] in approved,
                "hasRecipe": press["id"] in running,
            })
    return rows


def issue_rows(graph, recipes):
    index = _ix(graph)
    rows = []
    for recipe in recipes or []:
        for position, issue in enumerate(recipe.get("issues") or []):
            hours = downtime_hours(issue)
            state = issue_state(issue)
            rows.append({
                "id": recipe["id"],
                "key": "%s:%s" % (recipe["id"], position),
                "index": position,
                "product": product_name(index, recipe.get("productId")),
                "productId": recipe.get("productId") or "",
                "press": press_name(index, recipe.get("pressId")),
                "pressId": recipe.get("pressId") or "",
                "start": " ".join(part for part in (issue.get("startDate"), issue.get("startTime")) if part),
                "end": " ".join(part for part in (issue.get("endDate"), issue.get("endTime")) if part),
                "cause": issue.get("cause") or "",
                "worker": issue.get("worker") or "",
                "fix": issue.get("fix") or "",
                "hours": hours,
                "state": state,
                "status": "Closed" if state == "closed" else cap(state),
                "tone": {"closed": "ok", "check dates": "bad"}.get(state, "warn"),
            })
    rows.sort(key=lambda row: (row["state"] != "check dates", row["start"]), reverse=True)
    return rows


def _status_row(status):
    return {"status": status, "tone": tone(status)}


def recipe_row(graph, recipe):
    index = _ix(graph)
    status = setup_status(graph, recipe)
    row = {
        "id": recipe["id"],
        "product": product_name(index, recipe.get("productId")),
        "productId": recipe.get("productId") or "",
        "mold": recipe.get("moldId") or "",
        "press": press_name(index, recipe.get("pressId")),
        "pressId": recipe.get("pressId") or "",
        "variant": variant_label(index, recipe),
        "cycle": num(recipe.get("cycle")),
        "cooling": num(recipe.get("cooling")),
        "pph": pieces_per_hour(index, recipe),
        "materials": [material_name(index, code) for code in material_ids(recipe)],
        "colors": [color_short(index, code) for code in color_ids(recipe)],
        "lot": recipe.get("productLot") or "",
    }
    row.update(_status_row(status))
    return row


def summary_rows(graph, recipes):
    index = _ix(graph)
    source = live(recipes) or list(recipes or [])
    rows = []
    for product_id in uniq([recipe.get("productId") for recipe in source]):
        listed = [recipe for recipe in source if recipe.get("productId") == product_id]
        if not listed:
            continue
        product = index["product"].get(product_id)
        rows.append({
            "id": product_id,
            "name": product_name(index, product_id),
            "mold": listed[0].get("moldId") or "",
            "presses": uniq([press_name(index, recipe.get("pressId")) for recipe in listed]),
            "recipes": len(listed),
            "cycle": best_cycle(listed),
            "colors": uniq([color_short(index, code) for recipe in listed for code in color_ids(recipe)]),
            "status": product_status(graph, product) if product else "",
            "tone": tone(product_status(graph, product) if product else ""),
        })
    return rows


def _product_rows(graph):
    index = _ix(graph)
    rows = []
    for product in graph.get("products") or []:
        all_recipes = index["recipesByProduct"].get(product["id"]) or []
        live_recipes = live(all_recipes)
        status = product_status(graph, product)
        rows.append({
            "id": product["id"],
            "name": product.get("name") or "",
            "type": TYPES.get(product.get("type"), product.get("type") or ""),
            "erp": product.get("erpCode") or "",
            "mold": ", ".join(mold["id"] for mold in index["moldsByProduct"].get(product["id"]) or []),
            "presses": uniq([press_name(index, recipe.get("pressId")) for recipe in live_recipes]),
            "variants": len(variants_of(graph, product)),
            "recipes": len(live_recipes),
            "trial": len(all_recipes) - len(live_recipes),
            "materials": uniq([material_name(index, code) for recipe in live_recipes for code in material_ids(recipe)]),
            "colors": uniq([color_short(index, code) for recipe in live_recipes for code in color_ids(recipe)]),
            "approved": [press_name(index, code) for code in product.get("approvedPressIds") or [] if code in index["press"]],
            "links": len(product_links(graph, product)),
            "status": status,
            "tone": tone(status),
        })
    return rows


def _mold_rows(graph):
    index = _ix(graph)
    rows = []
    for mold in graph.get("molds") or []:
        live_recipes = live(index["recipesByMold"].get(mold["id"]) or [])
        status = mold_status(graph, mold)
        rows.append({
            "id": mold["id"],
            "name": mold.get("name") or "",
            "product": product_name(index, mold.get("productId")),
            "productId": mold.get("productId") or "",
            "presses": uniq([press_name(index, recipe.get("pressId")) for recipe in live_recipes]),
            "recipes": len(live_recipes),
            "cavities": mold.get("cavities"),
            "shot": mold.get("shotWeight"),
            "location": mold.get("location") or "",
            "status": status,
            "tone": tone(status),
        })
    return rows


def _press_rows(graph):
    index = _ix(graph)
    rows = []
    for press in graph.get("presses") or []:
        live_recipes = live(index["recipesByPress"].get(press["id"]) or [])
        board = press.get("board") or {}
        status = press_status(graph, press)
        robot = press.get("robot") or ""
        rows.append({
            "id": press["id"],
            "name": press.get("name") or "",
            "euromap": press.get("euromap") or "",
            "robot": "" if robot in ("", "-") else robot,
            "molds": len(uniq([recipe.get("moldId") for recipe in live_recipes])),
            "recipes": len(live_recipes),
            "board": " · ".join(part for part in (board.get("mounted"), board.get("location")) if part),
            "changeover": press.get("changeoverMin"),
            "status": status,
            "tone": tone(status),
        })
    return rows


def _recipe_rows(graph):
    return [recipe_row(graph, recipe) for recipe in graph.get("recipes") or []]


def _material_rows(graph):
    index = _ix(graph)
    rows = []
    for material in graph.get("materials") or []:
        used = live(index["recipesByMaterial"].get(material["id"]) or [])
        status = material_status(graph, material)
        rows.append({
            "id": material["id"],
            "text": material.get("text") or "",
            "kind": MATERIAL_KINDS.get(material.get("kind"), material.get("kind") or ""),
            "supplier": material.get("supplier") or "",
            "family": material.get("family") or "",
            "mfi": num(material.get("mfi")),
            "account": material.get("account") or "",
            "recipes": len(used),
            "products": len(uniq([recipe.get("productId") for recipe in used])),
            "status": status,
            "tone": tone(status),
        })
    return rows


def _color_rows(graph):
    index = _ix(graph)
    rows = []
    for color in graph.get("colors") or []:
        used = live(index["recipesByColor"].get(color["id"]) or [])
        status = color_status(graph, color)
        rows.append({
            "id": color["id"],
            "name": color.get("name") or "",
            "code": color.get("code") or "",
            "label": color.get("label") or "",
            "account": color.get("account") or "",
            "recipes": len(used),
            "products": len(uniq([recipe.get("productId") for recipe in used])),
            "status": status,
            "tone": tone(status),
        })
    return rows


_LISTS = {
    "product": _product_rows,
    "mold": _mold_rows,
    "press": _press_rows,
    "recipe": _recipe_rows,
    "material": _material_rows,
    "color": _color_rows,
    "issue": lambda graph: issue_rows(graph, graph.get("recipes")),
}


def list_view(graph, kind, gap_key=None):
    if kind not in _LISTS:
        return {"error": "Unknown list."}
    rows = _LISTS[kind](graph)
    banner = None
    if gap_key:
        match = None
        for item in gaps(graph):
            if item["key"] == gap_key and item["kind"] == kind:
                match = item
                break
        if match:
            wanted = set(match["ids"])
            rows = [row for row in rows if row["id"] in wanted]
            banner = {"count": match["count"], "title": match["title"], "benefit": match["benefit"]}
    return {"kind": kind, "rows": rows, "banner": banner}


def _public_gap(item):
    return {key: item[key] for key in ("key", "kind", "route", "who", "title", "benefit", "count")}


def overview(graph, who="all"):
    index = _ix(graph)
    persona = who or "all"
    all_gaps = gaps(graph)
    shown = [item for item in all_gaps if item["count"] and (persona == "all" or persona in item["who"])]
    done = [item["title"] for item in all_gaps if not item["count"]]
    live_all = live(graph.get("recipes") or [])
    cards = []
    for press in graph.get("presses") or []:
        mounted = (press.get("board") or {}).get("mounted") or ""
        product = None
        if mounted:
            for candidate in graph.get("products") or []:
                if candidate["name"].strip().upper() == mounted.strip().upper():
                    product = candidate
                    break
        matched = []
        if product:
            matched = [
                recipe for recipe in live(index["recipesByPress"].get(press["id"]) or [])
                if recipe.get("productId") == product["id"]
            ]
        best = best_cycle(matched)
        rates = [rate for rate in (pieces_per_hour(index, recipe) for recipe in matched) if rate]
        mold_count = len(uniq([recipe.get("moldId") for recipe in live(index["recipesByPress"].get(press["id"]) or [])]))
        cards.append({
            "id": press["id"],
            "name": press.get("name") or "",
            "euromap": press.get("euromap") or "",
            "mounted": mounted,
            "location": (press.get("board") or {}).get("location") or "",
            "idle": not mounted,
            "cycle": best,
            "pph": max(rates) if rates else None,
            "hasRecipe": bool(matched),
            "moldCount": mold_count,
            "changeover": press.get("changeoverMin"),
        })
    chart_labels = []
    chart_values = []
    for press in graph.get("presses") or []:
        chart_labels.append(press.get("name") or press["id"])
        chart_values.append(len(live(index["recipesByPress"].get(press["id"]) or [])))
    return {
        "who": persona,
        "presses": cards,
        "gaps": [_public_gap(item) for item in shown],
        "done": done,
        "counts": counts(graph),
        "chart": {"labels": chart_labels, "values": chart_values, "downtime": [
            round(sum(downtime_hours(issue) or 0 for recipe in index["recipesByPress"].get(press["id"]) or [] for issue in recipe.get("issues") or []), 1)
            for press in graph.get("presses") or []
        ]},
        "liveRecipes": len(live_all),
        "stoppages": issue_rows(graph, graph.get("recipes") or [])[:6],
    }


def structure(graph):
    return counts(graph)


def choices(graph):
    index = _ix(graph)
    return {
        "presses": [{"value": press["id"], "label": press.get("name") or press["id"]} for press in graph.get("presses") or []],
        "products": [{"value": product["id"], "label": "%s (%s)" % (product.get("name") or product["id"], product["id"])} for product in graph.get("products") or []],
        "materials": [{"value": material["id"], "label": "%s%s" % (material.get("text") or material["id"], (" · " + material["account"]) if material.get("account") else "")} for material in graph.get("materials") or []],
        "colors": [{"value": color["id"], "label": color_name(index, color["id"])} for color in graph.get("colors") or []],
        "types": [{"value": key, "label": label} for key, label in TYPES.items()],
        "kinds": [{"value": key, "label": label} for key, label in MATERIAL_KINDS.items()],
        "lifecycles": [{"value": value, "label": cap(value)} for value in LIFECYCLES],
        "moldStatuses": [{"value": value, "label": value} for value in MOLD_STATUSES],
        "workers": [{"value": name, "label": name} for name in graph.get("workers") or []],
    }


def _flow_recipe(graph, recipe):
    index = _ix(graph)
    return {
        "id": recipe["id"],
        "trial": bool(recipe.get("trial")),
        "standard": bool(recipe.get("standard")),
        "cycle": num(recipe.get("cycle")),
        "label": variant_label(index, recipe),
        "pph": pieces_per_hour(index, recipe),
        "materials": [{
            "id": code,
            "label": material_name(index, code),
            "account": (index["material"].get(code) or {}).get("account") or "",
        } for code in material_ids(recipe)],
        "colors": [{
            "id": code,
            "label": color_short(index, code),
            "account": (index["color"].get(code) or {}).get("account") or "",
        } for code in color_ids(recipe)],
    }


def _flow(graph, product):
    index = _ix(graph)
    all_recipes = index["recipesByProduct"].get(product["id"]) or []
    molds = index["moldsByProduct"].get(product["id"]) or []
    mold = molds[0] if molds else None
    by_press = group_by(all_recipes, "pressId")
    groups = []
    for press in graph.get("presses") or []:
        listed = by_press.get(press["id"])
        if not listed:
            continue
        groups.append({
            "pressId": press["id"],
            "pressName": press.get("name") or press["id"],
            "recipes": [_flow_recipe(graph, recipe) for recipe in listed],
        })
    return {
        "productId": product["id"],
        "productName": product.get("name") or "",
        "erpCode": product.get("erpCode") or "",
        "mold": None if mold is None else {"id": mold["id"], "name": mold.get("name") or "", "cavities": mold.get("cavities")},
        "groups": groups,
        "liveCount": len(live(all_recipes)),
    }


def _runs(graph, product):
    index = _ix(graph)
    live_recipes = live(index["recipesByProduct"].get(product["id"]) or [])
    molds = index["moldsByProduct"].get(product["id"]) or []
    mold = molds[0] if molds else None
    by_press = group_by(live_recipes, "pressId")
    runs = []
    for press in graph.get("presses") or []:
        listed = by_press.get(press["id"])
        if not listed:
            continue
        cycles = [cycle for cycle in (num(recipe.get("cycle")) for recipe in listed) if cycle is not None]
        same = bool(cycles) and all(cycle == cycles[0] for cycle in cycles)
        if not cycles:
            cycle_label = "cycle not written"
        elif same:
            cycle_label = "%s s" % trim_num(cycles[0])
        else:
            cycle_label = "best %s s" % trim_num(min(cycles))
        by_color = group_by(
            [{"key": variant_key(recipe) or "natural", "recipe": recipe} for recipe in listed],
            "key",
        )
        needs_standard = any(
            len(items) > 1 and not any(item["recipe"].get("standard") for item in items)
            for items in by_color.values()
        )
        mounted = (press.get("board") or {}).get("mounted") or ""
        ways = []
        for recipe in listed:
            ways.append({
                "id": recipe["id"],
                "colors": [{"id": code, "label": color_short(index, code)} for code in color_ids(recipe)],
                "materials": [{"id": code, "label": material_name(index, code)} for code in material_ids(recipe)],
                "standard": bool(recipe.get("standard")),
                "canProduce": has_base(index, recipe),
                "cycle": num(recipe.get("cycle")),
                "showCycle": not same,
            })
        runs.append({
            "pressId": press["id"],
            "pressName": press.get("name") or press["id"],
            "moldId": mold["id"] if mold else "",
            "cycleLabel": cycle_label,
            "onBoard": bool(mounted) and mounted.strip().upper() == (product.get("name") or "").strip().upper(),
            "colorWays": len(by_color),
            "needsStandard": needs_standard,
            "ways": ways,
        })
    return runs


def _plural(count, one, many=None):
    many = many or (one + "s")
    return "%s %s" % (count, one if count == 1 else many)


def _product_missing(graph, product):
    index = _ix(graph)
    all_recipes = index["recipesByProduct"].get(product["id"]) or []
    live_recipes = live(all_recipes)
    molds = index["moldsByProduct"].get(product["id"]) or []
    mold = molds[0] if molds else None
    links = product_links(graph, product)
    missing = []
    without_base = [recipe for recipe in live_recipes if not has_base(index, recipe)]
    if without_base:
        missing.append({"what": "Base material on %s" % _plural(len(without_base), "setup"), "why": "Colors or additives only; nothing can be produced from that record.", "action": ""})
    if not product.get("erpCode"):
        missing.append({"what": "ERP code", "why": "Orders and stock cannot be matched to this product.", "action": "edit-product"})
    if mold and not mold.get("cavities"):
        missing.append({"what": "Cavities on the mold", "why": "Pieces per hour cannot be computed.", "action": "edit-mold"})
    if mold and not mold.get("shotWeight"):
        missing.append({"what": "Shot weight on the mold", "why": "Material per piece and cost are unknown.", "action": "edit-mold"})
    unbooked = approved_without_recipe(graph, product)
    if unbooked:
        names = ", ".join(press_name(index, code) for code in unbooked)
        missing.append({"what": "Recipe on %s" % names, "why": "The product sheet approves %s, but there is no setting sheet for it." % ("this press" if len(unbooked) == 1 else "these presses"), "action": "add-recipe"})
    without_cycle = [recipe for recipe in live_recipes if not num(recipe.get("cycle"))]
    if without_cycle:
        missing.append({"what": "Cycle time on %s" % _plural(len(without_cycle), "recipe"), "why": "Hours per order cannot be computed.", "action": ""})
    for variant in variants_of(graph, product):
        by_press = group_by([recipe for recipe in variant["recipes"] if not recipe.get("trial")], "pressId")
        if any(len(listed) > 1 and not any(recipe.get("standard") for recipe in listed) for listed in by_press.values()):
            missing.append({"what": "Standard recipe", "why": "Several rows for the same color on the same press; the setter has to choose.", "action": ""})
            break
    if len(all_recipes) > len(live_recipes):
        missing.append({"what": _plural(len(all_recipes) - len(live_recipes), "trial row").capitalize(), "why": "Confirm or delete so the press list is true.", "action": ""})
    if links:
        missing.append({"what": "Sold item on linked parts", "why": "The bill of materials is still a name match.", "action": ""})
    return missing


def _first_mold(index, product_id):
    molds = index["moldsByProduct"].get(product_id) or []
    return molds[0] if molds else None


def detail_product(graph, code):
    index = _ix(graph)
    product = index["product"].get(code)
    if product is None:
        return {"missing": True, "kind": "product", "id": code}
    all_recipes = index["recipesByProduct"].get(code) or []
    live_recipes = live(all_recipes)
    mold = _first_mold(index, code)
    status = product_status(graph, product)
    return {
        "kind": "product",
        "missing": False,
        "id": product["id"],
        "name": product.get("name") or "",
        "status": status,
        "tone": tone(status),
        "type": product.get("type") or "part",
        "typeLabel": TYPES.get(product.get("type"), product.get("type") or ""),
        "lifecycle": product.get("lifecycle") or "active",
        "erpCode": product.get("erpCode") or "",
        "legacyId": product.get("legacyId") or "",
        "notes": product.get("notes") or "",
        "mold": None if mold is None else {
            "id": mold["id"],
            "cavities": mold.get("cavities"),
            "shotWeight": mold.get("shotWeight"),
            "location": mold.get("location") or "",
            "status": mold.get("status") or "in use",
        },
        "flow": _flow(graph, product),
        "runs": _runs(graph, product),
        "links": product_links(graph, product),
        "missingBits": _product_missing(graph, product),
        "approvedPresses": approved_presses(graph, product),
        "approvedPressIds": list(product.get("approvedPressIds") or []),
        "issues": issue_rows(graph, all_recipes),
        "recipes": [recipe_row(graph, recipe) for recipe in all_recipes],
        "trialCount": len(all_recipes) - len(live_recipes),
        "liveRecipes": [{
            "value": recipe["id"],
            "label": "%s · %s · %s" % (recipe["id"], press_name(index, recipe.get("pressId")), variant_label(index, recipe)),
        } for recipe in live_recipes],
    }


def detail_mold(graph, code):
    index = _ix(graph)
    mold = index["mold"].get(code)
    if mold is None:
        return {"missing": True, "kind": "mold", "id": code}
    status = mold_status(graph, mold)
    recipes = index["recipesByMold"].get(code) or []
    return {
        "kind": "mold",
        "missing": False,
        "id": mold["id"],
        "name": mold.get("name") or "",
        "status": status,
        "tone": tone(status),
        "productId": mold.get("productId") or "",
        "productName": product_name(index, mold.get("productId")),
        "cavities": mold.get("cavities"),
        "shotWeight": mold.get("shotWeight"),
        "location": mold.get("location") or "",
        "moldStatus": mold.get("status") or "in use",
        "recipes": [recipe_row(graph, recipe) for recipe in recipes],
    }


def detail_press(graph, code):
    index = _ix(graph)
    press = index["press"].get(code)
    if press is None:
        return {"missing": True, "kind": "press", "id": code}
    board = press.get("board") or {}
    recipes = index["recipesByPress"].get(code) or []
    status = press_status(graph, press)
    robot = press.get("robot") or ""
    return {
        "kind": "press",
        "missing": False,
        "id": press["id"],
        "name": press.get("name") or "",
        "status": status,
        "tone": tone(status),
        "alias": press.get("alias") or "",
        "euromap": press.get("euromap") or "",
        "serial": press.get("serial") or "",
        "robot": "" if robot in ("", "-") else robot,
        "robotSerial": press.get("robotSerial") or "",
        "robotYear": press.get("robotYear") or "",
        "lifecycle": press.get("lifecycle") or "active",
        "changeoverMin": press.get("changeoverMin"),
        "mounted": board.get("mounted") or "",
        "location": board.get("location") or "",
        "products": summary_rows(graph, recipes),
        "approved": _approved_on_press(graph, press),
        "recipes": [recipe_row(graph, recipe) for recipe in recipes],
        "issues": issue_rows(graph, recipes),
    }


def _approved_on_press(graph, press):
    index = _ix(graph)
    rows = []
    for product in graph.get("products") or []:
        if press["id"] not in (product.get("approvedPressIds") or []):
            continue
        listed = [recipe for recipe in live(index["recipesByProduct"].get(product["id"]) or []) if recipe.get("pressId") == press["id"]]
        status = "Has recipe" if listed else "No recipe here"
        rows.append({
            "id": product["id"],
            "name": product.get("name") or "",
            "mold": ", ".join(mold["id"] for mold in index["moldsByProduct"].get(product["id"]) or []),
            "presses": [press.get("name") or press["id"]],
            "recipes": len(listed),
            "cycle": best_cycle(listed),
            "colors": uniq([color_short(index, code) for recipe in listed for code in color_ids(recipe)]),
            "status": status,
            "tone": "ok" if listed else "warn",
        })
    return rows


def detail_recipe(graph, code):
    index = _ix(graph)
    recipe = index["recipe"].get(code)
    if recipe is None:
        return {"missing": True, "kind": "recipe", "id": code}
    status = setup_status(graph, recipe)
    siblings = [
        other["id"] for other in live(index["recipesByProduct"].get(recipe.get("productId")) or [])
        if other.get("pressId") == recipe.get("pressId") and variant_key(other) == variant_key(recipe) and other["id"] != recipe["id"]
    ]
    pph = pieces_per_hour(index, recipe)
    if pph:
        pph_hint = ""
    elif num(recipe.get("cycle")):
        pph_hint = "needs cavities"
    else:
        pph_hint = "needs cycle"
    material_slots = []
    for position, slot in enumerate(recipe.get("materialSlots") or []):
        item = index["material"].get(slot.get("materialId")) or {}
        material_slots.append({
            "index": position,
            "id": slot.get("materialId") or "",
            "name": material_name(index, slot.get("materialId")),
            "account": item.get("account") or "",
            "lot": slot.get("lot") or "",
        })
    color_slots = []
    for position, slot in enumerate(recipe.get("colorSlots") or []):
        item = index["color"].get(slot.get("colorId")) or {}
        color_slots.append({
            "index": position,
            "id": slot.get("colorId") or "",
            "name": color_name(index, slot.get("colorId")),
            "account": item.get("account") or "",
            "lot": slot.get("lot") or "",
        })
    return {
        "kind": "recipe",
        "missing": False,
        "id": recipe["id"],
        "status": status,
        "tone": tone(status),
        "trial": bool(recipe.get("trial")),
        "standard": bool(recipe.get("standard")),
        "productId": recipe.get("productId") or "",
        "productName": product_name(index, recipe.get("productId")),
        "pressId": recipe.get("pressId") or "",
        "pressName": press_name(index, recipe.get("pressId")),
        "moldId": recipe.get("moldId") or "",
        "cycle": recipe.get("cycle") or "",
        "cooling": recipe.get("cooling") or "",
        "screwRpm": recipe.get("screwRpm") or "",
        "pph": pph,
        "pphHint": pph_hint,
        "productLot": recipe.get("productLot") or "",
        "legacyId": recipe.get("legacyId"),
        "siblings": siblings,
        "zones": [{"key": key, "label": label, "value": (recipe.get("temps") or {}).get(key) or ""} for key, label in TEMP_LABELS],
        "temps": {key: (recipe.get("temps") or {}).get(key) or "" for key in TEMP_KEYS},
        "materialSlots": material_slots,
        "colorSlots": color_slots,
        "settings": [{"label": item.get("label") or "", "value": item.get("value") or ""} for item in recipe.get("settings") or []],
        "px": recipe.get("px") or "",
        "py": recipe.get("py") or "",
        "printPieces": recipe.get("printPieces") or "",
        "printTotal": recipe.get("printTotal") or "",
        "statusText": recipe.get("status") or "",
        "comment": recipe.get("comment") or "",
        "settingsNote": recipe.get("settingsNote") or "",
        "issues": issue_rows(graph, [recipe]),
        "rawIssues": [dict(issue, index=position) for position, issue in enumerate(recipe.get("issues") or [])],
    }


def detail_material(graph, code):
    index = _ix(graph)
    material = index["material"].get(code)
    if material is None:
        return {"missing": True, "kind": "material", "id": code}
    recipes = index["recipesByMaterial"].get(code) or []
    status = material_status(graph, material)
    link = material.get("link") or ""
    if not (link.startswith("https://") or link.startswith("http://")):
        link = ""
    return {
        "kind": "material",
        "missing": False,
        "id": material["id"],
        "name": material.get("text") or "",
        "status": status,
        "tone": tone(status),
        "kindLabel": MATERIAL_KINDS.get(material.get("kind"), material.get("kind") or ""),
        "supplier": material.get("supplier") or "",
        "family": material.get("family") or "",
        "mfi": material.get("mfi") or "",
        "account": material.get("account") or "",
        "invoiceCode": material.get("invoiceCode") or "",
        "description": material.get("description") or "",
        "notes": material.get("notes") or "",
        "kind": material.get("kind") or "resin",
        "catalog": bool(material.get("catalog")),
        "link": link,
        "rawLink": material.get("link") or "",
        "products": summary_rows(graph, recipes),
        "recipes": [recipe_row(graph, recipe) for recipe in recipes],
    }


def detail_color(graph, code):
    index = _ix(graph)
    color = index["color"].get(code)
    if color is None:
        return {"missing": True, "kind": "color", "id": code}
    recipes = index["recipesByColor"].get(code) or []
    status = color_status(graph, color)
    return {
        "kind": "color",
        "missing": False,
        "id": color["id"],
        "name": color_name(index, color["id"]),
        "status": status,
        "tone": tone(status),
        "label": color.get("label") or "",
        "code": color.get("code") or "",
        "colorName": color.get("name") or "",
        "account": color.get("account") or "",
        "shade": color.get("shade") or "",
        "notes": color.get("notes") or "",
        "catalog": bool(color.get("catalog")),
        "link": color.get("link") or "" if (color.get("link") or "").startswith(("https://", "http://")) else "",
        "products": summary_rows(graph, recipes),
        "recipes": [recipe_row(graph, recipe) for recipe in recipes],
    }


_DETAILS = {
    "product": detail_product,
    "mold": detail_mold,
    "press": detail_press,
    "recipe": detail_recipe,
    "material": detail_material,
    "color": detail_color,
}


def detail(graph, kind, code):
    builder = _DETAILS.get(kind)
    if builder is None:
        return {"missing": True, "kind": kind, "id": code}
    return builder(graph, code)


_LOOKALIKE = str.maketrans("αβεζηικμνορτυχς", "abezhikmnoptyxσ")


def fold(text):
    """Lower case without accents, with Greek capitals that look Latin read as Latin (Α100 = A100)."""
    plain = unicodedata.normalize("NFD", str(text or "").lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return plain.translate(_LOOKALIKE)


def search(graph, term, limit=14):
    query = fold(term).strip()
    if len(query) < 2:
        return []
    index = _ix(graph)
    found = []

    def push(kind, code, label):
        if len(found) >= limit:
            return
        found.append({"kind": kind, "id": code, "label": label})

    def hit(*parts):
        return query in fold(" ".join(part or "" for part in parts))

    for product in graph.get("products") or []:
        if hit(product.get("name"), product["id"], product.get("erpCode")):
            push("product", product["id"], product.get("name") or product["id"])
    for mold in graph.get("molds") or []:
        if hit(mold["id"], mold.get("name")):
            push("mold", mold["id"], mold.get("name") or mold["id"])
    for press in graph.get("presses") or []:
        if hit(press.get("name"), press["id"], press.get("alias")):
            push("press", press["id"], press.get("name") or press["id"])
    for recipe in graph.get("recipes") or []:
        product, press = product_name(index, recipe.get("productId")), press_name(index, recipe.get("pressId"))
        if hit(recipe["id"], product, press):
            push("recipe", recipe["id"], "%s on %s" % (product, press))
    for material in graph.get("materials") or []:
        if hit(material.get("text"), material["id"], material.get("account")):
            push("material", material["id"], material.get("text") or material["id"])
    for color in graph.get("colors") or []:
        if hit(color_name(index, color["id"]), color["id"], color.get("account")):
            push("color", color["id"], color_name(index, color["id"]))
    return found


def _blank_recipe():
    return {
        "temps": {key: "" for key in TEMP_KEYS},
        "cycle": "",
        "cooling": "",
        "screwRpm": "",
        "settings": [],
        "px": "",
        "py": "",
        "productLot": "",
        "printPieces": "",
        "printTotal": "",
        "status": "",
        "comment": "",
        "materialSlots": [],
        "colorSlots": [],
        "issues": [],
        "settingsNote": "",
        "trial": False,
        "standard": False,
    }


def _redirect(kind, code):
    return {"redirect": {"kind": kind, "code": code}}


def _refresh(dirty):
    return {"refresh": True, "dirty": dirty}


def _require_name(payload, key="name"):
    name = (payload.get(key) or "").strip()
    if not name:
        return None
    return name


def action_new_product(graph, payload):
    name = _require_name(payload)
    if not name:
        return {"error": "Name is required."}
    product = {
        "id": next_id("PRD", graph["products"], 4),
        "name": name,
        "legacyId": "",
        "moldId": None,
        "erpCode": (payload.get("erp") or "").strip(),
        "type": payload.get("type") or "part",
        "notes": "",
        "lifecycle": "active",
        "onlyOnCards": False,
    }
    graph["products"].append(product)
    result = _redirect("product", product["id"])
    result["dirty"] = {"products": [product["id"]]}
    return result


def action_new_mold(graph, payload):
    name = _require_name(payload)
    product_id = payload.get("product") or ""
    if not name:
        return {"error": "Mold name is required."}
    if product_id not in _ix(graph)["product"]:
        return {"error": "Choose the product this mold makes."}
    mold = {
        "id": next_id("MLD", graph["molds"], 4),
        "name": name,
        "productId": product_id,
        "cavities": whole(payload.get("cavities")),
        "shotWeight": whole(payload.get("shot")),
        "location": "",
        "status": "in use",
    }
    graph["molds"].append(mold)
    result = _redirect("mold", mold["id"])
    result["dirty"] = {"molds": [mold["id"]]}
    return result


def action_new_press(graph, payload):
    name = _require_name(payload)
    if not name:
        return {"error": "Name is required."}
    press = {
        "id": next_id("PRS", graph["presses"], 2),
        "name": name,
        "alias": "",
        "aa": 99,
        "serial": "",
        "robot": "",
        "robotSerial": "",
        "euromap": (payload.get("euromap") or "").strip(),
        "board": {"mounted": "", "location": "", "note": ""},
        "changeoverMin": whole(payload.get("changeover")),
        "lifecycle": "active",
    }
    graph["presses"].append(press)
    result = _redirect("press", press["id"])
    result["dirty"] = {"presses": [press["id"]]}
    return result


def action_new_material(graph, payload):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "Grade is required."}
    material = {
        "id": next_id("MAT", graph["materials"], 3),
        "text": text,
        "kind": payload.get("kind") or "resin",
        "supplier": (payload.get("supplier") or "").strip(),
        "mfi": "",
        "family": (payload.get("family") or "").strip(),
        "account": (payload.get("account") or "").strip(),
        "invoiceCode": "",
        "description": "",
        "link": "",
        "catalog": True,
    }
    graph["materials"].append(material)
    result = _redirect("material", material["id"])
    result["dirty"] = {"materials": [material["id"]]}
    return result


def action_new_color(graph, payload):
    name = _require_name(payload)
    code = (payload.get("code") or "").strip()
    if not name or not code:
        return {"error": "Color and label code are required."}
    color = {
        "id": next_id("COL", graph["colors"], 3),
        "code": code,
        "name": name,
        "label": "",
        "account": (payload.get("account") or "").strip(),
        "shade": "",
        "link": "",
        "catalog": True,
    }
    graph["colors"].append(color)
    result = _redirect("color", color["id"])
    result["dirty"] = {"colors": [color["id"]]}
    return result


def action_edit_product(graph, payload):
    product = _ix(graph)["product"].get(payload.get("contextId"))
    if product is None:
        return {"error": "Product was not found."}
    name = _require_name(payload)
    if not name:
        return {"error": "Name is required."}
    product["name"] = name
    product["type"] = payload.get("type") or product.get("type") or "part"
    product["lifecycle"] = payload.get("lifecycle") or "active"
    product["erpCode"] = (payload.get("erpCode") or "").strip()
    product["notes"] = (payload.get("notes") or "").strip()
    return _refresh({"products": [product["id"]]})


def action_clone_product(graph, payload):
    index = _ix(graph)
    source = index["product"].get(payload.get("contextId"))
    if source is None:
        return {"error": "Product was not found."}
    product = copy.deepcopy(source)
    product["id"] = next_id("PRD", graph["products"], 4)
    product["name"] = (source.get("name") or "Product") + " (copy)"
    product["legacyId"] = ""
    product["onlyOnCards"] = False
    product["moldId"] = None
    graph["products"].append(product)
    dirty = {"products": [product["id"]], "molds": [], "recipes": []}
    for source_mold in list(index["moldsByProduct"].get(source["id"]) or []):
        mold = copy.deepcopy(source_mold)
        mold["id"] = next_id("MLD", graph["molds"], 4)
        mold["name"] = (source_mold.get("name") or "Mold") + " (copy)"
        mold["productId"] = product["id"]
        graph["molds"].append(mold)
        dirty["molds"].append(mold["id"])
        for source_recipe in list(index["recipesByMold"].get(source_mold["id"]) or []):
            recipe = copy.deepcopy(source_recipe)
            recipe["id"] = next_id("REC", graph["recipes"], 4)
            recipe["legacyId"] = None
            recipe["productId"] = product["id"]
            recipe["moldId"] = mold["id"]
            recipe["comment"] = "copy of %s" % source_recipe["id"]
            recipe["standard"] = False
            recipe["issues"] = []
            graph["recipes"].append(recipe)
            dirty["recipes"].append(recipe["id"])
    result = _redirect("product", product["id"])
    result["dirty"] = dirty
    return result


def _ensure_mold(graph, product_id):
    index = _ix(graph)
    molds = index["moldsByProduct"].get(product_id) or []
    if molds:
        return molds[0], []
    product = index["product"].get(product_id)
    if product is None:
        return None, []
    mold = {
        "id": next_id("MLD", graph["molds"], 4),
        "name": product.get("name") or "Mold",
        "productId": product_id,
        "cavities": None,
        "shotWeight": None,
        "location": "",
        "status": "in use",
    }
    graph["molds"].append(mold)
    return mold, [mold["id"]]


def _new_recipe(graph, product_id, press_id, source):
    mold, new_molds = _ensure_mold(graph, product_id)
    if mold is None:
        return None, [], "Product was not found."
    if press_id not in _ix(graph)["press"]:
        return None, [], "Choose a press."
    base = copy.deepcopy(source) if source else _blank_recipe()
    recipe = base
    recipe["id"] = next_id("REC", graph["recipes"], 4)
    recipe["legacyId"] = None
    recipe["productId"] = product_id
    recipe["moldId"] = mold["id"]
    recipe["pressId"] = press_id
    recipe["trial"] = False
    recipe["standard"] = False
    recipe["issues"] = []
    recipe["comment"] = ("copy of %s" % source["id"]) if source else "created in Cyclops"
    graph["recipes"].append(recipe)
    return recipe, new_molds, ""


def action_add_recipe(graph, payload):
    index = _ix(graph)
    product_id = payload.get("contextId")
    source = index["recipe"].get(payload.get("from")) if payload.get("from") else None
    recipe, new_molds, error = _new_recipe(graph, product_id, payload.get("press"), source)
    if error:
        return {"error": error}
    if payload.get("color"):
        recipe["colorSlots"] = [{"slot": 1, "colorId": payload.get("color"), "lot": ""}]
    result = _redirect("recipe", recipe["id"])
    result["dirty"] = {"recipes": [recipe["id"]], "molds": new_molds}
    return result


def _target_recipes(graph, payload):
    index = _ix(graph)
    live_recipes = live(index["recipesByProduct"].get(payload.get("contextId")) or [])
    chosen = payload.get("recipe") or "all"
    if chosen == "all":
        return live_recipes
    recipe = index["recipe"].get(chosen)
    return [recipe] if recipe else []


def action_add_material(graph, payload):
    material_id = payload.get("material")
    if material_id not in _ix(graph)["material"]:
        return {"error": "Choose a raw material."}
    targets = _target_recipes(graph, payload)
    if not targets:
        return {"error": "There is no live recipe to attach this material to."}
    dirty = []
    for recipe in targets:
        if any(slot.get("materialId") == material_id for slot in recipe.get("materialSlots") or []):
            continue
        recipe.setdefault("materialSlots", []).append({
            "slot": len(recipe["materialSlots"]) + 1,
            "materialId": material_id,
            "lot": "",
        })
        dirty.append(recipe["id"])
    return _refresh({"recipes": dirty})


def action_add_color(graph, payload):
    color_id = payload.get("color")
    if color_id not in _ix(graph)["color"]:
        return {"error": "Choose a color."}
    targets = _target_recipes(graph, payload)
    if not targets:
        return {"error": "There is no live recipe to attach this color to."}
    dirty = []
    for recipe in targets:
        if any(slot.get("colorId") == color_id for slot in recipe.get("colorSlots") or []):
            continue
        recipe.setdefault("colorSlots", []).append({
            "slot": len(recipe["colorSlots"]) + 1,
            "colorId": color_id,
            "lot": "",
        })
        dirty.append(recipe["id"])
    return _refresh({"recipes": dirty})


def action_add_link(graph, payload):
    other = payload.get("other")
    current = payload.get("contextId")
    index = _ix(graph)
    if other not in index["product"] or current not in index["product"]:
        return {"error": "Choose another product."}
    if other == current:
        return {"error": "Choose a different product."}
    if payload.get("relation") == "part":
        link = {"lidId": other, "partId": current, "basis": "manual"}
    else:
        link = {"lidId": current, "partId": other, "basis": "manual"}
    graph["links"].append(link)
    return _refresh({"links": ["*"]})


def action_remove_link(graph, payload):
    lid = payload.get("lidId")
    part = payload.get("partId")
    graph["links"] = [
        link for link in graph.get("links") or []
        if not (link.get("lidId") == lid and link.get("partId") == part)
    ]
    return _refresh({"links": ["*"]})


def _number_error(payload, checks):
    """Name the first changed field that is not a number. Unchanged sheet values pass as they are."""
    for key, label, current in checks:
        if key not in payload:
            continue
        text = str(payload.get(key) or "").strip()
        if not text or text == str(current if current is not None else "").strip() or num(text) is not None:
            continue
        return "%s has to be a number." % label
    return None


def action_edit_mold(graph, payload):
    index = _ix(graph)
    if payload.get("contextKind") == "mold":
        mold = index["mold"].get(payload.get("contextId"))
    else:
        mold = _first_mold(index, payload.get("contextId"))
    if mold is None:
        return {"error": "This record has no mold yet."}
    error = _number_error(payload, [("cavities", "Cavities", mold.get("cavities")), ("shotWeight", "Shot weight", mold.get("shotWeight"))])
    if error:
        return {"error": error}
    mold["cavities"] = whole(payload.get("cavities"))
    mold["shotWeight"] = whole(payload.get("shotWeight"))
    mold["location"] = (payload.get("location") or "").strip()
    status = payload.get("status") or "in use"
    mold["status"] = status if status in MOLD_STATUSES else "in use"
    return _refresh({"molds": [mold["id"]]})


def action_edit_press(graph, payload):
    press = _ix(graph)["press"].get(payload.get("contextId"))
    if press is None:
        return {"error": "Press was not found."}
    error = _number_error(payload, [("changeoverMin", "Changeover time", press.get("changeoverMin"))])
    if error:
        return {"error": error}
    lifecycle = payload.get("lifecycle") or "active"
    press["lifecycle"] = lifecycle if lifecycle in LIFECYCLES else "active"
    press["changeoverMin"] = whole(payload.get("changeoverMin"))
    for key in ("euromap", "serial", "robot", "robotSerial", "robotYear"):
        if key in payload:
            press[key] = (payload.get(key) or "").strip()
    board = press.get("board") or {}
    board["mounted"] = (payload.get("mounted") or "").strip()
    board["location"] = (payload.get("location") or "").strip()
    press["board"] = board
    return _refresh({"presses": [press["id"]]})


def action_set_approved(graph, payload):
    index = _ix(graph)
    product = index["product"].get(payload.get("contextId"))
    if product is None:
        return {"error": "Product was not found."}
    wanted = payload.get("presses") or []
    if isinstance(wanted, str):
        wanted = [code.strip() for code in wanted.split(",")]
    product["approvedPressIds"] = [press["id"] for press in graph.get("presses") or [] if press["id"] in wanted]
    return _refresh({"products": [product["id"]]})


def _issue_from(payload):
    issue = _issue(payload)
    if not issue["cause"]:
        return None, "Write what stopped the press."
    if not issue["startDate"] or _moment(issue["startDate"], issue["startTime"] or "00:00") is None:
        return None, "Give the stop date as YYYY-MM-DD and the time as HH:MM."
    if issue["endDate"] and _moment(issue["endDate"], issue["endTime"] or "00:00") is None:
        return None, "Give the restart date as YYYY-MM-DD and the time as HH:MM."
    if downtime_hours(issue) is None and issue_state(issue) == "check dates":
        return None, "The restart is before the stop."
    return issue, ""


def action_add_issue(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    issue, error = _issue_from(payload)
    if error:
        return {"error": error}
    recipe.setdefault("issues", []).append(issue)
    return _refresh({"recipes": [recipe["id"]]})


def action_edit_issue(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    try:
        position = int(payload.get("index"))
    except (TypeError, ValueError):
        return {"error": "That stoppage is no longer on the recipe."}
    issues = recipe.get("issues") or []
    if position < 0 or position >= len(issues):
        return {"error": "That stoppage is no longer on the recipe."}
    issue, error = _issue_from(payload)
    if error:
        return {"error": error}
    issues[position] = issue
    return _refresh({"recipes": [recipe["id"]]})


def action_remove_issue(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    try:
        position = int(payload.get("index"))
    except (TypeError, ValueError):
        return {"error": "That stoppage is no longer on the recipe."}
    issues = list(recipe.get("issues") or [])
    if position < 0 or position >= len(issues):
        return {"error": "That stoppage is no longer on the recipe."}
    del issues[position]
    recipe["issues"] = issues
    return _refresh({"recipes": [recipe["id"]]})


def action_edit_material(graph, payload):
    material = _ix(graph)["material"].get(payload.get("contextId"))
    if material is None:
        return {"error": "Raw material was not found."}
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "Grade is required."}
    material["text"] = text
    kind = payload.get("kind") or material.get("kind") or "resin"
    material["kind"] = kind if kind in MATERIAL_KINDS else "resin"
    for key in ("supplier", "family", "mfi", "account", "invoiceCode", "description", "notes", "link"):
        if key in payload:
            material[key] = (payload.get(key) or "").strip()
    material["catalog"] = True
    return _refresh({"materials": [material["id"]]})


def action_edit_color(graph, payload):
    color = _ix(graph)["color"].get(payload.get("contextId"))
    if color is None:
        return {"error": "Color was not found."}
    code = (payload.get("code") or "").strip()
    if not code:
        return {"error": "Label code is required."}
    color["code"] = code
    for key in ("name", "label", "account", "shade", "notes", "link"):
        if key in payload:
            color[key] = (payload.get(key) or "").strip()
    color["catalog"] = True
    return _refresh({"colors": [color["id"]]})


def action_delete_recipe(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    graph["recipes"] = [item for item in graph["recipes"] if item["id"] != recipe["id"]]
    result = _redirect("product", recipe.get("productId"))
    result["dirty"] = {"recipes": [recipe["id"]]}
    return result


def action_edit_recipe(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    temps = recipe.get("temps") or {}
    checks = [("temp_" + key, "%s temperature" % ("Nozzle" if key == "nozzle" else key.upper()), temps.get(key)) for key in TEMP_KEYS]
    checks += [("cycle", "Cycle", recipe.get("cycle")), ("cooling", "Cooling", recipe.get("cooling")), ("screwRpm", "Screw speed", recipe.get("screwRpm"))]
    error = _number_error(payload, checks)
    if error:
        return {"error": error}
    for key in TEMP_KEYS:
        temps[key] = (payload.get("temp_" + key) or "").strip()
    recipe["temps"] = temps
    recipe["cycle"] = (payload.get("cycle") or "").strip()
    recipe["cooling"] = (payload.get("cooling") or "").strip()
    recipe["screwRpm"] = (payload.get("screwRpm") or "").strip()
    recipe["productLot"] = (payload.get("productLot") or "").strip()
    for key in ("comment", "settingsNote"):
        if key in payload:
            recipe[key] = (payload.get(key) or "").strip()
    if recipe.get("trial"):
        recipe["trial"] = False
    return _refresh({"recipes": [recipe["id"]]})


def action_set_standard(graph, payload):
    index = _ix(graph)
    recipe = index["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    dirty = []
    for other in live(index["recipesByProduct"].get(recipe.get("productId")) or []):
        if other.get("pressId") == recipe.get("pressId") and variant_key(other) == variant_key(recipe):
            if other.get("standard"):
                other["standard"] = False
                dirty.append(other["id"])
    recipe["standard"] = True
    if recipe["id"] not in dirty:
        dirty.append(recipe["id"])
    return _refresh({"recipes": dirty})


def action_clone_recipe(graph, payload):
    source = _ix(graph)["recipe"].get(payload.get("contextId"))
    if source is None:
        return {"error": "Recipe was not found."}
    recipe, new_molds, error = _new_recipe(graph, source.get("productId"), source.get("pressId"), source)
    if error:
        return {"error": error}
    result = _redirect("recipe", recipe["id"])
    result["dirty"] = {"recipes": [recipe["id"]], "molds": new_molds}
    return result


def action_add_slot_material(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    material_id = payload.get("material")
    if recipe is None:
        return {"error": "Recipe was not found."}
    if material_id not in _ix(graph)["material"]:
        return {"error": "Choose a raw material."}
    recipe.setdefault("materialSlots", []).append({
        "slot": len(recipe["materialSlots"]) + 1,
        "materialId": material_id,
        "lot": (payload.get("lot") or "").strip(),
    })
    return _refresh({"recipes": [recipe["id"]]})


def action_add_slot_color(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    color_id = payload.get("color")
    if recipe is None:
        return {"error": "Recipe was not found."}
    if color_id not in _ix(graph)["color"]:
        return {"error": "Choose a color."}
    recipe.setdefault("colorSlots", []).append({
        "slot": len(recipe["colorSlots"]) + 1,
        "colorId": color_id,
        "lot": (payload.get("lot") or "").strip(),
    })
    return _refresh({"recipes": [recipe["id"]]})


def action_remove_slot(graph, payload):
    recipe = _ix(graph)["recipe"].get(payload.get("contextId"))
    if recipe is None:
        return {"error": "Recipe was not found."}
    key = "materialSlots" if payload.get("slotKind") == "material" else "colorSlots"
    try:
        index = int(payload.get("index"))
    except (TypeError, ValueError):
        return {"error": "That row is no longer on the recipe."}
    slots = list(recipe.get(key) or [])
    if index < 0 or index >= len(slots):
        return {"error": "That row is no longer on the recipe."}
    del slots[index]
    recipe[key] = slots
    return _refresh({"recipes": [recipe["id"]]})


ACTIONS = {
    "new-product": action_new_product,
    "new-mold": action_new_mold,
    "new-press": action_new_press,
    "new-material": action_new_material,
    "new-color": action_new_color,
    "edit-product": action_edit_product,
    "clone-product": action_clone_product,
    "add-recipe": action_add_recipe,
    "add-material": action_add_material,
    "add-color": action_add_color,
    "add-link": action_add_link,
    "remove-link": action_remove_link,
    "edit-mold": action_edit_mold,
    "edit-press": action_edit_press,
    "edit-recipe": action_edit_recipe,
    "set-standard": action_set_standard,
    "clone-recipe": action_clone_recipe,
    "add-slot-material": action_add_slot_material,
    "add-slot-color": action_add_slot_color,
    "remove-slot": action_remove_slot,
    "set-approved": action_set_approved,
    "add-issue": action_add_issue,
    "edit-issue": action_edit_issue,
    "remove-issue": action_remove_issue,
    "edit-material": action_edit_material,
    "edit-color": action_edit_color,
    "delete-recipe": action_delete_recipe,
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
