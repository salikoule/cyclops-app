"""Small HTML fragments for ids, status, and pills, and moments in local time."""

from datetime import datetime

import anvil.js
from anvil.js import window

from cyclops_app import Layout, Nav


def _naive(js_date):
    return datetime(js_date.getFullYear(), js_date.getMonth() + 1, js_date.getDate(), js_date.getHours(), js_date.getMinutes())


def local(moment):
    """An ISO UTC moment from the server as a naive local datetime, or None.

    Converted by the browser's Date, which applies the offset of that date; anvil.tz.tzlocal() applies today's offset to every date.
    """
    text = str(moment or "")
    if len(text) < 19 or text[10] != "T":
        return None
    try:
        stamp = window.Date.UTC(int(text[0:4]), int(text[5:7]) - 1, int(text[8:10]), int(text[11:13]), int(text[14:16]), int(text[17:19]))
    except (TypeError, ValueError):
        return None
    return _naive(anvil.js.new(window.Date, stamp))


def now():
    """The current local minute as a naive datetime."""
    return _naive(anvil.js.new(window.Date))


def utc(day, clock):
    """A local day and HH:MM as an ISO UTC moment; "" without a day; the bare day when the time is missing, which the server refuses."""
    if not day:
        return ""
    if not clock:
        return day.isoformat()
    try:
        hour, minute = [int(part) for part in str(clock).replace(".", ":").split(":")[:2]]
    except (TypeError, ValueError):
        return day.isoformat()
    return anvil.js.new(window.Date, day.year, day.month - 1, day.day, hour, minute).toISOString()[:19] + "Z"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _date_text(year, month, day_of_month):
    """Built by hand, without strptime or strftime month names: they can block in the browser, and table formatters must not."""
    return "%02d %s %d" % (day_of_month, _MONTHS[month - 1], year)


def when(moment, fallback="—"):
    shown = local(moment)
    if shown is None:
        return fallback
    return "%s, %02d:%02d" % (_date_text(shown.year, shown.month, shown.day), shown.hour, shown.minute)


def day(value, fallback="—"):
    text = str(value or "")
    try:
        return _date_text(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (TypeError, ValueError, IndexError):
        return fallback


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
