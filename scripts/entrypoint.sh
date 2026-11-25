#!/bin/sh
set -eu

python - <<'PY'
import os
import time

import psycopg

url = os.environ["CYCLOPS_DATABASE_URL"]
for _ in range(60):
    try:
        psycopg.connect(url).close()
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("database did not answer")
PY

cd /srv
set -- anvil-app-server \
  --app cyclops_app \
  --port "${ANVIL_PORT:-3040}" \
  --auto-migrate \
  --origin "${ANVIL_ORIGIN:-http://localhost:3040}" \
  --database "jdbc:postgresql://db:5432/${POSTGRES_DB:-cyclops}?user=${POSTGRES_USER:-cyclops}&password=${POSTGRES_PASSWORD:-cyclops}" \
  --dep-id ST3GINETRT4QJYDC=craftify_library \
  --dep-id dep_wkevhfjmozeq0f=craftify_library \
  --dep-id dep_craftify_lib=craftify_library \
  --dep-id dep_r1gjp7ay80bem=craftify_library \
  --dep-id TGQCF3WT6FVL2EM2=tabulator \
  --dep-id C6ZZPAPN4YYF5NVJ=anvil_extras \
  --dep-id dep_d6bjyrizg8vut=tabulator \
  --dep-id dep_kfkrna97mklbm=anvil_extras \
  --dep-id 3PIDO5P3H4VPEMPL=routing \
  --dep-id dep_routing=routing \
  --dep-id dep_3cbnzlajrrq4tg=routing \
  --dep-id dep_2lwdiwk1dh75u=routing

case "${ANVIL_ORIGIN:-}" in
  https://*)
    set -- "$@" --disable-tls
    ;;
esac

if [ -n "${SMTP_HOST:-}" ]; then
  set -- "$@" --smtp-host "$SMTP_HOST" --smtp-port "${SMTP_PORT:-1025}"
fi
case "${SMTP_ENCRYPTION:-}" in
  ssl|starttls)
    set -- "$@" --smtp-encryption "$SMTP_ENCRYPTION"
    ;;
esac
if [ -n "${SMTP_USERNAME:-}" ]; then
  set -- "$@" --smtp-username "$SMTP_USERNAME" --smtp-password "${SMTP_PASSWORD:-}"
fi
if [ -n "${GOOGLE_CLIENT_ID:-}" ]; then
  set -- "$@" --google-client-id "$GOOGLE_CLIENT_ID" --google-client-secret "${GOOGLE_CLIENT_SECRET:-}"
fi
if [ -n "${MICROSOFT_APP_ID:-}" ]; then
  set -- "$@" \
    --microsoft-app-id "$MICROSOFT_APP_ID" \
    --microsoft-app-secret "${MICROSOFT_APP_SECRET:-}" \
    --microsoft-tenant-id "${MICROSOFT_TENANT_ID:-common}"
fi

exec "$@"
