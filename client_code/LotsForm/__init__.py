from ._anvil_designer import LotsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class LotsForm(LotsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "lot", routing_context)
