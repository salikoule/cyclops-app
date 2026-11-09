"""One page of a record list, read from the tables.

A list asks for a page with its sorters and header filters. The filters become a query on stored
columns (a name filter on a linked record finds those records first), the query is sliced to the
page, and only the page's records and what their rows are computed from are read. Calculated
columns (status, scrap, pieces per hour) show on the page but cannot be filtered or sorted.
"""

import datetime
import math
import re
import unicodedata

import anvil.tables
import anvil.tables.query as q
from anvil.tables import app_tables

import domain
import performance
import store

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class _NoMatch(Exception):
    """A filter that no row can satisfy."""


def _table(name):
    return getattr(app_tables, name)


def _text(value):
    return str(value or "").strip()


def _plain(text):
    return "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))


def _like(text):
    """Contains the text, in any case; the database does not fold Greek case or accents, so the plain upper and lower forms are tried too."""
    text = text.replace("%", "").replace("_", "")
    forms = list(dict.fromkeys((text, _plain(text).upper(), _plain(text).lower())))
    patterns = [q.ilike("%" + form + "%") for form in forms]
    return patterns[0] if len(patterns) == 1 else q.any_of(*patterns)


def _rows_where(table, **filters):
    found = list(_table(table).search(q.fetch_only("code"), **filters))
    if not found:
        raise _NoMatch()
    return found


# Filters: each takes the typed text and returns {column: condition} ----------------------------

def code(column="code"):
    return lambda text: {column: _like(text)}


def contains(column):
    return lambda text: {column: _like(text)}


def linked(column, table, field="name"):
    """Rows whose ``column`` links to a ``table`` row with ``field`` containing the text."""
    return lambda text: {column: q.any_of(*_rows_where(table, **{field: _like(text)}))}


def through(column, table, link, target, field="name"):
    """Rows whose ``column`` links to a ``table`` row whose ``link`` points at a matching ``target`` row."""
    def build(text):
        targets = _rows_where(target, **{field: _like(text)})
        return {column: q.any_of(*_rows_where(table, **{link: q.any_of(*targets)}))}
    return build


def chosen(column, values):
    """A list filter: the label picked maps to a condition."""
    def build(text):
        if text not in values:
            raise _NoMatch()
        return {column: values[text]}
    build.choices = list(values)
    return build


def moment(column):
    def build(text):
        start, end = period_of(text)
        begin, finish = performance.local_bounds(start, end)
        return {column: q.between(begin, finish, min_inclusive=True, max_inclusive=False)}
    return build


def day(column):
    def build(text):
        start, end = period_of(text)
        return {column: q.between(start, end, min_inclusive=True, max_inclusive=False)}
    return build


def period_of(text):
    """The days a typed date covers, as (first day, day after): "2025", "Mar 2025", "15 Mar 2025", "15/3/2025", "2025-03"."""
    words = [part for part in re.split(r"[\s/.,-]+", _text(text).lower()) if part]
    numbers, month = [], None
    for word in words:
        if word.isdigit():
            numbers.append(int(word))
        elif word[:3] in MONTHS:
            month = MONTHS.index(word[:3]) + 1
        else:
            raise _NoMatch()
    year = next((number for number in numbers if number > 31), None)
    rest = [number for number in numbers if number != year]
    if year is None:
        year = datetime.date.today().year
    try:
        if month is None and len(rest) >= 2:
            day_number, month = rest[0], rest[1]
            start = datetime.date(year, month, day_number)
            return start, start + datetime.timedelta(days=1)
        if month is None and len(rest) == 1 and len(words) == 2:
            month = rest[0]
            rest = []
        if month is not None and rest:
            start = datetime.date(year, month, rest[0])
            return start, start + datetime.timedelta(days=1)
        if month is not None:
            start = datetime.date(year, month, 1)
            return start, datetime.date(year + (month == 12), month % 12 + 1, 1)
        if numbers == [year]:
            return datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1)
    except ValueError:
        pass
    raise _NoMatch()


# What each list reads ----------------------------------------------------------------------------

def _item_context(plant, rows):
    store._every_recipe_of(plant, rows)
    if rows:
        using = [line["recipe"]["code"] for line in
                 app_tables.recipe_inputs.search(q.fetch_only(recipe=q.fetch_only("code")), item=q.any_of(*rows)) if line["recipe"] is not None]
        plant.by_codes("recipes", using)
    return store._recipe_context(plant)


def _mold_context(plant, rows):
    if rows:
        store._every_recipe_of(plant, [recipe["item"] for recipe in plant.find("recipes", mold=q.any_of(*rows))])
    return store._recipe_context(plant)


def _machine_context(plant, rows):
    if rows:
        plant.find("recipes", machine=q.any_of(*rows))
    plant.find("production_runs", ended_at=None, started_at=q.not_(None))
    plant.follow("production_runs", "recipe")
    return store._recipe_context(plant)


def _order_context(plant, rows):
    if rows:
        plant.find("production_runs", order=q.any_of(*rows))
    plant.follow("production_orders", "item")
    return plant


def _run_context(plant, rows):
    plant.all("personnel", "shifts", "scrap_reasons")
    return store._run_context(plant)


def _stoppage_context(plant, rows):
    plant.all("personnel", "stoppage_causes")
    plant.follow("stoppages", "run")
    return store._run_context(plant)


def _lot_context(plant, rows):
    plant.follow("lots", "run")
    plant.by_codes("production_runs", store._consumers(rows))
    return store._run_context(plant)


def _changeover_context(plant, rows):
    return store._changeover_items(plant)


RUNNING = {"Running": None, "Done": q.not_(None)}
OPEN = {"Open": None, "Closed": q.not_(None)}

LISTS = {
    "item": {
        "table": "items", "order": ("code", True), "context": _item_context, "row": domain.item_row,
        "sort": {"id": "code", "name": "name", "erp": "erp_code", "typeLabel": "item_type"},
        "filter": {"id": code(), "name": contains("name"), "erp": contains("erp_code"), "category": linked("category", "item_categories"),
                   "typeLabel": chosen("item_type", {label: key for key, label in domain.ITEM_TYPES})},
    },
    "mold": {
        "table": "molds", "order": ("code", True), "context": _mold_context, "row": domain.mold_row,
        "sort": {"id": "code", "name": "name", "cavities": "cavities", "shot": "shot_weight_g", "location": "location"},
        "filter": {"id": code(), "name": contains("name"), "location": contains("location")},
    },
    "machine": {
        "table": "machines", "order": ("code", True), "context": _machine_context, "row": domain.machine_row,
        "sort": {"id": "code", "name": "name", "euromap": "euromap", "changeover": "changeover_min", "location": "location"},
        "filter": {"id": code(), "name": contains("name"), "euromap": contains("euromap"), "type": linked("machine_type", "machine_types"),
                   "attachedTo": linked("attached_to", "machines")},
    },
    "recipe": {
        "table": "recipes", "order": ("code", True), "context": lambda plant, rows: store._recipe_context(plant), "row": domain.recipe_row,
        "sort": {"id": "code", "cycle": "cycle_s"},
        "filter": {"id": code(), "item": linked("item", "items"), "machine": linked("machine", "machines"), "mold": linked("mold", "molds", "code")},
    },
    "order": {
        "table": "production_orders", "order": ("code", True), "context": _order_context, "row": domain.order_row,
        "sort": {"id": "code", "quantity": "quantity", "due": "due_date", "erp": "erp_order_no"},
        "filter": {"id": code(), "item": linked("item", "items"), "erp": contains("erp_order_no"), "due": day("due_date"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.ORDER_STATUSES})},
    },
    "run": {
        "table": "production_runs", "order": ("started_at", False), "context": _run_context, "row": domain.run_row,
        "sort": {"id": "code", "start": "started_at", "good": "good_qty"},
        "filter": {"id": code(), "start": moment("started_at"), "order": linked("order", "production_orders", "code"),
                   "machine": through("recipe", "recipes", "machine", "machines"), "item": through("recipe", "recipes", "item", "items"),
                   "operator": linked("operator", "personnel"), "status": chosen("ended_at", RUNNING)},
    },
    "stoppage": {
        "table": "stoppages", "order": ("started_at", False), "context": _stoppage_context, "row": domain.stoppage_row,
        "sort": {"start": "started_at", "end": "ended_at"},
        "filter": {"start": moment("started_at"), "end": moment("ended_at"), "machine": linked("machine", "machines"),
                   "cause": linked("cause", "stoppage_causes"), "category": linked("cause", "stoppage_causes", "category"),
                   "description": contains("description"), "fix": contains("fix"), "reportedBy": linked("reported_by", "personnel"),
                   "status": chosen("ended_at", OPEN)},
    },
    "lot": {
        "table": "lots", "order": ("code", True), "context": _lot_context, "row": domain.lot_row,
        "sort": {"id": "code", "number": "number", "quantity": "quantity", "received": "received_at"},
        "filter": {"id": code(), "number": contains("number"), "item": linked("item", "items"), "origin": contains("origin"),
                   "received": moment("received_at"), "run": linked("run", "production_runs", "code"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.LOT_STATUSES})},
    },
    "changeover": {
        "table": "changeovers", "order": ("started_at", False), "context": _changeover_context, "row": domain.changeover_row,
        "sort": {"id": "code", "start": "started_at", "hours": "lost_h"},
        "filter": {"id": code(), "start": moment("started_at"), "machine": linked("machine", "machines"), "from": linked("from_item", "items"),
                   "to": linked("to_item", "items"), "kind": chosen("kind", {label: key for key, label in domain.CHANGEOVER_KINDS}),
                   "source": chosen("source", {label: key for key, label in domain.CHANGEOVER_SOURCES}),
                   "status": chosen("confidence", {"High": "high", "Medium": "medium", "Low": "low"}), "basis": contains("basis")},
    },
}


def capabilities():
    """Which fields each list can filter and sort, and the labels of its pick-list filters, for the page's column headers."""
    return {kind: {"filter": sorted(spec["filter"]), "sort": sorted(spec["sort"]),
                   "choices": {field: build.choices for field, build in spec["filter"].items() if hasattr(build, "choices")}}
            for kind, spec in LISTS.items()}


def _conditions(spec, filters, gap_ids):
    found = {}
    for entry in filters or []:
        build = spec["filter"].get(entry.get("field"))
        text = _text(entry.get("value"))
        if build is None or not text:
            continue
        for column, condition in build(text).items():
            found.setdefault(column, []).append(condition)
    if gap_ids is not None:
        if not gap_ids:
            raise _NoMatch()
        found.setdefault("code", []).append(q.any_of(*gap_ids))
    return {column: conditions[0] if len(conditions) == 1 else q.all_of(*conditions) for column, conditions in found.items()}


def _ordering(spec, sorters):
    chosen_sort = [(spec["sort"][entry["field"]], entry.get("dir") != "desc") for entry in sorters or [] if entry.get("field") in spec["sort"]]
    ordering = chosen_sort or [spec["order"]]
    if all(column != "code" for column, _ in ordering):
        ordering.append(("code", True))
    return [anvil.tables.order_by(column, ascending=ascending) for column, ascending in ordering]


def _gap(kind, key):
    if not key:
        return None, None
    graph = store._recipe_context(store._plant("items", "molds", "recipes", "stoppages", "lots")).graph()
    match = next((entry for entry in domain.gaps(graph) if entry["key"] == key and entry["kind"] == kind), None)
    if match is None:
        return None, None
    return match["ids"], {"count": match["count"], "title": match["title"], "benefit": match["benefit"]}


def page(kind, number=1, size=25, sorters=None, filters=None, gap=None):
    spec = LISTS.get(kind)
    if spec is None:
        return {"error": "Unknown list."}
    size = max(1, min(int(size or 25), 500))
    number = max(1, int(number or 1))
    gap_ids, banner = _gap(kind, gap)
    reply = {"data": [], "last_page": 1, "last_row": 0, "banner": banner}
    try:
        conditions = _conditions(spec, filters, gap_ids)
    except _NoMatch:
        return reply
    found = _table(spec["table"]).search(q.fetch_only("code"), *_ordering(spec, sorters), **conditions)
    total = len(found)
    codes = [row["code"] for row in found[(number - 1) * size:number * size]]
    plant = store._plant()
    rows = plant.by_codes(spec["table"], codes)
    graph = spec["context"](plant, rows).graph()
    read = domain.reindex(graph)[spec["table"]]
    reply.update({"data": [spec["row"](graph, read[code]) for code in codes if code in read],
                  "last_page": max(1, math.ceil(total / size)), "last_row": total})
    return reply
