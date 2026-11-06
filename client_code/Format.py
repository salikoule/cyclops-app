"""Small HTML fragments for ids, status, and pills, and moments in local time."""

from datetime import datetime

import anvil.tz

from cyclops_app import Layout, Nav


def local(moment):
    """An ISO UTC moment from the server as a local datetime, or None."""
    try:
        parsed = datetime.strptime(str(moment or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=anvil.tz.tzutc()).astimezone(anvil.tz.tzlocal())


def utc(day, clock):
    """A local day and HH:MM as an ISO UTC moment; "" without a day; the bare day when the time is missing, which the server refuses."""
    if not day:
        return ""
    if not clock:
        return day.isoformat()
    try:
        hour, minute = [int(part) for part in str(clock).replace(".", ":").split(":")[:2]]
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=anvil.tz.tzlocal())
    except (TypeError, ValueError):
        return day.isoformat()
    return moment.astimezone(anvil.tz.tzutc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def when(moment, fallback="—"):
    shown = local(moment)
    return shown.strftime("%d/%m/%y %H:%M") if shown else fallback


def day(value, fallback="—"):
    text = str(value or "")
    if len(text) < 10:
        return fallback
    return "%s/%s/%s" % (text[8:10], text[5:7], text[0:4])


def trim(value):
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return str(int(number))
    return ("%.4f" % number).rstrip("0").rstrip(".")


def clip(value, limit=120):
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def plural(count, one, many=None):
    many = many or (one + "s")
    return "%s %s" % (count, one if count == 1 else many)


def text(value, fallback="—"):
    if value is None or value == "":
        return fallback
    return Layout.esc(value)


def id_tag(kind, code):
    return '<span class="cy-id cy-%s">%s</span>' % (kind, Layout.esc(code or ""))


def status(label, tone):
    return '<span class="cy-st cy-%s">%s</span>' % (tone or "muted", Layout.esc(label or ""))


def flag(label, tone=""):
    extra = (" cy-" + tone) if tone else ""
    return '<span class="cy-flag%s">%s</span>' % (extra, Layout.esc(label or ""))


def link(kind, code, label=None):
    shown = code if label is None else label
    return '<a href="javascript:void(0)" data-nav="%s">%s</a>' % (
        Layout.esc(Nav.path(kind, code)),
        Layout.esc(shown),
    )


def pill(kind, code, label):
    return '<a class="cy-pill cy-%s" href="javascript:void(0)" data-nav="%s">%s</a>' % (
        kind,
        Layout.esc(Nav.path(kind, code)),
        Layout.esc(label),
    )


def pills(items, kind, limit=4):
    items = list(items or [])
    if not items:
        return '<span class="cy-empty">—</span>'
    shown = items[:limit]
    more = len(items) - len(shown)
    html = "".join('<span class="cy-pill cy-%s">%s</span>' % (kind, Layout.esc(item)) for item in shown)
    if more:
        html += '<span class="cy-pill cy-more">+%s</span>' % more
    return '<span class="cy-pills">%s</span>' % html


def who(names):
    return "".join('<span class="cy-who cy-%s">%s</span>' % (name, Layout.esc(name)) for name in (names or []))
