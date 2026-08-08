#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE polaris_audit;
    GRANT ALL PRIVILEGES ON DATABASE polaris_audit TO $POSTGRES_USER;
EOSQL
