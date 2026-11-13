# 0004 — Tenant column from the first migration

- Status: accepted (P0, 2026-11-11); revised after the P0 review (see 0006); extended by
  [0008](0008-grid-persistence-and-development-tenant.md) in P1.2b

## Context

The roadmap places multi-tenancy in P6, but the brief also lists tenant isolation as an
architecture principle. Adding a tenant column to every table, query and test after five
phases of development is a rewrite.

## Decision

- `core.organizations` is the tenant and exists from the baseline migration.
- Every tenant-owned table created from P1 onwards has a non-null `organization_id`.
- Child tables reference their parent with a composite foreign key that includes
  `organization_id`, so a row cannot point at another tenant's parent even through a bug.
- Repositories take the organisation as an explicit argument; no query is written without it.
- Tenant-owned tables get a row-level security policy against
  `core.current_organization_id()` in the migration that creates them. The mechanism and the
  roles it depends on are described in [0006](0006-separate-owner-and-runtime-database-roles.md).

## What exists today, and what does not

Exists and is tested:

- The runtime role is subject to row-level security (it is not a superuser, has no
  `BYPASSRLS`, and owns no table).
- `core.organizations` has a policy: a runtime session sees only the organisation named by
  its transaction's tenant context, and nothing without one.
- Tenant context set with `set_config(..., true)` ends with the transaction and does not
  leak to the next user of a pooled connection. A malformed context fails the query.

Added in P1.2b (decision 0008), and tested:

- The eight tables of the `grid` schema carry a policy for every command, with `WITH CHECK`.
- `tenancy.tenant_transaction` is the one place that sets tenant context.
- Composite foreign keys keep every reference inside its grid and its tenant.

Does **not** exist yet:

- No endpoint reads tenant data (P1.2c).
- No authenticated identity exists to derive a tenant from (P6). Until then the only tenant
  the application can act for is the fixed development tenant, in local and test.
- No organisation exists after migration. The development organisation is created by an
  explicit command, in local and test only.
- The owner role is not filtered (`FORCE ROW LEVEL SECURITY` is not set).

**GRIDWISE is therefore not access-controlled.** The database isolates tenants for the
runtime role once tenant context is set; nothing yet decides who may set which.

## Rules for the code that will set tenant context

- Set it per transaction: `SELECT set_config('app.current_organization_id', :id, true)`.
  Never use a session-level `SET`: on a pooled connection it would outlive the request.
- Derive the value from the authenticated identity on the server. Never from a header,
  query parameter or request body.

## Open risk for P2

Row-level security and composite foreign keys interact with TimescaleDB hypertables,
compression and continuous aggregates in ways that have not been tested here. Prototype
tenant isolation on a hypertable before the P2 telemetry schema is fixed.

## Consequences

- P1–P5 carry a small, constant cost (one extra column, argument and policy per table).
- P6 adds identity and the code that sets tenant context, not a data-model change.
- Until P6 there is **no** access control. The API must not be exposed beyond localhost.
