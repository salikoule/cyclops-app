from ._anvil_designer import AppStartupTemplate
from anvil import *
import anvil.server
import anvil.users
from craftify_library.CraftifyLoginForm import CraftifyLoginForm


class CyclopsLoginForm(CraftifyLoginForm):
    def _sign_in(self, email, password):
        try:
            anvil.users.login_with_email(email, password, remember=True)
            return True
        except Exception as error:
            message = str(error) or ""
            if "not been enabled" not in message:
                self._show_error(message or "Login failed.")
                return False
        try:
            anvil.server.call("cyclops_enable_new_user", email)
            anvil.users.login_with_email(email, password, remember=True)
            return True
        except Exception as error:
            self._show_error(str(error) or "Login failed.")
            return False

    def login_btn_click(self, **event_args):
        self.error_label.visible = False
        email = (self.email_textbox.text or "").strip()
        password = self.password_textbox.text or ""
        if not email or not password:
            self._show_error("Enter your email and password.")
            return
        if self._sign_in(email, password):
            self._go_next()

    def signup_btn_click(self, **event_args):
        self.error_label.visible = False
        email = (self.email_textbox.text or "").strip()
        password = self.password_textbox.text or ""
        if not email or not password:
            self._show_error("Enter an email and password to create an account.")
            return
        try:
            anvil.users.signup_with_email(email, password, remember=True)
        except Exception as error:
            message = str(error) or ""
            if "not been enabled" not in message:
                self._show_error(message or "Could not create the account.")
                return
        if self._sign_in(email, password):
            self._go_next()


class AppStartup(AppStartupTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        self.panel.clear()
        self.panel.add_component(
            CyclopsLoginForm(
                redirect_path="/overview",
                brand_text="Cyclops",
                brand_sub="Production records",
                copyright="© Cyclops",
                allow_signup=True,
                allow_google=False,
            ),
            full_width_row=True,
        )
