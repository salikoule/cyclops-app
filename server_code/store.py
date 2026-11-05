import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
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


def column(row, name, default=None):
    """A column the cloud schema may not have yet. Writes create it (auto_create_missing_columns)."""
    try:
        value = row[name]
    except Exception:
        return default
    return default if value is None else value


def _optional_table(name):
    try:
        return getattr(app_tables, name)
    except Exception:
        return None


def _workers_table():
    return _optional_table("workers")


def _log_tables():
    """(stoppages, production_runs), or None while the database lacks them; the logs then stay in JSON on the recipe row."""
    stoppages, runs = _optional_table("stoppages"), _optional_table("production_runs")
    return (stoppages, runs) if stoppages is not None and runs is not None else None


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


def _recipe_row_fields(item, logs_in_tables):
    fields = _recipe_fields(item)
    if logs_in_tables:
        fields.update(issues_json=None, runs_json=None)
    else:
        fields.update(issues_json=_dumps(item.get("issues")), runs_json=_dumps(item.get("runs")))
    return fields


def _stoppage_fields(issue, position, recipe_row, press_row, workers):
    name = issue.get("worker") or ""
    return {
        "recipe": recipe_row,
        "press": press_row,
        "worker": workers.get(name),
        "worker_name": name,
        "position": position,
        "start_date": issue.get("startDate") or "",
        "start_time": issue.get("startTime") or "",
        "end_date": issue.get("endDate") or "",
        "end_time": issue.get("endTime") or "",
        "cause": issue.get("cause") or "",
        "fix": issue.get("fix") or "",
    }


def _run_fields(run, position, recipe_row, press_row, workers):
    name = run.get("operator") or ""
    return {
        "recipe": recipe_row,
        "press": press_row,
        "operator": workers.get(name),
        "operator_name": name,
        "position": position,
        "start_date": run.get("startDate") or "",
        "start_time": run.get("startTime") or "",
        "end_date": run.get("endDate") or "",
        "end_time": run.get("endTime") or "",
        "shift": run.get("shift") or "",
        "good": domain.whole(run.get("good")),
        "scrap": domain.whole(run.get("scrap")),
        "scrap_reason": run.get("scrapReason") or "",
        "cycle": domain.whole(run.get("cycle")),
        "cavities": domain.whole(run.get("cavities")),
        "lot": run.get("lot") or "",
        "order_no": run.get("order") or "",
        "notes": run.get("notes") or "",
        "sample": bool(run.get("sample")),
    }


def _stoppage_item(row):
    return {
        "startDate": column(row, "start_date", ""),
        "startTime": column(row, "start_time", ""),
        "cause": column(row, "cause", ""),
        "worker": column(row, "worker_name", ""),
        "fix": column(row, "fix", ""),
        "endDate": column(row, "end_date", ""),
        "endTime": column(row, "end_time", ""),
    }


def _run_item(row):
    return {
        "startDate": column(row, "start_date", ""),
        "startTime": column(row, "start_time", ""),
        "endDate": column(row, "end_date", ""),
        "endTime": column(row, "end_time", ""),
        "shift": column(row, "shift", ""),
        "operator": column(row, "operator_name", ""),
        "good": domain.trim_num(column(row, "good")),
        "scrap": domain.trim_num(column(row, "scrap")),
        "scrapReason": column(row, "scrap_reason", ""),
        "cycle": domain.trim_num(column(row, "cycle")),
        "cavities": domain.trim_num(column(row, "cavities")),
        "lot": column(row, "lot", ""),
        "order": column(row, "order_no", ""),
        "notes": column(row, "notes", ""),
        "sample": bool(column(row, "sample", False)),
    }


def _set(fields):
    """Leave out empty links and numbers: a missing column cannot be auto-created from None."""
    return {key: value for key, value in fields.items() if value is not None}


def _write_logs(tables, items, recipe_rows):
    """Replace the stoppage and run rows of ``items`` (recipes); ``recipe_rows`` maps recipe code to its row."""
    stoppages, runs = tables
    workers_table = _workers_table()
    workers = {row["name"]: row for row in _rows(workers_table)} if workers_table is not None else {}
    presses = {row["code"]: row for row in _rows(app_tables.presses)}
    new_stops, new_runs = [], []
    for item in items:
        recipe_row = recipe_rows.get(item["id"])
        if recipe_row is None:
            continue
        press_row = presses.get(item.get("pressId"))
        new_stops += [_set(_stoppage_fields(issue, at, recipe_row, press_row, workers)) for at, issue in enumerate(item.get("issues") or [])]
        new_runs += [_set(_run_fields(run, at, recipe_row, press_row, workers)) for at, run in enumerate(item.get("runs") or [])]
    for start in range(0, len(new_stops), 200):
        stoppages.add_rows(new_stops[start:start + 200])
    for start in range(0, len(new_runs), 200):
        runs.add_rows(new_runs[start:start + 200])


def _drop_logs(tables, recipe_row):
    for table in tables:
        for row in table.search(recipe=recipe_row):
            row.delete()


def _unlink_press(tables, press_row):
    """Faster Storage tables may restrict or cascade a delete; a log keeps its row when its press goes."""
    for table in tables:
        for row in table.search(press=press_row):
            row.update(press=None)


def _read_logs(tables):
    """{recipe code: (issues, runs)} from the log tables, each list in its saved order."""
    found = {}
    for table, slot, reader in ((tables[0], 0, _stoppage_item), (tables[1], 1, _run_item)):
        for row in table.search():
            recipe_row = column(row, "recipe")
            if recipe_row is None:
                continue
            entry = found.setdefault(recipe_row["code"], ([], []))
            entry[slot].append((column(row, "position", 0), reader(row)))
    return {code: tuple([item for _, item in sorted(pairs, key=lambda pair: pair[0])] for pairs in entry)
            for code, entry in found.items()}


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
        "approvedPressIds": _loads(column(row, "approved_presses_json"), []),
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
        "robotYear": column(row, "robot_year", ""),
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
        "notes": column(row, "notes", ""),
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
        "notes": column(row, "notes", ""),
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
        "issues": _loads(column(row, "issues_json"), []),
        "runs": _loads(column(row, "runs_json"), None),
        "settingsNote": column(row, "settings_note", ""),
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
    tables = _log_tables()
    if tables is not None and column(_meta(), "logs_in_tables", False):
        logs = _read_logs(tables)
        for recipe in recipes:
            recipe["issues"], recipe["runs"] = logs.get(recipe["id"], ([], []))
    for items in (products, molds, materials, colors, recipes):
        items.sort(key=lambda item: item["id"])
    links = [{
        "lidId": row["lid_code"] or "",
        "partId": row["part_code"] or "",
        "basis": row["basis"] or "",
    } for row in _rows(app_tables.links)]
    table = _workers_table()
    workers = [row["name"] for row in _rows(table) if row["name"]] if table is not None else []
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
    workers_table = _workers_table()
    tables = _log_tables()
    for table in tables or ():
        table.delete_all_rows()
    for name in ("links",) + tuple(_WRITERS):
        _table(name).delete_all_rows()
    if workers_table is not None:
        workers_table.delete_all_rows()
    for kind, writer in _WRITERS.items():
        if kind == "recipes":
            writer = lambda item: _recipe_row_fields(item, tables is not None)
        rows = [writer(item) for item in graph.get(kind) or []]
        for start in range(0, len(rows), 200):
            _table(kind).add_rows(rows[start:start + 200])
    links = [_link_fields(item) for item in graph.get("links") or []]
    if links:
        app_tables.links.add_rows(links)
    workers = [{"name": name} for name in graph.get("workers") or []]
    if workers and workers_table is not None:
        workers_table.add_rows(workers)
    if tables is not None:
        _write_logs(tables, graph.get("recipes") or [], {row["code"]: row for row in _rows(app_tables.recipes)})
        _meta().update(logs_in_tables=True)


def _move_logs_to_tables(graph):
    """One-off: copy every recipe's stoppages and runs into their tables and empty the JSON columns."""
    tables = _log_tables()
    meta = _meta()
    if tables is None or column(meta, "logs_in_tables", False):
        return
    with anvil.tables.batch_update, anvil.tables.batch_delete:
        for table in tables:
            table.delete_all_rows()
        recipe_rows = {row["code"]: row for row in _rows(app_tables.recipes)}
        _write_logs(tables, graph.get("recipes") or [], recipe_rows)
        for row in recipe_rows.values():
            row.update(issues_json=None, runs_json=None)
    meta.update(logs_in_tables=True)


def _meta():
    row = app_tables.meta.get(name="plant")
    if row is None:
        row = app_tables.meta.add_row(name="plant", seeded=False, version=0)
    return row


def _snapshot_media(graph):
    raw = json.dumps(_plain(graph), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return anvil.BlobMedia("application/zlib", zlib.compress(raw, 6), name="plant.json.z")


def _read_snapshot(row):
    media = column(row, "snapshot")
    if media is None:
        return None
    try:
        return json.loads(zlib.decompress(media.get_bytes()).decode("utf-8"))
    except Exception:
        return None


def _save_snapshot(meta, graph):
    version = int(column(meta, "version", 0)) + 1
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
    version = column(meta, "version", 0)
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
    _move_logs_to_tables(loaded)
    _CACHE["graph"] = loaded
    _CACHE["version"] = version
    return loaded


def graph():
    with _LOCK:
        return _load_unlocked()


def _persist_unlocked(plant, dirty):
    dirty = dirty or {}
    tables = _log_tables() if column(_meta(), "logs_in_tables", False) else None
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
            if kind == "recipes":
                writer = lambda item: _recipe_row_fields(item, tables is not None)
            table = _table(kind)
            by_code = {item["id"]: item for item in plant.get(kind) or []}
            logged = {}
            for code in codes:
                item = by_code.get(code)
                row = table.get(code=code)
                if kind == "recipes" and tables is not None and row is not None:
                    _drop_logs(tables, row)
                if item is None:
                    if row is not None:
                        if kind == "presses" and tables is not None:
                            _unlink_press(tables, row)
                        row.delete()
                    continue
                if row is None:
                    row = table.add_row(**writer(item))
                else:
                    row.update(**writer(item))
                logged[code] = row
            if kind == "recipes" and tables is not None and logged:
                _write_logs(tables, [by_code[code] for code in logged], logged)
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
