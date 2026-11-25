#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "$ROOT/.." && pwd)"
LIB="$WORKSPACE/craftify-library"
VENV="$ROOT/.venv"
PORT="${ANVIL_PORT:-3040}"
DB_NAME="${ANVIL_PG_DB:-cyclops_plant}"

if [[ ! -x "$VENV/bin/anvil-app-server" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install anvil-app-server pytest "psycopg[binary]" "openpyxl==3.1.5"
fi
if ! "$VENV/bin/python" -c "import psycopg, openpyxl" >/dev/null 2>&1; then
  "$VENV/bin/pip" install "psycopg[binary]" "openpyxl==3.1.5"
fi
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
export PATH="$JAVA_HOME/bin:$PATH"

ln -sfn craftify-library "$WORKSPACE/craftify_library"

if [[ -x "$LIB/scripts/dev-server.sh" ]]; then
  bash "$LIB/scripts/dev-server.sh" &
  BOOT=$!
  sleep 4
  kill "$BOOT" 2>/dev/null || true
  wait "$BOOT" 2>/dev/null || true
fi

if ! pg_isready -q 2>/dev/null; then
  brew services start postgresql@14 2>/dev/null || true
fi
psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
  || psql -d postgres -c "CREATE DATABASE \"$DB_NAME\";"
psql -d "$DB_NAME" -tc "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'plant'" | grep -q 1 \
  || psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/db/plant.sql"

cd "$ROOT"
exec "$VENV/bin/anvil-app-server" \
  --app . \
  --port "$PORT" \
  --auto-migrate \
  --origin "http://localhost:$PORT" \
  --database "jdbc:postgresql://localhost/$DB_NAME?user=$(whoami)" \
  --dep-id ST3GINETRT4QJYDC=../craftify_library \
  --dep-id dep_wkevhfjmozeq0f=../craftify_library \
  --dep-id dep_craftify_lib=../craftify_library \
  --dep-id dep_r1gjp7ay80bem=../craftify_library \
  --dep-id TGQCF3WT6FVL2EM2=../tabulator \
  --dep-id C6ZZPAPN4YYF5NVJ=../anvil_extras \
  --dep-id dep_d6bjyrizg8vut=../tabulator \
  --dep-id dep_kfkrna97mklbm=../anvil_extras \
  --dep-id 3PIDO5P3H4VPEMPL=../routing \
  --dep-id dep_routing=../routing \
  --dep-id dep_3cbnzlajrrq4tg=../routing \
  --dep-id dep_2lwdiwk1dh75u=../routing
