from ._anvil_designer import OverviewFormTemplate
from anvil import *
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
from cyclops_app.Pages import mount_overview


class OverviewForm(OverviewFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_overview(self, routing_context)
