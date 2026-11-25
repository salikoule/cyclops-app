from ._anvil_designer import AppStartupTemplate
from anvil import *
import anvil.server
import anvil.users
from craftify_library.CraftifyLoginForm import CraftifyLoginForm


def _account_needs_enabling(message):
    """Local signup creates the row, then fails closed when confirmation email has nowhere to go."""
    lowered = (message or "").lower()
    return "not been enabled" in (message or "") or "smtp" in lowered or "confirm" in lowered or "not been confirmed" in lowered


class CyclopsLoginForm(CraftifyLoginForm):
    def __init__(self, **properties):
        CraftifyLoginForm.__init__(self, **properties)
        button = Button(
            text="Microsoft",
            role="login-sso-btn",
            spacing_above="none",
            spacing_below="small",
        )
        button.set_event_handler("click", self.microsoft_login_btn_click)
        self.login_form_card.add_component(button, full_width_row=True, index=11)

    def _mfa_for(self, email, password):
        """An authenticator code when this account has one. None when it has not enrolled, or the platform cannot say."""
        mfa = getattr(anvil.users, "mfa", None)
        if mfa is None or not hasattr(mfa, "get_available_mfa_types"):
            return None
        try:
            types = list(mfa.get_available_mfa_types(email, password) or [])
        except anvil.users.AuthenticationFailed:
            raise
        except Exception:
            return None
        if not types:
            return None
        result = mfa.mfa_login_with_form(email, password)
        if result == "reset_mfa":
            try:
                mfa.send_mfa_reset_email(email)
            except Exception:
                pass
            self._show_error("A two-factor reset was requested. It arrives only when email is configured.")
            return False
        if not result:
            return False
        return result

    def _sign_in(self, email, password):
        try:
            mfa = self._mfa_for(email, password)
        except anvil.users.AuthenticationFailed as error:
            message = str(error) or ""
            if not _account_needs_enabling(message):
                self._show_error(message or "Login failed.")
                return False
            mfa = None
        if mfa is False:
            return False
        try:
            if mfa:
                anvil.users.login_with_email(email, password, remember=True, mfa=mfa)
            else:
                anvil.users.login_with_email(email, password, remember=True)
            return True
        except anvil.users.AuthenticationFailed as error:
            if "MFA" in type(error).__name__ or "factor" in str(error).lower():
                return self._sign_in_mfa(email, password)
            message = str(error) or ""
            if not _account_needs_enabling(message):
                self._show_error(message or "Login failed.")
                return False
        except Exception as error:
            name = type(error).__name__
            if name == "MFARequired":
                return self._sign_in_mfa(email, password)
            message = str(error) or ""
            if not _account_needs_enabling(message):
                self._show_error(message or "Login failed.")
                return False
        try:
            anvil.server.call("cyclops_enable_new_user", email)
            if mfa:
                anvil.users.login_with_email(email, password, remember=True, mfa=mfa)
            else:
                anvil.users.login_with_email(email, password, remember=True)
            return True
        except Exception as error:
            if type(error).__name__ == "MFARequired":
                return self._sign_in_mfa(email, password)
            self._show_error(str(error) or "Login failed.")
            return False

    def _sign_in_mfa(self, email, password):
        mfa = getattr(anvil.users, "mfa", None)
        if mfa is None:
            self._show_error("This server asked for a second factor, and the authenticator API is not available.")
            return False
        result = mfa.mfa_login_with_form(email, password)
        if not result or result == "reset_mfa":
            if result == "reset_mfa":
                self._show_error("A two-factor reset was requested. It arrives only when email is configured.")
            return False
        try:
            anvil.users.login_with_email(email, password, remember=True, mfa=result)
            return True
        except Exception as error:
            self._show_error(str(error) or "Login failed.")
            return False

    def google_login_btn_click(self, **event_args):
        self.error_label.visible = False
        try:
            user = anvil.users.login_with_google(remember=True)
        except anvil.users.AuthenticationFailed as error:
            if type(error).__name__ == "MFARequired":
                self._show_error("This account needs an authenticator code. Sign in with email and password to enter it.")
                return
            if not self.signup_btn.visible:
                self._show_error("Google sign-in failed.")
                return
            try:
                user = anvil.users.signup_with_google(remember=True)
            except Exception as error:
                self._show_error(self._google_message(error))
                return
        except Exception as error:
            if type(error).__name__ == "MFARequired":
                self._show_error("This account needs an authenticator code. Sign in with email and password to enter it.")
                return
            self._show_error(self._google_message(error))
            return
        if not user:
            return
        try:
            anvil.server.call("cyclops_enable_new_user", user["email"])
        except Exception:
            pass
        self._go_next()

    def microsoft_login_btn_click(self, **event_args):
        self.error_label.visible = False
        try:
            user = anvil.users.login_with_microsoft(remember=True)
        except anvil.users.AuthenticationFailed as error:
            if type(error).__name__ == "MFARequired":
                self._show_error("This account needs an authenticator code. Sign in with email and password to enter it.")
                return
            if not self.signup_btn.visible:
                self._show_error("Microsoft sign-in failed.")
                return
            try:
                user = anvil.users.signup_with_microsoft(remember=True)
            except Exception as error:
                self._show_error(str(error) or "Could not create an account with Microsoft.")
                return
        except Exception as error:
            if type(error).__name__ == "MFARequired":
                self._show_error("This account needs an authenticator code. Sign in with email and password to enter it.")
                return
            self._show_error(str(error) or "Microsoft sign-in failed.")
            return
        if not user:
            return
        try:
            anvil.server.call("cyclops_enable_new_user", user["email"])
        except Exception:
            pass
        self._go_next()

    def _google_message(self, error):
        message = str(error) or "Google sign-in failed."
        lowered = message.lower()
        if "client" in lowered or "google" in lowered or "configured" in lowered:
            return message + " The server needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        return message

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
            if not _account_needs_enabling(message):
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
                redirect_path="/",
                brand_text="Cyclops",
                brand_sub="Production records",
                copyright="© Cyclops",
                allow_signup=True,
                allow_google=True,
            ),
            full_width_row=True,
        )
