#!/bin/sh
set -eu
if ! command -v docker >/dev/null 2>&1; then
  echo "ERREUR: Docker n'est pas installé." >&2; exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERREUR: Docker Compose v2 n'est pas disponible." >&2; exit 1
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Fichier .env créé. Renseignez-le puis relancez ./install.sh"
  exit 2
fi
docker compose build
docker compose up -d
docker compose ps
