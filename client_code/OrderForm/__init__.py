from ._anvil_designer import OrderFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class OrderForm(OrderFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "order", routing_context)
