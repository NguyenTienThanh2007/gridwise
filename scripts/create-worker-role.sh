#!/bin/sh
# Create the gridwise_worker role in a database volume initialised before P1.3b.
#
# New volumes get the role from infrastructure/postgres/init/010-gridwise-roles.sh. This
# does the same for an existing one, as the bootstrap superuser inside the postgres
# container, and changes nothing if the role already exists. The password is read by psql
# from the environment (\getenv), never from a command line. Decision 0011.
set -eu

if [ ! -f .env ]; then
  echo "create-worker-role: run from the repository root, with a .env file" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a
: "${GRIDWISE_DB_WORKER_PASSWORD:?set GRIDWISE_DB_WORKER_PASSWORD in .env}"
: "${POSTGRES_DB:?set POSTGRES_DB in .env}"

docker compose exec -T -e GRIDWISE_DB_WORKER_PASSWORD postgres \
  psql --no-psqlrc -v ON_ERROR_STOP=1 -v "DBNAME=$POSTGRES_DB" -U postgres -d "$POSTGRES_DB" <<'SQL'
\getenv worker_password GRIDWISE_DB_WORKER_PASSWORD
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gridwise_worker') AS missing \gset
\if :missing
CREATE ROLE gridwise_worker LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
  PASSWORD :'worker_password';
\echo create-worker-role: created gridwise_worker
\else
\echo create-worker-role: gridwise_worker already exists, nothing changed
\endif
GRANT CONNECT ON DATABASE :"DBNAME" TO gridwise_worker;
SQL
