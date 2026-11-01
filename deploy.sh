#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -f deploy.env ]; then cp deploy.env.example deploy.env; fi
compose() { docker compose --env-file deploy.env -f compose.server.yml "$@"; }
network=$(sed -n 's/^TRAEFIK_NETWORK=//p' deploy.env | tr -d '\r')
network=${network:-proxy}
docker network inspect "$network" >/dev/null 2>&1 || {
  echo "Network Traefik '$network' tidak ditemukan. Isi TRAEFIK_NETWORK di deploy.env sesuai server." >&2
  exit 1
}
if [ ! -f private/seed/portal.sqlite3 ] || [ ! -f private/seed/secret.key ]; then
  echo 'Ekstrak paket PRIVATE ke direktori ini sebelum menjalankan deploy.' >&2
  exit 1
fi
chmod 700 private private/seed
chmod 600 private/seed/*
mkdir -p private/backups
chmod 700 private/backups
image=$(sed -n 's/^PORTAL_IMAGE=//p' deploy.env | tr -d '\r')
loaded=0
if [ -f images/portal-amd64.tar ] && [ "${1:-}" != '--pull' ]; then
  docker load -i images/portal-amd64.tar
  loaded=1
fi
case "$image" in
  ''|pesse-se2026:local) compose build portal ;;
  *)
    if [ "$loaded" = 0 ] && ! compose pull; then
      docker image inspect "$image" >/dev/null 2>&1 || exit 1
      echo 'Registry belum dapat diakses; memakai image yang sudah dimuat pada server.'
    fi
    ;;
esac
compose up -d --pull never --wait --wait-timeout 180
compose ps
echo 'Portal siap pada origin Traefik. Tunnel: pesse.databenuanta.id -> http://traefik:80.'
