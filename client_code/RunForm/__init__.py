from ._anvil_designer import RunFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class RunForm(RunFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "run", routing_context)
