from ._anvil_designer import MoldFormTemplate
from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
from cyclops_app.Pages import mount_detail


class MoldForm(MoldFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "mold", routing_context)
