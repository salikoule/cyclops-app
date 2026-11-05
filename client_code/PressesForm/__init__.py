from ._anvil_designer import PressesFormTemplate
from anvil import *
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
from cyclops_app.Pages import mount_list


class PressesForm(PressesFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "press", routing_context)
