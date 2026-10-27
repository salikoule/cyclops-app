from ._anvil_designer import CyclopsShellTemplate
from anvil import *
import anvil.server
import anvil.users
from craftify_library.Startup import configure as configure_craftify_client
from craftify_library.CustomComponents.AccountMenu import AccountMenu
from craftify_library.CustomComponents.SettingsOverlay import SettingsOverlay
from craftify_library.CraftifyRouting import NavLink, add_event_handler, navigate
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


def _about():
    return Layout.stack(
        Layout.note("Cyclops is the plant record: product, mold, press, recipe, raw material, and color."),
        Layout.note("A recipe is one way of running a mold on a press. The overview shows the floor board and the gaps that still block a schedule."),
    )


class CyclopsShell(CyclopsShellTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        self._install_errors()
        configure_craftify_client()
        self._build_search()
        self._build_nav()
        self._build_footer()
        self._build_settings()
        add_event_handler("navigate", self._on_router_navigate)

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

        try:
            self._hits.dom_nodes["root"].addEventListener("click", on_click)
        except Exception:
            pass
        self.title_panel.clear()
        self.title_panel.add_component(self._hits, full_width_row=True)

    def _schedule_search(self, **event_args):
        try:
            from anvil.js.window import setTimeout
            setTimeout(self._run_search, 220)
        except Exception:
            self._run_search()

    def _run_search(self, *args):
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
            app_version="1.0",
            app_description="Production records.",
            default_section="plant",
            extra_sections=({"id": "plant", "label": "Plant", "build": _about},),
        )
        self.add_component(self._settings)

    def _on_settings(self, section=None, **event_args):
        self._settings.open(section or event_args.get("section") or "plant")

    def _on_logout(self, **event_args):
        try:
            anvil.users.logout()
        except Exception:
            pass
        navigate(path="/login")

    def _on_router_navigate(self, **event_args):
        self._clear_hits()
        self._build_nav()
