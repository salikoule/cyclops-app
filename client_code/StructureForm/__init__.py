from ._anvil_designer import StructureFormTemplate
from anvil import *
from cyclops_app.Pages import mount_structure


class StructureForm(StructureFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_structure(self, routing_context)
        from craftify_library.CustomComponents.TimePicker import TimePicker
        picker = TimePicker(time="9:30", min_time="06:00", max_time="22:00")
        picker.set_event_handler("change", lambda **e: Notification("time=" + picker.time).show())
        self.add_component(picker)
