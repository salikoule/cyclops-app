"""The plant record in relational Anvil tables.

The tables are the record: every product, mold, press, recipe, and log is a row, and the
references between them are link columns. ``records`` maps rows to the shape the domain module
works on.

Every page needs the whole plant (statuses and gaps look across all of it), so a compressed copy
sits on the ``meta`` row named "plant", with a version that goes up on each write. It is only a
cache. It is rebuilt from the tables whenever it is missing, and ``reload_from_tables`` rebuilds it
after rows are changed by hand in the Anvil editor.
"""

import datetime
import json
import threading
import zlib

import anvil
import anvil.tables
from anvil.tables import app_tables

import domain
import records

_LOCK = threading.Lock()
_CACHE = {"graph": None, "version": None}
_KINDS = ("products", "molds", "presses", "materials", "colors", "recipes", "links", "workers")
_RECIPE_CHILDREN = ("injection_settings", "recipe_materials", "recipe_colors", "stoppages", "production_runs")
_CLEAR_ORDER = ("product_links",) + _RECIPE_CHILDREN + ("recipes", "molds", "products", "presses", "materials", "colors", "workers")
_ENTITY_WRITERS = {
    "presses": records.press_row,
    "materials": records.material_row,
    "colors": records.color_row,
    "products": records.product_row,
    "molds": records.mold_row,
    "recipes": records.recipe_row,
}
_PERSIST_ORDER = ("presses", "materials", "colors", "products", "molds", "recipes")
_BATCH = 200


def column(row, name, default=None):
    try:
        value = row[name]
    except Exception:
        return default
    return default if value is None else value


def _table(name):
    return getattr(app_tables, name)


def _key_column(table):
    return "name" if table == "workers" else "code"


def _link_id(row, name):
    linked = row[name]
    return linked.get_id() if linked is not None else None


class _Refs:
    """Rows by code (workers by name), fetched once per write."""

    def __init__(self):
        self._rows = {}

    def __call__(self, table, code):
        key = (table, code)
        if key not in self._rows:
            self._rows[key] = _table(table).get(**{_key_column(table): code})
        return self._rows[key]

    def load(self, table):
        for row in _table(table).search():
            self._rows[(table, row[_key_column(table)])] = row

    def remember(self, table, code, row):
        self._rows[(table, code)] = row


def _add(table, rows):
    for start in range(0, len(rows), _BATCH):
        _table(table).add_rows(rows[start:start + _BATCH])


def _recipe_children(item, recipe_row, refs):
    """{table: rows} for everything that hangs off one recipe."""
    settings = records.injection_row(item, recipe_row)
    return {
        "injection_settings": [settings] if settings else [],
        "recipe_materials": records.material_slot_rows(item, recipe_row, refs),
        "recipe_colors": records.color_slot_rows(item, recipe_row, refs),
        "stoppages": records.stoppage_rows(item, recipe_row, refs),
        "production_runs": records.run_rows(item, recipe_row, refs),
    }


def _clear_all():
    for row in app_tables.presses.search():
        if row["mounted_product"] is not None:
            row.update(mounted_product=None)
    for name in _CLEAR_ORDER:
        _table(name).delete_all_rows()


def _write_all(plant):
    """Replace every table with the plant record, parents before the rows that link to them."""
    _clear_all()
    refs = _Refs()
    _add("workers", [records.worker_row(name) for name in plant.get("workers") or []])
    refs.load("workers")
    for kind in _PERSIST_ORDER:
        writer = _ENTITY_WRITERS[kind]
        _add(kind, [writer(item, refs) for item in plant.get(kind) or []])
        refs.load(kind)
    _add("product_links", [records.product_link_row(item, refs) for item in plant.get("links") or []])
    children = {name: [] for name in _RECIPE_CHILDREN}
    for item in plant.get("recipes") or []:
        for name, rows in _recipe_children(item, refs("recipes", item["id"]), refs).items():
            children[name] += rows
    for name in _RECIPE_CHILDREN:
        _add(name, children[name])
    for item in plant.get("presses") or []:
        if (item.get("board") or {}).get("mountedId"):
            refs("presses", item["id"]).update(**records.press_board_row(item, refs))


def _read_all():
    workers = list(app_tables.workers.search())
    worker_name = {row.get_id(): row["name"] for row in workers}
    product_rows = list(app_tables.products.search())
    product_code = {row.get_id(): row["code"] for row in product_rows}
    product_names = {row["code"]: row["name"] or "" for row in product_rows}
    press_rows = list(app_tables.presses.search())
    press_code = {row.get_id(): row["code"] for row in press_rows}
    material_code = {row.get_id(): row["code"] for row in app_tables.materials.search()}
    color_code = {row.get_id(): row["code"] for row in app_tables.colors.search()}

    products = [records.product_item(row, [press_code[linked.get_id()] for linked in row["approved_presses"] or []
                                           if linked.get_id() in press_code])
                for row in product_rows]
    presses = [records.press_item(row, product_code.get(_link_id(row, "mounted_product")), product_names) for row in press_rows]
    mold_rows = list(app_tables.molds.search())
    molds = [records.mold_item(row, product_code.get(_link_id(row, "product"))) for row in mold_rows]
    mold_code = {row.get_id(): row["code"] for row in mold_rows}
    mold_product = {item["id"]: item["productId"] for item in molds}

    recipes, recipe_by_id = [], {}
    for row in app_tables.recipes.search():
        mold = mold_code.get(_link_id(row, "mold"))
        item = records.recipe_item(row, mold, mold_product.get(mold), press_code.get(_link_id(row, "press")))
        recipes.append(item)
        recipe_by_id[row.get_id()] = item

    def owner(row):
        return recipe_by_id.get(_link_id(row, "recipe"))

    for row in app_tables.injection_settings.search():
        item = owner(row)
        if item is not None:
            item["settings"] = records.settings_items(row)
    slots = {"materialSlots": [], "colorSlots": [], "issues": [], "runs": []}
    for row in app_tables.recipe_materials.search():
        slots["materialSlots"].append((owner(row), row["slot"], records.material_slot_item(row, material_code.get(_link_id(row, "material")))))
    for row in app_tables.recipe_colors.search():
        slots["colorSlots"].append((owner(row), row["slot"], records.color_slot_item(row, color_code.get(_link_id(row, "color")))))
    for row in app_tables.stoppages.search():
        slots["issues"].append((owner(row), row["position"], records.stoppage_item(row, worker_name.get(_link_id(row, "worker")))))
    for row in app_tables.production_runs.search():
        slots["runs"].append((owner(row), row["position"], records.run_item(row, worker_name.get(_link_id(row, "operator")))))
    for key, entries in slots.items():
        for item, order, value in sorted((entry for entry in entries if entry[0] is not None), key=lambda entry: entry[1] or 0):
            item[key].append(value)

    links = [records.product_link_item(row, product_code.get(_link_id(row, "lid")), product_code.get(_link_id(row, "part")))
             for row in app_tables.product_links.search()]
    plant = {
        "products": products,
        "molds": molds,
        "presses": presses,
        "materials": [records.material_item(row) for row in app_tables.materials.search()],
        "colors": [records.color_item(row) for row in app_tables.colors.search()],
        "recipes": recipes,
        "links": links,
        "workers": sorted(name for name in worker_name.values() if name),
    }
    for kind in ("products", "molds", "presses", "materials", "colors", "recipes"):
        plant[kind].sort(key=lambda item: item["id"])
    return plant


def _plain(graph):
    return {kind: graph.get(kind) or [] for kind in _KINDS}


def _meta():
    row = app_tables.meta.get(name="plant")
    if row is None:
        row = app_tables.meta.add_row(name="plant", version=0)
    return row


def _cache_media(graph):
    raw = json.dumps(_plain(graph), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return anvil.BlobMedia("application/zlib", zlib.compress(raw, 6), name="plant.json.z")


def _read_cache(row):
    media = row["cache"]
    if media is None:
        return None
    try:
        return json.loads(zlib.decompress(media.get_bytes()).decode("utf-8"))
    except Exception:
        return None


def _save_cache(meta, graph):
    version = int(meta["version"] or 0) + 1
    meta.update(cache=_cache_media(graph), version=version, updated=datetime.datetime.now(datetime.timezone.utc))
    return version


def _ready(graph):
    domain.normalize(graph)
    domain.reindex(graph)
    return graph


def _seed(meta):
    import seed_data

    seed = seed_data.load()
    _write_all(_ready({kind: seed.get(kind) or [] for kind in _KINDS}))
    source = seed.get("meta") or {}
    meta.update(source=source.get("source") or seed_data.SOURCE, imported=records._date_in(source.get("imported")))


def _load_unlocked():
    meta = _meta()
    version = meta["version"] or 0
    if _CACHE["graph"] is not None and _CACHE["version"] == version:
        return _CACHE["graph"]
    loaded = _read_cache(meta)
    if loaded is not None:
        _ready(loaded)
    else:
        if len(app_tables.products.search()) == 0:
            _seed(meta)
        loaded = _ready(_read_all())
        version = _save_cache(meta, loaded)
    _CACHE["graph"] = loaded
    _CACHE["version"] = version
    return loaded


def graph():
    with _LOCK:
        return _load_unlocked()


def _ensure_workers(plant, items, refs):
    """A name typed on a stoppage or run that is not on the list yet becomes a worker row."""
    known = set(plant.get("workers") or [])
    for item in items:
        for name in [log.get("worker") for log in item.get("issues") or []] + [log.get("operator") for log in item.get("runs") or []]:
            name = (name or "").strip()
            if name and name not in known:
                refs.remember("workers", name, app_tables.workers.add_row(**records.worker_row(name)))
                plant.setdefault("workers", []).append(name)
                known.add(name)


def _drop_children(recipe_row):
    for name in _RECIPE_CHILDREN:
        for row in _table(name).search(recipe=recipe_row):
            row.delete()


def _persist_unlocked(plant, dirty):
    dirty = dirty or {}
    refs = _Refs()
    recipes = {item["id"]: item for item in plant.get("recipes") or []}
    _ensure_workers(plant, [recipes[code] for code in dirty.get("recipes") or [] if code in recipes], refs)
    for kind in _PERSIST_ORDER:
        codes = dirty.get(kind) or []
        if not codes:
            continue
        items = {item["id"]: item for item in plant.get(kind) or []}
        writer = _ENTITY_WRITERS[kind]
        for code in codes:
            item = items.get(code)
            row = refs(kind, code)
            if item is None:
                if row is not None:
                    if kind == "recipes":
                        _drop_children(row)
                    row.delete()
                continue
            if row is None:
                row = _table(kind).add_row(**writer(item, refs))
                refs.remember(kind, code, row)
            else:
                if kind == "recipes":
                    _drop_children(row)
                row.update(**writer(item, refs))
            if kind == "recipes":
                for name, rows in _recipe_children(item, row, refs).items():
                    if rows:
                        _table(name).add_rows(rows)
    for code in dirty.get("presses") or []:
        item = next((press for press in plant.get("presses") or [] if press["id"] == code), None)
        if item is not None:
            refs("presses", code).update(**records.press_board_row(item, refs))
    if dirty.get("links"):
        app_tables.product_links.delete_all_rows()
        _add("product_links", [records.product_link_row(item, refs) for item in plant.get("links") or []])
    _CACHE["version"] = _save_cache(_meta(), plant)
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
        _write_all(_ready({kind: graph_in.get(kind) or [] for kind in _KINDS}))
        loaded = _ready(_read_all())
        _CACHE["version"] = _save_cache(_meta(), loaded)
        _CACHE["graph"] = loaded
        return domain.counts(loaded)


def reload_from_tables():
    """Rebuild the cache from the tables after editing them in the Anvil editor."""
    with _LOCK:
        loaded = _ready(_read_all())
        _CACHE["version"] = _save_cache(_meta(), loaded)
        _CACHE["graph"] = loaded
        return domain.counts(loaded)


def reset_cache():
    with _LOCK:
        _CACHE["graph"] = None
        _CACHE["version"] = None
