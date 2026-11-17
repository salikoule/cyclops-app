"""The screen controller. Routes call the mount functions."""

import anvil.server
from anvil import *
from anvil.js import window
from craftify_library.CraftifyUtils import dialogs

from cyclops_app.session import Data
from cyclops_app.ui import Editor, Layout, Nav
from cyclops_app.ui.tabs import tab_bar

from .admin import Admin
from .common import CONFIRM, DIRECT
from .plant import Plant
from .record import Record


class Screen(Plant, Record, Admin):
    def __init__(self, form, kind, code, ctx):
        self.form = form
        self.kind = kind
        self.code = code
        self.query = Nav.query(ctx)
        self.tab = self.query.get("tab") or ""
        self.data = None

    def render(self):
        if self.kind == "overview":
            self._overview()
        elif self.kind == "floor":
            self._floor()
        elif self.kind == "structure":
            self._structure()
        elif self.kind == "configure":
            self._configure_page()
        elif self.kind == "users":
            self._users()
        elif self.kind == "history":
            self._history_page()
        elif self.kind == "notify":
            self._notifications()
        elif self.code:
            self._detail()
        else:
            self._list()

    def show(self, *children):
        """Replace the page. A form with ``content`` keeps its other components, such as a refresh timer."""
        target = getattr(self.form, "content", None) or self.form
        target.clear()
        kept = [child for child in children if child is not None and child != ""]
        target.add_component(Layout.stack(*kept), full_width_row=True)

    def show_tabbed(self, top, tabs):
        """``top`` stays above the tab bar; ``tabs`` are (key, label, count or None, build), and only the open tab is built.
        The open tab is kept in the address (?tab=) so a refresh or a shared link opens it again."""
        tabs = [tab for tab in tabs if tab]
        if self.code and self.kind in ("item", "mold", "machine", "recipe", "order", "run", "stoppage", "lot"):
            tabs = list(tabs) + [("history", "Audit", None, lambda: [self._record_history()])]
        if not tabs:
            self.show(*top)
            return
        if self.tab not in [tab[0] for tab in tabs]:
            self.tab = tabs[0][0]
        holder = Layout.stack()

        def fill():
            holder.clear()
            build = next(tab[3] for tab in tabs if tab[0] == self.tab)
            parts = [part for part in build() if part is not None]
            if len(parts) == 1 and "card" in getattr(parts[0], "dom_nodes", {}):
                parts[0].dom_nodes["title"].style.display = "none"
            for part in parts:
                Layout.add(holder, part)

        def on_select(key):
            self.tab = key
            url = window.URL(window.location.href)
            url.searchParams.set("tab", key)
            window.history.replaceState(window.history.state, "", url.toString())
            fill()

        bar = tab_bar([(key, label, count) for key, label, count, _build in tabs], self.tab, on_select)
        fill()
        self.show(*(list(top) + [bar, holder]))

    def act(self, action, **extra):
        def handler(**event_args):
            self.handle(action, extra)
        return handler

    def on_html(self, mode, node):
        if mode == "nav":
            Nav.open_path(Layout.attr(node, "data-nav"))
            return
        self.handle(Layout.attr(node, "data-action"), {
            "gap": Layout.attr(node, "data-gap"),
            "route": Layout.attr(node, "data-route"),
            "index": Layout.attr(node, "data-index"),
            "item": Layout.attr(node, "data-item"),
        })

    def handle(self, action, dataset):
        if action not in ("open-gap", "tab", "") and not Data.can_write():
            Notification("You have read-only access.", style="warning", timeout=4).show()
            return
        if action in ("log-shift", "close-shift"):
            card = next((entry for entry in (self.data or {}).get("machines") or [] if entry.get("id") == dataset.get("item")), None)
            if card is None:
                return
            Editor.open_editor(self, "log-shift", {"row": card, "close": action == "close-shift"})
            return
        if action == "open-gap":
            Nav.go(dataset.get("route"), query={"gap": dataset.get("gap") or ""})
            return
        if action == "edit-input-row":
            entry = next((entry for entry in (self.data or {}).get("inputs") or [] if entry.get("id") == dataset.get("item")), None)
            if entry is not None:
                Editor.open_editor(self, "edit-input", {"row": entry})
            return
        if action in DIRECT:
            ask = CONFIRM.get(action)
            if ask and not dialogs.confirm(ask[1], title=ask[0], confirm_text=ask[2], danger=ask[3]):
                return
            problem = self.apply(action, {"index": dataset.get("index") or "", "item": dataset.get("item") or ""})
            if problem:
                Notification(problem, style="warning", timeout=5).show()
            return
        if not Editor.open_editor(self, action, dataset):
            Notification("That edit is not available on this record.", style="warning").show()

    def apply(self, action, payload, close=None):
        """Run an edit. Returns an error message, or None once the page shows the result."""
        body = {"contextKind": self.kind or "", "contextId": self.code or ""}
        body.update(payload or {})
        try:
            result = anvil.server.call("cyclops_apply", action, body)
        except Exception as error:
            return str(error) or "The change could not be saved."
        if not result:
            return "The change could not be saved."
        if result.get("error"):
            return result["error"]
        gaps = result.get("gaps") or []
        if gaps:
            Notification("Saved. Still open: %s." % "; ".join(gaps), style="warning", timeout=6).show()
        if close is not None:
            close()
        Data.invalidate()
        redirect = result.get("redirect") or {}
        if redirect.get("kind"):
            Nav.go(redirect["kind"], redirect.get("code"))
            return None
        self.render()
        return None

    def block(self, markup):
        return Layout.interactive(markup, self.on_html)

def mount_overview(form, ctx):
    Screen(form, "overview", None, ctx).render()


def mount_structure(form, ctx):
    Screen(form, "structure", None, ctx).render()


def mount_configure(form, ctx):
    Screen(form, "configure", Nav.params(ctx).get("code"), ctx).render()


def mount_list(form, kind, ctx):
    Screen(form, kind, None, ctx).render()


def mount_detail(form, kind, ctx):
    Screen(form, kind, Nav.params(ctx).get("code"), ctx).render()


def mount_floor(form, ctx):
    Screen(form, "floor", None, ctx).render()


def mount_users(form, ctx):
    Screen(form, "users", None, ctx).render()


def mount_history(form, ctx):
    Screen(form, "history", None, ctx).render()


def mount_notifications(form, ctx):
    Screen(form, "notify", None, ctx).render()

