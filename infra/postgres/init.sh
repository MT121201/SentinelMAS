#!/bin/bash
# Creates multiple PostgreSQL databases on first container start.
# Invoked by postgres entrypoint via /docker-entrypoint-initdb.d/

set -e

# POSTGRES_MULTIPLE_DATABASES env var: comma-separated list, e.g. "masdb,langfuse"
if [ -n "$POSTGRES_MULTIPLE_DATABASES" ]; then
    echo "Creating additional databases: $POSTGRES_MULTIPLE_DATABASES"
    for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
        # Skip the default database which postgres already creates
        if [ "$db" != "$POSTGRES_DB" ]; then
            psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
                CREATE DATABASE "$db";
                GRANT ALL PRIVILEGES ON DATABASE "$db" TO "$POSTGRES_USER";
EOSQL
            echo "  ✓ Created database: $db"
        fi
    done
fi
