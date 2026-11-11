#!/bin/sh
# Creates the two GRIDWISE database roles. Runs once, when the PostgreSQL data directory is
# first initialised (docker-entrypoint-initdb.d). See docs/decisions/0006.
#
#   gridwise_owner  runs migrations; owns the database, schemas and tables
#   gridwise_app    used by the API; owns nothing; privileges are granted by migrations
#
# Neither role is a superuser, can bypass row-level security, or can create roles or
# databases. The bootstrap superuser (POSTGRES_USER) is not used by any application.
#
# Passwords are read by psql from the environment (\getenv), so they never appear on a
# command line. This file may be sourced by the image's entrypoint, so it sets no shell
# options and uses `exit` only to abort initialisation.

if [ -z "${GRIDWISE_DB_OWNER_PASSWORD:-}" ] || [ -z "${GRIDWISE_DB_APP_PASSWORD:-}" ]; then
  echo "010-gridwise-roles: GRIDWISE_DB_OWNER_PASSWORD and GRIDWISE_DB_APP_PASSWORD must be set" >&2
  exit 1
fi

psql --no-psqlrc -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL' || exit 1
\getenv owner_password GRIDWISE_DB_OWNER_PASSWORD
\getenv app_password GRIDWISE_DB_APP_PASSWORD

CREATE ROLE gridwise_owner LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  PASSWORD :'owner_password';

CREATE ROLE gridwise_app LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
  PASSWORD :'app_password';

-- The owner role owns the database (and, through pg_database_owner, the public schema).
ALTER DATABASE :"DBNAME" OWNER TO gridwise_owner;

-- Nobody connects by default; the runtime role may connect and nothing more.
REVOKE ALL ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO gridwise_app;
SQL

echo "010-gridwise-roles: created gridwise_owner and gridwise_app"
