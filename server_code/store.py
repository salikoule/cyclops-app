"""The plant record in relational Anvil tables.

The tables are the record and every request reads them directly: a page loads its own rows
through ``loader`` and an edit loads what it touches, changes it, and writes the changed rows
back in one transaction. ``records`` maps rows to the shape the domain module works on.
"""

import anvil.tables
import anvil.tables.query as q
from anvil.tables import app_tables

import domain
import loader
import records

_KINDS = ("products", "molds", "presses", "materials", "colors", "recipes", "links", "workers")
_RECIPE_LINES = ("recipe_materials", "recipe_colors", "stoppages", "production_runs")
_CLEAR_ORDER = _RECIPE_LINES + ("recipes", "molds", "products", "presses", "materials", "colors", "workers")
_ENTITY_WRITERS = {
    "presses": records.press_row,
    "materials": records.material_row,
    "colors": records.color_row,
    "products": records.product_row,
    "molds": records.mold_row,
    "recipes": records.recipe_row,
}
_PERSIST_ORDER = ("presses", "materials", "colors", "products", "molds", "recipes")
_LIST_CHILDREN = {
    "product": ("materials", "colors"),
    "mold": (),
    "press": (),
    "recipe": ("materials", "colors"),
    "material": ("materials",),
    "color": ("colors",),
    "issue": ("issues",),
    "run": ("runs", "issues"),
}
_CREATES = {
    "new-product": ("products",),
    "new-mold": ("molds",),
    "clone-product": ("products", "molds", "recipes"),
    "add-recipe": ("recipes", "molds"),
    "clone-recipe": ("recipes", "molds"),
}
_PRODUCT_ACTIONS = ("edit-product", "clone-product", "add-recipe", "add-material", "add-color", "add-link", "remove-link", "set-approved")
_RECIPE_ACTIONS = ("edit-recipe", "edit-injection", "set-standard", "clone-recipe", "delete-recipe", "add-slot-material",
                   "add-slot-color", "remove-slot", "add-issue", "edit-issue", "remove-issue", "add-run", "edit-run", "remove-run")
_BATCH = 200
_SEEDED = False


def _table(name):
    return getattr(app_tables, name)


def _key_column(table):
    return "name" if table == "workers" else "code"


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


# Reading ----------------------------------------------------------------------------------

def _whole(children=loader.CHILDREN, workers=False):
    return loader.Plant(whole=True, children=children, workers=workers).graph()


def _recipe_scope(plant, code):
    row = app_tables.recipes.get(q.fetch_only("code", press=q.fetch_only("code"), mold=q.fetch_only("code", product=q.fetch_only("code"))), code=code)
    if row is None:
        return plant
    plant.add_recipes([row])
    if row["press"] is not None:
        plant.add_spans([row["press"]["code"]])
    return plant


def _product_scope(plant, code):
    """The product, its lid, and the parts it is the lid of, each with its molds and recipes."""
    row = app_tables.products.get(q.fetch_only("code", lid=q.fetch_only("code")), code=code)
    if row is None:
        return plant
    codes = [code] + [part["code"] for part in app_tables.products.search(q.fetch_only("code"), lid=row)]
    if row["lid"] is not None:
        codes.append(row["lid"]["code"])
    return plant.add(products=codes)


def _mold_scope(plant, code):
    row = app_tables.molds.get(q.fetch_only("code", product=q.fetch_only("code")), code=code)
    if row is None:
        return plant
    return plant.add(products=[row["product"]["code"]] if row["product"] is not None else [], molds=[code])


def _press_scope(plant, code):
    row = plant.press(code)
    if row is None:
        return plant
    plant.add_recipes(loader.recipes_on_press(row))
    return plant.add(products=[product["code"] for product in app_tables.products.search(q.fetch_only("code"), approved_presses=[row])])


def _material_scope(plant, code):
    row = plant.material(code)
    return plant.add_recipes(loader.recipes_using("recipe_materials", "material", row)) if row is not None else plant


def _color_scope(plant, code):
    row = plant.color(code)
    return plant.add_recipes(loader.recipes_using("recipe_colors", "color", row)) if row is not None else plant


_SCOPES = {
    "product": _product_scope,
    "mold": _mold_scope,
    "press": _press_scope,
    "recipe": _recipe_scope,
    "material": _material_scope,
    "color": _color_scope,
}


def detail(kind, code):
    scope = _SCOPES.get(kind)
    if scope is None:
        return {"missing": True, "kind": kind, "id": code}
    return domain.detail(scope(loader.Plant(), code).graph(), kind, code)


def list_view(kind, gap=None):
    if kind not in _LIST_CHILDREN:
        return {"error": "Unknown list."}
    return domain.list_view(_whole(loader.CHILDREN if gap else _LIST_CHILDREN[kind]), kind, gap)


def overview(who="all"):
    return domain.overview(_whole(), who)


def structure():
    return domain.structure(_whole())


def search(term):
    if len(domain.fold(term).strip()) < 2:
        return []
    return domain.search(_whole(()), term)


def choices():
    return domain.choices(_whole(("colors",), workers=True))


def counts():
    """Row counts for the menu, one count query per table."""
    return {kind: len(_table(table).search()) for kind, table in (
        ("products", "products"), ("molds", "molds"), ("presses", "presses"), ("recipes", "recipes"),
        ("materials", "materials"), ("colors", "colors"), ("stoppages", "stoppages"), ("runs", "production_runs"))}


def downtime_hours():
    stops = app_tables.stoppages.search(q.fetch_only("start_date", "start_time", "end_date", "end_time"))
    return round(sum(domain.downtime_hours(records.stop_times(row)) or 0 for row in stops), 1)


# Writing ----------------------------------------------------------------------------------

def _add(table, rows):
    for start in range(0, len(rows), _BATCH):
        _table(table).add_rows(rows[start:start + _BATCH])


def _recipe_lines(item, recipe_row, refs):
    """{table: rows} for everything that hangs off one recipe."""
    return {
        "recipe_materials": records.material_slot_rows(item, recipe_row, refs),
        "recipe_colors": records.color_slot_rows(item, recipe_row, refs),
        "stoppages": records.stoppage_rows(item, recipe_row, refs),
        "production_runs": records.run_rows(item, recipe_row, refs),
    }


def _clear_all():
    for row in app_tables.presses.search(mounted_product=q.not_(None)):
        row.update(mounted_product=None)
    for row in app_tables.products.search(lid=q.not_(None)):
        row.update(lid=None)
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
    lines = {name: [] for name in _RECIPE_LINES}
    for item in plant.get("recipes") or []:
        for name, rows in _recipe_lines(item, refs("recipes", item["id"]), refs).items():
            lines[name] += rows
    for name in _RECIPE_LINES:
        _add(name, lines[name])
    for item in plant.get("products") or []:
        if item.get("lidId"):
            refs("products", item["id"]).update(**records.product_lid_row(item, refs))
    for item in plant.get("presses") or []:
        if (item.get("board") or {}).get("mountedId"):
            refs("presses", item["id"]).update(**records.press_board_row(item, refs))


def _ready(graph):
    domain.normalize(graph)
    domain.reindex(graph)
    return graph


@anvil.tables.in_transaction
def _seed_if_empty():
    if len(app_tables.products.search()) > 0:
        return
    import seed_data

    seed = seed_data.load()
    _write_all(_ready({kind: seed.get(kind) or [] for kind in _KINDS}))


def ensure_seeded():
    """A new app, or one whose tables were emptied, starts from the workbook import."""
    global _SEEDED
    if not _SEEDED:
        _seed_if_empty()
        _SEEDED = True


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


def _drop_lines(recipe_row):
    for name in _RECIPE_LINES:
        for row in _table(name).search(recipe=recipe_row):
            row.delete()


def _persist(plant, dirty):
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
                        _drop_lines(row)
                    row.delete()
                continue
            if row is None:
                row = _table(kind).add_row(**writer(item, refs))
                refs.remember(kind, code, row)
            else:
                if kind == "recipes":
                    _drop_lines(row)
                row.update(**writer(item, refs))
            if kind == "recipes":
                for name, rows in _recipe_lines(item, row, refs).items():
                    if rows:
                        _table(name).add_rows(rows)
    products = {item["id"]: item for item in plant.get("products") or []}
    for code in dirty.get("products") or []:
        if code in products:
            refs("products", code).update(**records.product_lid_row(products[code], refs))
    presses = {item["id"]: item for item in plant.get("presses") or []}
    for code in dirty.get("presses") or []:
        if code in presses:
            refs("presses", code).update(**records.press_board_row(presses[code], refs))


def _action_plant(action, payload):
    """What an edit reads: its record with everything the record's rules look at, the workers,
    and every stored code of a kind the edit may create."""
    plant = loader.Plant(workers=True, codes=_CREATES.get(action, ()))
    context = payload.get("contextId") or ""
    if action == "edit-mold" and payload.get("contextKind") == "mold":
        _mold_scope(plant, context)
    elif action in _PRODUCT_ACTIONS or action == "edit-mold":
        _product_scope(plant, context)
        for key in ("other", "lidId", "partId"):
            if payload.get(key):
                _product_scope(plant, payload[key])
        if payload.get("from"):
            _recipe_scope(plant, payload["from"])
    elif action in _RECIPE_ACTIONS:
        _recipe_scope(plant, context)
    elif action == "edit-press" and payload.get("mounted"):
        plant.add(products=[payload["mounted"]])
    elif action == "new-mold" and payload.get("product"):
        plant.add(products=[payload["product"]])
    return plant.graph()


@anvil.tables.in_transaction
def apply_action(action, payload):
    payload = payload or {}
    plant = _action_plant(action, payload)
    result = domain.dispatch(plant, action, payload)
    if result.get("error"):
        return {"error": result["error"]}
    _persist(plant, result.get("dirty") or {})
    return {"redirect": result.get("redirect"), "refresh": bool(result.get("refresh"))}


@anvil.tables.in_transaction
def replace_all(graph_in):
    """Replace the whole plant record, e.g. from the workbook import."""
    _write_all(_ready({kind: graph_in.get(kind) or [] for kind in _KINDS}))
    return domain.counts(_whole())
