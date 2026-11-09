from ._anvil_designer import ChangeoversFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class ChangeoversForm(ChangeoversFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "changeover", routing_context)
