#!/usr/bin/env bash
# Run on the server. Pulls master and rebuilds the demo.
# Future work stays on the dev branch until it is merged to master.
set -euo pipefail

SRC=/opt/cyclops-src
RUNTIME=/opt/cyclops
ENV_FILE="$RUNTIME/.env.production"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh
command -v git >/dev/null 2>&1 || { apt-get update && apt-get install -y git; }

mkdir -p "$SRC" "$RUNTIME"

pull() {
  url="$1"
  dest="$2"
  branch="$3"
  if [ ! -d "$dest/.git" ]; then
    git clone --branch "$branch" "$url" "$dest"
  else
    git -C "$dest" fetch origin "$branch"
    git -C "$dest" checkout "$branch"
    git -C "$dest" pull --ff-only origin "$branch"
  fi
}

pin() {
  url="$1"
  dest="$2"
  sha="$3"
  if [ ! -d "$dest/.git" ]; then
    git clone "$url" "$dest"
  else
    git -C "$dest" fetch origin
  fi
  git -C "$dest" checkout "$sha"
}

pull https://github.com/salikoule/cyclops-app.git "$SRC/cyclops-app" master
pull https://github.com/salikoule/craftify-library.git "$SRC/craftify-library" master
pin https://github.com/anvilistas/tabulator.git "$SRC/tabulator" 0d362830e40a6ca5601fe2a8fe157524d3df7948
pin https://github.com/anvilistas/anvil-extras.git "$SRC/anvil-extras" 7a3e625c5d2983323442edb321f3380bd24e8504
pin https://github.com/anvil-works/routing.git "$SRC/routing" dc365bbf7a80c3464f1be569015fe8307a67032d

rsync -a --delete --exclude .git "$SRC/cyclops-app/" "$RUNTIME/cyclops_app/"
rsync -a --delete --exclude .git "$SRC/craftify-library/" "$RUNTIME/craftify_library/"
rsync -a --delete --exclude .git "$SRC/tabulator/" "$RUNTIME/tabulator/"
rsync -a --delete --exclude .git "$SRC/anvil-extras/" "$RUNTIME/anvil_extras/"
rsync -a --delete --exclude .git "$SRC/routing/" "$RUNTIME/routing/"
cp "$SRC/cyclops-app/Dockerfile" "$RUNTIME/Dockerfile"
cp "$SRC/cyclops-app/scripts/entrypoint.sh" "$RUNTIME/entrypoint.sh"
cp "$SRC/cyclops-app/compose.prod.yaml" "$RUNTIME/compose.prod.yaml"
cp "$SRC/cyclops-app/Caddyfile" "$RUNTIME/Caddyfile"
mkdir -p "$RUNTIME/db"
cp "$SRC/cyclops-app/db/plant.sql" "$RUNTIME/db/plant.sql"
chmod 600 "$ENV_FILE"

cd "$RUNTIME"
docker compose --env-file .env.production -f compose.prod.yaml up -d --build
