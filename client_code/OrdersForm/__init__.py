from ._anvil_designer import OrdersFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class OrdersForm(OrdersFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "order", routing_context)
