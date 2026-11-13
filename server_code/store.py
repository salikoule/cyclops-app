"""The plant record in relational Anvil tables.

The tables are the record and every request reads them directly: a page loads its own rows
through ``loader`` and an edit loads what it touches, changes it, and writes back only the rows
and line tables that changed, in one transaction. ``records`` maps rows to the shape the domain
module works on.
"""

import copy
import datetime

import anvil.tables
import anvil.tables.query as q
from anvil.tables import app_tables

import accounts
import domain
import loader
import performance as performance_view
import records

_BATCH = 200
_SEEDED = False
_REFERENCE = ("machines", "machine_types", "item_categories", "units", "person_roles", "variant_attributes")
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
    if row["parent"] is not None:
        plant.by_codes("items", [row["parent"]["code"]])
    plant.find("items", parent=row)
    plant.lines("item_attributes")
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
    plant.find("changeovers", machine=row)
    _changeover_items(plant)
    return _run_context(plant)


def _changeover_items(plant):
    plant.follow("changeovers", "from_item")
    plant.follow("changeovers", "to_item")
    return plant


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
    plant.find("changeovers", to_run=row)
    plant.find("changeovers", from_run=row)
    _changeover_items(plant)
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

def detail(kind, code):
    if kind == "settings":
        return domain.settings_view(_plant(*_PEOPLE + _REASONS, "variant_attributes").graph())
    scope = _SCOPES.get(kind)
    if scope is None:
        return {"missing": True, "kind": kind, "id": code}
    return domain.detail(scope(_plant(), code).graph(), kind, code)


_OVERVIEW_FIELDS = {
    "item_categories": ("role",),
    "stoppage_causes": ("name", "category", "planned"),
    "personnel": ("name",),
    "machines": ("name", "status", "location", "euromap", "changeoverMin", "attachedToId"),
    "items": ("name", "type", "status", "categoryId", "erpCode", "approvedMachineIds"),
    "molds": ("cavities", "shotWeight"),
    "recipes": ("itemId", "machineId", "moldId", "status", "standard", "cycle"),
    "production_orders": ("itemId", "status"),
    "lots": ("itemId", "origin", "runId"),
    "stoppages": ("machineId", "runId", "causeId", "startedAt", "endedAt", "description", "fix", "reportedById"),
}
_OVERVIEW_RUN = ("orderId", "recipeId", "startedAt", "endedAt")


def _without_runs():
    """What counts and gaps read: the fields they use of every record except the runs, plus the runs still open
    and those the stoppages name. The run count is a query."""
    codes = loader.Codes()
    graph = {table: loader.narrow(table, keys, codes, coded=("runId",)) for table, keys in _OVERVIEW_FIELDS.items()}
    named = sorted({stop["runId"] for stop in graph["stoppages"] if stop.get("runId")})
    runs = loader.narrow("production_runs", _OVERVIEW_RUN, codes, ended_at=None, started_at=q.not_(None))
    if named:
        runs += loader.narrow("production_runs", _OVERVIEW_RUN, codes, code=q.any_of(*named))
    graph["production_runs"] = sorted({run["id"]: run for run in runs}.values(), key=lambda run: run["id"])
    for table, child, keys in (("recipes", "recipe_inputs", ("itemId", "share")), ("production_runs", "run_inputs", ("lotId", "quantity"))):
        lines = loader.narrow_lines(child, keys, codes)
        for entry in graph[table]:
            entry["inputs"] = lines.get(entry["id"], [])
    return graph


def _counted(counted):
    counted["runs"] = len(app_tables.production_runs.search())
    return counted


_PERFORMANCE_FIELDS = {
    "shifts": ("name", "start", "end"),
    "stoppage_causes": ("name", "category", "planned"),
    "machines": ("name", "attachedToId"),
    "items": ("name",),
    "recipes": ("itemId", "machineId"),
    "production_runs": ("recipeId", "shiftId", "startedAt", "endedAt", "good", "cavities", "cycle"),
    "stoppages": ("machineId", "runId", "startedAt", "endedAt", "causeId"),
    "changeovers": ("machineId", "fromRunId", "toRunId", "kind", "startedAt", "endedAt", "lostHours", "source", "confidence", "stoppageId"),
}
_CODED = {"changeovers": ("fromRunId", "toRunId", "stoppageId")}


def _run_span():
    """The plant's first and last run days, or None when nothing ran."""
    ends = []
    for ascending in (True, False):
        found = app_tables.production_runs.search(q.fetch_only("started_at"), anvil.tables.order_by("started_at", ascending=ascending),
                                                  started_at=q.not_(None))
        row = next(iter(found), None)
        if row is not None:
            ends.append(performance_view.local_day(row["started_at"]))
    return ends or None


def performance(year=None, month=0, machine=""):
    span = _run_span()
    years = list(range(span[1].year, span[0].year - 1, -1)) if span else []
    year = int(year) if year else (years[0] if years else datetime.date.today().year)
    begin, end = performance_view.period(year, month)
    within = {"production_runs": {"started_at": q.between(begin, end)}, "stoppages": {"started_at": q.between(begin, end)},
              "changeovers": {"ended_at": q.between(begin, end)}}
    chosen = app_tables.machines.get(q.fetch_only("code"), code=machine) if machine else None
    if chosen is not None:
        made_here = {row["item"] for row in app_tables.recipes.search(q.fetch_only(item=q.fetch_only("code")), machine=chosen) if row["item"]}
        recipes = list(app_tables.recipes.search(q.fetch_only("code"), item=q.any_of(*made_here))) if made_here else []
        within["production_runs"]["recipe"] = q.any_of(*recipes)
        within["stoppages"]["machine"] = chosen
        within["changeovers"]["machine"] = chosen
    codes = loader.Codes()
    graph = {table: loader.narrow(table, keys, codes, coded=_CODED.get(table, ()), **within.get(table, {}))
             for table, keys in _PERFORMANCE_FIELDS.items()}
    scrap = loader.narrow_lines("run_scrap", ("quantity",), codes)
    for run in graph["production_runs"]:
        run["scrap"] = scrap.get(run["id"], [])
    return performance_view.view(graph, year, month, machine, years, span[1] if span else None)


_DERIVE_FIELDS = {
    "item_categories": ("role",),
    "shifts": ("name", "start", "end"),
    "stoppage_causes": ("name", "changeover"),
    "items": ("categoryId",),
    "recipes": ("itemId", "machineId", "moldId"),
    "production_runs": ("recipeId", "shiftId", "startedAt", "endedAt", "good", "cavities", "cycle"),
    "stoppages": ("machineId", "runId", "startedAt", "endedAt", "causeId"),
}


class _CodeRefs:
    """Rows by code for the linked tables of a bulk write, each table read once with only its codes."""

    def __init__(self, tables):
        self.rows = {table: {row["code"]: row for row in _table(table).search(q.fetch_only("code"))} for table in tables}

    def __call__(self, table, code):
        return self.rows[table].get(code)


def derive_changeovers():
    """Derive the changeovers again from every run and stoppage; those entered by hand stay. Returns counts."""
    import changeovers

    codes = loader.Codes()
    graph = {table: loader.narrow(table, keys, codes) for table, keys in _DERIVE_FIELDS.items()}
    graph["changeovers"] = loader.narrow("changeovers", ("fromRunId", "toRunId", "source"), codes, coded=("fromRunId", "toRunId"),
                                         source="entered")
    for table, child, key, keys in (("recipes", "recipe_inputs", "inputs", ("itemId",)), ("production_runs", "run_scrap", "scrap", ("quantity",))):
        lines = loader.narrow_lines(child, keys, codes)
        for entry in graph[table]:
            entry[key] = lines.get(entry["id"], [])
    found = changeovers.derive(graph)
    _replace_derived(found, bool(graph["changeovers"]))
    return changeovers.summary(found)


@anvil.tables.in_transaction
def _replace_derived(found, entered):
    if entered:
        for row in app_tables.changeovers.search(source=q.not_("entered")):
            row.delete()
    else:
        app_tables.changeovers.delete_all_rows()
    refs = _CodeRefs(("machines", "production_runs", "items", "stoppages"))
    _add("changeovers", [records.to_row("changeovers", item, refs) for item in found])


def overview(who="all"):
    result = domain.overview(_without_runs(), who)
    _counted(result["counts"])
    return result


def structure():
    return _counted(domain.counts(_without_runs()))


def search(term):
    if len(domain.fold(term).strip()) < 2:
        return []
    plant = _plant("items", "molds", "recipes", "production_orders", "lots")
    runs = app_tables.production_runs.search(q.fetch_only("code"), code=q.ilike("%" + term.strip().replace("%", "") + "%"))
    plant.by_codes("production_runs", [row["code"] for row in runs[:16]])
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
    for row in app_tables.items.search(parent=q.not_(None)):
        row.update(parent=None)
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


def _ensure_attributes():
    """Variant attribute names, when the plant has not named any. Items already stored are not touched."""
    if list(app_tables.variant_attributes.search(q.fetch_only("code"))):
        return
    graph = domain.normalize({"variant_attributes": []})
    domain.ensure_variant_attributes(graph)
    for entry in graph["variant_attributes"]:
        app_tables.variant_attributes.add_row(**records.to_row("variant_attributes", entry, lambda *_args: None))


def ensure_seeded():
    """A new app, or one whose tables were emptied, starts from the workbook import."""
    global _SEEDED
    if not _SEEDED:
        _seed_if_empty()
        _ensure_attributes()
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
        _unlink_changeovers(table, row)
        row.delete()


def _unlink_changeovers(table, row):
    """A changeover goes with either of its runs; a deleted stoppage only stops being its source of times."""
    if table == "production_runs":
        for column in ("from_run", "to_run"):
            for change in app_tables.changeovers.search(**{column: row}):
                change.delete()
    elif table == "stoppages":
        for change in app_tables.changeovers.search(stoppage=row):
            change.update(stoppage=None)


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
                       ("color", "items"), ("mold", "molds"), ("lot", "lots"), ("from", "recipes"), ("stoppage", "stoppages"),
                       ("machine", "machines"), ("parentId", "items")):
        if payload.get(key):
            plant.by_codes(table, [payload[key]])
    if action in domain.WHOLE_ACTIONS:
        plant.all(*domain.WHOLE_ACTIONS[action])
    if action == "log-shift":
        machine = plant.get("machines", payload.get("machine") or payload.get("contextId") or "")
        recipes = plant.find("recipes", machine=machine) if machine is not None else []
        if recipes:
            plant.find("production_runs", recipe=q.any_of(*recipes), ended_at=None)
    if action in ("new-item", "edit-item", "clone-item"):
        plant.lines("item_attributes")
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


def _by_id(plant, table):
    return {item["id"]: item for item in plant.get(table) or []}


@anvil.tables.in_transaction
def apply_action(action, payload, actor=""):
    payload = payload or {}
    loaded = _action_plant(action, payload)
    plant = loaded.graph()
    before = {table: {item["id"]: copy.deepcopy(item) for item in plant.get(table) or []} for table in records.ORDER}
    result = domain.dispatch(plant, action, payload)
    if result.get("error"):
        return {"error": result["error"]}
    dirty = result.get("dirty") or {}
    _persist(plant, dirty, loaded, before)
    accounts.record_changes(before, {table: _by_id(plant, table) for table in records.ORDER}, dirty, actor)
    machines = _by_id(plant, "machines")
    stops = {}
    for code, stop in _by_id(plant, "stoppages").items():
        named = dict(stop)
        named["machineId"] = (machines.get(stop.get("machineId")) or {}).get("name") or stop.get("machineId") or ""
        stops[code] = named
    notices = accounts.notifications_for(before.get("stoppages") or {}, stops, _by_id(plant, "stoppage_causes"), dirty.get("stoppages"))
    return {"redirect": result.get("redirect"), "refresh": bool(result.get("refresh")), "gaps": result.get("gaps") or [],
            "notify": notices}


def floor(today):
    """Open runs, open stoppages, and open orders. Closed history stays in the tables."""
    plant = _plant("shifts", "personnel", "stoppage_causes", "molds")
    plant.find("production_runs", ended_at=None, started_at=q.not_(None))
    plant.follow("production_runs", "recipe")
    plant.follow("production_runs", "order")
    plant.follow("production_runs", "operator")
    plant.follow("production_runs", "shift")
    plant.follow("recipes", "mold")
    plant.follow("recipes", "item")
    plant.follow("production_orders", "item")
    plant.find("stoppages", ended_at=None)
    plant.follow("stoppages", "cause")
    plant.find("production_orders", status=q.any_of(*domain.OPEN_ORDERS))
    plant.follow("production_orders", "item")
    now = records.moment_text(datetime.datetime.now(datetime.timezone.utc))
    return domain.floor_view(plant.graph(), now, today or now[:10])


@anvil.tables.in_transaction
def replace_all(graph_in):
    """Replace the whole plant record, e.g. from the workbook import."""
    _write_all(domain.normalize({table: graph_in.get(table) or [] for table in records.ORDER}))
    _ensure_attributes()
    return counts()
