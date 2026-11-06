from ._anvil_designer import ConfigureFormTemplate
from anvil import *
from cyclops_app.Pages import mount_configure


class ConfigureForm(ConfigureFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_configure(self, routing_context)
