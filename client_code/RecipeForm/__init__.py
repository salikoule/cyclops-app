from ._anvil_designer import RecipeFormTemplate
from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
from cyclops_app.Pages import mount_detail


class RecipeForm(RecipeFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "recipe", routing_context)
