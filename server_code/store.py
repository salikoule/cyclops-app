import anvil.google.auth, anvil.google.drive, anvil.google.mail
from anvil.google.drive import app_files
"""Load and save the plant graph in Anvil tables.

The domain module always sees the sketch's shape. Tables are the storage
shape. The graph is cached for the life of the server process and written
through on each edit.
"""

import json
import os
import threading

from anvil.tables import app_tables

import domain

_LOCK = threading.Lock()
_CACHE = {"graph": None}
_SEED = os.path.join(os.path.dirname(__file__), "seed.json")


def _rows(table):
    try:
        return list(table.search())
    except IndexError:
        return list(table)


def _loads(text, fallback):
    if not text:
        return fallback
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return fallback
    return value


def _dumps(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _clear(table):
    for row in _rows(table):
        row.delete()


def _upsert(table, code, fields):
    row = table.get(code=code)
    if row is None:
        table.add_row(**fields)
    else:
        row.update(**fields)


def _product_fields(item):
    return {
        "code": item["id"],
        "name": item.get("name") or "",
        "legacy_id": item.get("legacyId") or "",
        "erp_code": item.get("erpCode") or "",
        "item_type": item.get("type") or "part",
        "notes": item.get("notes") or "",
        "lifecycle": item.get("lifecycle") or "active",
        "only_on_cards": bool(item.get("onlyOnCards")),
    }


def _mold_fields(item):
    return {
        "code": item["id"],
        "name": item.get("name") or "",
        "product_code": item.get("productId") or "",
        "cavities": item.get("cavities"),
        "shot_weight": item.get("shotWeight"),
        "location": item.get("location") or "",
        "status": item.get("status") or "in use",
    }


def _press_fields(item):
    board = item.get("board") or {}
    return {
        "code": item["id"],
        "name": item.get("name") or "",
        "alias": item.get("alias") or "",
        "aa": item.get("aa") if item.get("aa") is not None else 99,
        "serial": item.get("serial") or "",
        "robot": item.get("robot") or "",
        "robot_serial": item.get("robotSerial") or "",
        "euromap": item.get("euromap") or "",
        "mounted": board.get("mounted") or "",
        "board_location": board.get("location") or "",
        "board_note": board.get("note") or "",
        "changeover_min": item.get("changeoverMin"),
        "lifecycle": item.get("lifecycle") or "active",
    }


def _material_fields(item):
    return {
        "code": item["id"],
        "text": item.get("text") or "",
        "supplier": item.get("supplier") or "",
        "mfi": item.get("mfi") or "",
        "family": item.get("family") or "",
        "account": item.get("account") or "",
        "invoice_code": item.get("invoiceCode") or "",
        "description": item.get("description") or "",
        "link": item.get("link") or "",
        "catalog": bool(item.get("catalog")),
        "kind": item.get("kind") or "resin",
    }


def _color_fields(item):
    return {
        "code": item["id"],
        "label_code": item.get("code") or "",
        "name": item.get("name") or "",
        "label": item.get("label") or "",
        "account": item.get("account") or "",
        "shade": item.get("shade") or "",
        "link": item.get("link") or "",
        "catalog": bool(item.get("catalog")),
    }


def _recipe_fields(item):
    legacy = item.get("legacyId")
    return {
        "code": item["id"],
        "legacy_id": legacy if isinstance(legacy, (int, float)) else None,
        "product_code": item.get("productId") or "",
        "mold_code": item.get("moldId") or "",
        "press_code": item.get("pressId") or "",
        "temps_json": json.dumps(item.get("temps") or {}, ensure_ascii=False),
        "settings_json": json.dumps(item.get("settings") or [], ensure_ascii=False),
        "material_slots_json": json.dumps(item.get("materialSlots") or [], ensure_ascii=False),
        "color_slots_json": json.dumps(item.get("colorSlots") or [], ensure_ascii=False),
        "cycle": item.get("cycle") or "",
        "cooling": item.get("cooling") or "",
        "screw_rpm": item.get("screwRpm") or "",
        "px": item.get("px") or "",
        "py": item.get("py") or "",
        "product_lot": item.get("productLot") or "",
        "print_pieces": item.get("printPieces") or "",
        "print_total": item.get("printTotal") or "",
        "comment": item.get("comment") or "",
        "status_text": item.get("status") or "",
        "trial": bool(item.get("trial")),
        "standard": bool(item.get("standard")),
    }


def _link_fields(item):
    return {
        "lid_code": item.get("lidId") or "",
        "part_code": item.get("partId") or "",
        "basis": item.get("basis") or "",
    }


_WRITERS = {
    "products": (_product_fields, "products"),
    "molds": (_mold_fields, "molds"),
    "presses": (_press_fields, "presses"),
    "materials": (_material_fields, "materials"),
    "colors": (_color_fields, "colors"),
    "recipes": (_recipe_fields, "recipes"),
}


def _table(name):
    return getattr(app_tables, name)


def _write_all(graph):
    for kind, (writer, table_name) in _WRITERS.items():
        table = _table(table_name)
        for item in graph.get(kind) or []:
            fields = writer(item)
            _upsert(table, fields["code"], fields)
    _replace_links(graph.get("links") or [])


def _replace_links(links):
    _clear(app_tables.links)
    for item in links:
        app_tables.links.add_row(**_link_fields(item))


def _read():
    products = []
    for row in _rows(app_tables.products):
        products.append({
            "id": row["code"],
            "name": row["name"] or "",
            "legacyId": row["legacy_id"] or "",
            "erpCode": row["erp_code"] or "",
            "type": row["item_type"] or "",
            "notes": row["notes"] or "",
            "lifecycle": row["lifecycle"] or "",
            "onlyOnCards": bool(row["only_on_cards"]),
        })
    molds = []
    for row in _rows(app_tables.molds):
        molds.append({
            "id": row["code"],
            "name": row["name"] or "",
            "productId": row["product_code"] or "",
            "cavities": row["cavities"],
            "shotWeight": row["shot_weight"],
            "location": row["location"] or "",
            "status": row["status"] or "",
        })
    presses = []
    for row in _rows(app_tables.presses):
        presses.append({
            "id": row["code"],
            "name": row["name"] or "",
            "alias": row["alias"] or "",
            "aa": row["aa"],
            "serial": row["serial"] or "",
            "robot": row["robot"] or "",
            "robotSerial": row["robot_serial"] or "",
            "euromap": row["euromap"] or "",
            "board": {
                "mounted": row["mounted"] or "",
                "location": row["board_location"] or "",
                "note": row["board_note"] or "",
            },
            "changeoverMin": row["changeover_min"],
            "lifecycle": row["lifecycle"] or "",
        })
    materials = []
    for row in _rows(app_tables.materials):
        materials.append({
            "id": row["code"],
            "text": row["text"] or "",
            "supplier": row["supplier"] or "",
            "mfi": row["mfi"] or "",
            "family": row["family"] or "",
            "account": row["account"] or "",
            "invoiceCode": row["invoice_code"] or "",
            "description": row["description"] or "",
            "link": row["link"] or "",
            "catalog": bool(row["catalog"]),
            "kind": row["kind"] or "",
        })
    colors = []
    for row in _rows(app_tables.colors):
        colors.append({
            "id": row["code"],
            "code": row["label_code"] or "",
            "name": row["name"] or "",
            "label": row["label"] or "",
            "account": row["account"] or "",
            "shade": row["shade"] or "",
            "link": row["link"] or "",
            "catalog": bool(row["catalog"]),
        })
    recipes = []
    for row in _rows(app_tables.recipes):
        recipes.append({
            "id": row["code"],
            "legacyId": row["legacy_id"],
            "productId": row["product_code"] or "",
            "moldId": row["mold_code"] or "",
            "pressId": row["press_code"] or "",
            "temps": _loads(row["temps_json"], {}),
            "settings": _loads(row["settings_json"], []),
            "materialSlots": _loads(row["material_slots_json"], []),
            "colorSlots": _loads(row["color_slots_json"], []),
            "cycle": row["cycle"] or "",
            "cooling": row["cooling"] or "",
            "screwRpm": row["screw_rpm"] or "",
            "px": row["px"] or "",
            "py": row["py"] or "",
            "productLot": row["product_lot"] or "",
            "printPieces": row["print_pieces"] or "",
            "printTotal": row["print_total"] or "",
            "comment": row["comment"] or "",
            "status": row["status_text"] or "",
            "trial": bool(row["trial"]),
            "standard": bool(row["standard"]),
        })
    links = []
    for row in _rows(app_tables.links):
        links.append({
            "lidId": row["lid_code"] or "",
            "partId": row["part_code"] or "",
            "basis": row["basis"] or "",
        })
    return {
        "products": products,
        "molds": molds,
        "presses": presses,
        "materials": materials,
        "colors": colors,
        "recipes": recipes,
        "links": links,
    }


def _seed():
    for name in ("links", "recipes", "molds", "products", "materials", "colors", "presses"):
        _clear(_table(name))
    with open(_SEED, encoding="utf-8") as handle:
        raw = json.load(handle)
    graph = {
        "products": raw.get("products") or [],
        "molds": raw.get("molds") or [],
        "presses": raw.get("presses") or [],
        "materials": raw.get("materials") or [],
        "colors": raw.get("colors") or [],
        "recipes": raw.get("recipes") or [],
        "links": raw.get("links") or [],
    }
    domain.normalize(graph)
    domain.reindex(graph)
    _write_all(graph)
    return graph


def _mark_seeded():
    row = app_tables.meta.get(name="plant")
    if row is None:
        app_tables.meta.add_row(name="plant", seeded=True)
    else:
        row["seeded"] = True
        row.update()


def _load_unlocked():
    if _CACHE["graph"] is not None:
        return _CACHE["graph"]
    meta = None
    try:
        meta = app_tables.meta.get(name="plant")
    except Exception:
        meta = None
    seeded = bool(meta and meta["seeded"])
    if seeded:
        loaded = _read()
    else:
        _seed()
        _mark_seeded()
        loaded = _read()
    domain.normalize(loaded)
    domain.reindex(loaded)
    _CACHE["graph"] = loaded
    return loaded


def graph():
    with _LOCK:
        return _load_unlocked()


def _persist_unlocked(plant, dirty):
    dirty = dirty or {}
    for kind, codes in dirty.items():
        if kind == "links":
            _replace_links(plant.get("links") or [])
            continue
        writer_table = _WRITERS.get(kind)
        if writer_table is None or not codes:
            continue
        writer, table_name = writer_table
        table = _table(table_name)
        by_code = {item["id"]: item for item in plant.get(kind) or []}
        for code in codes:
            item = by_code.get(code)
            if item is None:
                row = table.get(code=code)
                if row is not None:
                    row.delete()
            else:
                fields = writer(item)
                _upsert(table, fields["code"], fields)
    _CACHE["graph"] = plant


def apply_action(action, payload):
    with _LOCK:
        plant = _load_unlocked()
        result = domain.dispatch(plant, action, payload or {})
        if result.get("error"):
            return {"error": result["error"]}
        _persist_unlocked(plant, result.get("dirty") or {})
        return {"redirect": result.get("redirect"), "refresh": bool(result.get("refresh"))}


def reset_cache():
    with _LOCK:
        _CACHE["graph"] = None
