"""Load and save the plant graph in Anvil tables.

The domain module always sees the sketch's shape. The entity tables are the
storage shape and what the Anvil editor shows. A compressed copy of the whole
graph sits on the ``meta`` row named "plant", with a version that goes up on
every write, so a fresh server process loads one row instead of seven tables
and a process holding an older copy notices and reloads.
"""

import datetime
import json
import threading
import zlib

import anvil
import anvil.tables
from anvil.tables import app_tables

import domain

_LOCK = threading.Lock()
_CACHE = {"graph": None, "version": None}
_KINDS = ("products", "molds", "presses", "materials", "colors", "recipes", "links", "workers")


def _rows(table):
    return list(table.search())


def _loads(text, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def _dumps(value):
    return json.dumps(value if value is not None else [], ensure_ascii=False)


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
        "approved_presses_json": _dumps(item.get("approvedPressIds") or []),
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
        "robot_year": item.get("robotYear") or "",
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
        "notes": item.get("notes") or "",
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
        "notes": item.get("notes") or "",
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
        "settings_json": _dumps(item.get("settings")),
        "material_slots_json": _dumps(item.get("materialSlots")),
        "color_slots_json": _dumps(item.get("colorSlots")),
        "issues_json": _dumps(item.get("issues")),
        "settings_note": item.get("settingsNote") or "",
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
    "products": _product_fields,
    "molds": _mold_fields,
    "presses": _press_fields,
    "materials": _material_fields,
    "colors": _color_fields,
    "recipes": _recipe_fields,
}


def _table(name):
    return getattr(app_tables, name)


def _plain(graph):
    return {kind: graph.get(kind) or [] for kind in _KINDS}


def _read_tables():
    products = [{
        "id": row["code"],
        "name": row["name"] or "",
        "legacyId": row["legacy_id"] or "",
        "erpCode": row["erp_code"] or "",
        "type": row["item_type"] or "",
        "notes": row["notes"] or "",
        "lifecycle": row["lifecycle"] or "",
        "onlyOnCards": bool(row["only_on_cards"]),
        "approvedPressIds": _loads(row["approved_presses_json"], []),
    } for row in _rows(app_tables.products)]
    molds = [{
        "id": row["code"],
        "name": row["name"] or "",
        "productId": row["product_code"] or "",
        "cavities": row["cavities"],
        "shotWeight": row["shot_weight"],
        "location": row["location"] or "",
        "status": row["status"] or "",
    } for row in _rows(app_tables.molds)]
    presses = [{
        "id": row["code"],
        "name": row["name"] or "",
        "alias": row["alias"] or "",
        "aa": row["aa"],
        "serial": row["serial"] or "",
        "robot": row["robot"] or "",
        "robotSerial": row["robot_serial"] or "",
        "robotYear": row["robot_year"] or "",
        "euromap": row["euromap"] or "",
        "board": {
            "mounted": row["mounted"] or "",
            "location": row["board_location"] or "",
            "note": row["board_note"] or "",
        },
        "changeoverMin": row["changeover_min"],
        "lifecycle": row["lifecycle"] or "",
    } for row in _rows(app_tables.presses)]
    presses.sort(key=lambda press: press["id"])
    materials = [{
        "id": row["code"],
        "text": row["text"] or "",
        "supplier": row["supplier"] or "",
        "mfi": row["mfi"] or "",
        "family": row["family"] or "",
        "account": row["account"] or "",
        "invoiceCode": row["invoice_code"] or "",
        "description": row["description"] or "",
        "notes": row["notes"] or "",
        "link": row["link"] or "",
        "catalog": bool(row["catalog"]),
        "kind": row["kind"] or "",
    } for row in _rows(app_tables.materials)]
    colors = [{
        "id": row["code"],
        "code": row["label_code"] or "",
        "name": row["name"] or "",
        "label": row["label"] or "",
        "account": row["account"] or "",
        "shade": row["shade"] or "",
        "notes": row["notes"] or "",
        "link": row["link"] or "",
        "catalog": bool(row["catalog"]),
    } for row in _rows(app_tables.colors)]
    recipes = [{
        "id": row["code"],
        "legacyId": row["legacy_id"],
        "productId": row["product_code"] or "",
        "moldId": row["mold_code"] or "",
        "pressId": row["press_code"] or "",
        "temps": _loads(row["temps_json"], {}),
        "settings": _loads(row["settings_json"], []),
        "materialSlots": _loads(row["material_slots_json"], []),
        "colorSlots": _loads(row["color_slots_json"], []),
        "issues": _loads(row["issues_json"], []),
        "settingsNote": row["settings_note"] or "",
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
    } for row in _rows(app_tables.recipes)]
    for items in (products, molds, materials, colors, recipes):
        items.sort(key=lambda item: item["id"])
    links = [{
        "lidId": row["lid_code"] or "",
        "partId": row["part_code"] or "",
        "basis": row["basis"] or "",
    } for row in _rows(app_tables.links)]
    workers = [row["name"] for row in _rows(app_tables.workers) if row["name"]]
    return {
        "products": products,
        "molds": molds,
        "presses": presses,
        "materials": materials,
        "colors": colors,
        "recipes": recipes,
        "links": links,
        "workers": workers,
    }


def _write_tables(graph):
    """Replace every entity table with the graph, in batches."""
    for name in ("links", "workers") + tuple(_WRITERS):
        _table(name).delete_all_rows()
    for kind, writer in _WRITERS.items():
        rows = [writer(item) for item in graph.get(kind) or []]
        for start in range(0, len(rows), 200):
            _table(kind).add_rows(rows[start:start + 200])
    links = [_link_fields(item) for item in graph.get("links") or []]
    if links:
        app_tables.links.add_rows(links)
    workers = [{"name": name} for name in graph.get("workers") or []]
    if workers:
        app_tables.workers.add_rows(workers)


def _meta():
    row = app_tables.meta.get(name="plant")
    if row is None:
        row = app_tables.meta.add_row(name="plant", seeded=False, version=0)
    return row


def _snapshot_media(graph):
    raw = json.dumps(_plain(graph), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return anvil.BlobMedia("application/zlib", zlib.compress(raw, 6), name="plant.json.z")


def _read_snapshot(row):
    media = row["snapshot"]
    if media is None:
        return None
    try:
        return json.loads(zlib.decompress(media.get_bytes()).decode("utf-8"))
    except Exception:
        return None


def _save_snapshot(meta, graph):
    version = int(meta["version"] or 0) + 1
    meta.update(
        snapshot=_snapshot_media(graph),
        version=version,
        seeded=True,
        updated=datetime.datetime.now(datetime.timezone.utc),
    )
    return version


def _seed_graph():
    import seed_data

    return seed_data.load()


def _ready(graph):
    domain.normalize(graph)
    domain.reindex(graph)
    return graph


def _load_unlocked():
    meta = _meta()
    version = meta["version"] or 0
    if _CACHE["graph"] is not None and _CACHE["version"] == version:
        return _CACHE["graph"]
    loaded = _read_snapshot(meta)
    if loaded is not None:
        _ready(loaded)
    else:
        if meta["seeded"] and len(app_tables.products.search()) > 0:
            loaded = _ready(_read_tables())
        else:
            loaded = _ready(_seed_graph())
            _write_tables(loaded)
        version = _save_snapshot(meta, loaded)
    _CACHE["graph"] = loaded
    _CACHE["version"] = version
    return loaded


def graph():
    with _LOCK:
        return _load_unlocked()


def _persist_unlocked(plant, dirty):
    dirty = dirty or {}
    with anvil.tables.batch_update, anvil.tables.batch_delete:
        for kind, codes in dirty.items():
            if kind == "links":
                app_tables.links.delete_all_rows()
                links = [_link_fields(item) for item in plant.get("links") or []]
                if links:
                    app_tables.links.add_rows(links)
                continue
            writer = _WRITERS.get(kind)
            if writer is None or not codes:
                continue
            table = _table(kind)
            by_code = {item["id"]: item for item in plant.get(kind) or []}
            for code in codes:
                item = by_code.get(code)
                row = table.get(code=code)
                if item is None:
                    if row is not None:
                        row.delete()
                elif row is None:
                    table.add_row(**writer(item))
                else:
                    row.update(**writer(item))
    _CACHE["version"] = _save_snapshot(_meta(), plant)
    _CACHE["graph"] = plant


def apply_action(action, payload):
    with _LOCK:
        plant = _load_unlocked()
        result = domain.dispatch(plant, action, payload or {})
        if result.get("error"):
            return {"error": result["error"]}
        _persist_unlocked(plant, result.get("dirty") or {})
        return {"redirect": result.get("redirect"), "refresh": bool(result.get("refresh"))}


def replace_all(graph_in):
    """Replace the whole plant record, e.g. from the workbook import."""
    with _LOCK:
        loaded = _ready({kind: graph_in.get(kind) or [] for kind in _KINDS})
        _write_tables(loaded)
        _CACHE["version"] = _save_snapshot(_meta(), loaded)
        _CACHE["graph"] = loaded
        return domain.counts(loaded)


def reload_from_tables():
    """Rebuild the snapshot from the entity tables after editing them in the Anvil editor."""
    with _LOCK:
        loaded = _ready(_read_tables())
        _CACHE["version"] = _save_snapshot(_meta(), loaded)
        _CACHE["graph"] = loaded
        return domain.counts(loaded)


def reset_cache():
    with _LOCK:
        _CACHE["graph"] = None
        _CACHE["version"] = None
