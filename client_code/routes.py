import anvil.users
from craftify_library.CraftifyRouting import AuthenticatedShellRoute, Redirect, Route

from cyclops_app import Data


class AppPage(AuthenticatedShellRoute):
    template = "CyclopsShell"
    login_path = "/login"
    screen = ""

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
    form = "AppStartup"

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


class FloorRoute(AppPage):
    path = "/floor"
    form = "FloorForm"
    screen = "floor"


class OverviewRoute(AppPage):
    path = "/overview"
    form = "OverviewForm"
    screen = "overview"


class PerformanceRoute(AppPage):
    path = "/performance"
    form = "PerformanceForm"
    screen = "performance"


class StructureRoute(AppPage):
    path = "/structure"
    form = "StructureForm"
    screen = "overview"


class ItemsRoute(AppPage):
    path = "/items"
    form = "ItemsForm"
    screen = "item"


class ItemRoute(AppPage):
    path = "/items/:code"
    form = "ItemForm"
    screen = "item"


class MoldsRoute(AppPage):
    path = "/molds"
    form = "MoldsForm"
    screen = "mold"


class MoldRoute(AppPage):
    path = "/molds/:code"
    form = "MoldForm"
    screen = "mold"


class MachinesRoute(AppPage):
    path = "/machines"
    form = "MachinesForm"
    screen = "machine"


class MachineRoute(AppPage):
    path = "/machines/:code"
    form = "MachineForm"
    screen = "machine"


class RecipesRoute(AppPage):
    path = "/recipes"
    form = "RecipesForm"
    screen = "recipe"


class RecipeRoute(AppPage):
    path = "/recipes/:code"
    form = "RecipeForm"
    screen = "recipe"


class OrdersRoute(AppPage):
    path = "/orders"
    form = "OrdersForm"
    screen = "order"


class OrderRoute(AppPage):
    path = "/orders/:code"
    form = "OrderForm"
    screen = "order"


class ProductionRoute(AppPage):
    path = "/production"
    form = "ProductionForm"
    screen = "run"


class RunRoute(AppPage):
    path = "/production/:code"
    form = "RunForm"
    screen = "run"


class StoppagesRoute(AppPage):
    path = "/stoppages"
    form = "StoppagesForm"
    screen = "stoppage"


class ChangeoversRoute(AppPage):
    path = "/changeovers"
    form = "ChangeoversForm"
    screen = "changeover"


class LotsRoute(AppPage):
    path = "/lots"
    form = "LotsForm"
    screen = "lot"


class LotRoute(AppPage):
    path = "/lots/:code"
    form = "LotForm"
    screen = "lot"


class ConfigureRoute(Route):
    path = "/configure"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        raise Redirect(path="/configure/shifts")


class ConfigureSectionRoute(AppPage):
    path = "/configure/:code"
    form = "ConfigureForm"
    screen = "configure"


class NotificationsRoute(AppPage):
    path = "/notifications"
    form = "NotificationsForm"
    screen = "notify"


class AccountRoute(Route):
    path = "/account"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        raise Redirect(path="/floor", query={"settings": "account"})


class HistoryRoute(AppPage):
    path = "/history"
    form = "HistoryForm"
    screen = "history"


class UsersRoute(AppPage):
    path = "/users"
    form = "UsersForm"
    screen = "users"
