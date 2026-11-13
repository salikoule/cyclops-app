from ._anvil_designer import ExportFormTemplate
from craftify_library.CraftifyRouting import navigate


class ExportForm(ExportFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)

    def form_show(self, **event_args):
        navigate(path="/overview")
