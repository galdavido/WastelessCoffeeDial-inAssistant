-- A SELECT-only role for the dev instance's admin dashboard to read the
-- friends database with.
--
-- The prod volume already exists, so docker-entrypoint-initdb.d will never run
-- this on its own. Apply it once, by hand:
--
--   docker compose -f compose.prod.yaml exec -T db \
--     psql -U barista -d barista_db -v pw="'<a long random password>'" \
--     < scripts/create_readonly_role.sql
--
-- Idempotent: safe to re-run, and re-running resets the password.
\set ON_ERROR_STOP on

SELECT 'CREATE ROLE wcda_readonly LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wcda_readonly')
\gexec

ALTER ROLE wcda_readonly WITH PASSWORD :pw;

-- Belt and braces: even a SELECT grant left behind by a future migration
-- cannot be written through if every transaction starts read-only.
ALTER ROLE wcda_readonly SET default_transaction_read_only = on;

SELECT format('GRANT CONNECT ON DATABASE %I TO wcda_readonly', current_database())
\gexec

GRANT USAGE ON SCHEMA public TO wcda_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO wcda_readonly;

-- Tables a later migration adds are covered without re-running this.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO wcda_readonly;
