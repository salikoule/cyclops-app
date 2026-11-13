from ._anvil_designer import HistoryFormTemplate
from anvil import *
from cyclops_app.Pages import mount_history


class HistoryForm(HistoryFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_history(self, routing_context)
