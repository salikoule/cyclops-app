from ._anvil_designer import MachineFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class MachineForm(MachineFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "machine", routing_context)
