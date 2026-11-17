#!/bin/sh
set -eu
docker compose run --rm --no-deps --entrypoint python rh-sync /app/sync_engine.py
