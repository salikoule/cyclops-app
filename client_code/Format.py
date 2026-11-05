import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
"""Small HTML fragments for ids, status, and pills."""

from cyclops_app import Layout, Nav


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
