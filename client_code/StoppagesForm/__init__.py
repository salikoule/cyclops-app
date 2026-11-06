from ._anvil_designer import StoppagesFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class StoppagesForm(StoppagesFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "stoppage", routing_context)
