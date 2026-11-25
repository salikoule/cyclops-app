"""Signed-in users: role, screen grants, notifications, and the audit list.

The plant graph does not include these tables, so a workbook import does not wipe them.
Sign-in stays on Anvil's users table. Roles, notices, and the audit list are ordinary rows.
"""

import datetime

import anvil.server

import access
import audit
import records
import sql

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
    rows = sql.query("SELECT email, role, active, screens FROM plant.access_grants")
    return [{"email": row["email"] or "", "role": row["role"] or "observer", "active": bool(row["active"]),
             "screens": _screens(row)} for row in rows]


def _prefs():
    rows = sql.query("SELECT email, maintenance, breakdowns FROM plant.notification_prefs")
    return [{"email": row["email"] or "", "maintenance": bool(row["maintenance"]), "breakdowns": bool(row["breakdowns"])}
            for row in rows]


def unread_count(email):
    key = access.email_key(email)
    row = sql.one(
        "SELECT count(*) AS n FROM plant.notifications WHERE read_at IS NULL AND lower(btrim(email)) = %s",
        (key,),
    )
    return int(row["n"]) if row else 0


def _grant(email):
    return sql.one(
        """
        SELECT id, email, role, screens, active
        FROM plant.access_grants
        WHERE lower(btrim(email)) = %s
        """,
        (access.email_key(email),),
    )


@sql.in_transaction
def resolve(user):
    """The signed-in user's access. The first account, or the next one when no administrator is active, becomes administrator."""
    email = _user_email(user)
    if not email:
        raise anvil.server.PermissionDenied("Sign in to continue.")
    if user["enabled"] is False:
        raise anvil.server.PermissionDenied("This account is deactivated.")
    profiles = _profiles()
    row = _grant(email)
    active_admin = any(profile["role"] == "administrator" and profile["active"] for profile in profiles)
    if row is None:
        role = "administrator" if not active_admin else "observer"
        row = sql.one(
            """
            INSERT INTO plant.access_grants (email, role, screens, active)
            VALUES (%s, %s, %s, true)
            RETURNING id, email, role, screens, active
            """,
            (email, role, sql.as_json({"ids": access.default_ids(role)})),
        )
        write_audit([audit.user_row(email, email, _now(), "Signed in as %s" % access.ROLE_LABEL[role], {"role": [None, role]})])
    elif row["active"] is False:
        raise anvil.server.PermissionDenied("This account is deactivated.")
    elif not active_admin and row["role"] != "administrator":
        previous = row["role"] or "observer"
        sql.execute(
            "UPDATE plant.access_grants SET role = 'administrator', active = true, screens = %s WHERE id = %s",
            (sql.as_json({"ids": access.default_ids("administrator")}), row["id"]),
        )
        row = _grant(email)
        write_audit([audit.user_row(email, email, _now(), "Became administrator because none was active",
                                    {"role": [previous, "administrator"]})])
    stored = None if row["role"] == "administrator" else _screens(row)
    return access.session_view(email, row["role"] or "observer", stored, unread_count(email))


def require(user):
    session = resolve(user)
    return session


def write_audit(entries):
    for entry in entries or []:
        sql.execute(
            """
            INSERT INTO plant.audit_events (at, email, record_table, record, action, summary, changes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                records.parse_moment(entry.get("at")) or datetime.datetime.now(datetime.timezone.utc),
                entry.get("email") or "",
                entry.get("recordTable") or "",
                entry.get("record") or "",
                entry.get("action") or "",
                entry.get("summary") or "",
                sql.as_json(entry.get("changes") or {}),
            ),
        )


def history(kind="", code="", limit=80):
    table = ""
    if kind:
        table = next((name for name, label in audit.TABLE_KIND.items() if label == kind), kind)
    if code:
        found = sql.query(
            """
            SELECT at, email, record_table, record, action, summary, changes
            FROM plant.audit_events
            WHERE record_table = %s AND record = %s
            ORDER BY at DESC
            LIMIT %s
            """,
            (table, code, int(limit)),
        )
    else:
        found = sql.query(
            """
            SELECT at, email, record_table, record, action, summary, changes
            FROM plant.audit_events
            ORDER BY at DESC
            LIMIT %s
            """,
            (int(limit),),
        )
    rows = []
    for row in found:
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
        sql.execute(
            """
            INSERT INTO plant.notifications (email, kind, record, title, body, created_at, read_at)
            VALUES (%s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                entry.get("email") or "",
                entry.get("kind") or "",
                entry.get("record") or "",
                entry.get("title") or "",
                entry.get("body") or "",
                records.parse_moment(entry.get("createdAt")) or datetime.datetime.now(datetime.timezone.utc),
            ),
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
    rows = sql.query(
        """
        SELECT id, kind, record, title, body, created_at, read_at
        FROM plant.notifications
        WHERE lower(btrim(email)) = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (key, int(limit)),
    )
    return [{
        "id": row["id"],
        "kind": row["kind"] or "",
        "record": row["record"] or "",
        "title": row["title"] or "",
        "body": row["body"] or "",
        "at": records.moment_text(row["created_at"]),
        "read": row["read_at"] is not None,
    } for row in rows]


@sql.in_transaction
def mark_notifications(email):
    key = access.email_key(email)
    now = datetime.datetime.now(datetime.timezone.utc)
    sql.execute(
        "UPDATE plant.notifications SET read_at = %s WHERE read_at IS NULL AND lower(btrim(email)) = %s",
        (now, key),
    )


def notification_prefs(email):
    row = _pref_row(email)
    if row is None:
        return {"maintenance": False, "breakdowns": False}
    return {"maintenance": bool(row["maintenance"]), "breakdowns": bool(row["breakdowns"])}


def _pref_row(email):
    key = access.email_key(email)
    return sql.one(
        """
        SELECT id, email, maintenance, breakdowns
        FROM plant.notification_prefs
        WHERE lower(btrim(email)) = %s
        """,
        (key,),
    )


@sql.in_transaction
def save_notification_prefs(email, maintenance, breakdowns):
    row = _pref_row(email)
    if row is None:
        sql.execute(
            "INSERT INTO plant.notification_prefs (email, maintenance, breakdowns) VALUES (%s, %s, %s)",
            (email, bool(maintenance), bool(breakdowns)),
        )
    else:
        sql.execute(
            "UPDATE plant.notification_prefs SET maintenance = %s, breakdowns = %s WHERE id = %s",
            (bool(maintenance), bool(breakdowns), row["id"]),
        )
    return notification_prefs(email)


def list_users():
    profiles = {access.email_key(row["email"]): row for row in sql.query(
        "SELECT email, role, active, screens FROM plant.access_grants")}
    found = []
    for user in sql.query("SELECT email, enabled, last_login FROM app_tables.users"):
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


@sql.in_transaction
def save_access(actor, payload):
    session = resolve(actor)
    if session["role"] != "administrator":
        return {"error": "That needs an administrator."}
    email = (payload.get("email") or "").strip()
    user = sql.one("SELECT email, enabled FROM app_tables.users WHERE email = %s", (email,))
    if user is None:
        return {"error": "That user was not found."}
    role = payload.get("role") or ""
    if role not in access.ROLES:
        return {"error": "Choose a role."}
    active = str(payload.get("active") or "").lower() in ("yes", "true", "1")
    if not access.leaves_an_admin(_profiles(), email, role, active):
        return {"error": "Keep at least one active administrator."}
    screens = _split_screens(payload.get("screens"))
    row = _grant(email)
    before_role = row["role"] if row is not None else "observer"
    before_active = bool(row["active"]) if row is not None else True
    if row is None:
        sql.execute(
            "INSERT INTO plant.access_grants (email, role, active, screens) VALUES (%s, %s, %s, %s)",
            (email, role, active, sql.as_json({"ids": screens})),
        )
    else:
        sql.execute(
            "UPDATE plant.access_grants SET role = %s, active = %s, screens = %s WHERE id = %s",
            (role, active, sql.as_json({"ids": screens}), row["id"]),
        )
    sql.execute("UPDATE app_tables.users SET enabled = %s WHERE email = %s", (active, email))
    write_audit([audit.user_row(
        email, session["email"], _now(),
        "Set %s to %s%s" % (email, access.ROLE_LABEL[role], "" if active else ", deactivated"),
        {"role": [before_role, role], "active": [before_active, active], "screens": [None, screens]},
    )])
    return {"refresh": True}
