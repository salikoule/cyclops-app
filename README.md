# Cyclops

Production records for the plant: products, molds, presses, recipes, raw materials, and colors. The screens follow the Cyclops sketch. The shell, login, tables, and charts follow the body-composition app and **craftify-library**.

A **recipe** is one way of running a mold on a press: the feed, the barrel temperatures, and the injection settings. Sheet row 345 stays `REC-0345`. Status, pieces per hour, and the gap list are computed, not typed in.

## Local run

Same prerequisites as [craftify-library/docs/LOCAL-DEV.md](../craftify-library/docs/LOCAL-DEV.md): Java 21, Postgres, and the sibling `routing`, `tabulator`, and `anvil_extras` checkouts.

```bash
chmod +x scripts/dev-server.sh
./scripts/dev-server.sh
# http://localhost:3032
```

Sign up with email on the login screen. The first signed-in account becomes an administrator. Later sign-ups are observers until an administrator sets the role. The first signed-in page loads the workbook clone into the data tables (446 products, 501 recipes). Edits after that are stored.

## Sign-in

Email and password work on the local server. The login screen also offers Google, and Account can enroll an authenticator app.

Google does not complete until the app has OAuth credentials. In the Anvil editor, open app `ITOALDABOFNQOHPL`, then the Google service, and set the client ID and client secret from Google Cloud (Web application). Use the redirect URI Anvil shows. The Users service already has “Allow login with Google” on. For this local server, put the same client ID in `anvil.yaml` under the Google service `client_config`, and the secret under `server_config`, then restart. Do not commit the secret. The app calls `anvil.users.login_with_google` and will not accept a token you paste in.

Two-factor authentication is optional per account. On Account, “Set up authenticator app” uses Anvil’s TOTP methods (`generate_totp_secret`, `validate_totp_code`, `add_mfa_method`). The login screen asks for a code when that account has one enrolled. The local server can only do this if its Users service exposes those methods. To make the server reject a password that is not paired with a code for every account, open the Users service in the Anvil editor and turn on “Require 2-factor authentication”. That setting applies to every user, so leave it off while two-factor should stay optional. Reset-by-email needs the Anvil email service. Microsoft sign-in is not part of this app.

In the Anvil IDE, add **craftify-library** as a dependency if you sync to cloud (`ST3GINETRT4QJYDC`).

## Tests

```bash
.venv/bin/pytest tests/test_domain.py -q
```

`scripts/dev-server.sh` creates that virtualenv. Any pytest on the path works too; the tests only need the standard library.
