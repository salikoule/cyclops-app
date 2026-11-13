"""Server API for the Cyclops plant record."""

import json
import time
import zlib

import anvil.server
from anvil.tables import app_tables
from craftify_library.CraftifyAuth import craftify_require_user

import access
import accounts
import exports
import listing
import seed_data
import store


def _guard():
    user = craftify_require_user()
    store.ensure_seeded()
    return user


def _session():
    session = accounts.resolve(_guard())
    return session


def _open(screen):
    session = _session()
    stored = None if session["role"] == "administrator" else session.get("screens")
    if not access.can_open(session["role"], stored, screen):
        raise anvil.server.PermissionDenied("You cannot open that screen.")
    return session


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
    if row is None:
        return
    profile = app_tables.access_grants.get(email=email)
    if profile is not None and not profile["active"]:
        return
    if row["enabled"] and row["confirmed_email"]:
        return
    row["enabled"] = True
    row["confirmed_email"] = True
    row.update()


@anvil.server.callable
def cyclops_session():
    return _timed("session", _session)


@anvil.server.callable
def cyclops_overview(who="all"):
    _open("overview")
    return _timed("overview", store.overview, who or "all")


@anvil.server.callable
def cyclops_structure():
    _open("overview")
    return _timed("structure", store.structure)


@anvil.server.http_endpoint("/list/:kind", methods=["POST"])
def cyclops_list_page(kind, **_query):
    """One page of a list for Tabulator's remote mode. Only the signed-in browser's own requests share its session."""
    try:
        session = _session()
    except Exception as error:
        return anvil.server.HttpResponse(401, str(error))
    if not access.can_open(session["role"], None if session["role"] == "administrator" else session["screens"], kind):
        return anvil.server.HttpResponse(403, "You cannot open that list.")
    asked = anvil.server.request.body_json or {}
    sorters = [{"field": entry.get("field"), "dir": entry.get("dir")} for entry in asked.get("sort") or []]
    filters = [{"field": entry.get("field"), "value": entry.get("value")} for entry in asked.get("filter") or []]
    return _timed("list page %s %s" % (kind, asked.get("page")), listing.page, kind, int(asked.get("page") or 1),
                  int(asked.get("size") or 25), sorters, filters, asked.get("gap") or None)


@anvil.server.callable
def cyclops_list_fields():
    _session()
    return listing.capabilities()


@anvil.server.callable
def cyclops_detail(kind, code):
    session = _session()
    screen = "configure" if kind == "settings" else kind
    stored = None if session["role"] == "administrator" else session.get("screens")
    if kind != "settings" and screen not in ("",) and not access.can_open(session["role"], stored, screen):
        raise anvil.server.PermissionDenied("You cannot open that record.")
    if kind == "settings" and not access.can_open(session["role"], stored, "configure"):
        raise anvil.server.PermissionDenied("You cannot open that record.")
    return _timed("detail %s %s" % (kind, code), store.detail, kind, code)


@anvil.server.callable
def cyclops_performance(year=None, month=0, machine=""):
    _open("performance")
    result = _timed("performance", store.performance, year, month or 0, machine or "")
    result["checks"] = getattr(seed_data, "CHECKS", [])
    result["source"] = seed_data.SOURCE
    return result


@anvil.server.callable
def cyclops_derive_changeovers():
    session = _session()
    if not session["canWrite"]:
        raise anvil.server.PermissionDenied("You have read-only access.")
    return _timed("derive changeovers", store.derive_changeovers)


@anvil.server.callable
def cyclops_search(term):
    session = _session()
    hits = _timed("search", store.search, term or "")
    allowed = set(session.get("screens") or [])
    return [hit for hit in hits or [] if hit.get("kind") in allowed]


@anvil.server.callable
def cyclops_choices():
    _session()
    result = store.choices()
    result["accessRoles"] = [{"value": key, "label": access.ROLE_LABEL[key]} for key in access.ROLES]
    result["accessScreens"] = [{"value": key, "label": label} for key, label in access.CATALOG]
    return result


@anvil.server.callable
def cyclops_apply(action, payload=None):
    session = _session()
    payload = _payload(payload)
    if action == "save-access":
        return _timed("save access", accounts.save_access, _guard(), payload)
    if not access.can_apply(session["role"], action):
        return {"error": "You have read-only access."}
    result = _timed("apply %s" % action, store.apply_action, action, payload, session["email"])
    if result.get("notify"):
        accounts.try_email(result.pop("notify"))
    return result


@anvil.server.callable
def cyclops_floor(today=""):
    session = _session()
    if not access.can_open(session["role"], None if session["role"] == "administrator" else session["screens"], "floor"):
        raise anvil.server.PermissionDenied("You cannot open the live floor.")
    return _timed("floor", store.floor, today or "")


@anvil.server.callable
def cyclops_export(kind, fmt="csv", filters=None, gap=None):
    session = _session()
    if kind not in listing.LISTS or not access.can_open(session["role"], None if session["role"] == "administrator" else session["screens"], kind):
        raise anvil.server.PermissionDenied("You cannot export that list.")
    rows = _timed("export %s %s filters=%s" % (kind, fmt, len(filters or [])), listing.records_for, kind, filters or [], gap or None)
    if fmt == "xlsx":
        media = anvil.BlobMedia("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                exports.xlsx_bytes(kind, rows), name="%s.xlsx" % kind)
    else:
        media = anvil.BlobMedia("text/csv", exports.csv_bytes(kind, rows), name="%s.csv" % kind)
    return media


@anvil.server.callable
def cyclops_history(kind="", code=""):
    session = _session()
    if code:
        if not access.can_open(session["role"], None if session["role"] == "administrator" else session["screens"], kind):
            raise anvil.server.PermissionDenied("You cannot open that record.")
        return accounts.history(kind, code, 40)
    if session["role"] != "administrator":
        raise anvil.server.PermissionDenied("Change history is for an administrator.")
    return accounts.history(limit=200)


@anvil.server.callable
def cyclops_users():
    session = _session()
    if session["role"] != "administrator":
        raise anvil.server.PermissionDenied("Users are for an administrator.")
    return {"users": accounts.list_users(), "catalog": session["catalog"], "roles": session["roles"]}


@anvil.server.callable
def cyclops_notifications():
    session = _session()
    return accounts.list_notifications(session["email"])


@anvil.server.callable
def cyclops_mark_notifications():
    session = _session()
    accounts.mark_notifications(session["email"])
    return {"unread": 0}


@anvil.server.callable
def cyclops_notification_prefs():
    session = _session()
    return accounts.notification_prefs(session["email"])


@anvil.server.callable
def cyclops_save_notification_prefs(maintenance=False, breakdowns=False):
    session = _session()
    return accounts.save_notification_prefs(session["email"], bool(maintenance), bool(breakdowns))


@anvil.server.callable
def cyclops_data_status():
    _session()
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
