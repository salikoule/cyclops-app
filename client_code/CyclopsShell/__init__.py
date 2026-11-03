from ._anvil_designer import CyclopsShellTemplate
from anvil import *
import anvil.server
import anvil.tz
import anvil.users
from craftify_library.Startup import configure as configure_craftify_client
from craftify_library.CustomComponents.AccountMenu import AccountMenu
from craftify_library.CustomComponents.SettingsOverlay import SettingsOverlay
from craftify_library.CraftifyRouting import NavLink, add_event_handler, get_routing_context, navigate
from craftify_library.CraftifyUtils import dialogs
from cyclops_app import Format, Layout, Nav

NAV = (
    ("Overview", "overview", "fa:table-cells", True),
    ("Structure", "structure", "fa:sitemap", True),
    None,
    ("Products", "product", "fa:box", False),
    ("Molds", "mold", "fa:cubes", False),
    ("Presses", "press", "fa:industry", False),
    ("Recipes", "recipe", "fa:sliders", False),
    ("Materials", "material", "fa:flask", False),
    ("Colors", "color", "fa:palette", False),
)

BRAND = (
    '<div class="nav-brand bc-brand">'
    '<div class="nav-brand-mark bc-brand-mark">CY</div>'
    '<div class="nav-brand-text bc-brand-text"><strong>Cyclops</strong><span>Production records</span></div>'
    "</div>"
)

_ERRORS = False


def _local(moment):
    try:
        return moment.astimezone(anvil.tz.tzlocal())
    except Exception:
        return moment


def _plant_section():
    try:
        status = anvil.server.call("cyclops_data_status") or {}
    except Exception as error:
        return Layout.note("The data status could not be loaded: %s" % error, "warn")
    counted = status.get("counts") or {}
    updated = status.get("updated")
    pairs = (
        ("Imported from", status.get("source") or "—"),
        ("Last saved", _local(updated).strftime("%d %b %Y, %H:%M") if updated else "—"),
        ("Revision", Format.trim(status.get("version")) or "0"),
        ("Records", "%s products · %s molds · %s presses · %s recipes" % (
            counted.get("products"), counted.get("molds"), counted.get("presses"), counted.get("recipes"))),
        ("Feeds", "%s materials · %s colors" % (counted.get("materials"), counted.get("colors"))),
        ("Stoppages", "%s logged · %s h of downtime" % (counted.get("stoppages") or 0, Format.trim(counted.get("downtimeHours")) or "0")),
    )
    facts = "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (Layout.esc(label), Layout.esc(value)) for label, value in pairs)

    def reload(**event_args):
        if not dialogs.confirm(
            "Rows edited by hand in the Anvil Data Tables view replace what the app holds now.",
            title="Reload from the data tables?",
            confirm_text="Reload",
        ):
            return
        try:
            counted_now = anvil.server.call("cyclops_reload_from_tables") or {}
        except Exception as error:
            Notification(str(error), style="danger", timeout=6).show()
            return
        from cyclops_app import Data
        Data.invalidate()
        Notification("Reloaded %s products and %s recipes." % (counted_now.get("products"), counted_now.get("recipes")), style="success").show()
        shell = get_open_form()
        if hasattr(shell, "refresh_counts"):
            shell.refresh_counts()

    return Layout.stack(
        Layout.html('<div><h3>Plant data</h3><p class="cs-lead">Cyclops is the plant record: product, mold, press, recipe, raw material, and color. A recipe is one way of running a mold on a press.</p></div>'),
        Layout.html('<dl class="bc-dl cy-dl">%s</dl>' % facts),
        Layout.note("To load the workbook again, run scripts/import_workbook.py with the server Uplink key. It replaces every record."),
        Layout.button("Reload from data tables", reload),
    )


class CyclopsShell(CyclopsShellTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        self._install_errors()
        configure_craftify_client()
        self._search_timer = None
        self._build_search()
        self._build_nav()
        self._build_footer()
        self._build_settings()
        add_event_handler("navigate", self._on_router_navigate)
        self._maybe_open_from_query(routing_context)

    def _install_errors(self):
        global _ERRORS
        if _ERRORS:
            return
        try:
            import anvil
            from craftify_library.CraftifyUtils.ErrorHandling import error_handler
            anvil.set_default_error_handler(error_handler)
            _ERRORS = True
        except Exception:
            pass

    def _build_search(self):
        self._search = TextBox(placeholder="Find a product, mold, press, recipe, material, or color")
        self._search.set_event_handler("change", self._schedule_search)
        self._search.set_event_handler("pressed_enter", self._run_search)
        self._hits = HtmlTemplate(
            html='<div class="cy-search" anvil-name="root"><div class="cy-search-box" anvil-slot="box"></div><div class="cy-hits" anvil-name="hits"></div></div>'
        )
        self._hits.add_component(self._search, slot="box")

        def on_click(event):
            target = getattr(event, "target", None)
            node = Layout.closest(target, "[data-nav]") if target is not None else None
            if node is None:
                return
            try:
                event.preventDefault()
            except Exception:
                pass
            Nav.open_path(Layout.attr(node, "data-nav"))
            self._search.text = ""
            self._clear_hits()

        def on_key(event):
            if getattr(event, "key", "") == "Escape":
                self._clear_hits()

        def on_outside(event):
            target = getattr(event, "target", None)
            if target is not None and Layout.closest(target, ".cy-search") is None:
                self._clear_hits()

        try:
            from anvil.js.window import document
            self._hits.dom_nodes["root"].addEventListener("click", on_click)
            self._hits.dom_nodes["root"].addEventListener("keydown", on_key)
            document.addEventListener("click", on_outside)
        except Exception:
            pass
        self.title_panel.clear()
        self.title_panel.add_component(self._hits, full_width_row=True)

    def _schedule_search(self, **event_args):
        try:
            from anvil.js.window import clearTimeout, setTimeout
            if self._search_timer is not None:
                clearTimeout(self._search_timer)
            self._search_timer = setTimeout(self._run_search, 260)
        except Exception:
            self._run_search()

    def _run_search(self, *args, **event_args):
        self._search_timer = None
        text = (self._search.text or "").strip()
        if len(text) < 2:
            self._clear_hits()
            return
        try:
            hits = anvil.server.call("cyclops_search", text)
        except Exception:
            return
        if (self._search.text or "").strip() != text:
            return
        self._render_hits(hits or [])

    def _render_hits(self, hits):
        node = self._hits.dom_nodes["hits"]
        if not hits:
            node.innerHTML = '<div class="cy-hit cy-muted">Nothing matches.</div>'
        else:
            rows = []
            for hit in hits:
                rows.append(
                    '<a href="javascript:void(0)" data-nav="%s">%s<span>%s</span><span class="cy-kind">%s</span></a>'
                    % (
                        Layout.esc(Nav.path(hit.get("kind"), hit.get("id"))),
                        Format.id_tag(hit.get("kind"), hit.get("id")),
                        Layout.esc(hit.get("label")),
                        Layout.esc(Nav.LABEL.get(hit.get("kind"), "")),
                    )
                )
            node.innerHTML = "".join(rows)
        node.classList.add("open")

    def _clear_hits(self):
        try:
            node = self._hits.dom_nodes["hits"]
            node.innerHTML = ""
            node.classList.remove("open")
        except Exception:
            pass

    def refresh_counts(self):
        self._build_nav()

    def _build_nav(self):
        counts = {}
        try:
            counts = anvil.server.call("cyclops_nav") or {}
        except Exception:
            counts = {}
        self.menu_panel.clear()
        self.menu_panel.add_component(Layout.html(BRAND), full_width_row=True)
        for item in NAV:
            if item is None:
                self.menu_panel.add_component(Layout.html('<div class="cy-nav-sep"></div>'), full_width_row=True)
                continue
            text, kind, icon, exact = item
            count = counts.get(Nav.COUNT_KEY.get(kind) or "")
            label = text if count is None else "%s · %s" % (text, count)
            self.menu_panel.add_component(NavLink(
                text=label,
                path=Nav.path(kind),
                icon=icon,
                exact_path=exact,
                align="left",
                icon_align="left",
                font_size=13,
                spacing_above="none",
                spacing_below="none",
            ))

    def _build_footer(self):
        email = ""
        try:
            email = anvil.server.call("craftify_current_user_email") or ""
        except Exception:
            email = ""
        self.footer_panel.clear()
        menu = AccountMenu(email=email or "")
        menu.set_event_handler("settings_click", self._on_settings)
        menu.set_event_handler("logout_click", self._on_logout)
        self.footer_panel.add_component(menu, full_width_row=True)

    def _build_settings(self):
        self._settings = SettingsOverlay(
            app_name="Cyclops",
            app_version="1.1",
            app_description="Production records for the injection floor.",
            default_section="plant",
            extra_sections=({"id": "plant", "label": "Plant data", "build": _plant_section},),
            hidden_sections=("notifications", "ai", "data"),
        )
        self.add_component(self._settings)

    def open_settings(self, section=None):
        if section in (None, "", "settings"):
            section = "plant"
        self._settings.open(section)

    def close_settings(self):
        self._settings.close()

    def _on_settings(self, section=None, **event_args):
        self.open_settings(section or event_args.get("section"))

    def _on_logout(self, **event_args):
        try:
            anvil.users.logout()
        except Exception:
            pass
        navigate(path="/login")

    def _on_router_navigate(self, routing_context=None, **event_args):
        self._clear_hits()
        self._maybe_open_from_query(routing_context)

    def _maybe_open_from_query(self, routing_context=None):
        ctx = routing_context
        if ctx is None:
            try:
                ctx = get_routing_context()
            except Exception:
                ctx = None
        section = (getattr(ctx, "query", None) or {}).get("settings")
        if section:
            self.open_settings(section)
