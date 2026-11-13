"""Sign-in security helpers for the account settings overlay."""

import anvil.users
from anvil import *
from cyclops_app import Layout


def enroll_totp():
    user = anvil.users.get_user()
    email = user["email"] if user else ""
    password_box = TextBox(placeholder="Current password", hide_text=True)
    if not alert(password_box, title="Confirm your password", buttons=[("Continue", True), ("Cancel", False)]):
        return
    password = password_box.text or ""
    if not password:
        Notification("Enter your password.", style="warning").show()
        return
    mfa = getattr(anvil.users, "mfa", None)
    if mfa is None:
        Notification("Two-factor authentication is not available in this environment.", style="warning", timeout=6).show()
        return
    try:
        config = mfa.generate_totp_secret(email)
    except Exception as error:
        Notification(str(error) or "Authenticator setup could not start.", style="warning", timeout=8).show()
        return
    code_box = TextBox(placeholder="6-digit code")
    panel = ColumnPanel()
    panel.add_component(Label(text="Scan the QR code with an authenticator app, then enter the current 6-digit code."))
    panel.add_component(Image(source=config.get("qr_code"), height=180, display_mode="shrink_to_fit"))
    panel.add_component(code_box)
    if not alert(panel, title="Authenticator app", buttons=[("Confirm", True), ("Cancel", False)]):
        return
    try:
        if not mfa.validate_totp_code(config.get("mfa_method"), (code_box.text or "").strip()):
            Notification("That code did not match.", style="warning").show()
            return
        mfa.add_mfa_method(password, config.get("mfa_method"), True)
    except Exception as error:
        Notification(str(error) or "Two-factor authentication was not saved.", style="danger", timeout=6).show()
        return
    Notification("Two-factor authentication is on. The next email sign-in asks for your authenticator code.", style="success", timeout=5).show()


def account_mfa_panel():
    panel = ColumnPanel(spacing_above="none", spacing_below="none")
    panel.add_component(Label(text="Optional authenticator-app codes on email sign-in. Google sign-in is unchanged."))
    panel.add_component(Layout.button("Set up authenticator app", enroll_totp, primary=True))
    return panel
