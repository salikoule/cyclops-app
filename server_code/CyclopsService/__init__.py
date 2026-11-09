"""Server API for the Cyclops plant record."""

import json
import time
import zlib

import anvil.server
from anvil.tables import app_tables
from craftify_library.CraftifyAuth import craftify_require_user

import listing
import seed_data
import store


def _guard():
    user = craftify_require_user()
    store.ensure_seeded()
    return user


def _timed(label, work, *args):
    """Run one call and print how long it took, so the App Logs show where time goes."""
    started = time.time()
    result = work(*args)
    print("%s %.2fs" % (label, time.time() - started))
    return result


def _payload(value):
    if not value:
        return {}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


@anvil.server.callable
def cyclops_enable_new_user(email):
    """The local Users service creates accounts disabled. Enable one that has never signed in."""
    email = (email or "").strip()
    if not email or "@" not in email:
        return
    row = app_tables.users.get(email=email)
    if row is None or row["last_login"] is not None:
        return
    row["enabled"] = True
    row["confirmed_email"] = True
    row.update()


@anvil.server.callable
def cyclops_overview(who="all"):
    _guard()
    return _timed("overview", store.overview, who or "all")


@anvil.server.callable
def cyclops_structure():
    _guard()
    return _timed("structure", store.structure)


@anvil.server.http_endpoint("/list/:kind", methods=["POST"])
def cyclops_list_page(kind, **_query):
    """One page of a list for Tabulator's remote mode. Only the signed-in browser's own requests share its session."""
    try:
        _guard()
    except Exception as error:
        return anvil.server.HttpResponse(401, str(error))
    asked = anvil.server.request.body_json or {}
    sorters = [{"field": entry.get("field"), "dir": entry.get("dir")} for entry in asked.get("sort") or []]
    filters = [{"field": entry.get("field"), "value": entry.get("value")} for entry in asked.get("filter") or []]
    return _timed("list page %s %s" % (kind, asked.get("page")), listing.page, kind, int(asked.get("page") or 1),
                  int(asked.get("size") or 25), sorters, filters, asked.get("gap") or None)


@anvil.server.callable
def cyclops_list_fields():
    _guard()
    return listing.capabilities()


@anvil.server.callable
def cyclops_detail(kind, code):
    _guard()
    return _timed("detail %s %s" % (kind, code), store.detail, kind, code)


@anvil.server.callable
def cyclops_performance(year=None, month=0, machine=""):
    _guard()
    result = _timed("performance", store.performance, year, month or 0, machine or "")
    result["checks"] = getattr(seed_data, "CHECKS", [])
    result["source"] = seed_data.SOURCE
    return result


@anvil.server.callable
def cyclops_derive_changeovers():
    _guard()
    return _timed("derive changeovers", store.derive_changeovers)


@anvil.server.callable
def cyclops_search(term):
    _guard()
    return _timed("search", store.search, term or "")


@anvil.server.callable
def cyclops_choices():
    _guard()
    return _timed("choices", store.choices)


@anvil.server.callable
def cyclops_apply(action, payload=None):
    _guard()
    return _timed("apply %s" % action, store.apply_action, action, _payload(payload))


@anvil.server.callable
def cyclops_data_status():
    _guard()
    counted = store.counts()
    counted["downtimeHours"] = store.downtime_hours()
    return {"counts": counted, "source": seed_data.SOURCE}


@anvil.server.callable
def cyclops_import_plant(media):
    """Replace the plant record with a workbook import. Server Uplink only: scripts/import_workbook.py."""
    if anvil.server.context.client.type != "uplink":
        raise anvil.server.PermissionDenied("The workbook import runs from scripts/import_workbook.py with the server Uplink key.")
    graph = json.loads(zlib.decompress(media.get_bytes()).decode("utf-8"))
    return store.replace_all(graph)
