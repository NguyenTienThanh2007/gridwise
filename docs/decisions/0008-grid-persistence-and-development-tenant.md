# 0008 — Grid persistence and the development tenant

- Status: accepted (P1.2b, 2026-11-13)

## Context

P1.2 stores the engine's network model in PostgreSQL and makes it tenant-owned. Three
things had to be settled: how the model maps to tables, how the API tells the database
which tenant it acts for, and what stands in for a tenant while there is no authentication.

## Decisions

### 1. One typed table per element type, in a `grid` schema

`grid.grids` and seven element tables: `buses`, `lines`, `transformers`, `loads`,
`generators`, `external_grids`, `switches`. Columns carry the engine's field names and
units. A generic JSON table was rejected: it allows neither foreign keys nor row checks.

- **Stable identifier.** Each element has a `key`: the engine's element id, unique per grid
  within its type. It is what results and, later, telemetry refer to. The row `id` is
  internal.
- **Uniqueness is scoped to the tenant.** The key is unique on
  `(organization_id, grid_id, key)`, not `(grid_id, key)`. PostgreSQL checks uniqueness
  when a row is inserted and foreign keys afterwards. With the shorter key, a tenant
  inserting into another tenant's grid got "duplicate key" for a key that exists there and
  "foreign key" for one that does not, and could enumerate that grid's keys. Found in the
  P1.2b review and tested. Every unique constraint on a tenant-owned table leads with
  `organization_id` for this reason.
- **Indexes.** That unique index also serves every lookup and cascade by
  `(organization_id, grid_id)`, so no separate index is created for it (the plan listed
  one). Each reference column to a bus, line or transformer has its own index.
- **Composite foreign keys.** Every reference to a grid, bus, line or transformer includes
  `organization_id` and `grid_id`. A row cannot point into another grid or another tenant.
  This holds for every role, including the owner.
- **Deletes.** Deleting a grid deletes its elements (cascade). A bus, line or transformer
  that something still references cannot be deleted. The references use `NO ACTION`, not
  `RESTRICT`: `RESTRICT` is checked immediately and would also refuse the cascade.
- **A switch's target** is three nullable foreign keys with a check that exactly one is set.
- **Numbers are `double precision`**, so the values the engine hashes are the values stored.

### 2. The database checks one row; the engine checks the network

Row checks cover signs, ranges, enumerations, values that must be given together, and
finite numbers. Rules that need more than one row stay in the engine's validation:

| Rule                                                                 | Enforced by |
| -------------------------------------------------------------------- | ----------- |
| Line length > 0, generator fields match its control mode, and so on  | database    |
| A transformer's HV bus has a higher nominal voltage than its LV bus  | engine      |
| A line joins buses of the same voltage                               | engine      |
| One voltage reference per bus; at least one in-service external grid | engine      |
| A switch sits at a terminal of its element; no duplicate switches    | engine      |

The grid API (P1.2c, decision 0009) runs the engine's validation on every write, in the
same transaction, before anything is written. Before P1.2c the
only writers are the seed command, which validates, and tests.

**NaN and infinity.** PostgreSQL orders NaN above every number, so `CHECK (x > 0)` accepts
it. Every numeric column has an explicit finite check, and a test fails if a numeric column
is added without one.

### 3. Synthetic data only

`grids.data_origin` is checked to equal `'synthetic'`. Storing anything else needs a
migration, which is a reviewed decision and not a configuration change.

### 4. Row-level security on all eight tables

One policy per table, `FOR ALL TO gridwise_app`, with `USING` and `WITH CHECK` both
`organization_id = core.current_organization_id()`. The runtime role gets `SELECT`,
`INSERT`, `UPDATE` and `DELETE` on these tables and `USAGE` on the schema, by name. It gets
no `TRUNCATE` (which ignores row-level security), `REFERENCES` or `TRIGGER`.

### 5. Tenant context is set in one place, per transaction

`tenancy.tenant_transaction(engine, organization_id)` opens a transaction and sets
`app.current_organization_id` with `set_config(..., true)` as its first statement. The
setting ends with the transaction, however it ends, so it cannot reach the next user of a
pooled connection. Repositories for tenant-owned data accept only the `TenantSession` it
yields, and they also filter by `organization_id` explicitly.

### 6. The development tenant needs two keys

Before authentication (P6), tenant-scoped code runs for one fixed organisation. It is
available only if **both** hold:

1. `GRIDWISE_ENVIRONMENT` is `local` or `test`;
2. `GRIDWISE_DEV_ORGANIZATION_ID` is set. It has no default.

The second key exists because `environment` defaults to `local`: with the environment
check alone, a deployment that forgot to set it would have a development tenant.
Configuration refuses the setting in `staging` and `production`, and the resolver checks
the environment again.

### 7. Optimistic concurrency by compare-and-swap (D5)

Since P1.2c the grid service locks the row with `SELECT … FOR UPDATE` and compares the
version itself, which lets it tell "not found" (404) from "stale" (412); see decision 0009.
The compare-and-swap below remains in the repository.

`grids.version` starts at 1. A writer calls `claim_version(grid_id, expected)` first, which
runs `UPDATE … SET version = version + 1 WHERE id = … AND version = :expected`. No row
updated means a conflict. The update locks the grid row, so concurrent writers to one grid
are serialised and the later one sees the conflict. A database trigger on the element
tables was rejected: it would hide the rule and could not tell the caller which version it
had read.

### 8. The topology hash is stored

`grids.topology_hash` holds the engine's `grid_hash` of the stored topology. It is written
with the topology and lets P1.3 record what a run was computed from without reloading the
grid. A test rebuilds the model from the rows and compares.

### 9. Diagram coordinates (D6)

`buses.diagram_x` and `diagram_y` are optional schematic positions. They are not electrical,
not geographic, and not part of the hash.

### 10. Demonstration data comes from a command, not a migration

`python -m gridwise_api.seed` (`make seed-demo`) creates the development organisation and
the CIGRE MV benchmark grid.

- It runs as the owner role, like migrations: only the owner can create an organisation.
  It never uses the API's credentials, and the API never sees the owner's.
- It refuses to run unless the environment is explicitly `local` or `test`.
- It is deterministic (fixed ids, element ids derived by UUID version 5, no clock, no random
  numbers) and idempotent. A demonstration grid that differs is not overwritten without
  `--replace`.
- A migration was rejected: it would create the development organisation in production too.

## What this does and does not establish

Established and tested:

- For the runtime role, each of the eight tables shows nothing without tenant context and
  only the tenant's own rows with it.
- A tenant cannot create, change, delete or reference another tenant's rows.
- Tenant context does not survive a commit, a rollback or a failed statement on a pooled
  connection, and two concurrent transactions do not mix.
- The runtime role cannot run migrations, alter or drop anything, or remove a policy.

Not established:

- **GRIDWISE is still not access-controlled.** Nothing authenticates a caller. The
  development tenant selects a tenant; it does not protect one.
- HTTP access arrived in P1.2c (decision 0009), still for the development tenant only.
- The owner role is not filtered by row-level security (`FORCE ROW LEVEL SECURITY` is not
  set). The seed command runs as the owner and therefore relies on its explicit filters.
- Row-level security on TimescaleDB hypertables (P2) is still untested, as noted in 0004.
- **Row ids can still be probed.** The runtime role may set `id` on insert, and primary keys
  are checked regardless of row-level security, so inserting a row with another tenant's
  id reveals that the id exists. Ids are random UUIDs, so this needs a leaked id. Rule for
  P1.2c: the API never accepts a row id from a client; ids come from the database. Closing
  it in the database would need column-level grants and a different id allocation.

## Consequences

- An existing local database is at revision `0001`. `make migrate` upgrades it in place; the
  API reports `schema_mismatch` until then.
- Renaming a grid changes its `topology_hash`, because the engine's hash includes the name.
  P1.2c must recompute the hash on rename.
- Row ids of grids created through the API come from `uuidv7()`. Only seeded rows have
  derived ids.
