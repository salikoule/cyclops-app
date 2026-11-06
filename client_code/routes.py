import anvil.users
from craftify_library.CraftifyRouting import AuthenticatedShellRoute, Redirect, Route


class AppPage(AuthenticatedShellRoute):
    template = "CyclopsShell"
    login_path = "/login"


class LoginRoute(Route):
    path = "/login"
    form = "AppStartup"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is not None:
            raise Redirect(path="/overview")


class RootRoute(Route):
    path = "/"

    def before_load(self, **loader_args):
        if anvil.users.get_user() is None:
            raise Redirect(path="/login")
        raise Redirect(path="/overview")


class OverviewRoute(AppPage):
    path = "/overview"
    form = "OverviewForm"


class PerformanceRoute(AppPage):
    path = "/performance"
    form = "PerformanceForm"


class StructureRoute(AppPage):
    path = "/structure"
    form = "StructureForm"


class ItemsRoute(AppPage):
    path = "/items"
    form = "ItemsForm"


class ItemRoute(AppPage):
    path = "/items/:code"
    form = "ItemForm"


class MoldsRoute(AppPage):
    path = "/molds"
    form = "MoldsForm"


class MoldRoute(AppPage):
    path = "/molds/:code"
    form = "MoldForm"


class MachinesRoute(AppPage):
    path = "/machines"
    form = "MachinesForm"


class MachineRoute(AppPage):
    path = "/machines/:code"
    form = "MachineForm"


class RecipesRoute(AppPage):
    path = "/recipes"
    form = "RecipesForm"


class RecipeRoute(AppPage):
    path = "/recipes/:code"
    form = "RecipeForm"


class OrdersRoute(AppPage):
    path = "/orders"
    form = "OrdersForm"


class OrderRoute(AppPage):
    path = "/orders/:code"
    form = "OrderForm"


class ProductionRoute(AppPage):
    path = "/production"
    form = "ProductionForm"


class RunRoute(AppPage):
    path = "/production/:code"
    form = "RunForm"


class StoppagesRoute(AppPage):
    path = "/stoppages"
    form = "StoppagesForm"


class LotsRoute(AppPage):
    path = "/lots"
    form = "LotsForm"


class LotRoute(AppPage):
    path = "/lots/:code"
    form = "LotForm"


class ConfigureRoute(Route):
    path = "/configure"

    def before_load(self, **loader_args):
        raise Redirect(path="/configure/shifts")


class ConfigureSectionRoute(AppPage):
    path = "/configure/:code"
    form = "ConfigureForm"
