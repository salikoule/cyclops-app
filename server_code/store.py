"""The plant record in relational Anvil tables.

The tables are the record and every request reads them directly: a page loads its own rows
through ``loader`` and an edit loads what it touches, changes it, and writes back only the rows
and line tables that changed, in one transaction. ``records`` maps rows to the shape the domain
module works on.
"""

import copy

import anvil.tables
import anvil.tables.query as q
from anvil.tables import app_tables

import domain
import loader
import records

_BATCH = 200
_SEEDED = False
_REFERENCE = ("machines", "machine_types", "item_categories", "units", "person_roles")
_PEOPLE = ("personnel", "shifts")
_REASONS = ("stoppage_causes", "scrap_reasons")
_SETTINGS = _REFERENCE + _PEOPLE + _REASONS


def _table(name):
    return getattr(app_tables, name)


class _Refs:
    """Rows by code, from what the request read, else fetched once."""

    def __init__(self, known=()):
        self._rows = dict(known)

    def __call__(self, table, code):
        key = (table, code)
        if key not in self._rows:
            self._rows[key] = _table(table).get(code=code)
        return self._rows[key]

    def load(self, table):
        for row in _table(table).search():
            self._rows[(table, row["code"])] = row

    def remember(self, table, code, row):
        self._rows[(table, code)] = row


# Reading ----------------------------------------------------------------------------------

def _plant(*tables, codes=()):
    return loader.Plant(codes=codes).all(*(_REFERENCE + tables))


def _recipe_context(plant):
    """For the loaded recipes: their inputs, molds, made and fed items."""
    plant.lines("recipe_inputs")
    plant.follow("recipe_inputs", "item")
    plant.follow("recipes", "mold")
    plant.follow("recipes", "item")
    return plant


def _run_context(plant):
    """For the loaded runs: their recipes, orders, scrap, consumed and produced lots, and stoppages."""
    runs = list(plant.rows["production_runs"].values())
    plant.follow("production_runs", "recipe")
    plant.follow("production_runs", "order")
    plant.lines("run_scrap")
    plant.lines("run_inputs")
    plant.follow("run_inputs", "lot")
    if runs:
        plant.find("lots", run=q.any_of(*runs))
        plant.find("stoppages", run=q.any_of(*runs))
    plant.follow("lots", "item")
    plant.follow("production_orders", "item")
    return _recipe_context(plant)


def _every_recipe_of(plant, items):
    """All recipes of ``items``, which an item's status and row are computed from."""
    items = [row for row in items if row is not None]
    if items:
        plant.find("recipes", item=q.any_of(*items))
    return _recipe_context(plant)


def _item_scope(plant, code):
    row = plant.get("items", code)
    if row is None:
        return plant
    made = plant.find("recipes", item=row)
    using = [line["recipe"]["code"] for line in app_tables.recipe_inputs.search(q.fetch_only(recipe=q.fetch_only("code")), item=row)
             if line["recipe"] is not None]
    _every_recipe_of(plant, [recipe["item"] for recipe in plant.by_codes("recipes", using)])
    if made:
        plant.find("production_runs", recipe=q.any_of(*made))
    plant.by_codes("production_runs", _consumers(plant.find("lots", item=row)))
    plant.find("production_orders", item=row)
    plant.all("personnel", "shifts")
    return _run_context(plant)


def _mold_scope(plant, code):
    row = plant.get("molds", code)
    if row is not None:
        _every_recipe_of(plant, [recipe["item"] for recipe in plant.find("recipes", mold=row)])
    return _recipe_context(plant)


def _machine_scope(plant, code):
    row = plant.get("machines", code)
    if row is None:
        return plant
    on_machine = plant.find("recipes", machine=row)
    approved = plant.find("items", approved_machines=[row])
    _every_recipe_of(plant, approved + [recipe["item"] for recipe in on_machine])
    if on_machine:
        plant.find("production_runs", recipe=q.any_of(*on_machine))
    plant.find("stoppages", machine=row)
    plant.follow("stoppages", "run")
    plant.all("personnel", "shifts", "stoppage_causes")
    return _run_context(plant)


def _recipe_scope(plant, code):
    row = plant.get("recipes", code)
    if row is None:
        return plant
    if row["item"] is not None:
        plant.find("recipes", item=row["item"])
    plant.find("production_runs", recipe=row)
    plant.all("personnel", "shifts", "stoppage_causes")
    return _run_context(plant)


def _order_scope(plant, code):
    row = plant.get("production_orders", code)
    if row is not None:
        plant.find("production_runs", order=row)
        _every_recipe_of(plant, [row["item"]])
    plant.all("personnel", "shifts")
    return _run_context(plant)


def _consumers(lots):
    """Codes of the runs that consumed any of ``lots``."""
    if not lots:
        return []
    found = app_tables.run_inputs.search(q.fetch_only(run=q.fetch_only("code")), lot=q.any_of(*lots))
    return [line["run"]["code"] for line in found if line["run"] is not None]


def _run_scope(plant, code):
    row = plant.get("production_runs", code)
    if row is None:
        return plant
    plant.all("personnel", "shifts", "stoppage_causes", "scrap_reasons")
    _run_context(plant)
    plant.by_codes("production_runs", _consumers(plant.find("lots", run=row)))
    if row["recipe"] is not None:
        wanted = [line["item"] for line in plant.lines_of("recipe_inputs", plant.get("recipes", row["recipe"]["code"])) or []]
        if wanted:
            plant.find("lots", item=q.any_of(*wanted))
    return _run_context(plant)


def _lot_scope(plant, code):
    """The lot and its family: back through the runs that made it to the lots they consumed, down to
    the supplier lots, and forward through the runs that consumed it to the lots they made."""
    row = plant.get("lots", code)
    if row is None:
        return plant
    back, forward = [row], [row]
    for _ in range(10):
        makers = plant.by_codes("production_runs", [lot["run"]["code"] for lot in back if lot["run"] is not None])
        fed = app_tables.run_inputs.search(q.fetch_only(lot=q.fetch_only("code")), run=q.any_of(*makers)) if makers else []
        back = plant.by_codes("lots", [line["lot"]["code"] for line in fed if line["lot"] is not None])
        users = plant.by_codes("production_runs", _consumers(forward))
        forward = plant.find("lots", run=q.any_of(*users)) if users else []
        if not back and not forward:
            break
    plant.all("personnel", "shifts")
    return _run_context(plant)


_SCOPES = {
    "item": _item_scope,
    "mold": _mold_scope,
    "machine": _machine_scope,
    "recipe": _recipe_scope,
    "order": _order_scope,
    "run": _run_scope,
    "lot": _lot_scope,
}

_LISTS = {
    "item": lambda: _recipe_context(_plant("items", "recipes")),
    "mold": lambda: _recipe_context(_plant("molds", "recipes", "items")),
    "machine": lambda: _run_context(_plant("recipes", "items", "molds", "production_runs", "stoppages")),
    "recipe": lambda: _recipe_context(_plant("recipes", "items", "molds")),
    "order": lambda: _run_context(_plant("production_orders", "production_runs", "items")),
    "run": lambda: _run_context(_plant("production_runs", "production_orders", "recipes", "items", "personnel", "shifts", "scrap_reasons")),
    "stoppage": lambda: _run_context(_plant("stoppages", "production_runs", "recipes", "items", "personnel", "stoppage_causes")),
    "lot": lambda: _run_context(_plant("lots", "items", "production_runs", "recipes")),
}


def detail(kind, code):
    if kind == "settings":
        return domain.settings_view(_plant(*_PEOPLE + _REASONS).graph())
    scope = _SCOPES.get(kind)
    if scope is None:
        return {"missing": True, "kind": kind, "id": code}
    return domain.detail(scope(_plant(), code).graph(), kind, code)


def list_view(kind, gap=None):
    build = _LISTS.get(kind)
    if build is None:
        return {"error": "Unknown list."}
    return domain.list_view(build().graph(), kind, gap)


def _whole():
    plant = _plant("items", "molds", "recipes", "production_orders", "production_runs", "stoppages", "lots", *(_PEOPLE + _REASONS))
    return _run_context(plant).graph()


def overview(who="all"):
    return domain.overview(_whole(), who)


def structure():
    return domain.counts(_whole())


def search(term):
    if len(domain.fold(term).strip()) < 2:
        return []
    plant = _plant("items", "molds", "recipes", "production_orders", "production_runs", "lots")
    return domain.search(plant.graph(), term)


def choices():
    plant = _plant("items", "molds", "recipes", "production_orders", "production_runs", *(_PEOPLE + _REASONS))
    plant.lines("recipe_inputs")
    return domain.choices(plant.graph())


def counts():
    """Row counts for the menu, one count query per table."""
    return {table: len(_table(table).search()) for table in (
        "items", "molds", "machines", "recipes", "production_orders", "production_runs", "stoppages", "lots")}


def downtime_hours():
    stops = app_tables.stoppages.search(q.fetch_only("started_at", "ended_at"))
    return round(sum(domain.span_hours(records.moment_text(row["started_at"]), records.moment_text(row["ended_at"])) or 0
                     for row in stops), 1)


# Writing ----------------------------------------------------------------------------------

def _add(table, rows):
    for start in range(0, len(rows), _BATCH):
        _table(table).add_rows(rows[start:start + _BATCH])


def _clear_all():
    for row in app_tables.machines.search(attached_to=q.not_(None)):
        row.update(attached_to=None)
    for child, _, _, _, _ in records.CHILDREN:
        _table(child).delete_all_rows()
    for table in reversed(records.ORDER):
        _table(table).delete_all_rows()


def _write_all(plant):
    """Replace every table with the plant record, parents before the rows that link to them."""
    _clear_all()
    refs = _Refs()
    for table in records.ORDER:
        _add(table, [records.to_row(table, item, refs, skip=records.LATE.get(table, ())) for item in plant.get(table) or []])
        refs.load(table)
    for table, columns in records.LATE.items():
        for item in plant.get(table) or []:
            late = records.late_row(table, item, refs)
            if any(value is not None for value in late.values()):
                refs(table, item["id"]).update(**late)
    for child, parent, _, _, _ in records.CHILDREN:
        rows = []
        for item in plant.get(parent) or []:
            rows += records.child_rows(child, item, refs(parent, item["id"]), refs)
        _add(child, rows)


@anvil.tables.in_transaction
def _seed_if_empty():
    if len(app_tables.items.search()) > 0:
        return
    import seed_data

    seed = seed_data.load()
    _write_all(domain.normalize({table: seed.get(table) or [] for table in records.ORDER}))


def ensure_seeded():
    """A new app, or one whose tables were emptied, starts from the workbook import."""
    global _SEEDED
    if not _SEEDED:
        _seed_if_empty()
        _SEEDED = True


def _codes(table, code):
    """A stand-in for row links, so a writer's output can be compared without reading rows."""
    return (table, code) if code else None


def _same(table, before, item):
    return before is not None and records.to_row(table, before, _codes) == records.to_row(table, item, _codes)


def _same_lines(child, before, item):
    if before is None:
        return False
    old, new = records.child_rows(child, before, None, _codes), records.child_rows(child, item, None, _codes)
    return sorted(map(repr, old)) == sorted(map(repr, new))


def _drop_lines(loaded, child, parent_row, whole=False):
    """Delete the ``child`` lines of ``parent_row`` that were read. Replacing lines that were never
    read would lose them, so that is refused unless every line goes (``whole``)."""
    _, _, parent_column, _, _ = next(spec for spec in records.CHILDREN if spec[0] == child)
    rows = loaded.lines_of(child, parent_row)
    if rows is None:
        if not whole:
            raise RuntimeError("%s lines of %s were not read before the save." % (child, parent_row["code"]))
        rows = _table(child).search(**{parent_column: parent_row})
    for row in rows:
        row.delete()


def _persist(plant, dirty, loaded, before):
    """Write the dirty records back, skipping rows and line tables that are as they were read.
    Rows are added and changed parents first, and deleted children first."""
    refs = _Refs(loaded.known_rows())
    items = {table: {item["id"]: item for item in plant.get(table) or []} for table in records.ORDER}
    gone = []
    for table in records.ORDER:
        for code in dirty.get(table) or []:
            item, old, row = items[table].get(code), before[table].get(code), refs(table, code)
            if item is None:
                if row is not None:
                    gone.append((table, row))
                continue
            if row is None:
                row = _table(table).add_row(**records.to_row(table, item, refs, skip=records.LATE.get(table, ())))
                refs.remember(table, code, row)
            elif not _same(table, old, item):
                row.update(**records.to_row(table, item, refs, skip=records.LATE.get(table, ())))
    for table in records.LATE:
        for code in dirty.get(table) or []:
            item, old = items[table].get(code), before[table].get(code)
            if item is not None and (old is None or records.late_row(table, old, _codes) != records.late_row(table, item, _codes)):
                refs(table, code).update(**records.late_row(table, item, refs))
    for child, parent, _, _, _ in records.CHILDREN:
        for code in dirty.get(parent) or []:
            item, old = items[parent].get(code), before[parent].get(code)
            if item is None or _same_lines(child, old, item):
                continue
            row = refs(parent, code)
            if old is not None:
                _drop_lines(loaded, child, row)
            rows = records.child_rows(child, item, row, refs)
            if rows:
                _table(child).add_rows(rows)
    for table, row in sorted(gone, key=lambda pair: -records.ORDER.index(pair[0])):
        for child, parent, _, _, _ in records.CHILDREN_OF.get(table, ()):
            _drop_lines(loaded, child, row, whole=True)
        row.delete()


def _action_plant(action, payload):
    """What an edit reads: its record with everything its rules look at, and every stored code of
    a table the edit may create a row in."""
    kind = payload.get("contextKind") or ""
    context = payload.get("contextId") or ""
    plant = _plant(*_PEOPLE + _REASONS, codes=domain.CREATES.get(action, ()))
    scope = _SCOPES.get(kind)
    if scope is not None and context:
        scope(plant, context)
    for key, table in (("recipe", "recipes"), ("run", "production_runs"), ("order", "production_orders"), ("item", "items"),
                       ("color", "items"), ("mold", "molds"), ("lot", "lots"), ("from", "recipes"), ("stoppage", "stoppages")):
        if payload.get(key):
            plant.by_codes(table, [payload[key]])
    if action in domain.WHOLE_ACTIONS:
        plant.all(*domain.WHOLE_ACTIONS[action])
    _run_context(plant)
    if action in domain.LOT_NUMBER_ACTIONS:
        _lots_of_items(plant, action, payload)
    return plant


def _lots_of_items(plant, action, payload):
    """Every lot of the item a lot is written for, so its number can be checked as unique."""
    items = [plant.get("items", payload.get("item"))] if payload.get("item") else []
    context = payload.get("contextId") or ""
    if payload.get("contextKind") == "lot":
        lot = plant.get("lots", context)
        items.append(lot["item"] if lot is not None else None)
    if payload.get("contextKind") == "run":
        run = plant.get("production_runs", context)
        recipe = plant.get("recipes", run["recipe"]["code"]) if run is not None and run["recipe"] is not None else None
        items.append(recipe["item"] if recipe is not None else None)
    items = [row for row in items if row is not None]
    if items:
        plant.find("lots", item=q.any_of(*items))


@anvil.tables.in_transaction
def apply_action(action, payload):
    payload = payload or {}
    loaded = _action_plant(action, payload)
    plant = loaded.graph()
    before = {table: {item["id"]: copy.deepcopy(item) for item in plant.get(table) or []} for table in records.ORDER}
    result = domain.dispatch(plant, action, payload)
    if result.get("error"):
        return {"error": result["error"]}
    _persist(plant, result.get("dirty") or {}, loaded, before)
    return {"redirect": result.get("redirect"), "refresh": bool(result.get("refresh"))}


@anvil.tables.in_transaction
def replace_all(graph_in):
    """Replace the whole plant record, e.g. from the workbook import."""
    _write_all(domain.normalize({table: graph_in.get(table) or [] for table in records.ORDER}))
    return counts()
