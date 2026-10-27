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

Sign up with email on the login screen. The first signed-in page loads the workbook clone into the data tables (446 products, 501 recipes). Edits after that are stored.

In the Anvil IDE, add **craftify-library** as a dependency if you sync to cloud (`ST3GINETRT4QJYDC`).

## Tests

```bash
.venv/bin/pytest tests/test_domain.py -q
```

`scripts/dev-server.sh` creates that virtualenv. Any pytest on the path works too; the tests only need the standard library.
