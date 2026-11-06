from ._anvil_designer import MachinesFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class MachinesForm(MachinesFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "machine", routing_context)
