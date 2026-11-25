#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "$ROOT/.." && pwd)"
STAGE="$ROOT/.build"

rm -rf "$STAGE"
mkdir -p "$STAGE"
rsync -a \
  --exclude .git --exclude .venv --exclude .build --exclude __pycache__ --exclude .anvil-data --exclude .anvil \
  "$ROOT/" "$STAGE/cyclops_app/"
for pair in "craftify-library:craftify_library" "tabulator:tabulator" "anvil_extras:anvil_extras" "routing:routing"; do
  src="${pair%%:*}"
  dest="${pair##*:}"
  rsync -a --exclude .git --exclude .venv --exclude __pycache__ \
    "$WORKSPACE/$src/" "$STAGE/$dest/"
done
cp "$ROOT/Dockerfile" "$STAGE/Dockerfile"
cp "$ROOT/scripts/entrypoint.sh" "$STAGE/entrypoint.sh"

cd "$ROOT"
docker compose up --build "$@"
