-- Runs once, on first initialisation of the Postgres data volume.
--
-- Only the extension and the schema are created here. The tables themselves
-- belong to Alembic (`alembic upgrade head`) — keeping DDL in exactly one
-- place is what makes the schema reproducible on an existing volume, where
-- this file is never executed again.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS identity;
