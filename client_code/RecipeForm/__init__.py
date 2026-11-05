from ._anvil_designer import RecipeFormTemplate
from anvil import *
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
from cyclops_app.Pages import mount_detail


class RecipeForm(RecipeFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "recipe", routing_context)
