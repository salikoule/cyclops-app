from ._anvil_designer import PerformanceFormTemplate
from anvil import *
from cyclops_app.Performance import mount_performance


class PerformanceForm(PerformanceFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_performance(self, routing_context)
