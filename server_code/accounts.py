"""Signed-in users: role, screen grants, notifications, and the audit list.

The plant graph does not include these tables, so a workbook import does not wipe them.
"""

import datetime

import anvil.server
import anvil.tables
from anvil.tables import app_tables

import access
import audit
import records

_UNSET = object()


def _now():
    return records.moment_text(datetime.datetime.now(datetime.timezone.utc))


def _user_email(user):
    try:
        return (user["email"] or "").strip()
    except Exception:
        return ""


def _screens(row):
    raw = row["screens"] if row is not None else None
    if isinstance(raw, dict):
        return list(raw.get("ids") or [])
    return None


def _profiles():
    return [{"email": row["email"] or "", "role": row["role"] or "observer", "active": bool(row["active"]),
             "screens": _screens(row)} for row in app_tables.access_grants.search()]


def _prefs():
    return [{"email": row["email"] or "", "maintenance": bool(row["maintenance"]), "breakdowns": bool(row["breakdowns"])}
            for row in app_tables.notification_prefs.search()]


def unread_count(email):
    key = access.email_key(email)
    return sum(1 for row in app_tables.notifications.search(read_at=None) if access.email_key(row["email"]) == key)


def resolve(user):
    """The signed-in user's access. The first account, or the next one when no administrator is active, becomes administrator."""
    email = _user_email(user)
    if not email:
        raise anvil.server.PermissionDenied("Sign in to continue.")
    if user["enabled"] is False:
        raise anvil.server.PermissionDenied("This account is deactivated.")
    profiles = _profiles()
    row = app_tables.access_grants.get(email=email)
    active_admin = any(profile["role"] == "administrator" and profile["active"] for profile in profiles)
    if row is None:
        role = "administrator" if not active_admin else "observer"
        row = app_tables.access_grants.add_row(email=email, role=role, screens={"ids": access.default_ids(role)}, active=True)
        write_audit([audit.user_row(email, email, _now(), "Signed in as %s" % access.ROLE_LABEL[role], {"role": [None, role]})])
    elif row["active"] is False:
        raise anvil.server.PermissionDenied("This account is deactivated.")
    elif not active_admin and row["role"] != "administrator":
        previous = row["role"] or "observer"
        row.update(role="administrator", active=True, screens={"ids": access.default_ids("administrator")})
        write_audit([audit.user_row(email, email, _now(), "Became administrator because none was active",
                                    {"role": [previous, "administrator"]})])
    stored = None if row["role"] == "administrator" else _screens(row)
    return access.session_view(email, row["role"] or "observer", stored, unread_count(email))


def require(user):
    session = resolve(user)
    return session


def write_audit(entries):
    for entry in entries or []:
        app_tables.audit_events.add_row(
            at=records.parse_moment(entry.get("at")) or datetime.datetime.now(datetime.timezone.utc),
            email=entry.get("email") or "",
            record_table=entry.get("recordTable") or "",
            record=entry.get("record") or "",
            action=entry.get("action") or "",
            summary=entry.get("summary") or "",
            changes=entry.get("changes") or {},
        )


def history(kind="", code="", limit=80):
    table = ""
    if kind:
        table = next((name for name, label in audit.TABLE_KIND.items() if label == kind), kind)
    query = {"record_table": table, "record": code} if code else {}
    found = app_tables.audit_events.search(anvil.tables.order_by("at", ascending=False), **query)
    rows = []
    for row in list(found)[:limit]:
        table = row["record_table"] or ""
        changes = dict(row["changes"] or {})
        rows.append({
            "at": records.moment_text(row["at"]),
            "email": row["email"] or "",
            "table": table,
            "record": row["record"] or "",
            "kind": audit.TABLE_KIND.get(table, ""),
            "place": "%s %s" % (audit.TABLE_LABEL.get(table, table), row["record"] or ""),
            "action": row["action"] or "",
            "summary": row["summary"] or "",
            "changes": changes,
            "lines": audit.present_changes(table, changes),
        })
    return rows


def record_changes(before, after, dirty, email):
    write_audit(audit.rows(before, after, dirty, email, _now()))


def _notify_rows(entries):
    stored = []
    for entry in entries or []:
        app_tables.notifications.add_row(
            email=entry.get("email") or "",
            kind=entry.get("kind") or "",
            record=entry.get("record") or "",
            title=entry.get("title") or "",
            body=entry.get("body") or "",
            created_at=records.parse_moment(entry.get("createdAt")) or datetime.datetime.now(datetime.timezone.utc),
            read_at=None,
        )
        stored.append(entry)
    return stored


def notifications_for(before_stops, after_stops, causes, dirty_codes):
    """Notifications for stoppages whose cause newly qualifies. Returns the rows written."""
    import notify

    when = _now()
    entries = []
    for code in dirty_codes or []:
        after = after_stops.get(code)
        if after is None:
            continue
        cause = causes.get(after.get("causeId") or "")
        kind = notify.kind_for(before_stops.get(code), after, cause)
        entries.extend(notify.for_users(kind, after, cause, _prefs(), when))
    return _notify_rows(entries)


def try_email(entries):
    """Second channel. Failure leaves the in-app row in place."""
    if not entries:
        return False
    try:
        import anvil.email
    except Exception:
        return False
    sent = False
    for entry in entries:
        try:
            anvil.email.send(to=entry.get("email"), subject=entry.get("title") or "Cyclops", text=entry.get("body") or "")
            sent = True
        except Exception:
            continue
    return sent


def list_notifications(email, limit=50):
    key = access.email_key(email)
    rows = [row for row in app_tables.notifications.search(anvil.tables.order_by("created_at", ascending=False))
            if access.email_key(row["email"]) == key]
    return [{
        "id": row.get_id(),
        "kind": row["kind"] or "",
        "record": row["record"] or "",
        "title": row["title"] or "",
        "body": row["body"] or "",
        "at": records.moment_text(row["created_at"]),
        "read": row["read_at"] is not None,
    } for row in rows[:limit]]


def mark_notifications(email):
    key = access.email_key(email)
    now = datetime.datetime.now(datetime.timezone.utc)
    for row in app_tables.notifications.search(read_at=None):
        if access.email_key(row["email"]) == key:
            row.update(read_at=now)


def notification_prefs(email):
    row = _pref_row(email)
    if row is None:
        return {"maintenance": False, "breakdowns": False}
    return {"maintenance": bool(row["maintenance"]), "breakdowns": bool(row["breakdowns"])}


def _pref_row(email):
    key = access.email_key(email)
    for row in app_tables.notification_prefs.search():
        if access.email_key(row["email"]) == key:
            return row
    return None


def save_notification_prefs(email, maintenance, breakdowns):
    row = _pref_row(email)
    if row is None:
        app_tables.notification_prefs.add_row(email=email, maintenance=bool(maintenance), breakdowns=bool(breakdowns))
    else:
        row.update(maintenance=bool(maintenance), breakdowns=bool(breakdowns))
    return notification_prefs(email)


def list_users():
    profiles = {access.email_key(row["email"]): row for row in app_tables.access_grants.search()}
    found = []
    for user in app_tables.users.search():
        email = user["email"] or ""
        profile = profiles.get(access.email_key(email))
        role = (profile["role"] if profile is not None else "observer") or "observer"
        if role not in access.ROLES:
            role = "observer"
        active = bool(user["enabled"]) and (profile is None or bool(profile["active"]))
        stored = _screens(profile) if profile is not None else access.default_ids(role)
        found.append({
            "email": email,
            "role": role,
            "roleLabel": access.ROLE_LABEL.get(role, role),
            "active": active,
            "screens": stored or [],
            "lastLogin": records.moment_text(user["last_login"]),
        })
    found.sort(key=lambda entry: entry["email"].lower())
    return found


def _split_screens(value):
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    allowed = {key for key, _ in access.CATALOG}
    return [key for key in value or [] if key in allowed]


def save_access(actor, payload):
    session = resolve(actor)
    if session["role"] != "administrator":
        return {"error": "That needs an administrator."}
    email = (payload.get("email") or "").strip()
    user = app_tables.users.get(email=email)
    if user is None:
        return {"error": "That user was not found."}
    role = payload.get("role") or ""
    if role not in access.ROLES:
        return {"error": "Choose a role."}
    active = str(payload.get("active") or "").lower() in ("yes", "true", "1")
    if not access.leaves_an_admin(_profiles(), email, role, active):
        return {"error": "Keep at least one active administrator."}
    screens = _split_screens(payload.get("screens"))
    row = app_tables.access_grants.get(email=email)
    before_role = row["role"] if row is not None else "observer"
    before_active = bool(row["active"]) if row is not None else True
    if row is None:
        row = app_tables.access_grants.add_row(email=email, role=role, active=active, screens={"ids": screens})
    else:
        row.update(role=role, active=active, screens={"ids": screens})
    user.update(enabled=active)
    write_audit([audit.user_row(
        email, session["email"], _now(),
        "Set %s to %s%s" % (email, access.ROLE_LABEL[role], "" if active else ", deactivated"),
        {"role": [before_role, role], "active": [before_active, active], "screens": [None, screens]},
    )])
    return {"refresh": True}
