"""In-app alerts for stoppages.

A cause with ``planned`` set is maintenance. A cause with neither ``planned`` nor ``changeover``
is a breakdown. A changeover is neither, so it does not alert.
"""


def kind_for(before, after, cause):
    """The alert this save should raise, or "" when it should stay quiet.

    A new stoppage alerts when its cause qualifies. A later edit alerts only when the cause changes
    to one that qualifies, so saving the same stoppage again does not repeat the alert.
    """
    if not after or not cause:
        return ""
    if cause.get("planned"):
        kind = "maintenance"
    elif cause.get("changeover"):
        return ""
    else:
        kind = "breakdown"
    if before is None:
        return kind
    if (before.get("causeId") or "") != (after.get("causeId") or ""):
        return kind
    return ""


def _wanted(pref, kind):
    if kind == "maintenance":
        return bool(pref.get("maintenance"))
    if kind == "breakdown":
        return bool(pref.get("breakdowns"))
    return False


def for_users(kind, stop, cause, prefs, when):
    """One notification dict per user who opted into ``kind``. No row when nobody opted in."""
    if kind not in ("maintenance", "breakdown") or not stop:
        return []
    cause_name = (cause or {}).get("name") or "Stoppage"
    machine = stop.get("machineId") or ""
    title = "Planned maintenance" if kind == "maintenance" else "Breakdown"
    body = "%s on %s. %s" % (cause_name, machine or "a machine", (stop.get("description") or "").strip())
    body = body.strip()
    notes = []
    for pref in prefs or []:
        if not pref.get("email") or not _wanted(pref, kind):
            continue
        notes.append({
            "email": pref["email"],
            "kind": kind,
            "record": stop.get("id") or "",
            "title": title,
            "body": body,
            "createdAt": when,
        })
    return notes
