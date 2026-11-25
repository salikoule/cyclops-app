#!/usr/bin/env bash
# One command, once a host exists: scripts/deploy.sh user@host
# The host needs SSH and a public IPv4. Docker is installed if it is missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "$ROOT/.." && pwd)"
ENV_FILE="$ROOT/.env.production"
HOST="${1:-}"

if [ -z "$HOST" ]; then
  echo "Usage: scripts/deploy.sh user@host" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Copy .env.production.example to .env.production and fill it in." >&2
  exit 1
fi

python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path
needed = ("SITE_ADDRESS", "ANVIL_ORIGIN", "POSTGRES_PASSWORD")
found = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    found[key.strip()] = value.strip().strip('"').strip("'")
missing = [key for key in needed if not found.get(key)]
if missing:
    raise SystemExit("Missing in .env.production: " + ", ".join(missing))
if any(ch in found["POSTGRES_PASSWORD"] for ch in "@/:#?&"):
    raise SystemExit("POSTGRES_PASSWORD must be letters and digits only.")
PY

STAGE="$ROOT/.build"
rm -rf "$STAGE"
mkdir -p "$STAGE"
rsync -a \
  --exclude .git --exclude .venv --exclude .build --exclude __pycache__ --exclude .anvil-data --exclude .anvil --exclude .env.production \
  "$ROOT/" "$STAGE/cyclops_app/"
for pair in "craftify-library:craftify_library" "tabulator:tabulator" "anvil_extras:anvil_extras" "routing:routing"; do
  src="${pair%%:*}"
  dest="${pair##*:}"
  rsync -a --exclude .git --exclude .venv --exclude __pycache__ \
    "$WORKSPACE/$src/" "$STAGE/$dest/"
done
cp "$ROOT/Dockerfile" "$STAGE/Dockerfile"
cp "$ROOT/scripts/entrypoint.sh" "$STAGE/entrypoint.sh"
cp "$ROOT/compose.prod.yaml" "$STAGE/compose.prod.yaml"
cp "$ROOT/Caddyfile" "$STAGE/Caddyfile"
# The image build context is the stage root. The schema file is referenced as ./db/plant.sql.
mkdir -p "$STAGE/db"
cp "$ROOT/db/plant.sql" "$STAGE/db/plant.sql"

ssh -o BatchMode=yes "$HOST" 'command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sudo sh'
ssh -o BatchMode=yes "$HOST" 'sudo mkdir -p /opt/cyclops && sudo chown "$USER" /opt/cyclops'
rsync -a --delete \
  --exclude .env.production \
  "$STAGE/" "$HOST:/opt/cyclops/"
scp -o BatchMode=yes "$ENV_FILE" "$HOST:/opt/cyclops/.env.production"
ssh -o BatchMode=yes "$HOST" 'chmod 600 /opt/cyclops/.env.production && cd /opt/cyclops && sudo docker compose --env-file .env.production -f compose.prod.yaml up -d --build'
