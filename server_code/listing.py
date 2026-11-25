"""One page of a record list, read from the tables.

A list asks for a page with its sorters and header filters. The filters become a query, Postgres
counts the matches and returns one page, and only that page is loaded. A status word, a calculated number (pieces per hour, scrap, progress), and the hours
printed in a cell are expressions in that same query.
"""

import datetime
import math
import re
import unicodedata

import sql

import domain
import performance
import store

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class _NoMatch(Exception):
    """A filter that no row can satisfy."""


def _text(value):
    return str(value or "").strip()


def _plain(text):
    return "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))


def _like(text):
    """Contains the text, in any case; the database does not fold Greek case or accents, so the plain upper and lower forms are tried too."""
    text = text.replace("%", "").replace("_", "")
    forms = list(dict.fromkeys((text, _plain(text).upper(), _plain(text).lower())))
    patterns = [sql.ilike("%" + form + "%") for form in forms]
    return patterns[0] if len(patterns) == 1 else sql.any_of(*patterns)


def _rows_where(table, **filters):
    parts, params = [], []
    for column, condition in filters.items():
        text, vals = sql.compile_pred(sql.store_column(table, column), condition)
        parts.append(text)
        params.extend(vals)
    found = sql.query(
        "SELECT t.id, t.code FROM plant." + sql.ident(table) + " t WHERE " + " AND ".join(parts),
        params,
    )
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
    return lambda text: {column: sql.any_of(*_rows_where(table, **{field: _like(text)}))}


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
    return lambda text: {column: sql.any_of(*_match_rows(table, fields, text))}


def any_of_fields(table, fields):
    """This table's own rows, matching the text on any of ``fields``."""
    def build(text):
        return {"code": sql.any_of(*[row["code"] for row in _match_rows(table, fields, text)])}
    return build


def link_named(column, table):
    """A pick-list of the names in ``table``. The choice has to match the name exactly."""
    def build(text):
        return {column: sql.any_of(*_rows_where(table, name=text))}

    def choices():
        try:
            rows = sql.query("SELECT name FROM plant." + sql.ident(table) + " WHERE name <> ''")
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
        return {column: sql.any_of(*_rows_where(table, **{link: sql.any_of(*targets)}))}
    return build


def through_any(column, table, link, target, fields=("code", "name")):
    """Like :func:`through`, matching the target on any of ``fields``."""
    def build(text):
        targets = _match_rows(target, fields, text)
        return {column: sql.any_of(*_rows_where(table, **{link: sql.any_of(*targets)}))}
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
        return sql.gte(number)
    if op == ">":
        return sql.gt(number)
    if op == "<=":
        return sql.lte(number)
    if op == "<":
        return sql.lt(number)
    if op == "=":
        return number
    raise _NoMatch()


_CONDITION_OPS = ("equals", "notEqual", "greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual", "inRange", "blank", "notBlank")
_LEGACY_OPS = {">=": "greaterThanOrEqual", ">": "greaterThan", "<=": "lessThanOrEqual", "<": "lessThan", "=": "equals"}


def _encoded_condition(text):
    """``cf|equals|8`` or ``cf|inRange|2025-12-01|2025-12-31``. Empty when the text is an older filter."""
    raw = _text(text)
    if not raw.startswith("cf|"):
        return None
    bits = raw.split("|")
    if len(bits) < 2 or bits[1] not in _CONDITION_OPS:
        raise _NoMatch()
    return bits[1], bits[2:]


def _number_value(text):
    raw = _text(text).replace(",", ".")
    if raw == "":
        raise _NoMatch()
    try:
        return float(raw)
    except ValueError:
        raise _NoMatch()


def _whole(number):
    return int(number) if number == int(number) else number


def _condition_values(text):
    """``(op, [numbers])`` from an AG Grid number condition, or from ``>= 2``."""
    encoded = _encoded_condition(text)
    if encoded is None:
        op, number = _compare_parts(text)
        return _LEGACY_OPS[op], [number]
    op, values = encoded
    if op in ("blank", "notBlank"):
        return op, []
    if op == "inRange":
        if len(values) < 2:
            raise _NoMatch()
        return op, [_number_value(values[0]), _number_value(values[1])]
    if not values:
        raise _NoMatch()
    return op, [_number_value(values[0])]


def _number_holds(value, op, values):
    """Whether a displayed number satisfies one condition. Blanks fail every comparison."""
    if op == "blank":
        return value is None
    if op == "notBlank":
        return value is not None
    if value is None:
        return False
    if op == "inRange":
        low, high = values
        if high < low:
            low, high = high, low
        return low <= value <= high
    number = values[0]
    if op == "equals":
        return value == number
    if op == "notEqual":
        return value != number
    if op == "greaterThan":
        return value > number
    if op == "greaterThanOrEqual":
        return value >= number
    if op == "lessThan":
        return value < number
    if op == "lessThanOrEqual":
        return value <= number
    raise _NoMatch()


def _stored_number_query(op, values):
    if op == "blank":
        return None
    if op == "notBlank":
        return sql.not_(None)
    if op == "inRange":
        low, high = values
        if high < low:
            low, high = high, low
        return sql.between(_whole(low), _whole(high), min_inclusive=True, max_inclusive=True)
    number = _whole(values[0])
    if op == "equals":
        return number
    if op == "notEqual":
        return sql.all_of(sql.not_(None), sql.not_(number))
    if op == "greaterThan":
        return sql.gt(number)
    if op == "greaterThanOrEqual":
        return sql.gte(number)
    if op == "lessThan":
        return sql.lt(number)
    if op == "lessThanOrEqual":
        return sql.lte(number)
    raise _NoMatch()


def compare(column):
    """A stored number, compared the way an AG Grid number filter compares it."""
    def build(text):
        op, values = _condition_values(text)
        return {column: _stored_number_query(op, values)}
    return build


def clock(start_col, end_col):
    """Hours between two moments, compared as the number the cell shows."""
    def build(text):
        op, values = _condition_values(text)
        return {"__clock__": (start_col, end_col, op, values)}
    return build


class _Rank:
    """A calculated number. ``keys(rows)`` maps a row code to the number shown in that column."""

    def __init__(self, keys, fetch=()):
        self.keys = keys
        self.fetch = tuple(fetch)


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
    for recipe in sql.query(
        """
        SELECT r.status, i.code AS item_code
        FROM plant.recipes r
        JOIN plant.items i ON i.id = r.item_id
        WHERE i.code = ANY(%s::text[])
        """,
        (list(wanted),),
    ):
        if recipe["status"] == "approved":
            counts[recipe["item_code"]]["recipes"] += 1
        elif recipe["status"] == "trial":
            counts[recipe["item_code"]]["trial"] += 1
    using = {code: [] for code in wanted}
    for line in sql.query(
        """
        SELECT i.code AS item_code, r.status
        FROM plant.recipe_inputs ri
        JOIN plant.items i ON i.id = ri.item_id
        JOIN plant.recipes r ON r.id = ri.recipe_id
        WHERE i.code = ANY(%s::text[])
        """,
        (list(wanted),),
    ):
        using[line["item_code"]].append({"status": line["status"]})
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
    for recipe in sql.query(
        """
        SELECT m.code AS mold_code, r.status
        FROM plant.recipes r
        JOIN plant.molds m ON m.id = r.mold_id
        WHERE m.code = ANY(%s::text[])
        """,
        (list(wanted),),
    ):
        grouped[recipe["mold_code"]].append({"status": recipe["status"]})
    return {code: len(domain.live(recipes)) for code, recipes in grouped.items()}


def _machine_recipe_stats(rows):
    wanted = {row["code"] for row in rows}
    grouped = {code: [] for code in wanted}
    if not wanted:
        return {code: {"recipes": 0, "molds": 0} for code in wanted}
    for recipe in sql.query(
        """
        SELECT mac.code AS machine_code, r.status, mold.code AS mold_code
        FROM plant.recipes r
        JOIN plant.machines mac ON mac.id = r.machine_id
        LEFT JOIN plant.molds mold ON mold.id = r.mold_id
        WHERE mac.code = ANY(%s::text[])
        """,
        (list(wanted),),
    ):
        grouped[recipe["machine_code"]].append({"status": recipe["status"], "moldId": recipe["mold_code"] or ""})
    stats = {}
    for code, recipes in grouped.items():
        running = domain.live(recipes)
        stats[code] = {"recipes": len(running), "molds": len(domain.uniq(recipe.get("moldId") for recipe in running))}
    return stats


def _recipe_pph(rows):
    result = {row["code"]: None for row in rows}
    if not result:
        return result
    for recipe in sql.query(
        """
        SELECT r.code, r.cycle_s, m.code AS mold_code, m.cavities
        FROM plant.recipes r
        LEFT JOIN plant.molds m ON m.id = r.mold_id
        WHERE r.code = ANY(%s::text[])
        """,
        (list(result),),
    ):
        mold_id = recipe["mold_code"] or ""
        index = {"molds": ({mold_id: {"cavities": recipe["cavities"]}} if recipe["mold_code"] else {})}
        result[recipe["code"]] = domain.pieces_per_hour(index, {"moldId": mold_id, "cycle": recipe["cycle_s"]})
    return result


def _order_totals(rows):
    codes = [row["code"] for row in rows]
    result = {code: {"made": 0, "runs": 0, "progress": None} for code in codes}
    if not codes:
        return result
    loaded = sql.query("SELECT code, quantity FROM plant.production_orders WHERE code = ANY(%s::text[])", (codes,))
    goods = {row["code"]: [] for row in loaded}
    for run in sql.query(
        """
        SELECT o.code AS order_code, r.good_qty
        FROM plant.production_runs r
        JOIN plant.production_orders o ON o.id = r.order_id
        WHERE o.code = ANY(%s::text[])
        """,
        (codes,),
    ):
        goods[run["order_code"]].append(run["good_qty"])
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
    loaded = sql.query(
        """
        SELECT r.code, r.started_at, r.ended_at, r.good_qty, r.cycle_s, r.cavities_running,
               rec.code AS recipe_code, rec.cycle_s AS recipe_cycle, m.code AS mold_code, m.cavities
        FROM plant.production_runs r
        LEFT JOIN plant.recipes rec ON rec.id = r.recipe_id
        LEFT JOIN plant.molds m ON m.id = rec.mold_id
        WHERE r.code = ANY(%s::text[])
        """,
        (codes,),
    )
    scrap = {}
    for line in sql.query(
        """
        SELECT run.code AS run_code, s.quantity
        FROM plant.run_scrap s
        JOIN plant.production_runs run ON run.id = s.run_id
        WHERE run.code = ANY(%s::text[])
        """,
        (codes,),
    ):
        scrap.setdefault(line["run_code"], []).append({"quantity": line["quantity"]})
    stops = []
    for stop in sql.query(
        """
        SELECT s.code, s.started_at, s.ended_at, run.code AS run_code
        FROM plant.stoppages s
        JOIN plant.production_runs run ON run.id = s.run_id
        WHERE run.code = ANY(%s::text[])
        """,
        (codes,),
    ):
        stops.append({"id": stop["code"], "runId": stop["run_code"], "startedAt": _moment_text(stop["started_at"]),
                      "endedAt": _moment_text(stop["ended_at"])})
    by_code = {row["code"]: row for row in loaded}
    recipes, molds, run_dicts = {}, {}, []
    for code in codes:
        row = by_code.get(code)
        if row is None:
            continue
        recipe_id = row["recipe_code"] or ""
        mold_id = row["mold_code"] or ""
        if recipe_id:
            recipes[recipe_id] = {"id": recipe_id, "moldId": mold_id, "cycle": row["recipe_cycle"]}
        if mold_id:
            molds[mold_id] = {"id": mold_id, "cavities": row["cavities"]}
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
    if not counts:
        return counts
    for line in sql.query(
        """
        SELECT l.code, count(ri.id) AS used
        FROM plant.lots l
        LEFT JOIN plant.run_inputs ri ON ri.lot_id = l.id
        WHERE l.code = ANY(%s::text[])
        GROUP BY l.code
        """,
        (list(counts),),
    ):
        counts[line["code"]] = int(line["used"])
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
            clauses.append(sql.between(begin, finish, min_inclusive=True, max_inclusive=False))
        else:
            clauses.append(sql.between(start, end, min_inclusive=True, max_inclusive=False))
    if len(clauses) == 1:
        return {column: clauses[0]}
    return {column: sql.any_of(*clauses)}


def _iso_day(text):
    try:
        return datetime.date.fromisoformat(_text(text))
    except ValueError:
        raise _NoMatch()


def _date_window(op, values):
    """A half-open day window for one date condition. ``from`` and ``until`` are open on one side."""
    if op == "blank":
        return ("blank",)
    if op == "notBlank":
        return ("notBlank",)
    if not values or not values[0]:
        raise _NoMatch()
    start = _iso_day(values[0])
    if op == "equals":
        return ("within", start, start + datetime.timedelta(days=1))
    if op == "greaterThan":
        return ("from", start + datetime.timedelta(days=1))
    if op == "greaterThanOrEqual":
        return ("from", start)
    if op == "lessThan":
        return ("until", start)
    if op == "lessThanOrEqual":
        return ("until", start + datetime.timedelta(days=1))
    if op == "notEqual":
        return ("outside", start, start + datetime.timedelta(days=1))
    if op == "inRange":
        if len(values) < 2 or not values[1]:
            raise _NoMatch()
        end = _iso_day(values[1])
        if end < start:
            start, end = end, start
        return ("within", start, end + datetime.timedelta(days=1))
    raise _NoMatch()


def _date_query(column, op, values, as_moment):
    window = _date_window(op, values)
    kind = window[0]
    if kind == "blank":
        return {column: None}
    if kind == "notBlank":
        return {column: sql.not_(None)}

    def edge(day):
        if not as_moment:
            return day
        return performance.local_bounds(day, day)[0]

    if kind == "within":
        return _between_ranges(column, [(window[1], window[2])], as_moment=as_moment)
    if kind == "from":
        return {column: sql.gte(edge(window[1]))}
    if kind == "until":
        return {column: sql.lt(edge(window[1]))}
    start, finish = edge(window[1]), edge(window[2])
    return {column: sql.any_of(sql.lt(start), sql.gte(finish))}


def moment(column):
    def build(text):
        encoded = _encoded_condition(text)
        if encoded is None:
            return _between_ranges(column, period_ranges(text), as_moment=True)
        op, values = encoded
        return _date_query(column, op, values, True)
    return build


def day(column):
    def build(text):
        encoded = _encoded_condition(text)
        if encoded is None:
            return _between_ranges(column, period_ranges(text), as_moment=False)
        op, values = encoded
        return _date_query(column, op, values, False)
    return build


# What each list reads ----------------------------------------------------------------------------

def _item_context(plant, rows):
    plant.follow("items", "parent")
    store._every_recipe_of(plant, rows)
    if rows:
        using = [found["code"] for found in sql.query(
            """
            SELECT r.code
            FROM plant.recipe_inputs ri
            JOIN plant.recipes r ON r.id = ri.recipe_id
            WHERE ri.item_id = ANY(%s::bigint[])
            """,
            ([row.get_id() for row in rows],),
        )]
        plant.by_codes("recipes", using)
    return store._recipe_context(plant)


def _mold_context(plant, rows):
    if rows:
        store._every_recipe_of(plant, [recipe["item"] for recipe in plant.find(
            "recipes", "t.mold_id = ANY(%s::bigint[])", ([row.get_id() for row in rows],))])
    return store._recipe_context(plant)


def _machine_context(plant, rows):
    if rows:
        ids = [row.get_id() for row in rows]
        plant.find("recipes", "t.machine_id = ANY(%s::bigint[])", (ids,))
        plant.find(
            "production_runs",
            "t.ended_at IS NULL AND t.started_at IS NOT NULL AND t.recipe_id IN "
            "(SELECT id FROM plant.recipes WHERE machine_id = ANY(%s::bigint[]))",
            (ids,),
        )
    plant.follow("production_runs", "recipe")
    return store._recipe_context(plant)


def _order_context(plant, rows):
    if rows:
        plant.find("production_runs", "t.order_id = ANY(%s::bigint[])", ([row.get_id() for row in rows],))
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


RUNNING = {"Running": None, "Done": sql.not_(None)}
OPEN = {"Open": None, "Closed": sql.not_(None)}


def _stoppage_item():
    """Stoppages whose run's recipe is for an item matching the code or the name."""
    def build(text):
        items = _match_rows("items", ("code", "name"), text)
        recipes = _rows_where("recipes", item=sql.any_of(*items))
        runs = _rows_where("production_runs", recipe=sql.any_of(*recipes))
        return {"run": sql.any_of(*runs)}
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
                   "cavities": compare("cavities"), "shot": compare("shot_weight_g"),
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
                   "changeover": compare("changeover_min"),
                   "status": shown(domain.MACHINE_SHOWN)},
    },
    "recipe": {
        "table": "recipes", "order": ("code", True), "context": lambda plant, rows: store._recipe_context(plant), "row": domain.recipe_row,
        "sort": {"id": "code", "cycle": "cycle_s", "pph": _Rank(_recipe_pph)},
        "shown": domain.recipe_status,
        "filter": {"id": code(), "item": linked_any("item", "items"), "machine": linked("machine", "machines"),
                   "mold": linked("mold", "molds", "code"), "cycle": compare("cycle_s"),
                   "status": shown(domain.RECIPE_SHOWN)},
    },
    "order": {
        "table": "production_orders", "order": ("code", True), "context": _order_context, "row": domain.order_row,
        "sort": {"id": "code", "quantity": "quantity", "due": "due_date", "erp": "erp_order_no",
                 "made": _metric_rank("made", _order_totals), "progress": _metric_rank("progress", _order_totals),
                 "runs": _metric_rank("runs", _order_totals)},
        "filter": {"id": code(), "item": linked_any("item", "items"), "erp": contains("erp_order_no"),
                   "quantity": compare("quantity"), "due": day("due_date"),
                   "status": chosen("status", {domain.cap(status): status for status in domain.ORDER_STATUSES})},
    },
    "run": {
        "table": "production_runs", "order": ("started_at", False), "context": _run_context, "row": domain.run_row,
        "sort": {"id": "code", "start": "started_at", "end": "ended_at", "good": "good_qty",
                 "hours": _span_rank("started_at", "ended_at", blank_zero=True),
                 "scrapPct": _metric_rank("scrapPct", _run_metrics), "pph": _metric_rank("pph", _run_metrics),
                 "performance": _metric_rank("performance", _run_metrics)},
        "filter": {"id": code(), "start": moment("started_at"), "end": moment("ended_at"),
                   "order": linked("order", "production_orders", "code"),
                   "machine": through("recipe", "recipes", "machine", "machines"), "item": through_any("recipe", "recipes", "item", "items"),
                   "hours": clock("started_at", "ended_at"), "good": compare("good_qty"),
                   "shift": link_named("shift", "shifts"),
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
                   "quantity": compare("quantity"), "received": moment("received_at"),
                   "run": linked("run", "production_runs", "code"),
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
        found.setdefault("code", []).append(sql.any_of(*gap_ids))
    query = {column: conditions[0] if len(conditions) == 1 else sql.all_of(*conditions) for column, conditions in found.items()}
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


def _shown_hours_number(row, start, end):
    text = _hours_shown(row, start, end)
    if not text:
        return None
    return float(text)


def _filter_clock(rows, clocks):
    if not clocks:
        return rows
    kept = []
    for row in rows:
        if all(_number_holds(_shown_hours_number(row, start, end), op, values) for start, end, op, values in clocks):
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
    parts, params = [], []
    for column, condition in conditions.items():
        text, vals = sql.compile_pred(sql.store_column(spec["table"], column), condition)
        parts.append(text)
        params.extend(vals)
    found = sql.read(spec["table"], " AND ".join(parts) if parts else "TRUE", params,
                     sql.order_clause(spec["table"], _sort_columns(spec, sorters)))
    found = _filter_clock(found, clocks)
    found = _filter_hours_text(found, hours)
    found = _filter_shown_status(spec, found, statuses)
    return _apply_ranks(spec, found, sorters)


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


def _recipe_status_sql(alias):
    """The words recipe_status shows, for a recipe row aliased as ``alias``."""
    temps = (
        "(SELECT count(*) FROM jsonb_array_elements(coalesce(%s.temps, '[]'::jsonb)) elem "
        "WHERE elem->>'label' IN ('Nozzle', 'T6', 'T5', 'T4', 'T3', 'T2', 'T1') "
        "AND nullif(elem->>'value', '') IS NOT NULL "
        "AND (jsonb_typeof(elem->'value') = 'number' OR elem->>'value' ~ '^-?[0-9]+([.,][0-9]+)?$'))" % alias
    )
    has_base = (
        "EXISTS (SELECT 1 FROM plant.recipe_inputs ri "
        "JOIN plant.items i ON i.id = ri.item_id "
        "JOIN plant.item_categories c ON c.id = i.category_id "
        "WHERE ri.recipe_id = %s.id AND c.role = 'base')" % alias
    )
    return (
        "CASE WHEN %s.status = 'retired' THEN 'Retired' "
        "WHEN %s.status = 'trial' THEN 'Trial' "
        "WHEN NOT %s THEN 'Cannot produce' "
        "WHEN %s.cycle_s IS NULL OR %s.cycle_s = 0 OR %s < 3 THEN 'Incomplete' "
        "WHEN %s.standard THEN 'Standard' ELSE 'Active' END"
    ) % (alias, alias, has_base, alias, alias, temps, alias)


def _item_status_sql():
    recipe = _recipe_status_sql("r")
    approved = "r.item_id = t.id AND r.status = 'approved'"
    return (
        "CASE WHEN t.status = 'retired' THEN 'Retired' "
        "WHEN t.item_type = 'RAW' THEN CASE "
        "WHEN NOT EXISTS (SELECT 1 FROM plant.recipe_inputs ri "
        "JOIN plant.recipes r ON r.id = ri.recipe_id "
        "WHERE ri.item_id = t.id AND r.status = 'approved') THEN 'Unused' "
        "WHEN t.erp_code = '' THEN 'No code' ELSE 'Active' END "
        "WHEN t.item_type <> 'SFG' THEN 'Active' "
        "WHEN NOT EXISTS (SELECT 1 FROM plant.recipes r WHERE r.item_id = t.id) THEN 'No recipe' "
        "WHEN NOT EXISTS (SELECT 1 FROM plant.recipes r WHERE %s) THEN 'Trial only' "
        "WHEN NOT EXISTS (SELECT 1 FROM plant.recipes r WHERE %s AND (%s) <> 'Cannot produce') THEN 'Cannot produce' "
        "WHEN EXISTS (SELECT 1 FROM plant.recipes r WHERE %s AND (%s) IN ('Cannot produce', 'Incomplete')) THEN 'Incomplete' "
        "ELSE 'Active' END"
    ) % (approved, approved, recipe, approved, recipe)


_MOLD_STATUS_SQL = (
    "CASE WHEN coalesce(t.status, '') <> '' AND t.status <> 'in use' "
    "THEN upper(left(t.status, 1)) || substr(t.status, 2) "
    "WHEN NOT EXISTS (SELECT 1 FROM plant.recipes r WHERE r.mold_id = t.id AND r.status = 'approved') THEN 'Unused' "
    "WHEN t.cavities IS NULL OR t.cavities = 0 THEN 'Incomplete' ELSE 'Active' END"
)

_MACHINE_STATUS_SQL = (
    "CASE WHEN t.status = 'retired' THEN 'Retired' "
    "WHEN EXISTS (SELECT 1 FROM plant.production_runs r "
    "JOIN plant.recipes rec ON rec.id = r.recipe_id "
    "WHERE rec.machine_id = t.id AND r.started_at IS NOT NULL AND r.ended_at IS NULL) THEN 'Running' "
    "WHEN t.attached_to_id IS NOT NULL THEN 'Attached' "
    "WHEN NOT EXISTS (SELECT 1 FROM plant.recipes r WHERE r.machine_id = t.id AND r.status = 'approved') THEN 'No recipes' "
    "ELSE 'Idle' END"
)

_STATUS_SQL = {}


def _status_sql():
    if not _STATUS_SQL:
        _STATUS_SQL["recipes"] = _recipe_status_sql("t")
        _STATUS_SQL["items"] = _item_status_sql()
        _STATUS_SQL["molds"] = _MOLD_STATUS_SQL
        _STATUS_SQL["machines"] = _MACHINE_STATUS_SQL
    return _STATUS_SQL


_SPAN_HOURS_SQL = (
    "CASE WHEN t.started_at IS NULL OR t.ended_at IS NULL OR t.ended_at < t.started_at THEN NULL "
    "ELSE round((EXTRACT(EPOCH FROM (t.ended_at - t.started_at)) / 3600.0)::numeric, 2) END"
)

_RUN_DOWN_SQL = (
    "(SELECT coalesce(sum(EXTRACT(EPOCH FROM (least(t.ended_at, s.ended_at) - greatest(t.started_at, s.started_at))) / 3600.0), 0) "
    "FROM plant.stoppages s WHERE s.run_id = t.id "
    "AND s.started_at IS NOT NULL AND s.ended_at IS NOT NULL AND s.ended_at >= s.started_at "
    "AND least(t.ended_at, s.ended_at) > greatest(t.started_at, s.started_at))"
)

_RUN_SCRAP_SQL = "(SELECT coalesce(sum(quantity), 0) FROM plant.run_scrap WHERE run_id = t.id)"

_RUN_MADE_SQL = "CASE WHEN t.good_qty IS NULL THEN NULL ELSE coalesce(t.good_qty, 0) + %s END" % _RUN_SCRAP_SQL

_RUN_RUNNING_SQL = "CASE WHEN (%s) IS NULL THEN NULL ELSE (%s) - %s END" % (_SPAN_HOURS_SQL, _SPAN_HOURS_SQL, _RUN_DOWN_SQL)

_RUN_RATE_SQL = "CASE WHEN (%s) > 0 AND (%s) > 0 THEN (%s) / (%s) END" % (_RUN_MADE_SQL, _RUN_RUNNING_SQL, _RUN_MADE_SQL, _RUN_RUNNING_SQL)

_RUN_TARGET_SQL = (
    "(SELECT CASE WHEN coalesce(nullif(t.cycle_s, 0), rec.cycle_s) > 0 "
    "AND coalesce(nullif(t.cavities_running, 0), m.cavities) > 0 "
    "THEN 3600.0 / coalesce(nullif(t.cycle_s, 0), rec.cycle_s) "
    "* coalesce(nullif(t.cavities_running, 0), m.cavities) END "
    "FROM plant.recipes rec LEFT JOIN plant.molds m ON m.id = rec.mold_id WHERE rec.id = t.recipe_id)"
)


def _sort_expressions():
    """Calculated columns, as the number the cell shows. Blank stays NULL so it sorts last."""
    run_hours = "CASE WHEN (%s) IS NULL OR round((%s)::numeric, 1) = 0 THEN NULL ELSE round((%s)::numeric, 1) END" % (
        _SPAN_HOURS_SQL, _SPAN_HOURS_SQL, _SPAN_HOURS_SQL)
    run_pph = "CASE WHEN (%s) IS NULL THEN NULL ELSE round((%s))::int END" % (_RUN_RATE_SQL, _RUN_RATE_SQL)
    run_perf = (
        "CASE WHEN (%s) IS NULL OR (%s) IS NULL OR (%s) = 0 THEN NULL ELSE round(100.0 * (%s) / (%s))::int END"
        % (_RUN_RATE_SQL, _RUN_TARGET_SQL, _RUN_TARGET_SQL, _RUN_RATE_SQL, _RUN_TARGET_SQL)
    )
    run_scrap_pct = (
        "CASE WHEN (%s) IS NULL OR (%s) = 0 THEN NULL ELSE round((100.0 * (%s) / (%s))::numeric, 1) END"
        % (_RUN_MADE_SQL, _RUN_MADE_SQL, _RUN_SCRAP_SQL, _RUN_MADE_SQL)
    )
    made = "(SELECT coalesce(sum(good_qty), 0) FROM plant.production_runs r WHERE r.order_id = t.id)"
    return {
        ("items", "recipes"): "(SELECT count(*) FROM plant.recipes r WHERE r.item_id = t.id AND r.status = 'approved')",
        ("items", "trial"): "(SELECT count(*) FROM plant.recipes r WHERE r.item_id = t.id AND r.status = 'trial')",
        ("items", "usedIn"): (
            "(SELECT count(*) FROM plant.recipe_inputs ri JOIN plant.recipes r ON r.id = ri.recipe_id "
            "WHERE ri.item_id = t.id AND r.status = 'approved')"
        ),
        ("molds", "recipes"): "(SELECT count(*) FROM plant.recipes r WHERE r.mold_id = t.id AND r.status = 'approved')",
        ("machines", "recipes"): "(SELECT count(*) FROM plant.recipes r WHERE r.machine_id = t.id AND r.status = 'approved')",
        ("machines", "molds"): (
            "(SELECT count(DISTINCT coalesce(r.mold_id::text, '')) FROM plant.recipes r "
            "WHERE r.machine_id = t.id AND r.status = 'approved')"
        ),
        ("recipes", "pph"): (
            "(SELECT CASE WHEN m.cavities > 0 AND t.cycle_s > 0 "
            "THEN round(3600.0 / t.cycle_s * m.cavities)::int END "
            "FROM plant.molds m WHERE m.id = t.mold_id)"
        ),
        ("production_orders", "made"): made,
        ("production_orders", "runs"): "(SELECT count(*) FROM plant.production_runs r WHERE r.order_id = t.id)",
        ("production_orders", "progress"): (
            "CASE WHEN t.quantity IS NULL OR t.quantity = 0 THEN NULL ELSE round(100.0 * %s / t.quantity)::int END" % made
        ),
        ("production_runs", "hours"): run_hours,
        ("production_runs", "scrapPct"): run_scrap_pct,
        ("production_runs", "pph"): run_pph,
        ("production_runs", "performance"): run_perf,
        ("stoppages", "hours"): _SPAN_HOURS_SQL,
        ("lots", "used"): "(SELECT count(*) FROM plant.run_inputs ri WHERE ri.lot_id = t.id)",
    }


def _order_sql(spec, sorters):
    """ORDER BY for one page. A calculated sort puts blanks last in either direction, then the code."""
    ranks = [(entry, spec["sort"][entry["field"]]) for entry in sorters or []
             if isinstance(spec["sort"].get(entry.get("field")), _Rank)]
    if not ranks:
        return sql.order_clause(spec["table"], _sort_columns(spec, sorters))
    expressions = _sort_expressions()
    pieces = []
    for entry, _rank in ranks:
        expr = expressions.get((spec["table"], entry["field"]))
        if not expr:
            return None
        direction = "DESC" if entry.get("dir") == "desc" else "ASC"
        pieces.append("(CASE WHEN (%s) IS NULL THEN 1 ELSE 0 END) ASC" % expr)
        pieces.append("(%s) %s" % (expr, direction))
    pieces.append("t.code ASC")
    return ", ".join(pieces)


def _span_sql(start, end):
    """Hours from one moment to the other, to two decimals, or NULL when a moment is missing or they run backwards."""
    start, end = sql.ident(start), sql.ident(end)
    return (
        "CASE WHEN t.%s IS NULL OR t.%s IS NULL OR t.%s < t.%s THEN NULL "
        "ELSE round((EXTRACT(EPOCH FROM (t.%s - t.%s)) / 3600.0)::numeric, 2) END"
        % (start, end, end, start, end, start)
    )


def _shown_hours_sql(start, end):
    """The number the hours filter compares: the two-decimal span, rounded to a tenth. Zero is blank."""
    span = _span_sql(start, end)
    return "CASE WHEN (%s) IS NULL OR (%s) = 0 THEN NULL ELSE round((%s)::numeric, 1) END" % (span, span, span)


def _clock_clause(start, end, op, values):
    expr = "(" + _shown_hours_sql(start, end) + ")"

    def number(value):
        value = _whole(value)
        return str(int(value) if isinstance(value, int) else value)

    if op == "blank":
        return expr + " IS NULL", []
    if op == "notBlank":
        return expr + " IS NOT NULL", []
    if op == "inRange":
        low, high = values
        if high < low:
            low, high = high, low
        return expr + " >= %s::numeric AND " + expr + " <= %s::numeric", [number(low), number(high)]
    if op == "notEqual":
        return expr + " IS NOT NULL AND " + expr + " IS DISTINCT FROM %s::numeric", [number(values[0])]
    symbol = {"equals": "=", "greaterThan": ">", "greaterThanOrEqual": ">=", "lessThan": "<", "lessThanOrEqual": "<="}[op]
    return expr + " " + symbol + " %s::numeric", [number(values[0])]


def _hours_text_clause(start, end, needle):
    number = "(" + _shown_hours_sql(start, end) + ")"
    shown = (
        "CASE WHEN %s IS NULL THEN '' WHEN %s = trunc(%s) THEN trunc(%s)::int::text "
        "ELSE rtrim(rtrim(to_char(%s, 'FM999990.0000'), '0'), '.') END"
        % (number, number, number, number, number)
    )
    return "strpos((" + shown + "), %s) > 0", [needle]


def _sql_slice(spec, filters, gap_ids, sorters, number, size):
    """One page from COUNT and LIMIT, or None when a sort has no SQL expression."""
    conditions, clocks, statuses, hours = _conditions(spec, filters, gap_ids)
    status = _status_sql().get(spec["table"]) if statuses else None
    if statuses and status is None:
        return None
    parts, params = [], []
    for column, condition in conditions.items():
        text, vals = sql.compile_pred(sql.store_column(spec["table"], column), condition)
        parts.append(text)
        params.extend(vals)
    if statuses:
        parts.append("(" + status + ") = ANY(%s::text[])")
        params.append(statuses)
    for start, end, op, values in clocks:
        text, vals = _clock_clause(start, end, op, values)
        parts.append(text)
        params.extend(vals)
    for start, end, needle in hours:
        text, vals = _hours_text_clause(start, end, needle)
        parts.append(text)
        params.extend(vals)
    order = _order_sql(spec, sorters)
    if not order:
        return None
    where = " AND ".join(parts) if parts else "TRUE"
    total = sql.count(spec["table"], where, params)
    codes = sql.codes_page(spec["table"], where, params, order, size, (number - 1) * size)
    return codes, total


def _fill(spec, codes, total, size, banner):
    reply = {"data": [], "last_page": max(1, math.ceil(total / size)) if total else 1, "last_row": total, "banner": banner}
    if not codes:
        return reply
    plant = store._plant()
    rows = plant.by_codes(spec["table"], codes)
    graph = spec["context"](plant, rows).graph()
    read = domain.reindex(graph)[spec["table"]]
    reply["data"] = [spec["row"](graph, read[code]) for code in codes if code in read]
    return reply


def page(kind, number=1, size=25, sorters=None, filters=None, gap=None):
    spec = LISTS.get(kind)
    if spec is None:
        return {"error": "Unknown list."}
    size = max(1, min(int(size or 25), 500))
    number = max(1, int(number or 1))
    gap_ids, banner = _gap(kind, gap)
    empty = {"data": [], "last_page": 1, "last_row": 0, "banner": banner}
    try:
        sliced = _sql_slice(spec, filters, gap_ids, sorters, number, size)
    except _NoMatch:
        return empty
    if sliced is None:
        try:
            found = _found(spec, filters, gap_ids, sorters)
        except _NoMatch:
            return empty
        total = len(found)
        codes = [row["code"] for row in found[(number - 1) * size:number * size]]
    else:
        codes, total = sliced
    return _fill(spec, codes, total, size, banner)
