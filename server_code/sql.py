"""SQL against the plant schema.

Reads and writes are ordinary statements. A linked column is a foreign key;
the row handed to the rest of the server carries the linked id and code.
"""

import os
import re
import threading
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

import records

_NAME = re.compile(r"[a-z][a-z0-9_]*")
_local = threading.local()

MULTI = {
    "items": {"approved_machines": ("item_machines", "item_id", "machine_id", "machines")},
    "personnel": {"qualified_machines": ("personnel_machines", "personnel_id", "machine_id", "machines")},
}


class Row(dict):
    def get_id(self):
        return self["_id"]


class Pred:
    """A boolean expression. ``{c}`` is the column it is applied to."""

    def __init__(self, text, params=()):
        self.text = text
        self.params = list(params)


def ident(name):
    if not _NAME.fullmatch(name or ""):
        raise ValueError(name)
    return name


def as_json(value):
    if value is None:
        return None
    return Json(value)


def connect():
    url = os.environ.get("CYCLOPS_DATABASE_URL")
    kwargs = {"row_factory": dict_row, "autocommit": True, "application_name": "cyclops-sql"}
    if url:
        return psycopg.connect(url, **kwargs)
    name = os.environ.get("CYCLOPS_PG_DB", "cyclops_plant")
    return psycopg.connect(dbname=name, **kwargs)


def connection():
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        _local.conn = connect()
    return _local.conn


@contextmanager
def transaction():
    with connection().transaction():
        yield


def in_transaction(fn):
    def wrapped(*args, **kwargs):
        with transaction():
            return fn(*args, **kwargs)
    return wrapped


def query(statement, params=()):
    with connection().cursor() as cur:
        cur.execute(statement, params)
        if cur.description is None:
            return []
        return list(cur.fetchall())


def one(statement, params=()):
    rows = query(statement, params)
    return rows[0] if rows else None


def execute(statement, params=()):
    with connection().cursor() as cur:
        cur.execute(statement, params)
        return cur.rowcount


def columns_of(table):
    if table in records.COLUMNS:
        return records.COLUMNS[table]
    for child, parent, parent_column, _, columns in records.CHILDREN:
        if child == table:
            return [(parent_column, "", records.link(parent))] + list(columns)
    raise KeyError(table)


def store_column(table, column):
    for col, _, kind in columns_of(table):
        if col == column and isinstance(kind, tuple) and kind[0] == "link":
            return "t." + ident(column) + "_id"
    return "t." + ident(column)


def _select_sql(table):
    pieces = ["t.id AS _id"]
    joins = []
    alias_n = 0
    if table in records.COLUMNS:
        pieces.append("t.code")
    for column, _, kind in columns_of(table):
        if isinstance(kind, tuple) and kind[0] == "link":
            alias = "j%d" % alias_n
            alias_n += 1
            pieces.append("t.%s_id AS %s_id" % (column, column))
            pieces.append("%s.code AS %s_code" % (alias, column))
            joins.append("LEFT JOIN plant.%s %s ON %s.id = t.%s_id" % (ident(kind[1]), alias, alias, column))
        elif isinstance(kind, tuple) and kind[0] == "links":
            continue
        else:
            pieces.append("t.%s" % column)
    if table == "recipes":
        pieces.extend(["t.temps", "t.injection", "t.extra"])
    statement = "SELECT " + ", ".join(pieces) + " FROM plant.%s t" % ident(table)
    if joins:
        statement += " " + " ".join(joins)
    return statement


SELECTS = {table: _select_sql(table) for table, _columns in records.TABLES}
SELECTS.update({spec[0]: _select_sql(spec[0]) for spec in records.CHILDREN})


def _assemble(table, record, multi):
    row = Row(_id=record["_id"])
    if "code" in record:
        row["code"] = record["code"] or ""
    for column, _, kind in columns_of(table):
        if isinstance(kind, tuple) and kind[0] == "links":
            row[column] = list(multi.get(column, {}).get(record["_id"], []))
        elif isinstance(kind, tuple) and kind[0] == "link":
            linked = record[column + "_id"]
            row[column] = None if linked is None else Row(_id=linked, code=record[column + "_code"] or "")
        else:
            row[column] = record[column]
    if table == "recipes":
        row["temps"] = record["temps"]
        row["injection"] = record["injection"]
        row["extra"] = record["extra"]
    return row


def _multi(table, ids):
    spec = MULTI.get(table) or {}
    found = {}
    if not spec or not ids:
        return found
    for column, (junction, parent_col, child_col, target) in spec.items():
        rows = query(
            """
            SELECT j.%s AS parent_id, j.%s AS child_id, c.code
            FROM plant.%s j
            JOIN plant.%s c ON c.id = j.%s
            WHERE j.%s = ANY(%%s::bigint[])
            ORDER BY j.%s, j.position
            """ % (parent_col, child_col, junction, target, child_col, parent_col, parent_col),
            (list(ids),),
        )
        grouped = {}
        for row in rows:
            grouped.setdefault(row["parent_id"], []).append(Row(_id=row["child_id"], code=row["code"] or ""))
        found[column] = grouped
    return found


def read(table, where="TRUE", params=(), order=""):
    statement = SELECTS[table] + " WHERE " + where
    if order:
        statement += " ORDER BY " + order
    records_ = query(statement, params)
    linked = _multi(table, [row["_id"] for row in records_])
    return [_assemble(table, row, linked) for row in records_]


def count(table, where="TRUE", params=()):
    row = one("SELECT count(*) AS n FROM plant." + ident(table) + " t WHERE " + where, params)
    return int(row["n"]) if row else 0


def codes_page(table, where, params, order, limit, offset):
    """Codes for one page. ``where`` and ``order`` are SQL we built; values stay in ``params``."""
    rows = query(
        "SELECT t.code FROM plant." + ident(table) + " t WHERE " + where
        + " ORDER BY " + order + " LIMIT %s OFFSET %s",
        tuple(params) + (limit, offset),
    )
    return [row["code"] for row in rows]


def _stored(table, fields):
    spec = {column: kind for column, _, kind in columns_of(table)}
    cols, params, multi = [], [], []
    for key, value in fields.items():
        kind = spec.get(key)
        if isinstance(kind, tuple) and kind[0] == "links":
            multi.append((key, value or []))
            continue
        if isinstance(kind, tuple) and kind[0] == "link":
            cols.append(ident(key) + "_id")
            params.append(None if value is None else value.get_id())
            continue
        cols.append(ident(key))
        if kind == records.JSON or (kind is None and isinstance(value, (dict, list))):
            params.append(as_json(value))
        else:
            params.append(value)
    return cols, params, multi


def _replace_multi(table, row_id, pairs):
    spec = MULTI.get(table) or {}
    for key, values in pairs:
        junction, parent_col, child_col, _target = spec[key]
        execute("DELETE FROM plant.%s WHERE %s = %%s" % (junction, parent_col), (row_id,))
        for position, linked in enumerate(values):
            if linked is None:
                continue
            execute(
                "INSERT INTO plant.%s (%s, %s, position) VALUES (%%s, %%s, %%s)" % (junction, parent_col, child_col),
                (row_id, linked.get_id(), position),
            )


def insert(table, fields):
    cols, params, multi = _stored(table, fields)
    marks = ", ".join(["%s"] * len(cols))
    row = one(
        "INSERT INTO plant.%s (%s) VALUES (%s) RETURNING id" % (ident(table), ", ".join(cols), marks),
        params,
    )
    _replace_multi(table, row["id"], multi)
    return read(table, "t.id = %s", (row["id"],))[0]


def update(table, row_id, fields):
    cols, params, multi = _stored(table, fields)
    if cols:
        assigns = ", ".join("%s = %%s" % col for col in cols)
        params.append(row_id)
        execute("UPDATE plant.%s SET %s WHERE id = %%s" % (ident(table), assigns), params)
    if multi:
        _replace_multi(table, row_id, multi)


def delete(table, row_id):
    execute("DELETE FROM plant." + ident(table) + " WHERE id = %s", (row_id,))


def delete_where(table, where, params=()):
    execute("DELETE FROM plant." + ident(table) + " WHERE " + where, params)


def ilike(pattern):
    return Pred("{c} ILIKE %s", [pattern])


def any_of(*values):
    if not values:
        return Pred("FALSE")
    if all(isinstance(value, Pred) for value in values):
        text = "(" + " OR ".join("(" + value.text + ")" for value in values) + ")"
        return Pred(text, [param for value in values for param in value.params])
    if all(isinstance(value, dict) and "id" in value for value in values):
        return Pred("{c} = ANY(%s::bigint[])", [[value["id"] for value in values]])
    return Pred("{c} = ANY(%s::text[])", [list(values)])


def all_of(*values):
    parts, params = [], []
    for value in values:
        if isinstance(value, Pred):
            parts.append("(" + value.text + ")")
            params.extend(value.params)
        elif value is None:
            parts.append("({c} IS NULL)")
        else:
            parts.append("({c} = %s)")
            params.append(value)
    return Pred(" AND ".join(parts), params)


def not_(value):
    if value is None:
        return Pred("{c} IS NOT NULL")
    if isinstance(value, Pred):
        return Pred("NOT (" + value.text + ")", list(value.params))
    return Pred("{c} IS DISTINCT FROM %s", [value])


def gt(value):
    return Pred("{c} > %s", [value])


def gte(value):
    return Pred("{c} >= %s", [value])


def lt(value):
    return Pred("{c} < %s", [value])


def lte(value):
    return Pred("{c} <= %s", [value])


def between(low, high, min_inclusive=True, max_inclusive=False):
    left = ">=" if min_inclusive else ">"
    right = "<=" if max_inclusive else "<"
    return Pred("{c} " + left + " %s AND {c} " + right + " %s", [low, high])


def compile_pred(column, condition):
    if isinstance(condition, Pred):
        return condition.text.replace("{c}", column), list(condition.params)
    if condition is None:
        return column + " IS NULL", []
    return column + " = %s", [condition]


def order_clause(table, pairs):
    return ", ".join(store_column(table, column) + (" ASC" if ascending else " DESC") for column, ascending in pairs)
