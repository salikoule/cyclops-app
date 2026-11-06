from ._anvil_designer import CyclopsShellTemplate
from anvil import *
import anvil.server
import anvil.users
from craftify_library.Startup import configure as configure_craftify_client
from craftify_library.CustomComponents.AccountMenu import AccountMenu
from craftify_library.CustomComponents.SettingsOverlay import SettingsOverlay
from craftify_library.CraftifyRouting import NavLink, add_event_handler, get_routing_context, navigate
from cyclops_app import Format, Layout, Nav

NAV = (
    ("Overview", "overview", "fa:table-cells", True),
    None,
    ("Items", "item", "fa:box", False),
    ("Molds", "mold", "fa:cubes", False),
    ("Machines", "machine", "fa:industry", False),
    ("Recipes", "recipe", "fa:sliders", False),
    None,
    ("Orders", "order", "fa:clipboard-list", False),
    ("Production", "run", "fa:play", False),
    ("Stoppages", "stoppage", "fa:wrench", False),
    ("Lots", "lot", "fa:barcode", False),
    None,
    ("Configure", "configure", "fa:list-check", False),
)

BRAND = (
    '<div class="nav-brand bc-brand">'
    '<div class="nav-brand-mark bc-brand-mark">CY</div>'
    '<div class="nav-brand-text bc-brand-text"><strong>Cyclops</strong><span>Production records</span></div>'
    "</div>"
)

_ERRORS = False


def _shortcut():
    from anvil.js.window import navigator
    return "⌘K" if "Mac" in str(navigator.platform or "") else "Ctrl K"


def _plant_section():
    try:
        status = anvil.server.call("cyclops_data_status") or {}
    except Exception as error:
        return Layout.note("The data status could not be loaded: %s" % error, "warn")
    counted = status.get("counts") or {}
    pairs = (
        ("Imported from", status.get("source") or "—"),
        ("Records", "%s items · %s molds · %s machines · %s recipes" % (
            counted.get("items"), counted.get("molds"), counted.get("machines"), counted.get("recipes"))),
        ("Production", "%s orders · %s runs · %s lots" % (
            counted.get("production_orders"), counted.get("production_runs"), counted.get("lots"))),
        ("Stoppages", "%s logged · %s h of downtime" % (counted.get("stoppages") or 0, Format.trim(counted.get("downtimeHours")) or "0")),
    )
    facts = "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (Layout.esc(label), Layout.esc(value)) for label, value in pairs)
    return Layout.stack(
        Layout.html('<div><h3>Plant data</h3><p class="cs-lead">Cyclops is the plant record: items, molds, machines, recipes, and the production log with its lots. Shifts, causes, and categories are on the Configure page.</p></div>'),
        Layout.html('<dl class="bc-dl cy-dl">%s</dl>' % facts),
        Layout.note("Every page reads the data tables directly, so rows edited in the Anvil Data Tables view show on the next page load. To load the workbook again, run scripts/import_workbook.py with the server Uplink key. It replaces every record."),
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
        """Search lives in a pop-up opened from the sidebar button or Ctrl/Cmd+K, so no top bar is needed."""
        self._search = TextBox(placeholder="Find an item, mold, machine, recipe, order, run, or lot")
        self._search.set_event_handler("change", self._schedule_search)
        self._hits = HtmlTemplate(
            html=(
                '<div class="cy-palette" anvil-name="root"><div class="cy-search">'
                '<div class="cy-search-box" anvil-slot="box"></div>'
                '<div class="cy-hits" anvil-name="hits"></div>'
                '<div class="cy-palette-keys">↑ ↓ to move · Enter to open · Esc to close</div>'
                "</div></div>"
            )
        )
        self._hits.add_component(self._search, slot="box")
        self._active = -1
        root = self._hits.dom_nodes["root"]

        def on_click(event):
            target = getattr(event, "target", None)
            if target is None:
                return
            if target == root:
                self.close_search()
                return
            node = Layout.closest(target, "[data-nav]")
            if node is None:
                return
            event.preventDefault()
            self._open_hit(node)

        def on_key(event):
            key = getattr(event, "key", "")
            if key == "Escape":
                self.close_search()
            elif key in ("ArrowDown", "ArrowUp"):
                event.preventDefault()
                self._move_active(1 if key == "ArrowDown" else -1)
            elif key == "Enter":
                event.preventDefault()
                links = self._hit_links()
                if 0 <= self._active < len(links):
                    self._open_hit(links[self._active])
                else:
                    self._run_search()

        def on_global(event):
            if (getattr(event, "metaKey", False) or getattr(event, "ctrlKey", False)) and str(getattr(event, "key", "")).lower() == "k":
                event.preventDefault()
                self.open_search()

        from anvil.js.window import document
        root.addEventListener("click", on_click)
        root.addEventListener("keydown", on_key)
        document.addEventListener("keydown", on_global)
        self.add_component(self._hits)

    def open_search(self, *args):
        self._search.text = ""
        self._clear_hits()
        self._hits.dom_nodes["root"].classList.add("open")
        self._search.focus()

    def close_search(self):
        self._hits.dom_nodes["root"].classList.remove("open")
        self._clear_hits()

    def _open_hit(self, node):
        path = Layout.attr(node, "data-nav")
        self.close_search()
        Nav.open_path(path)

    def _hit_links(self):
        return list(self._hits.dom_nodes["hits"].querySelectorAll("a[data-nav]"))

    def _move_active(self, step):
        links = self._hit_links()
        if not links:
            return
        self._active = (self._active + step) % len(links)
        for index, link in enumerate(links):
            if index == self._active:
                link.classList.add("is-active")
                link.scrollIntoView({"block": "nearest"})
            else:
                link.classList.remove("is-active")

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
        self._active = -1
        self._move_active(1)

    def _clear_hits(self):
        self._active = -1
        node = self._hits.dom_nodes["hits"]
        node.innerHTML = ""
        node.classList.remove("open")

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
        find = Layout.html(
            '<a class="cy-find" anvil-name="root" href="javascript:void(0)" data-nav-label="Search" aria-label="Search">'
            '<i class="fa fa-magnifying-glass"></i><span class="link-text">Search</span><kbd>%s</kbd></a>' % _shortcut()
        )
        find.dom_nodes["root"].addEventListener("click", self.open_search)
        self.menu_panel.add_component(find, full_width_row=True)
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
        self.close_search()
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
