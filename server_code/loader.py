"""Reads the plant tables for one request, in the shape the domain module works on.

A request names what it shows, and its scope in ``store`` reads those rows and what decides
their status: a recipe brings its inputs and runs, a run its scrap, lots and stoppages. Every
query names its columns, with only the code of each linked row, so following a link never
fetches rows one at a time. Nothing is cached between requests; the tables are the record.
"""

import anvil.tables.query as q
from anvil.tables import app_tables

import records


def _table(name):
    return getattr(app_tables, name)


def _fetch(columns, extra=()):
    plain, nested = list(extra), {}
    for column, _, kind in columns:
        if isinstance(kind, tuple):
            nested[column] = q.fetch_only("code")
        else:
            plain.append(column)
    return q.fetch_only(*plain, **nested)


_ROW_FETCH = {table: _fetch(columns, ("code",) + (("temps", "injection", "extra") if table == "recipes" else ()))
              for table, columns in records.TABLES}
_CHILD = {spec[0]: spec for spec in records.CHILDREN}
_CHILD_FETCH = {child: _fetch(columns + [(parent_column, "", records.link(parent))])
                for child, parent, parent_column, _, columns in records.CHILDREN}
_TARGET = {(table, column): kind[1] for table, columns in records.TABLES for column, _, kind in columns if isinstance(kind, tuple)}
_TARGET.update({(child, column): kind[1] for child, _, _, _, columns in records.CHILDREN for column, _, kind in columns if isinstance(kind, tuple)})


class Codes:
    """Row id -> code for the rows a view has read, so links can be read without fetching any column of the linked row."""

    def __init__(self):
        self.known = {}

    def remember(self, table, rows):
        self.known.setdefault(table, {}).update((row.get_id(), row["code"]) for row in rows)

    def code_of(self, table, linked):
        known = self.known.setdefault(table, {})
        if linked.get_id() not in known:
            known[linked.get_id()] = linked["code"]
        return known[linked.get_id()]


def _bare_fetch(columns, extra=(), coded=()):
    plain, nested = list(extra), {}
    for column, key, kind in columns:
        if isinstance(kind, tuple):
            nested[column] = q.fetch_only("code") if key in coded else q.fetch_only()
        else:
            plain.append(column)
    return q.fetch_only(*plain, **nested)


def _narrow_item(row, spec, first, codes):
    item = {first: row["code"]} if first else {}
    for column, key, kind in spec:
        item[key] = records.read_value(kind, row[column], codes.code_of)
    return item


def narrow(table, keys, codes, coded=(), **filters):
    """The rows of ``table`` matching ``filters``, with only the record fields in ``keys``, sorted by code. For read-only
    views; read linked tables first so ``codes`` knows their rows, or name the link keys in ``coded`` to fetch their code."""
    spec = [entry for entry in records.COLUMNS[table] if entry[1] in keys]
    rows = list(_table(table).search(_bare_fetch(spec, ("code",), coded), **filters))
    codes.remember(table, rows)
    found = [_narrow_item(row, spec, "id", codes) for row in rows]
    found.sort(key=lambda item: item["id"])
    return found


def narrow_lines(child, keys, codes):
    """Parent code -> the ``child`` lines of the parents ``codes`` has read, with only the fields in ``keys``."""
    _, parent, parent_column, _, columns = _CHILD[child]
    spec = [entry for entry in columns if entry[1] in keys]
    parents = codes.known.get(parent) or {}
    by_parent = {}
    for row in _table(child).search(_bare_fetch(spec + [(parent_column, "", records.link(parent))])):
        owner = row[parent_column]
        if owner is not None and owner.get_id() in parents:
            by_parent.setdefault(parents[owner.get_id()], []).append(_narrow_item(row, spec, None, codes))
    return by_parent


def _linked(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


class Plant:
    def __init__(self, codes=()):
        self.rows = {table: {} for table in records.ORDER}
        self.whole = set()
        self.line_rows = {}
        self.read_lines = set()
        self.covered = {}
        self.codes = {table: [row["code"] for row in _table(table).search(q.fetch_only("code"))] for table in codes}

    def _add(self, table, found):
        known = self.rows[table]
        added = []
        for row in found:
            if row.get_id() not in known:
                known[row.get_id()] = row
            added.append(known[row.get_id()])
        return added

    def all(self, *tables):
        for table in tables:
            if table not in self.whole:
                self._add(table, _table(table).search(_ROW_FETCH[table]))
                self.whole.add(table)
        return self

    def find(self, table, **filters):
        if table in self.whole:
            rows = list(self.rows[table].values())
            return [row for row in rows if all(_matches(row, column, wanted) for column, wanted in filters.items())]
        return self._add(table, _table(table).search(_ROW_FETCH[table], **filters))

    def get(self, table, code):
        for row in self.rows[table].values():
            if row["code"] == code:
                return row
        if table in self.whole:
            return None
        return (self._add(table, [row for row in [_table(table).get(_ROW_FETCH[table], code=code)] if row is not None]) or [None])[0]

    def by_codes(self, table, codes):
        known = {row["code"] for row in self.rows[table].values()}
        wanted = sorted({code for code in codes if code and code not in known})
        if wanted and table not in self.whole:
            self._add(table, _table(table).search(_ROW_FETCH[table], code=q.any_of(*wanted)))
        return [row for row in self.rows[table].values() if row["code"] in set(codes)]

    def follow(self, table, column):
        """Read the rows that the loaded ``table`` rows link to through ``column``."""
        source = self.line_values(table) if table in _CHILD else self.rows[table].values()
        codes = [linked["code"] for row in source for linked in _linked(row[column])]
        return self.by_codes(_TARGET[(table, column)], codes)

    def lines(self, child):
        """Read the ``child`` line rows of every loaded parent row not read yet."""
        _, parent, parent_column, _, _ = _CHILD[child]
        covered = self.covered.setdefault(child, set())
        parents = [row for key, row in self.rows[parent].items() if key not in covered]
        if parents:
            if parent in self.whole and not covered:
                found = _table(child).search(_CHILD_FETCH[child])
            else:
                found = _table(child).search(_CHILD_FETCH[child], **{parent_column: q.any_of(*parents)})
            covered.update(row.get_id() for row in parents)
            for row in found:
                linked = row[parent_column]
                if linked is not None:
                    self.line_rows.setdefault((child, linked.get_id()), []).append(row)
        self.read_lines.add(child)
        return self.line_values(child)

    def line_values(self, child):
        return [row for (name, _), rows in self.line_rows.items() if name == child for row in rows]

    def lines_of(self, child, parent_row):
        """The ``child`` rows read for ``parent_row``, or None when they were not read."""
        if parent_row.get_id() not in self.covered.get(child, ()):
            return None
        return self.line_rows.get((child, parent_row.get_id()), [])

    def known_rows(self):
        """((table, code), row) for every record row read."""
        for table, rows in self.rows.items():
            for row in rows.values():
                yield (table, row["code"]), row

    def graph(self):
        code_by_id = {table: {key: row["code"] for key, row in rows.items()} for table, rows in self.rows.items()}

        def code_of(table, linked):
            return code_by_id[table].get(linked.get_id()) or linked["code"]

        plant = {table: [records.to_item(table, row, code_of) for row in rows.values()] for table, rows in self.rows.items()}
        by_id = {table: {key: item for key, item in zip(rows.keys(), plant[table])} for table, rows in self.rows.items()}
        for child in self.read_lines:
            _, parent, _, list_key, _ = _CHILD[child]
            for (name, parent_id), rows in self.line_rows.items():
                if name == child and parent_id in by_id[parent]:
                    by_id[parent][parent_id][list_key] = [records.child_item(child, row, code_of) for row in rows]
        for table in plant:
            plant[table].sort(key=lambda item: item["id"])
        plant["loaded"] = {table: ("all" if table in self.whole else "some") for table, rows in self.rows.items() if rows or table in self.whole}
        plant["lines"] = sorted(self.read_lines)
        if self.codes:
            plant["codes"] = self.codes
        return plant


def _matches(row, column, wanted):
    value = row[column]
    if hasattr(wanted, "get_id"):
        return any(linked.get_id() == wanted.get_id() for linked in _linked(value))
    return value == wanted
