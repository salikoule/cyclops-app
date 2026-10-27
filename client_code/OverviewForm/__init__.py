from ._anvil_designer import OverviewFormTemplate
from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
from cyclops_app.Pages import mount_overview


class OverviewForm(OverviewFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_overview(self, routing_context)
