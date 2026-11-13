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


def _match_rows(table, fields, text):
    """Rows of ``table`` whose ``code`` or other listed fields contain ``text``."""
    found, seen = [], set()
    for field in fields:
        try:
            rows = _rows_where(table, **{field: _like(text)})
        except _NoMatch:
            continue
        for row in rows:
            code = row["code"]
            if code in seen:
                continue
            seen.add(code)
            found.append(row)
    if not found:
        raise _NoMatch()
    return found


def linked_any(column, table, fields=("code", "name")):
    """A link filter that matches any of ``fields`` (an item's code or its name)."""
    return lambda text: {column: q.any_of(*_match_rows(table, fields, text))}


def through(column, table, link, target, field="name"):
    """Rows whose ``column`` links to a ``table`` row whose ``link`` points at a matching ``target`` row."""
    def build(text):
        targets = _rows_where(target, **{field: _like(text)})
        return {column: q.any_of(*_rows_where(table, **{link: q.any_of(*targets)}))}
    return build


def through_any(column, table, link, target, fields=("code", "name")):
    """Like :func:`through`, matching the target on any of ``fields``."""
    def build(text):
        targets = _match_rows(target, fields, text)
        return {column: q.any_of(*_rows_where(table, **{link: q.any_of(*targets)}))}
    return build


def _compare_parts(text):
    raw = _text(text).replace(",", ".")
    op = ">="
    for token in (">=", "<=", ">", "<", "="):
        if raw.startswith(token):
            op = token
            raw = raw[len(token):].strip()
            break
    if raw == "":
        raise _NoMatch()
    try:
        number = float(raw)
    except ValueError:
        raise _NoMatch()
    return op, number


def _compare_query(op, number):
    if op == ">=":
        return q.greater_than_or_equal_to(number)
    if op == ">":
        return q.greater_than(number)
    if op == "<=":
        return q.less_than_or_equal_to(number)
    if op == "<":
        return q.less_than(number)
    if op == "=":
        return number
    raise _NoMatch()


def compare(column):
    """A stored number: the header value is ``>= 2``, ``< 0.5``, and so on."""
    def build(text):
        op, number = _compare_parts(text)
        return {column: _compare_query(op, number)}
    return build


def clock(start_col, end_col):
    """Hours between two moments. Applied after the query, because the duration is not stored."""
    def build(text):
        op, number = _compare_parts(text)
        return {"__clock__": (start_col, end_col, op, number)}
    return build


def _clock_ok(hours, op, number):
    if hours is None:
        return False
    if op == ">=":
        return hours >= number
    if op == ">":
        return hours > number
    if op == "<=":
        return hours <= number
    if op == "<":
        return hours < number
    return hours == number


def chosen(column, values):
    """A list filter: the label picked maps to a condition."""
    def build(text):
        if text not in values:
            raise _NoMatch()
        return {column: values[text]}
    build.choices = list(values)
    return build


def _normalize_typed_date(text):
    """Drop filter hint tails, clock times, and extra whitespace before parsing."""
    cleaned = _text(text)
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip() or cleaned
    cleaned = re.sub(r"\s*\d{1,2}:\d{2}(?::\d{2})?\s*", " ", cleaned)
    return cleaned.strip()


def _period_words(text):
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
    return words, month, year, rest, numbers


def _period_span(year, month, rest, numbers, words):
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
        raise _NoMatch()
    raise _NoMatch()


def _iso_period_range(text):
    """``YYYY-MM-DD..YYYY-MM-DD`` from the date-range picker (end date inclusive)."""
    raw = _text(text)
    if ".." not in raw:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            day = datetime.date.fromisoformat(raw)
            return [(day, day + datetime.timedelta(days=1))]
        return None
    left, right = raw.split("..", 1)
    try:
        start = datetime.date.fromisoformat(left.strip())
        end_inclusive = datetime.date.fromisoformat(right.strip())
    except ValueError:
        return None
    if end_inclusive < start:
        raise _NoMatch()
    return [(start, end_inclusive + datetime.timedelta(days=1))]


def period_ranges(text):
    """Half-open day ranges for a header date filter — one range, or two when the year is omitted."""
    iso = _iso_period_range(text)
    if iso is not None:
        return iso
    cleaned = _normalize_typed_date(text)
    words, month, year, rest, numbers = _period_words(cleaned)
    if year is not None:
        return [_period_span(year, month, rest, numbers, words)]
    today = datetime.date.today()
    years = []
    if month is not None or rest:
        years = [today.year, today.year - 1]
    elif numbers:
        years = numbers
    else:
        years = [today.year]
    spans = []
    for try_year in years:
        try:
            spans.append(_period_span(try_year, month, rest, numbers, words))
        except _NoMatch:
            continue
    if not spans:
        raise _NoMatch()
    return list(dict.fromkeys(spans))


def period_of(text):
    """The primary day range for ``text`` (first of :func:`period_ranges`)."""
    return period_ranges(text)[0]


def _between_ranges(column, ranges, *, as_moment):
    clauses = []
    for start, end in ranges:
        if as_moment:
            begin, finish = performance.local_bounds(start, end)
            clauses.append(q.between(begin, finish, min_inclusive=True, max_inclusive=False))
        else:
            clauses.append(q.between(start, end, min_inclusive=True, max_inclusive=False))
    if len(clauses) == 1:
        return {column: clauses[0]}
    return {column: q.any_of(*clauses)}


def moment(column):
    def build(text):
        return _between_ranges(column, period_ranges(text), as_moment=True)
    return build


def day(column):
    def build(text):
        return _between_ranges(column, period_ranges(text), as_moment=False)
    return build


# What each list reads ----------------------------------------------------------------------------

def _item_context(plant, rows):
    plant.follow("items", "parent")
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


def _stoppage_item():
    """Stoppages whose run's recipe is for an item matching the code or the name."""
    def build(text):
        items = _match_rows("items", ("code", "name"), text)
        recipes = _rows_where("recipes", item=q.any_of(*items))
        runs = _rows_where("production_runs", recipe=q.any_of(*recipes))
        return {"run": q.any_of(*runs)}
    return build

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
        "filter": {"id": code(), "item": linked_any("item", "items"), "machine": linked("machine", "machines"), "mold": linked("mold", "molds", "code")},
    },
    "order": {
        "table": "production_orders", "order": ("code", True), "context": _order_context, "row": domain.order_row,
        "sort": {"id": "code", "quantity": "quantity", "due": "due_date", "erp": "erp_order_no"},
        "filter": {"id": code(), "item": linked_any("item", "items"), "erp": contains("erp_order_no"), "due": day("due_date"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.ORDER_STATUSES})},
    },
    "run": {
        "table": "production_runs", "order": ("started_at", False), "context": _run_context, "row": domain.run_row,
        "sort": {"id": "code", "start": "started_at", "good": "good_qty"},
        "filter": {"id": code(), "start": moment("started_at"), "order": linked("order", "production_orders", "code"),
                   "machine": through("recipe", "recipes", "machine", "machines"), "item": through_any("recipe", "recipes", "item", "items"),
                   "hours": clock("started_at", "ended_at"),
                   "operator": linked("operator", "personnel"), "status": chosen("ended_at", RUNNING)},
    },
    "stoppage": {
        "table": "stoppages", "order": ("started_at", False), "context": _stoppage_context, "row": domain.stoppage_row,
        "sort": {"start": "started_at", "end": "ended_at"},
        "filter": {"start": moment("started_at"), "end": moment("ended_at"), "hours": clock("started_at", "ended_at"),
                   "machine": linked("machine", "machines"), "item": _stoppage_item(),
                   "cause": linked("cause", "stoppage_causes"), "category": linked("cause", "stoppage_causes", "category"),
                   "description": contains("description"), "fix": contains("fix"), "reportedBy": linked("reported_by", "personnel"),
                   "status": chosen("ended_at", OPEN)},
    },
    "lot": {
        "table": "lots", "order": ("code", True), "context": _lot_context, "row": domain.lot_row,
        "sort": {"id": "code", "number": "number", "quantity": "quantity", "received": "received_at"},
        "filter": {"id": code(), "number": contains("number"), "item": linked_any("item", "items"), "origin": contains("origin"),
                   "received": moment("received_at"), "run": linked("run", "production_runs", "code"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.LOT_STATUSES})},
    },
    "changeover": {
        "table": "changeovers", "order": ("started_at", False), "context": _changeover_context, "row": domain.changeover_row,
        "sort": {"id": "code", "start": "started_at", "hours": "lost_h"},
        "filter": {"id": code(), "start": moment("started_at"), "hours": compare("lost_h"), "machine": linked("machine", "machines"),
                   "from": linked_any("from_item", "items"), "to": linked_any("to_item", "items"),
                   "kind": chosen("kind", {label: key for key, label in domain.CHANGEOVER_KINDS}),
                   "source": chosen("source", {label: key for key, label in domain.CHANGEOVER_SOURCES}),
                   "status": chosen("confidence", {"High": "high", "Medium": "medium", "Low": "low"}), "basis": contains("basis")},
    },
}


def capabilities():
    """Which fields each list can filter and sort, and the labels of its pick-list filters, for the page's column headers."""
    return {kind: {"filter": sorted(spec["filter"].keys()), "sort": sorted(spec["sort"].keys()),
                   "choices": {field: build.choices for field, build in spec["filter"].items() if hasattr(build, "choices")}}
            for kind, spec in LISTS.items()}


def _conditions(spec, filters, gap_ids):
    found, clocks = {}, []
    for entry in filters or []:
        build = spec["filter"].get(entry.get("field"))
        text = _text(entry.get("value"))
        if build is None or not text:
            continue
        for column, condition in build(text).items():
            if column == "__clock__":
                clocks.append(condition)
            else:
                found.setdefault(column, []).append(condition)
    if gap_ids is not None:
        if not gap_ids:
            raise _NoMatch()
        found.setdefault("code", []).append(q.any_of(*gap_ids))
    query = {column: conditions[0] if len(conditions) == 1 else q.all_of(*conditions) for column, conditions in found.items()}
    return query, clocks


def _filter_clock(rows, clocks):
    if not clocks:
        return rows
    kept = []
    for row in rows:
        if all(_clock_ok(domain.span_hours(row[start], row[end]), op, number) for start, end, op, number in clocks):
            kept.append(row)
    return kept


def _found(spec, filters, gap_ids, sorters):
    conditions, clocks = _conditions(spec, filters, gap_ids)
    columns = ["code"]
    for start, end, _op, _number in clocks:
        columns.extend((start, end))
    found = list(_table(spec["table"]).search(q.fetch_only(*list(dict.fromkeys(columns))), *_ordering(spec, sorters), **conditions))
    return _filter_clock(found, clocks)


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


def matching_codes(kind, filters=None, gap=None):
    """Every code of ``kind`` that matches the same filters as the list page, in list order."""
    spec = LISTS.get(kind)
    if spec is None:
        return None
    gap_ids, _banner = _gap(kind, gap)
    try:
        found = _found(spec, filters, gap_ids, ())
    except _NoMatch:
        return []
    return [row["code"] for row in found]


def records_for(kind, filters=None, gap=None):
    """The rows of a list, filters included, for an export. Read in batches so a long log stays bounded."""
    spec = LISTS.get(kind)
    codes = matching_codes(kind, filters, gap)
    if spec is None or codes is None:
        return None
    rows = []
    for start in range(0, len(codes), 200):
        chunk = codes[start:start + 200]
        plant = store._plant()
        loaded = plant.by_codes(spec["table"], chunk)
        graph = spec["context"](plant, loaded).graph()
        read = domain.reindex(graph)[spec["table"]]
        rows.extend(spec["row"](graph, read[code]) for code in chunk if code in read)
    return rows


def page(kind, number=1, size=25, sorters=None, filters=None, gap=None):
    spec = LISTS.get(kind)
    if spec is None:
        return {"error": "Unknown list."}
    size = max(1, min(int(size or 25), 500))
    number = max(1, int(number or 1))
    gap_ids, banner = _gap(kind, gap)
    reply = {"data": [], "last_page": 1, "last_row": 0, "banner": banner}
    try:
        found = _found(spec, filters, gap_ids, sorters)
    except _NoMatch:
        return reply
    total = len(found)
    codes = [row["code"] for row in found[(number - 1) * size:number * size]]
    plant = store._plant()
    rows = plant.by_codes(spec["table"], codes)
    graph = spec["context"](plant, rows).graph()
    read = domain.reindex(graph)[spec["table"]]
    reply.update({"data": [spec["row"](graph, read[code]) for code in codes if code in read],
                  "last_page": max(1, math.ceil(total / size)), "last_row": total})
    return reply
