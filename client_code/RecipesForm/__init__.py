from ._anvil_designer import RecipesFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class RecipesForm(RecipesFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "recipe", routing_context)
