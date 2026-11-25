import anvil.server
import anvil.users
from craftify_library.CraftifyRouting import AuthenticatedShellRoute, Redirect, Route

from cyclops_app.session import Data


class AppPage(AuthenticatedShellRoute):
    template = "shell.CyclopsShell"
    login_path = "/login"
    screen = ""
    cache_form = True

    def before_load(self, **loader_args):
        AuthenticatedShellRoute.before_load(self, **loader_args)
        if not self.screen:
            return
        try:
            session = Data.session(force=True)
        except Exception as error:
            if "deactivated" in str(error).lower():
                anvil.users.logout()
                raise Redirect(path="/login")
            raise
        if self.screen not in (session.get("screens") or []):
            raise Redirect(path=session.get("home") or "/account")


class LoginRoute(Route):
    path = "/login"
    form = "shell.AppStartup"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is not None:
            raise Redirect(path="/")


class RootRoute(Route):
    path = "/"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        try:
            home = Data.session(force=True).get("home") or "/floor"
        except Exception as error:
            if "deactivated" in str(error).lower():
                anvil.users.logout()
                raise Redirect(path="/login")
            raise
        raise Redirect(path=home)


class ConfigureRoute(Route):
    path = "/configure"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        raise Redirect(path="/configure/shifts")


class AccountRoute(Route):
    path = "/account"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        raise Redirect(path="/floor", query={"settings": "account"})


def _quiet_before_load(self, **loader_args):
    """The floor reloads on its own. Its sign-in check should not cover the board with a spinner."""
    with anvil.server.no_loading_indicator:
        AppPage.before_load(self, **loader_args)


def _page(name, path, screen, form="pages.PageForm", mode="", key=""):
    """One route class. ``mode`` is list, detail, or page; ``key`` is the record kind or the page name."""
    attrs = {"path": path, "form": form, "screen": screen, "mode": mode}
    if form == "live.FloorForm":
        attrs["cache_form"] = False
        attrs["before_load"] = _quiet_before_load
    if mode in ("list", "detail"):
        attrs["kind"] = key
    elif mode == "page":
        attrs["page"] = key
    globals()[name] = type(name, (AppPage,), attrs)


# Structure is gated by the overview screen: it is the same plant picture, drawn as a tree.
_page("FloorRoute", "/floor", "floor", form="live.FloorForm")
_page("OverviewRoute", "/overview", "overview", mode="page", key="overview")
_page("PerformanceRoute", "/performance", "performance", mode="page", key="performance")
_page("StructureRoute", "/structure", "overview", mode="page", key="structure")
_page("ItemsRoute", "/items", "item", mode="list", key="item")
_page("ItemRoute", "/items/:code", "item", mode="detail", key="item")
_page("MoldsRoute", "/molds", "mold", mode="list", key="mold")
_page("MoldRoute", "/molds/:code", "mold", mode="detail", key="mold")
_page("MachinesRoute", "/machines", "machine", mode="list", key="machine")
_page("MachineRoute", "/machines/:code", "machine", mode="detail", key="machine")
_page("RecipesRoute", "/recipes", "recipe", mode="list", key="recipe")
_page("RecipeRoute", "/recipes/:code", "recipe", mode="detail", key="recipe")
_page("OrdersRoute", "/orders", "order", mode="list", key="order")
_page("OrderRoute", "/orders/:code", "order", mode="detail", key="order")
_page("ProductionRoute", "/production", "run", mode="list", key="run")
_page("RunRoute", "/production/:code", "run", mode="detail", key="run")
_page("StoppagesRoute", "/stoppages", "stoppage", mode="list", key="stoppage")
_page("ChangeoversRoute", "/changeovers", "changeover", mode="list", key="changeover")
_page("LotsRoute", "/lots", "lot", mode="list", key="lot")
_page("LotRoute", "/lots/:code", "lot", mode="detail", key="lot")
_page("ConfigureSectionRoute", "/configure/:code", "configure", mode="page", key="configure")
_page("NotificationsRoute", "/notifications", "notify", mode="page", key="notify")
_page("HistoryRoute", "/history", "history", mode="page", key="history")
_page("UsersRoute", "/users", "users", mode="page", key="users")
