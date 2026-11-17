"""One page of a record list, read from the tables.

A list asks for a page with its sorters and header filters. The filters become a query on stored
columns (a name filter on a linked record finds those records first), the query is sliced to the
page, and only the page's records and what their rows are computed from are read. A number or
percentage column can be sorted: stored numbers are ordered in the query, and a calculated
number is ordered after the query, before the page is sliced.
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


def any_of_fields(table, fields):
    """This table's own rows, matching the text on any of ``fields``."""
    def build(text):
        return {"code": q.any_of(*[row["code"] for row in _match_rows(table, fields, text)])}
    return build


def link_named(column, table):
    """A pick-list of the names in ``table``. The choice has to match the name exactly."""
    def build(text):
        return {column: q.any_of(*_rows_where(table, name=text))}

    def choices():
        try:
            rows = _table(table).search(q.fetch_only("name"))
        except Exception:
            return []
        return sorted({row["name"] for row in rows if row["name"]})

    build.choices = choices
    return build


def shown(labels):
    """A pick-list of the status labels the page shows. Applied after the query."""
    def build(text):
        if text not in labels:
            raise _NoMatch()
        return {"__status__": text}
    build.choices = tuple(labels)
    return build


def hours_text(start_col, end_col):
    """The hours printed in the cell, matched as text. The duration is not a stored column."""
    def build(text):
        needle = _text(text).lower().replace(",", ".").replace("h", "").strip()
        if not needle:
            raise _NoMatch()
        return {"__hours__": (start_col, end_col, needle)}
    return build


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


class _Rank:
    """A calculated number. ``keys(rows)`` maps a row code to the number shown in that column."""

    def __init__(self, keys, fetch=()):
        self.keys = keys
        self.fetch = tuple(fetch)


def _chunks(items, size):
    items = list(items)
    return [items[start:start + size] for start in range(0, len(items), size)]


def _search_codes(table, fetch, codes):
    found = []
    for chunk in _chunks(codes, 300):
        found.extend(table.search(fetch, code=q.any_of(*chunk)))
    return found


def _search_linked(table, fetch, column, parents):
    found = []
    for chunk in _chunks(parents, 200):
        found.extend(table.search(fetch, **{column: q.any_of(*chunk)}))
    return found


def _num_part(value, descending):
    """Blanks stay at the bottom, in either direction."""
    if value is None or value == "":
        return (1, 0.0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return (1, 0.0)
    return (0, -number if descending else number)


def _span_rank(start, end, blank_zero=False):
    """Hours between two stored moments. Runs round to the tenth and treat zero as blank, as the row does."""

    def keys(rows):
        found = {}
        for row in rows:
            hours = domain.span_hours(_moment_text(row[start]), _moment_text(row[end]))
            if blank_zero:
                hours = round(hours, 1) if hours else None
            found[row["code"]] = hours
        return found

    return _Rank(keys, (start, end))


def _item_counts(rows):
    wanted = {row["code"] for row in rows}
    counts = {code: {"recipes": 0, "trial": 0, "usedIn": 0} for code in wanted}
    if not wanted:
        return counts
    for recipe in _table("recipes").search(q.fetch_only("status", item=q.fetch_only("code"))):
        item = recipe["item"]
        if item is None or item["code"] not in counts:
            continue
        if recipe["status"] == "approved":
            counts[item["code"]]["recipes"] += 1
        elif recipe["status"] == "trial":
            counts[item["code"]]["trial"] += 1
    using = {code: [] for code in wanted}
    for line in _table("recipe_inputs").search(q.fetch_only(item=q.fetch_only("code"), recipe=q.fetch_only("status"))):
        item, recipe = line["item"], line["recipe"]
        if item is None or recipe is None or item["code"] not in using:
            continue
        using[item["code"]].append({"status": recipe["status"]})
    for code, recipes in using.items():
        counts[code]["usedIn"] = len(domain.live(recipes))
    return counts


def _count_rank(field, counts):
    def keys(rows):
        return {code: values[field] for code, values in counts(rows).items()}
    return _Rank(keys)


def _mold_recipes(rows):
    wanted = {row["code"] for row in rows}
    grouped = {code: [] for code in wanted}
    if not wanted:
        return {code: 0 for code in wanted}
    for recipe in _table("recipes").search(q.fetch_only("status", mold=q.fetch_only("code"))):
        mold = recipe["mold"]
        if mold is not None and mold["code"] in grouped:
            grouped[mold["code"]].append({"status": recipe["status"]})
    return {code: len(domain.live(recipes)) for code, recipes in grouped.items()}


def _machine_recipe_stats(rows):
    wanted = {row["code"] for row in rows}
    grouped = {code: [] for code in wanted}
    if not wanted:
        return {code: {"recipes": 0, "molds": 0} for code in wanted}
    for recipe in _table("recipes").search(q.fetch_only("status", machine=q.fetch_only("code"), mold=q.fetch_only("code"))):
        machine = recipe["machine"]
        if machine is None or machine["code"] not in grouped:
            continue
        mold = recipe["mold"]
        grouped[machine["code"]].append({"status": recipe["status"], "moldId": mold["code"] if mold is not None else ""})
    stats = {}
    for code, recipes in grouped.items():
        running = domain.live(recipes)
        stats[code] = {"recipes": len(running), "molds": len(domain.uniq(recipe.get("moldId") for recipe in running))}
    return stats


def _recipe_pph(rows):
    result = {row["code"]: None for row in rows}
    for recipe in _search_codes(_table("recipes"), q.fetch_only("code", "cycle_s", mold=q.fetch_only("code", "cavities")), result):
        mold = recipe["mold"]
        mold_id = mold["code"] if mold is not None else ""
        index = {"molds": ({mold_id: {"cavities": mold["cavities"]}} if mold is not None else {})}
        result[recipe["code"]] = domain.pieces_per_hour(index, {"moldId": mold_id, "cycle": recipe["cycle_s"]})
    return result


def _order_totals(rows):
    codes = [row["code"] for row in rows]
    result = {code: {"made": 0, "runs": 0, "progress": None} for code in codes}
    loaded = _search_codes(_table("production_orders"), q.fetch_only("code", "quantity"), codes)
    goods = {row["code"]: [] for row in loaded}
    for run in _search_linked(_table("production_runs"), q.fetch_only("good_qty", order=q.fetch_only("code")), "order", loaded):
        order = run["order"]
        if order is not None and order["code"] in goods:
            goods[order["code"]].append(run["good_qty"])
    quantity = {row["code"]: row["quantity"] for row in loaded}
    for code, values in goods.items():
        made = sum(domain.num(value) or 0 for value in values)
        qty = quantity.get(code)
        result[code] = {"made": made, "runs": len(values), "progress": int(round(100.0 * made / qty)) if qty else None}
    return result


def _run_metrics(rows):
    """The same hours, scrap, rate, and performance the production row shows."""
    codes = [row["code"] for row in rows]
    if not codes:
        return {}
    loaded = _search_codes(_table("production_runs"), q.fetch_only(
        "code", "started_at", "ended_at", "good_qty", "cycle_s", "cavities_running",
        recipe=q.fetch_only("code", "cycle_s", mold=q.fetch_only("code", "cavities")),
    ), codes)
    scrap = {}
    for line in _search_linked(_table("run_scrap"), q.fetch_only("quantity", run=q.fetch_only("code")), "run", loaded):
        run = line["run"]
        if run is not None:
            scrap.setdefault(run["code"], []).append({"quantity": line["quantity"]})
    stops = []
    for stop in _search_linked(_table("stoppages"), q.fetch_only("code", "started_at", "ended_at", run=q.fetch_only("code")), "run", loaded):
        run = stop["run"]
        if run is None:
            continue
        stops.append({"id": stop["code"], "runId": run["code"], "startedAt": _moment_text(stop["started_at"]), "endedAt": _moment_text(stop["ended_at"])})
    by_code = {row["code"]: row for row in loaded}
    recipes, molds, run_dicts = {}, {}, []
    for code in codes:
        row = by_code.get(code)
        if row is None:
            continue
        recipe = row["recipe"]
        mold = recipe["mold"] if recipe is not None else None
        recipe_id = recipe["code"] if recipe is not None else ""
        mold_id = mold["code"] if mold is not None else ""
        if recipe is not None:
            recipes[recipe_id] = {"id": recipe_id, "moldId": mold_id, "cycle": recipe["cycle_s"]}
        if mold is not None:
            molds[mold_id] = {"id": mold_id, "cavities": mold["cavities"]}
        run_dicts.append({
            "id": code, "recipeId": recipe_id, "startedAt": _moment_text(row["started_at"]), "endedAt": _moment_text(row["ended_at"]),
            "good": row["good_qty"], "cycle": row["cycle_s"], "cavities": row["cavities_running"], "scrap": scrap.get(code, []),
        })
    graph = {"recipes": list(recipes.values()), "molds": list(molds.values()), "stoppages": stops, "production_runs": run_dicts}
    domain.reindex(graph)
    return {run["id"]: domain.run_metrics(graph, run) for run in run_dicts}


def _metric_rank(field, metrics):
    def keys(rows):
        return {code: values.get(field) for code, values in metrics(rows).items()}
    return _Rank(keys)


def _lot_used(rows):
    counts = {row["code"]: 0 for row in rows}
    loaded = _search_codes(_table("lots"), q.fetch_only("code"), counts)
    for line in _search_linked(_table("run_inputs"), q.fetch_only(lot=q.fetch_only("code")), "lot", loaded):
        lot = line["lot"]
        if lot is not None and lot["code"] in counts:
            counts[lot["code"]] += 1
    return counts


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
        "sort": {"id": "code", "name": "name", "erp": "erp_code", "typeLabel": "item_type",
                 "recipes": _count_rank("recipes", _item_counts), "trial": _count_rank("trial", _item_counts),
                 "usedIn": _count_rank("usedIn", _item_counts)},
        "shown": domain.item_status,
        "filter": {"name": any_of_fields("items", ("code", "name")), "erp": contains("erp_code"),
                   "category": link_named("category", "item_categories"),
                   "typeLabel": chosen("item_type", {label: key for key, label in domain.ITEM_TYPES}),
                   "status": shown(domain.ITEM_SHOWN)},
    },
    "mold": {
        "table": "molds", "order": ("code", True), "context": _mold_context, "row": domain.mold_row,
        "sort": {"id": "code", "name": "name", "cavities": "cavities", "shot": "shot_weight_g", "location": "location",
                 "recipes": _Rank(_mold_recipes)},
        "shown": domain.mold_status,
        "filter": {"name": any_of_fields("molds", ("code", "name")), "location": contains("location"),
                   "status": shown(domain.MOLD_SHOWN)},
    },
    "machine": {
        "table": "machines", "order": ("code", True), "context": _machine_context, "row": domain.machine_row,
        "sort": {"id": "code", "name": "name", "euromap": "euromap", "changeover": "changeover_min", "location": "location",
                 "molds": _metric_rank("molds", _machine_recipe_stats), "recipes": _metric_rank("recipes", _machine_recipe_stats)},
        "shown": domain.machine_status,
        "filter": {"name": any_of_fields("machines", ("code", "name")), "euromap": contains("euromap"),
                   "type": link_named("machine_type", "machine_types"),
                   "attachedTo": linked("attached_to", "machines"),
                   "status": shown(domain.MACHINE_SHOWN)},
    },
    "recipe": {
        "table": "recipes", "order": ("code", True), "context": lambda plant, rows: store._recipe_context(plant), "row": domain.recipe_row,
        "sort": {"id": "code", "cycle": "cycle_s", "pph": _Rank(_recipe_pph)},
        "shown": domain.recipe_status,
        "filter": {"id": code(), "item": linked_any("item", "items"), "machine": linked("machine", "machines"),
                   "mold": linked("mold", "molds", "code"), "status": shown(domain.RECIPE_SHOWN)},
    },
    "order": {
        "table": "production_orders", "order": ("code", True), "context": _order_context, "row": domain.order_row,
        "sort": {"id": "code", "quantity": "quantity", "due": "due_date", "erp": "erp_order_no",
                 "made": _metric_rank("made", _order_totals), "progress": _metric_rank("progress", _order_totals),
                 "runs": _metric_rank("runs", _order_totals)},
        "filter": {"id": code(), "item": linked_any("item", "items"), "erp": contains("erp_order_no"), "due": day("due_date"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.ORDER_STATUSES})},
    },
    "run": {
        "table": "production_runs", "order": ("started_at", False), "context": _run_context, "row": domain.run_row,
        "sort": {"id": "code", "start": "started_at", "good": "good_qty",
                 "hours": _span_rank("started_at", "ended_at", blank_zero=True),
                 "scrapPct": _metric_rank("scrapPct", _run_metrics), "pph": _metric_rank("pph", _run_metrics),
                 "performance": _metric_rank("performance", _run_metrics)},
        "filter": {"id": code(), "start": moment("started_at"), "order": linked("order", "production_orders", "code"),
                   "machine": through("recipe", "recipes", "machine", "machines"), "item": through_any("recipe", "recipes", "item", "items"),
                   "hours": hours_text("started_at", "ended_at"),
                   "operator": linked("operator", "personnel"), "status": chosen("ended_at", RUNNING)},
    },
    "stoppage": {
        "table": "stoppages", "order": ("started_at", False), "context": _stoppage_context, "row": domain.stoppage_row,
        "sort": {"start": "started_at", "end": "ended_at", "hours": _span_rank("started_at", "ended_at")},
        "filter": {"start": moment("started_at"), "end": moment("ended_at"), "hours": clock("started_at", "ended_at"),
                   "machine": linked("machine", "machines"), "item": _stoppage_item(),
                   "cause": linked("cause", "stoppage_causes"), "category": linked("cause", "stoppage_causes", "category"),
                   "description": contains("description"), "fix": contains("fix"), "reportedBy": linked("reported_by", "personnel"),
                   "status": chosen("ended_at", OPEN)},
    },
    "lot": {
        "table": "lots", "order": ("code", True), "context": _lot_context, "row": domain.lot_row,
        "sort": {"id": "code", "number": "number", "quantity": "quantity", "received": "received_at", "used": _Rank(_lot_used)},
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


def _choice_labels(build):
    labels = getattr(build, "choices", None)
    if callable(labels):
        labels = labels()
    return list(labels or [])


def capabilities():
    """Which fields each list can filter and sort, and the labels of its pick-list filters, for the page's column headers."""
    return {kind: {"filter": sorted(spec["filter"].keys()), "sort": sorted(spec["sort"].keys()),
                   "choices": {field: _choice_labels(build) for field, build in spec["filter"].items() if hasattr(build, "choices")}}
            for kind, spec in LISTS.items()}


def _conditions(spec, filters, gap_ids):
    found, clocks, statuses, hours = {}, [], [], []
    for entry in filters or []:
        build = spec["filter"].get(entry.get("field"))
        text = _text(entry.get("value"))
        if build is None or not text:
            continue
        for column, condition in build(text).items():
            if column == "__clock__":
                clocks.append(condition)
            elif column == "__status__":
                statuses.append(condition)
            elif column == "__hours__":
                hours.append(condition)
            else:
                found.setdefault(column, []).append(condition)
    if gap_ids is not None:
        if not gap_ids:
            raise _NoMatch()
        found.setdefault("code", []).append(q.any_of(*gap_ids))
    query = {column: conditions[0] if len(conditions) == 1 else q.all_of(*conditions) for column, conditions in found.items()}
    return query, clocks, statuses, hours


def _moment_text(value):
    if value is None or value == "":
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _hours_shown(row, start, end):
    hours = domain.span_hours(_moment_text(row[start]), _moment_text(row[end]))
    if not hours:
        return ""
    rounded = round(hours, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return ("%.4f" % rounded).rstrip("0").rstrip(".")


def _filter_hours_text(rows, needles):
    if not needles:
        return rows
    kept = []
    for row in rows:
        if all(needle in _hours_shown(row, start, end) for start, end, needle in needles):
            kept.append(row)
    return kept


def _filter_shown_status(spec, rows, labels):
    if not labels:
        return rows
    reader = spec.get("shown")
    if reader is None:
        return rows
    plant = store._plant()
    loaded = plant.by_codes(spec["table"], [row["code"] for row in rows])
    graph = spec["context"](plant, loaded).graph()
    read = domain.reindex(graph)[spec["table"]]
    wanted = set(labels)
    return [row for row in rows if row["code"] in read and reader(graph, read[row["code"]]) in wanted]


def _filter_clock(rows, clocks):
    if not clocks:
        return rows
    kept = []
    for row in rows:
        if all(_clock_ok(domain.span_hours(_moment_text(row[start]), _moment_text(row[end])), op, number) for start, end, op, number in clocks):
            kept.append(row)
    return kept


def _sort_columns(spec, sorters):
    """Stored columns only. A calculated number is ordered later, in Python."""
    chosen = [(spec["sort"][entry["field"]], entry.get("dir") != "desc") for entry in sorters or []
              if isinstance(spec["sort"].get(entry.get("field")), str)]
    ordering = chosen or [spec["order"]]
    if all(column != "code" for column, _ascending in ordering):
        ordering.append(("code", True))
    return ordering


def _apply_ranks(spec, rows, sorters):
    active = [(entry, spec["sort"][entry["field"]]) for entry in sorters or []
              if isinstance(spec["sort"].get(entry.get("field")), _Rank)]
    if not active:
        return rows
    maps = {entry["field"]: rank.keys(rows) for entry, rank in active}

    def sort_key(row):
        return tuple(_num_part(maps[entry["field"]].get(row["code"]), entry.get("dir") == "desc") for entry, _rank in active) + ((row["code"] or ""),)

    return sorted(rows, key=sort_key)


def _found(spec, filters, gap_ids, sorters):
    conditions, clocks, statuses, hours = _conditions(spec, filters, gap_ids)
    columns = ["code"]
    for start, end, *_rest in clocks + hours:
        columns.extend((start, end))
    for entry in sorters or []:
        rank = spec["sort"].get(entry.get("field"))
        if isinstance(rank, _Rank):
            columns.extend(rank.fetch)
    found = list(_table(spec["table"]).search(q.fetch_only(*list(dict.fromkeys(columns))), *_ordering(spec, sorters), **conditions))
    found = _filter_clock(found, clocks)
    found = _filter_hours_text(found, hours)
    found = _filter_shown_status(spec, found, statuses)
    return _apply_ranks(spec, found, sorters)


def _ordering(spec, sorters):
    return [anvil.tables.order_by(column, ascending=ascending) for column, ascending in _sort_columns(spec, sorters)]


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
