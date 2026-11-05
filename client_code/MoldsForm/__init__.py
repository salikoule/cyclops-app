from ._anvil_designer import MoldsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class MoldsForm(MoldsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "mold", routing_context)
