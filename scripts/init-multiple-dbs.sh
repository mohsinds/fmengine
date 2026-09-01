#!/bin/bash
# Create multiple databases inside the primary Postgres instance for Temporal + MLflow.
# Mounted at /docker-entrypoint-initdb.d/ by docker-compose.yml (runs once on first boot).
set -euo pipefail

# POSTGRES_MULTIPLE_DATABASES is a comma-separated list, e.g.
#   fmtrader,temporal,temporal_visibility,mlflow
if [ -z "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
  echo "POSTGRES_MULTIPLE_DATABASES is empty; nothing to create."
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    SELECT 'Creating databases from POSTGRES_MULTIPLE_DATABASES';
EOSQL

IFS=',' read -ra DBS <<< "$POSTGRES_MULTIPLE_DATABASES"
for db in "${DBS[@]}"; do
  db_trimmed="$(echo "$db" | xargs)"
  if [ -z "$db_trimmed" ]; then
    continue
  fi
  echo "Ensuring database '$db_trimmed' exists..."
  exists="$(psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${db_trimmed}'")"
  if [ "$exists" = "1" ]; then
    echo "  already exists"
  else
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" \
      -c "CREATE DATABASE \"${db_trimmed}\";"
    echo "  created"
  fi
done
