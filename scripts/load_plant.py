#!/usr/bin/env python3
"""Copy the current Cyclops rows into the plant schema.

The source database is opened read-only. The target must not be that database.
Ids are kept, so foreign keys copy across without a lookup table.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "plant.sql"
NAME = re.compile(r"[a-z_][a-z0-9_]*")
LIVE = "cyclops_app_anvil"

TABLES = (
    "item_categories", "machine_types", "units", "variant_attributes", "person_roles", "shifts",
    "stoppage_causes", "scrap_reasons", "machines", "personnel", "items", "molds", "recipes",
    "production_orders", "production_runs", "lots", "stoppages", "changeovers", "recipe_inputs",
    "run_scrap", "run_inputs", "item_attributes", "access_grants", "audit_events",
    "notification_prefs", "notifications",
)
SOURCES = {"recipes": "data_tables.table_3"}
JUNCTIONS = (
    ("item_machines", "item_id", "machine_id", "data_tables.table_23_link_approved_machines"),
    ("personnel_machines", "personnel_id", "machine_id", "data_tables.table_16_link_qualified_machines"),
)


def quote(name):
    if not NAME.fullmatch(name or ""):
        raise SystemExit("unexpected name %r" % (name,))
    return '"' + name + '"'


def statements(script):
    found, buf = [], []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            text = "\n".join(buf).strip()
            if text:
                found.append(text)
            buf = []
    if buf and "".join(buf).strip():
        raise SystemExit("plant.sql has a statement that does not end with ';'")
    return found


def types_of(conn, relation):
    schema, name = relation.split(".")
    rows = conn.execute(
        """
        SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
        """,
        (schema, name),
    ).fetchall()
    return {row["name"]: row["type"] for row in rows}


def dest_columns(conn, table):
    return conn.execute(
        """
        SELECT column_name AS name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'plant' AND table_name = %s AND column_name <> 'id'
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()


def source_of(table):
    return SOURCES.get(table, "app_tables." + table)


def column_map(src, dst, table):
    source = source_of(table)
    src_types = types_of(src, source)
    columns = dest_columns(dst, table)
    dest_names = {col["name"] for col in columns}
    selects, dests, metas = [quote("_id")], [quote("id")], [{"type": "bigint", "nullable": False}]
    for col in columns:
        name = col["name"]
        if name.endswith("_id") and name[:-3] in src_types and name[:-3] not in dest_names:
            selects.append(quote(name[:-3]))
            dests.append(quote(name))
            metas.append({"type": "bigint", "nullable": True})
            continue
        if name not in src_types:
            raise SystemExit("%s.%s is not in %s" % (table, name, source))
        src_type = src_types[name]
        if src_type == "datetime_with_tz":
            selects.append("(%s).utc AT TIME ZONE 'UTC'" % quote(name))
        elif src_type == "text" and col["data_type"] == "jsonb":
            selects.append(
                "CASE WHEN %(c)s IS NULL OR btrim(%(c)s) = '' THEN NULL ELSE %(c)s::jsonb END" % {"c": quote(name)}
            )
        else:
            selects.append(quote(name))
        dests.append(quote(name))
        metas.append({"type": col["data_type"], "nullable": col["is_nullable"] == "YES"})
    return source, selects, dests, metas


def coerce(value, meta):
    if value is None and not meta["nullable"]:
        if meta["type"] == "boolean":
            return False
        if meta["type"] == "text":
            return ""
    if meta["type"] == "jsonb" and value is not None:
        if isinstance(value, str):
            value = json.loads(value)
        return Json(value)
    return value


def load_table(src, dst, table):
    source, selects, dests, metas = column_map(src, dst, table)
    with src.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT %s FROM %s" % (", ".join(selects), source))
        fetched = cur.fetchall()
    payload = [tuple(coerce(row[i], metas[i]) for i in range(len(metas))) for row in fetched]
    if payload:
        with dst.cursor() as cur:
            cur.executemany(
                "INSERT INTO plant.%s (%s) VALUES (%s)" % (table, ", ".join(dests), ", ".join(["%s"] * len(dests))),
                payload,
            )
    src_n = src.execute("SELECT count(*) AS n FROM %s" % source).fetchone()["n"]
    dst_n = dst.execute("SELECT count(*) AS n FROM plant.%s" % table).fetchone()["n"]
    if src_n != dst_n:
        raise SystemExit("%s: source %s, loaded %s" % (table, src_n, dst_n))
    print("%s %s" % (table, dst_n))


def load_junction(src, dst, table, parent_col, child_col, source):
    rows = src.execute("SELECT from_row, to_row, idx FROM %s ORDER BY from_row, idx" % source).fetchall()
    if rows:
        with dst.cursor() as cur:
            cur.executemany(
                "INSERT INTO plant.%s (%s, %s, position) VALUES (%%s, %%s, %%s)" % (table, parent_col, child_col),
                [(row["from_row"], row["to_row"], row["idx"]) for row in rows],
            )
    src_n = src.execute("SELECT count(*) AS n FROM %s" % source).fetchone()["n"]
    dst_n = dst.execute("SELECT count(*) AS n FROM plant.%s" % table).fetchone()["n"]
    if src_n != dst_n:
        raise SystemExit("%s: source %s, loaded %s" % (table, src_n, dst_n))
    print("%s %s" % (table, dst_n))


def set_sequences(dst):
    tables = dst.execute(
        """
        SELECT table_name AS name
        FROM information_schema.columns
        WHERE table_schema = 'plant' AND column_name = 'id'
        ORDER BY 1
        """
    ).fetchall()
    for row in tables:
        table = row["name"]
        if not NAME.fullmatch(table):
            continue
        seq = dst.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", ("plant." + table,)).fetchone()["seq"]
        if not seq:
            continue
        dst.execute(
            "SELECT setval(%s, GREATEST(COALESCE((SELECT max(id) FROM plant.%s), 1), 1),"
            " (SELECT max(id) FROM plant.%s) IS NOT NULL)" % ("%s", table, table),
            (seq,),
        )


def main():
    parser = argparse.ArgumentParser(description="Load plant tables from the current Cyclops database.")
    parser.add_argument("--source", default=LIVE)
    parser.add_argument("--target", default="cyclops_plant")
    args = parser.parse_args()
    if args.target == args.source or args.target == LIVE:
        raise SystemExit("refusing to write %s" % args.target)
    if not NAME.fullmatch(args.target) or not NAME.fullmatch(args.source):
        raise SystemExit("database names must be plain identifiers")

    admin = psycopg.connect(dbname="postgres", autocommit=True)
    exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.target,)).fetchone()
    if exists is None:
        admin.execute("CREATE DATABASE %s" % quote(args.target))
    admin.close()

    src = psycopg.connect(
        dbname=args.source, row_factory=dict_row, autocommit=True,
        options="-c default_transaction_read_only=on -c timezone=UTC",
        application_name="cyclops-load-source",
    )
    dst = psycopg.connect(dbname=args.target, row_factory=dict_row, autocommit=False, options="-c timezone=UTC",
                          application_name="cyclops-load")
    try:
        with dst.transaction():
            dst.execute("DROP SCHEMA IF EXISTS plant CASCADE")
            for statement in statements(SCHEMA.read_text()):
                dst.execute(statement)
            for table in TABLES:
                load_table(src, dst, table)
            for spec in JUNCTIONS:
                load_junction(src, dst, *spec)
            set_sequences(dst)
            dangling = dst.execute(
                """
                SELECT count(*) AS n
                FROM plant.recipes r
                LEFT JOIN plant.items i ON i.id = r.item_id
                WHERE r.item_id IS NOT NULL AND i.id IS NULL
                """
            ).fetchone()["n"]
            if dangling:
                raise SystemExit("%s recipes point at a missing item" % dangling)
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    print("loaded %s" % args.target)


if __name__ == "__main__":
    try:
        main()
    except psycopg.Error as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
