"""The database schema revision this build of the API expects.

Bump it in the same change that adds a migration. A unit test fails if it does not match
the Alembic head, so it cannot silently fall behind.
"""

EXPECTED_SCHEMA_REVISION = "0002"
