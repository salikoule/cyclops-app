from ._anvil_designer import ColorsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class ColorsForm(ColorsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "color", routing_context)
