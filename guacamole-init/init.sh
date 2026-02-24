#!/bin/bash
# Guacamole database initializer
# This runs as an init container ONCE, then exits.
# It downloads the official Guacamole schema and imports it into Postgres.
# The main guacamole container waits for this to complete via depends_on.

set -e

echo "==> Waiting for PostgreSQL to be ready..."
until pg_isready -h "$POSTGRESQL_HOSTNAME" -U "$POSTGRESQL_USER"; do
  sleep 2
done

echo "==> Checking if Guacamole schema already exists..."
TABLE_EXISTS=$(psql -h "$POSTGRESQL_HOSTNAME" -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE" -tAc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='guacamole_connection';")

if [ "$TABLE_EXISTS" -gt "0" ]; then
  echo "==> Schema already exists — skipping init."
  exit 0
fi

echo "==> Downloading Guacamole schema..."
# Pull the schema directly from the official Guacamole Docker image
docker run --rm guacamole/guacamole /opt/guacamole/bin/initdb.sh --postgresql > /tmp/initdb.sql

echo "==> Importing schema into PostgreSQL..."
psql -h "$POSTGRESQL_HOSTNAME" -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE" -f /tmp/initdb.sql

echo "==> Guacamole database initialized successfully."
