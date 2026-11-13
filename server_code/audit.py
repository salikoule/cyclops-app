"""Change rows for operational records. Nothing here reads the database."""

AUDITED = ("items", "molds", "machines", "recipes", "production_orders", "production_runs", "stoppages", "lots", "access")

TABLE_KIND = {
    "items": "item", "molds": "mold", "machines": "machine", "recipes": "recipe",
    "production_orders": "order", "production_runs": "run", "stoppages": "stoppage", "lots": "lot",
    "access": "users",
}

TABLE_LABEL = {
    "items": "Item", "molds": "Mold", "machines": "Machine", "recipes": "Recipe",
    "production_orders": "Order", "production_runs": "Run", "stoppages": "Stoppage", "lots": "Lot",
    "access": "User",
}

FIELD_LABEL = {
    "items": {
        "name": "Name", "erpCode": "ERP code", "type": "Type", "categoryId": "Category", "parentId": "Parent item",
        "uomId": "Unit", "status": "Status", "notes": "Notes",
    },
    "molds": {
        "name": "Name", "erpCode": "ERP code", "cavities": "Cavities", "shotWeight": "Shot weight", "status": "Status",
    },
    "machines": {
        "name": "Name", "typeId": "Type", "location": "Location", "floor": "Floor", "status": "Status", "attachedToId": "Attached to",
    },
    "recipes": {
        "itemId": "Item", "machineId": "Machine", "moldId": "Mold", "cycle": "Cycle time", "status": "Status",
        "standard": "Standard recipe", "inputs": "Inputs", "settings": "Machine settings", "temps": "Barrel temperatures",
        "comment": "Comment", "settingsNote": "Settings note",
    },
    "production_orders": {
        "itemId": "Item", "quantity": "Quantity", "dueDate": "Due date", "status": "Status", "erpOrderNo": "ERP order",
    },
    "production_runs": {
        "recipeId": "Recipe", "orderId": "Order", "machineId": "Machine", "shiftId": "Shift", "operatorId": "Operator",
        "startedAt": "Started", "endedAt": "Ended", "good": "Good pieces", "scrap": "Scrap", "inputs": "Consumed lots",
        "status": "Status",
    },
    "stoppages": {
        "machineId": "Machine", "runId": "Run", "causeId": "Cause", "startedAt": "Started", "endedAt": "Ended",
        "description": "Description",
    },
    "lots": {
        "itemId": "Item", "number": "Lot number", "quantity": "Quantity", "received": "Received", "origin": "Origin", "runId": "Run",
    },
    "access": {
        "role": "Role", "active": "Active", "screens": "Screens",
    },
}


def _plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return str(value)


def _format_scalar(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _input_lines(rows):
    lines = {}
    for entry in rows or []:
        code = entry.get("itemId") or entry.get("id") or ""
        if code:
            lines[code] = entry
    return lines


def _diff_inputs(old, new):
    """One line per input item whose share or presence changed."""
    before = _input_lines(old)
    after = _input_lines(new)
    lines = []
    for code in sorted(set(before) | set(after)):
        was, now = before.get(code), after.get(code)
        if was is None and now is not None:
            share = now.get("share")
            lines.append({
                "field": "inputs",
                "label": "Input %s added" % code,
                "before": "—",
                "after": "share %s" % _format_scalar(share),
            })
        elif was is not None and now is None:
            lines.append({
                "field": "inputs",
                "label": "Input %s removed" % code,
                "before": "share %s" % _format_scalar(was.get("share")),
                "after": "—",
            })
        else:
            old_share, new_share = was.get("share"), now.get("share")
            if old_share != new_share:
                lines.append({
                    "field": "inputs",
                    "label": "Input %s share" % code,
                    "before": _format_scalar(old_share),
                    "after": _format_scalar(new_share),
                })
    return lines


def field_changes(before, after):
    """``{field: [old, new]}`` for values that differ. The id is the record, not a change."""
    keys = set((before or {}).keys()) | set((after or {}).keys())
    changes = {}
    for key in sorted(keys):
        if key == "id":
            continue
        old, new = (before or {}).get(key), (after or {}).get(key)
        if old != new:
            changes[key] = [_plain(old), _plain(new)]
    return changes


def field_label(table, field):
    return (FIELD_LABEL.get(table) or {}).get(field) or field


def present_changes(table, changes):
    """Flat rows for the audit UI: label, before, after."""
    lines = []
    for field, pair in sorted((changes or {}).items()):
        old, new = (pair[0], pair[1]) if isinstance(pair, (list, tuple)) and len(pair) == 2 else (None, pair)
        if field == "inputs" and (isinstance(old, list) or isinstance(new, list)):
            lines.extend(_diff_inputs(old, new))
            continue
        if isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
            lines.append({
                "field": field,
                "label": field_label(table, field),
                "before": _format_scalar(old),
                "after": _format_scalar(new),
            })
        else:
            lines.append({
                "field": field,
                "label": field_label(table, field),
                "before": _format_scalar(old),
                "after": _format_scalar(new),
            })
    return lines


def _summary(action, code, changes, table=""):
    if action == "create":
        return "Created %s %s" % (TABLE_LABEL.get(table, "record"), code)
    if action == "delete":
        return "Deleted %s %s" % (TABLE_LABEL.get(table, "record"), code)
    labels = [field_label(table, field) for field in list(changes)[:6]]
    extra = "" if len(changes) <= 6 else " +%s more" % (len(changes) - 6)
    return "Updated %s" % (", ".join(labels) + extra)


def rows(before, after, dirty, email, when):
    """One audit row per created, updated, or deleted record in ``dirty``."""
    found = []
    for table, codes in (dirty or {}).items():
        if table not in AUDITED:
            continue
        old_rows = (before or {}).get(table) or {}
        new_rows = (after or {}).get(table) or {}
        for code in codes or []:
            old, new = old_rows.get(code), new_rows.get(code)
            if old is None and new is None:
                continue
            if old is None:
                action, changes = "create", field_changes({}, new)
            elif new is None:
                action, changes = "delete", {}
            else:
                changes = field_changes(old, new)
                if not changes:
                    continue
                action = "update"
            row = {
                "at": when,
                "email": email or "",
                "recordTable": table,
                "record": code,
                "kind": TABLE_KIND.get(table, ""),
                "place": "%s %s" % (TABLE_LABEL.get(table, table), code),
                "action": action,
                "summary": _summary(action, code, changes, table),
                "changes": changes,
                "lines": present_changes(table, changes),
            }
            found.append(row)
    return found


def user_row(email, actor, when, summary, changes):
    table = "access"
    plain = _plain(changes) or {}
    return {
        "at": when,
        "email": actor or "",
        "recordTable": table,
        "record": email or "",
        "kind": "users",
        "place": "User %s" % (email or ""),
        "action": "update",
        "summary": summary,
        "changes": plain,
        "lines": present_changes(table, plain),
    }
