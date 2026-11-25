"""The plant record in ordinary Postgres tables.

The tables are the record and every request reads them directly: a page loads its own rows
through ``loader`` and an edit loads what it touches, changes it, and writes back only the rows
and line tables that changed, in one transaction. ``records`` maps rows to the shape the domain
module works on.
"""

import copy
import datetime

import accounts
import domain
import loader
import performance as performance_view
import records
import sql

_SEEDED = False
_REFERENCE = ("machines", "machine_types", "item_categories", "units", "person_roles", "variant_attributes")
_PEOPLE = ("personnel", "shifts")
_REASONS = ("stoppage_causes", "scrap_reasons")
_SETTINGS = _REFERENCE + _PEOPLE + _REASONS


def _ids(rows):
    return [row.get_id() for row in rows if row is not None]


class _Refs:
    """Rows by code, from what the request read, else fetched once."""

    def __init__(self, known=()):
        self._rows = dict(known)

    def __call__(self, table, code):
        key = (table, code)
        if key not in self._rows:
            found = sql.read(table, "t.code = %s", (code,))
            self._rows[key] = found[0] if found else None
        return self._rows[key]

    def load(self, table):
        for row in sql.read(table):
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
        plant.find("lots", "t.run_id = ANY(%s::bigint[])", (_ids(runs),))
        plant.find("stoppages", "t.run_id = ANY(%s::bigint[])", (_ids(runs),))
    plant.follow("lots", "item")
    plant.follow("production_orders", "item")
    return _recipe_context(plant)


def _every_recipe_of(plant, items):
    """All recipes of ``items``, which an item's status and row are computed from."""
    items = [row for row in items if row is not None]
    if items:
        plant.find("recipes", "t.item_id = ANY(%s::bigint[])", (_ids(items),))
    return _recipe_context(plant)


def _item_scope(plant, code):
    row = plant.get("items", code)
    if row is None:
        return plant
    if row["parent"] is not None:
        plant.by_codes("items", [row["parent"]["code"]])
    plant.find("items", "t.parent_id = %s", (row.get_id(),))
    plant.lines("item_attributes")
    made = plant.find("recipes", "t.item_id = %s", (row.get_id(),))
    using = [found["code"] for found in sql.query(
        """
        SELECT r.code
        FROM plant.recipe_inputs ri
        JOIN plant.recipes r ON r.id = ri.recipe_id
        WHERE ri.item_id = %s
        """,
        (row.get_id(),),
    )]
    _every_recipe_of(plant, [recipe["item"] for recipe in plant.by_codes("recipes", using)])
    if made:
        plant.find("production_runs", "t.recipe_id = ANY(%s::bigint[])", (_ids(made),))
    plant.by_codes("production_runs", _consumers(plant.find("lots", "t.item_id = %s", (row.get_id(),))))
    plant.find("production_orders", "t.item_id = %s", (row.get_id(),))
    plant.all("personnel", "shifts")
    return _run_context(plant)


def _mold_scope(plant, code):
    row = plant.get("molds", code)
    if row is not None:
        _every_recipe_of(plant, [recipe["item"] for recipe in plant.find("recipes", "t.mold_id = %s", (row.get_id(),))])
    return _recipe_context(plant)


def _machine_scope(plant, code):
    row = plant.get("machines", code)
    if row is None:
        return plant
    on_machine = plant.find("recipes", "t.machine_id = %s", (row.get_id(),))
    approved = plant.find("items", "t.id IN (SELECT item_id FROM plant.item_machines WHERE machine_id = %s)", (row.get_id(),))
    _every_recipe_of(plant, approved + [recipe["item"] for recipe in on_machine])
    if on_machine:
        plant.find("production_runs", "t.recipe_id = ANY(%s::bigint[])", (_ids(on_machine),))
    plant.find("stoppages", "t.machine_id = %s", (row.get_id(),))
    plant.follow("stoppages", "run")
    plant.all("personnel", "shifts", "stoppage_causes")
    plant.find("changeovers", "t.machine_id = %s", (row.get_id(),))
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
        plant.find("recipes", "t.item_id = %s", (row["item"].get_id(),))
    plant.find("production_runs", "t.recipe_id = %s", (row.get_id(),))
    plant.all("personnel", "shifts", "stoppage_causes")
    return _run_context(plant)


def _order_scope(plant, code):
    row = plant.get("production_orders", code)
    if row is not None:
        plant.find("production_runs", "t.order_id = %s", (row.get_id(),))
        _every_recipe_of(plant, [row["item"]])
    plant.all("personnel", "shifts")
    return _run_context(plant)


def _consumers(lots):
    """Codes of the runs that consumed any of ``lots``."""
    if not lots:
        return []
    found = sql.query(
        """
        SELECT r.code
        FROM plant.run_inputs ri
        JOIN plant.production_runs r ON r.id = ri.run_id
        WHERE ri.lot_id = ANY(%s::bigint[])
        """,
        (_ids(lots),),
    )
    return [line["code"] for line in found]


def _run_scope(plant, code):
    row = plant.get("production_runs", code)
    if row is None:
        return plant
    plant.all("personnel", "shifts", "stoppage_causes", "scrap_reasons")
    _run_context(plant)
    plant.find("changeovers", "t.to_run_id = %s", (row.get_id(),))
    plant.find("changeovers", "t.from_run_id = %s", (row.get_id(),))
    _changeover_items(plant)
    plant.by_codes("production_runs", _consumers(plant.find("lots", "t.run_id = %s", (row.get_id(),))))
    if row["recipe"] is not None:
        wanted = [line["item"] for line in plant.lines_of("recipe_inputs", plant.get("recipes", row["recipe"]["code"])) or []]
        if wanted:
            plant.find("lots", "t.item_id = ANY(%s::bigint[])", (_ids(wanted),))
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
        fed = sql.query(
            """
            SELECT l.code
            FROM plant.run_inputs ri
            JOIN plant.lots l ON l.id = ri.lot_id
            WHERE ri.run_id = ANY(%s::bigint[])
            """,
            (_ids(makers),),
        ) if makers else []
        back = plant.by_codes("lots", [line["code"] for line in fed])
        users = plant.by_codes("production_runs", _consumers(forward))
        forward = plant.find("lots", "t.run_id = ANY(%s::bigint[])", (_ids(users),)) if users else []
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
    runs = loader.narrow("production_runs", _OVERVIEW_RUN, codes, where="t.ended_at IS NULL AND t.started_at IS NOT NULL")
    if named:
        runs += loader.narrow("production_runs", _OVERVIEW_RUN, codes, where="t.code = ANY(%s::text[])", params=(named,))
    graph["production_runs"] = sorted({run["id"]: run for run in runs}.values(), key=lambda run: run["id"])
    for table, child, keys in (("recipes", "recipe_inputs", ("itemId", "share")), ("production_runs", "run_inputs", ("lotId", "quantity"))):
        lines = loader.narrow_lines(child, keys, codes)
        for entry in graph[table]:
            entry["inputs"] = lines.get(entry["id"], [])
    return graph


def _counted(counted):
    counted["runs"] = sql.count("production_runs")
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
def _run_span():
    """The plant's first and last run days, or None when nothing ran."""
    first = sql.one("SELECT started_at FROM plant.production_runs WHERE started_at IS NOT NULL ORDER BY started_at ASC LIMIT 1")
    last = sql.one("SELECT started_at FROM plant.production_runs WHERE started_at IS NOT NULL ORDER BY started_at DESC LIMIT 1")
    if first is None or last is None:
        return None
    return [performance_view.local_day(first["started_at"]), performance_view.local_day(last["started_at"])]


def performance(year=None, month=0, machine=""):
    span = _run_span()
    years = list(range(span[1].year, span[0].year - 1, -1)) if span else []
    year = int(year) if year else (years[0] if years else datetime.date.today().year)
    begin, end = performance_view.period(year, month)
    windows = {
        "production_runs": ("t.started_at >= %s AND t.started_at < %s", [begin, end]),
        "stoppages": ("t.started_at >= %s AND t.started_at < %s", [begin, end]),
        "changeovers": ("t.ended_at >= %s AND t.ended_at < %s", [begin, end]),
    }
    if machine:
        chosen = sql.one("SELECT id FROM plant.machines WHERE code = %s", (machine,))
        if chosen is not None:
            made_here = [row["item_id"] for row in sql.query(
                "SELECT DISTINCT item_id FROM plant.recipes WHERE machine_id = %s AND item_id IS NOT NULL",
                (chosen["id"],),
            )]
            recipe_ids = [row["id"] for row in sql.query(
                "SELECT id FROM plant.recipes WHERE item_id = ANY(%s::bigint[])", (made_here,),
            )] if made_here else []
            text, params = windows["production_runs"]
            windows["production_runs"] = (text + " AND t.recipe_id = ANY(%s::bigint[])", params + [recipe_ids])
            for name in ("stoppages", "changeovers"):
                text, params = windows[name]
                windows[name] = (text + " AND t.machine_id = %s", params + [chosen["id"]])
    codes = loader.Codes()
    graph = {}
    for table, keys in _PERFORMANCE_FIELDS.items():
        where, params = windows.get(table, ("TRUE", []))
        graph[table] = loader.narrow(table, keys, codes, where=where, params=params)
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
        self.rows = {table: {row["code"]: row for row in sql.read(table)} for table in tables}

    def __call__(self, table, code):
        return self.rows[table].get(code)


def derive_changeovers():
    """Derive the changeovers again from every run and stoppage; those entered by hand stay. Returns counts."""
    import changeovers

    codes = loader.Codes()
    graph = {table: loader.narrow(table, keys, codes) for table, keys in _DERIVE_FIELDS.items()}
    graph["changeovers"] = loader.narrow("changeovers", ("fromRunId", "toRunId", "source"), codes,
                                         where="t.source = %s", params=("entered",))
    for table, child, key, keys in (("recipes", "recipe_inputs", "inputs", ("itemId",)), ("production_runs", "run_scrap", "scrap", ("quantity",))):
        lines = loader.narrow_lines(child, keys, codes)
        for entry in graph[table]:
            entry[key] = lines.get(entry["id"], [])
    found = changeovers.derive(graph)
    _replace_derived(found, bool(graph["changeovers"]))
    return changeovers.summary(found)


@sql.in_transaction
def _replace_derived(found, entered):
    if entered:
        sql.delete_where("changeovers", "source IS DISTINCT FROM %s", ("entered",))
    else:
        sql.delete_where("changeovers", "TRUE")
    refs = _CodeRefs(("machines", "production_runs", "items", "stoppages"))
    _add("changeovers", [records.to_row("changeovers", item, refs) for item in found])


def overview(who="all"):
    result = domain.overview(_without_runs(), who)
    _counted(result["counts"])
    return result


def structure():
    return _counted(domain.counts(_without_runs()))


# The same fold as domain.fold for letters this plant actually types: Greek lookalikes, a tonos on
# those letters, and the common Latin accents. Combining marks are already gone from the stored text.
_FOLD_FROM = "άέήίόύώαβεζηικμνορτυχςàáâãäåèéêëìíîïòóôõöùúûüýÿñç"
_FOLD_TO = "aehioyoabezhikmnoptyxσaaaaaaeeeeiiiiooooouuuuyync"


def _fold_sql(expr):
    return "translate(lower(%s), '%s', '%s')" % (expr, _FOLD_FROM, _FOLD_TO)


def _named(alias):
    """A linked record's label: its name, or its code when the name is blank, or nothing when it is missing."""
    return "CASE WHEN %s.code IS NULL THEN '' WHEN %s.name <> '' THEN %s.name ELSE %s.code END" % (alias, alias, alias, alias)


def search(term):
    """Up to 16 hits, in the same kind order as the old scan, without loading those tables."""
    query = domain.fold(term).strip()
    if len(query) < 2:
        return []
    needle = "%" + query.replace("%", "").replace("_", "") + "%"
    found = []

    def take(statement):
        if len(found) >= 16:
            return
        found.extend(sql.query(statement, (needle, 16 - len(found))))

    def like(expr):
        return _fold_sql(expr) + " LIKE %s"

    take(
        "SELECT 'item' AS kind, t.code AS id, " + _named("t") + " AS label FROM plant.items t WHERE "
        + like("coalesce(t.name, '') || ' ' || t.code || ' ' || coalesce(t.erp_code, '') || ' ' || coalesce(t.properties->>'labelCode', '')")
        + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'mold' AS kind, t.code AS id, " + _named("t") + " AS label FROM plant.molds t WHERE "
        + like("t.code || ' ' || coalesce(t.name, '')") + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'machine' AS kind, t.code AS id, " + _named("t") + " AS label FROM plant.machines t WHERE "
        + like("coalesce(t.name, '') || ' ' || t.code || ' ' || coalesce(t.alias, '')") + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'recipe' AS kind, t.code AS id, " + _named("i") + " || ' on ' || " + _named("m") + " AS label "
        "FROM plant.recipes t "
        "LEFT JOIN plant.items i ON i.id = t.item_id "
        "LEFT JOIN plant.machines m ON m.id = t.machine_id WHERE "
        + like("t.code || ' ' || " + _named("i") + " || ' ' || " + _named("m"))
        + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'order' AS kind, t.code AS id, t.code || ' · ' || " + _named("i") + " AS label "
        "FROM plant.production_orders t LEFT JOIN plant.items i ON i.id = t.item_id WHERE "
        + like("t.code || ' ' || coalesce(t.erp_order_no, '') || ' ' || " + _named("i"))
        + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'run' AS kind, t.code AS id, t.code AS label FROM plant.production_runs t WHERE "
        + like("t.code") + " ORDER BY t.code LIMIT %s"
    )
    take(
        "SELECT 'lot' AS kind, t.code AS id, t.number || ' · ' || " + _named("i") + " AS label "
        "FROM plant.lots t LEFT JOIN plant.items i ON i.id = t.item_id WHERE "
        + like("coalesce(t.number, '') || ' ' || t.code || ' ' || coalesce(t.supplier_lot, '')")
        + " ORDER BY t.code LIMIT %s"
    )
    return found


def _runs_by_machine():
    """Every run under its machine, newest first. A narrow read: the stoppage editor still lists old runs."""
    grouped = {}
    rows = sql.query(
        """
        SELECT r.code, r.ended_at, mac.code AS machine,
               CASE WHEN i.name <> '' THEN i.name WHEN i.code IS NOT NULL THEN i.code ELSE '' END AS item
        FROM plant.production_runs r
        LEFT JOIN plant.recipes rec ON rec.id = r.recipe_id
        LEFT JOIN plant.machines mac ON mac.id = rec.machine_id
        LEFT JOIN plant.items i ON i.id = rec.item_id
        ORDER BY r.started_at DESC NULLS LAST
        """
    )
    for row in rows:
        grouped.setdefault(row["machine"] or "", []).append({
            "value": row["code"],
            "label": "%s · %s%s" % (row["code"], row["item"] or "", "" if row["ended_at"] else " · running"),
        })
    return grouped


def choices():
    plant = _plant("items", "molds", "recipes", "production_orders", *(_PEOPLE + _REASONS))
    plant.lines("recipe_inputs")
    result = domain.choices(plant.graph())
    result["runsByMachine"] = _runs_by_machine()
    return result


def counts():
    """Row counts for the menu, one count query per table."""
    return {table: sql.count(table) for table in (
        "items", "molds", "machines", "recipes", "production_orders", "production_runs", "stoppages", "lots")}


def downtime_hours():
    """The same total the old loop showed: each stop rounded to two decimals, then the sum to one."""
    row = sql.one(
        """
        SELECT round(coalesce(sum(
            CASE WHEN started_at IS NULL OR ended_at IS NULL OR ended_at < started_at THEN 0
            ELSE round((EXTRACT(EPOCH FROM (ended_at - started_at)) / 3600.0)::numeric, 2) END
        ), 0)::numeric, 1) AS hours
        FROM plant.stoppages
        """
    )
    return float(row["hours"]) if row and row["hours"] is not None else 0.0


# Writing ----------------------------------------------------------------------------------

def _add(table, rows):
    for fields in rows:
        sql.insert(table, fields)


def _clear_all():
    sql.execute("UPDATE plant.machines SET attached_to_id = NULL")
    sql.execute("UPDATE plant.items SET parent_id = NULL")
    for child, _, _, _, _ in records.CHILDREN:
        sql.execute("DELETE FROM plant." + sql.ident(child))
    for table in reversed(records.ORDER):
        sql.execute("DELETE FROM plant." + sql.ident(table))


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
                kept = refs(table, item["id"])
                if kept is not None:
                    sql.update(table, kept.get_id(), late)
    for child, parent, _, _, _ in records.CHILDREN:
        rows = []
        for item in plant.get(parent) or []:
            rows += records.child_rows(child, item, refs(parent, item["id"]), refs)
        _add(child, rows)


@sql.in_transaction
def _seed_if_empty():
    if sql.count("items") > 0:
        return
    import seed_data

    seed = seed_data.load()
    _write_all(domain.normalize({table: seed.get(table) or [] for table in records.ORDER}))


def _ensure_attributes():
    """Variant attribute names, when the plant has not named any. Items already stored are not touched."""
    if sql.one("SELECT id FROM plant.variant_attributes LIMIT 1"):
        return
    graph = domain.normalize({"variant_attributes": []})
    domain.ensure_variant_attributes(graph)
    for entry in graph["variant_attributes"]:
        sql.insert("variant_attributes", records.to_row("variant_attributes", entry, lambda *_args: None))


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
        sql.delete_where(child, parent_column + "_id = %s", (parent_row.get_id(),))
        return
    ids = [row.get_id() for row in rows]
    if ids:
        sql.delete_where(child, "id = ANY(%s::bigint[])", (ids,))


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
                row = sql.insert(table, records.to_row(table, item, refs, skip=records.LATE.get(table, ())))
                refs.remember(table, code, row)
            elif not _same(table, old, item):
                sql.update(table, row.get_id(), records.to_row(table, item, refs, skip=records.LATE.get(table, ())))
    for table in records.LATE:
        for code in dirty.get(table) or []:
            item, old = items[table].get(code), before[table].get(code)
            if item is not None and (old is None or records.late_row(table, old, _codes) != records.late_row(table, item, _codes)):
                kept = refs(table, code)
                if kept is not None:
                    sql.update(table, kept.get_id(), records.late_row(table, item, refs))
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
                _add(child, rows)
    for table, row in sorted(gone, key=lambda pair: -records.ORDER.index(pair[0])):
        for child, parent, _, _, _ in records.CHILDREN_OF.get(table, ()):
            _drop_lines(loaded, child, row, whole=True)
        _unlink_changeovers(table, row)
        sql.delete(table, row.get_id())


def _unlink_changeovers(table, row):
    """A changeover goes with either of its runs; a deleted stoppage only stops being its source of times."""
    if table == "production_runs":
        sql.delete_where("changeovers", "from_run_id = %s OR to_run_id = %s", (row.get_id(), row.get_id()))
    elif table == "stoppages":
        sql.execute("UPDATE plant.changeovers SET stoppage_id = NULL WHERE stoppage_id = %s", (row.get_id(),))


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
        recipes = plant.find("recipes", "t.machine_id = %s", (machine.get_id(),)) if machine is not None else []
        if recipes:
            plant.find("production_runs", "t.recipe_id = ANY(%s::bigint[]) AND t.ended_at IS NULL", (_ids(recipes),))
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
        plant.find("lots", "t.item_id = ANY(%s::bigint[])", (_ids(items),))


def _by_id(plant, table):
    return {item["id"]: item for item in plant.get(table) or []}


@sql.in_transaction
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
    plant.find("production_runs", "t.ended_at IS NULL AND t.started_at IS NOT NULL")
    plant.follow("production_runs", "recipe")
    plant.follow("production_runs", "order")
    plant.follow("production_runs", "operator")
    plant.follow("production_runs", "shift")
    plant.follow("recipes", "mold")
    plant.follow("recipes", "item")
    plant.follow("production_orders", "item")
    plant.find("stoppages", "t.ended_at IS NULL")
    plant.follow("stoppages", "cause")
    plant.find("production_orders", "t.status = ANY(%s::text[])", (list(domain.OPEN_ORDERS),))
    plant.follow("production_orders", "item")
    now = records.moment_text(datetime.datetime.now(datetime.timezone.utc))
    return domain.floor_view(plant.graph(), now, today or now[:10])


@sql.in_transaction
def replace_all(graph_in):
    """Replace the whole plant record, e.g. from the workbook import."""
    _write_all(domain.normalize({table: graph_in.get(table) or [] for table in records.ORDER}))
    _ensure_attributes()
    return counts()
