"""Who can see a screen and who can write.

Roles are fixed statuses the code branches on: ``administrator``, ``user``, ``observer``.
The words an administrator sees are labels. A plant list of job titles stays on personnel roles.
"""

ROLES = ("administrator", "user", "observer")
ROLE_LABEL = {"administrator": "Administrator", "user": "User", "observer": "Observer"}

# (key, label) in sidebar order. ``always`` is on for every signed-in user.
# ``admin`` is only on a sidebar for an administrator, and is not a grant.
SCREENS = (
    ("floor", "Live floor", False, False),
    ("overview", "Overview", False, False),
    ("performance", "Performance", False, False),
    ("item", "Items", False, False),
    ("mold", "Molds", False, False),
    ("machine", "Machines", False, False),
    ("recipe", "Recipes", False, False),
    ("order", "Orders", False, False),
    ("run", "Production", False, False),
    ("stoppage", "Stoppages", False, False),
    ("changeover", "Changeovers", False, False),
    ("lot", "Lots", False, False),
    ("configure", "Configure", False, False),
    ("notify", "Notifications", True, False),
    ("account", "Account", True, False),
    ("history", "Audit log", False, True),
    ("users", "Users", False, True),
)

SCREEN_LABEL = {key: label for key, label, _, _ in SCREENS}
ALWAYS = tuple(key for key, _, always, _ in SCREENS if always)
ADMIN_ONLY = tuple(key for key, _, _, admin in SCREENS if admin)
CATALOG = tuple((key, label) for key, label, always, admin in SCREENS if not always and not admin)
HOME_ORDER = ("floor", "overview", "performance", "run", "order", "item")


def email_key(value):
    return str(value or "").strip().lower()


def default_ids(role):
    """Screens stored for a new account. Administrators ignore the stored list."""
    if role == "administrator":
        return [key for key, _, _, _ in SCREENS]
    return [key for key, _, always, admin in SCREENS if not always and not admin]


def visible_screens(role, stored):
    """Sidebar keys for this role. ``stored`` is the granted keys; None uses the default."""
    if role == "administrator":
        return [key for key, _, _, _ in SCREENS]
    granted = set(default_ids(role) if stored is None else stored)
    granted.update(ALWAYS)
    return [key for key, _, _, admin in SCREENS if key in granted and not admin]


PATHS = {
    "floor": "/floor", "overview": "/overview", "performance": "/performance", "item": "/items",
    "mold": "/molds", "machine": "/machines", "recipe": "/recipes", "order": "/orders",
    "run": "/production", "stoppage": "/stoppages", "changeover": "/changeovers", "lot": "/lots",
    "configure": "/configure", "notify": "/notifications", "account": "/account",
    "history": "/history", "users": "/users",
}


def home_path(role, stored):
    visible = visible_screens(role, stored)
    for key in list(HOME_ORDER) + visible:
        if key in visible:
            return PATHS[key]
    return "/account"


def can_open(role, stored, screen):
    return screen in visible_screens(role, stored)


ADMIN_ACTIONS = {"save-access"}


def can_apply(role, action):
    """Operational writes. Changing a user's role or screens is an administrator action."""
    if role == "administrator":
        return True
    if role == "user":
        return action not in ADMIN_ACTIONS
    return False


def leaves_an_admin(profiles, email, role, active):
    """False when this save would leave no active administrator."""
    key = email_key(email)
    kept = False
    for profile in profiles:
        same = email_key(profile.get("email")) == key
        if same:
            if active and role == "administrator":
                kept = True
        elif profile.get("role") == "administrator" and profile.get("active"):
            kept = True
    return kept


def session_view(email, role, stored, unread=0):
    role = role if role in ROLES else "observer"
    visible = visible_screens(role, stored)
    return {
        "email": email or "",
        "role": role,
        "roleLabel": ROLE_LABEL.get(role, role),
        "canWrite": role in ("administrator", "user"),
        "screens": visible,
        "catalog": [{"value": key, "label": label} for key, label in CATALOG],
        "roles": [{"value": key, "label": ROLE_LABEL[key]} for key in ROLES],
        "home": home_path(role, stored),
        "unread": unread or 0,
    }
