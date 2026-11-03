from ._anvil_designer import OverviewFormTemplate
from anvil import *
from cyclops_app.Pages import mount_overview


class OverviewForm(OverviewFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_overview(self, routing_context)
