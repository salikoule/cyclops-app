import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
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


class StructureRoute(AppPage):
    path = "/structure"
    form = "StructureForm"


class ProductsRoute(AppPage):
    path = "/products"
    form = "ProductsForm"


class ProductRoute(AppPage):
    path = "/products/:code"
    form = "ProductForm"


class MoldsRoute(AppPage):
    path = "/molds"
    form = "MoldsForm"


class MoldRoute(AppPage):
    path = "/molds/:code"
    form = "MoldForm"


class PressesRoute(AppPage):
    path = "/presses"
    form = "PressesForm"


class PressRoute(AppPage):
    path = "/presses/:code"
    form = "PressForm"


class RecipesRoute(AppPage):
    path = "/recipes"
    form = "RecipesForm"


class RecipeRoute(AppPage):
    path = "/recipes/:code"
    form = "RecipeForm"


class MaterialsRoute(AppPage):
    path = "/materials"
    form = "MaterialsForm"


class MaterialRoute(AppPage):
    path = "/materials/:code"
    form = "MaterialForm"


class ColorsRoute(AppPage):
    path = "/colors"
    form = "ColorsForm"


class ColorRoute(AppPage):
    path = "/colors/:code"
    form = "ColorForm"
