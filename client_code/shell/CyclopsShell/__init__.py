from ._anvil_designer import CyclopsShellTemplate
from anvil import *
import anvil.server
import anvil.users
from craftify_library.Startup import configure as configure_craftify_client
from craftify_library.CustomComponents.AccountMenu import AccountMenu
from craftify_library.CustomComponents.SearchPalette import SearchPalette
from craftify_library.CustomComponents.SettingsOverlay import SettingsOverlay
from craftify_library.CraftifyRouting import NavLink, add_event_handler, get_routing_context, navigate
from cyclops_app.session import Data
from cyclops_app.ui import Format, Layout, Nav

NAV = (
    ("Live floor", "floor", "fa:gauge-high", True),
    ("Overview", "overview", "fa:table-cells", True),
    ("Performance", "performance", "fa:chart-line", False),
    "Records",
    ("Items", "item", "fa:box", False),
    ("Molds", "mold", "fa:cubes", False),
    ("Machines", "machine", "fa:industry", False),
    ("Recipes", "recipe", "fa:bowl-food", False),
    "Operations",
    ("Orders", "order", "fa:clipboard-list", False),
    ("Production", "run", "fa:play", False),
    ("Stoppages", "stoppage", "fa:wrench", False),
    ("Changeovers", "changeover", "fa:arrow-right-arrow-left", False),
    ("Lots", "lot", "fa:barcode", False),
    "Setup",
    ("Configure", "configure", "fa:list-check", False),
    ("Notifications", "notify", "fa:bell", True),
    ("Audit log", "history", "fa:clock-rotate-left", True),
    ("Users", "users", "fa:users", True),
)

BRAND = (
    '<div class="nav-brand bc-brand cy-brand">'
    '<img class="cy-brand-logo" src="_/theme/cyclops-logo.png" alt="Cyclops">'
    '<div class="nav-brand-text bc-brand-text"><span>Production records</span></div>'
    "</div>"
)

_ERRORS = False


def _search(text):
    hits = anvil.server.call_s("cyclops_search", text) or []
    return [
        {
            "id": hit.get("id"),
            "title": hit.get("label"),
            "badge": hit.get("id"),
            "badge_class": "cy-id cy-%s" % hit.get("kind"),
            "kind": Nav.LABEL.get(hit.get("kind"), ""),
            "path": Nav.path(hit.get("kind"), hit.get("id")),
        }
        for hit in hits
    ]


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
        self._search = SearchPalette(
            search=_search,
            placeholder="Find an item, mold, machine, recipe, order, run, or lot",
            recent_key="cyclops",
        )
        self._search.set_event_handler("select", self._on_search_select)
        self.add_component(self._search)

    def _on_search_select(self, hit, **event_args):
        Nav.open_path(hit.get("path"))

    def _build_nav(self):
        self.menu_panel.clear()
        self.menu_panel.add_component(Layout.html(BRAND), full_width_row=True)
        self.menu_panel.add_component(self._search.trigger(), full_width_row=True)
        try:
            allowed = set((Data.session().get("screens") or []))
            unread = Data.session().get("unread") or 0
        except Exception:
            allowed, unread = set(), 0
        pending = None
        for item in NAV:
            if isinstance(item, str):
                pending = item
                continue
            text, kind, icon, exact = item
            if kind not in allowed:
                continue
            if pending:
                self.menu_panel.add_component(Layout.html('<div class="cf-nav-group">%s</div>' % Layout.esc(pending)), full_width_row=True)
                pending = None
            if kind == "notify" and unread:
                text = "Notifications (%s)" % unread
            self.menu_panel.add_component(NavLink(
                text=text,
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
        from cyclops_app.account.AccountSettings import plant_alerts_panel
        from cyclops_app.account.Security import account_mfa_panel

        self._settings = SettingsOverlay(
            app_name="Cyclops",
            app_version="1.1",
            app_description="Production records for the injection floor.",
            default_section="plant",
            extra_sections=(
                {"id": "plant", "label": "Plant data", "build": _plant_section},
                {"id": "alerts", "label": "Plant alerts", "build": plant_alerts_panel},
            ),
            hidden_sections=("notifications", "ai", "data"),
            account_mfa_build=account_mfa_panel,
        )
        self.add_component(self._settings)
        self._settings.set_event_handler("profile_photo_changed", self._on_account_identity)
        self._settings.set_event_handler("display_name_changed", self._on_account_identity)

    def _on_account_identity(self, **event_args):
        footer = getattr(self, "footer_panel", None)
        if footer is None:
            return
        for component in footer.get_components():
            refresh = getattr(component, "refresh_identity", None) or getattr(component, "refresh_avatar", None)
            if callable(refresh):
                refresh()
                return

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
        Data.invalidate_session()
        navigate(path="/login")

    def _on_router_navigate(self, routing_context=None, **event_args):
        self._search.close()
        try:
            Data.session(force=True)
        except Exception:
            pass
        self._build_nav()
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
