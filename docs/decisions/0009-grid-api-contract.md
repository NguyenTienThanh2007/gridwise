# 0009 — Grid API contract

- Status: accepted (P1.2c, 2026-11-13)

## Context

P1.2b stores grids in a tenant-owned schema. P1.2c makes them reachable over HTTP. The
decisions that mattered: how a write is kept atomic and valid, how concurrent writers are
detected, how a client learns nothing about other tenants, and where the API may exist
while the tenant is still a fixed development setting.

## Decisions

### 1. Resources

| Method and path                                       | Purpose                                          |
| ----------------------------------------------------- | ------------------------------------------------ |
| `POST /api/v1/grids`                                  | Create a grid with its whole network             |
| `GET /api/v1/grids`                                   | List grids (`limit` 1–100, `offset`)             |
| `GET`, `PATCH`, `DELETE /api/v1/grids/{id}`           | Read; rename or describe; delete                 |
| `GET`, `PUT /api/v1/grids/{id}/topology`              | Read or replace the whole network                |
| `GET /api/v1/grids/{id}/assets/{type}`                | List the elements of one type                    |
| `GET`, `PATCH /api/v1/grids/{id}/assets/{type}/{key}` | Read one element; change its name and state (D3) |

`frequency_hz` belongs to the network and changes only with a topology replacement.
`data_origin` and `version` are read-only, and a client never chooses a row id.

### 2. Where the API exists

The routes are registered only when the environment is `local` or `test`. In `staging` and
`production` they do not exist, so every grid path is a plain `404`: nothing about the
development mechanism is visible there. In `local` or `test` without
`GRIDWISE_DEV_ORGANIZATION_ID`, every grid request is refused with
`503 development_tenant_not_configured` before any database query.

The development tenant is a choice of tenant made by the server's configuration. It is not
authentication and not authorisation, and no response or document presents it as either.

### 3. One transaction per write, validated before writing

Every write runs in one `tenant_transaction`:

1. lock the grid row (`SELECT … FOR UPDATE`);
2. compare its version with `If-Match`;
3. build the model that will be stored (from the body, or by applying the change to the
   stored model) and validate it with the engine;
4. write the change, the recomputed `topology_hash` and `version + 1`;
5. commit.

Any failure before the commit rolls back everything, including a failure after the old
elements were deleted. A create is validated before its transaction opens. The engine's
validation and hashing are plain Python; no power flow runs during a request.

The hash is recomputed by every write that can change it. Renaming changes it (the engine's
hash includes the name); a description does not, and neither do diagram positions. Every
write increments the version.

### 4. A topology replacement keeps keys, not row ids

Replacing a topology deletes the grid's elements and inserts the new ones. Keys, the stable
identifiers, are kept; row ids are new. Row ids are not exposed anywhere, so nothing outside
can depend on them. A difference-based update was rejected as much more code for no visible
benefit before results reference rows.

### 5. ETag and If-Match (D5)

The ETag of a grid, its topology and every one of its assets is the grid's version as a
strong tag, `"7"`. Every write requires `If-Match` with exactly one such tag.

| Request                                                 | Response                                      |
| ------------------------------------------------------- | --------------------------------------------- |
| No `If-Match`                                           | `428 precondition_required`                   |
| `*`, a weak tag, a list, or anything but `"<n>"`, n ≥ 1 | `400 invalid_if_match`                        |
| A version other than the current one                    | `412 version_conflict` and the current `ETag` |

`*` is refused because it would match any version and switch the check off. The row lock
serialises writers to one grid, so of two writers with the same `If-Match` exactly one
succeeds. `If-None-Match` and `304` are not supported yet.

### 6. Nothing about other tenants

A grid that does not exist and a grid of another tenant give the same `404` body and no
`ETag`. The lock and the version check run only after the grid is found for the caller's
tenant, so a stale `If-Match` on another tenant's grid is still `404`, never a `412` that
would reveal a version. Organisation ids and element row ids appear in no response. This
also closes, for the API, the row-id probing noted in decision 0008.

### 7. Strict schemas

Unknown fields are refused. Numbers must be finite JSON numbers; an integer is accepted
where a decimal is expected. Booleans must be JSON booleans, so `"false"` and `0` are
refused. Names are 1–200 characters and not blank; keys are 1–200 letters, digits, `.`,
`_` or `-`. Rejected input is never echoed back: an error names the location and type only.

Engine validation failures return `422 grid_validation_failed` with every issue, each with
its location (`[element type, key, field]`) and the engine's stable code as `type`.

### 8. Limits

A request body may have at most `GRIDWISE_MAX_REQUEST_BODY_BYTES` (2 MiB) and a grid at
most `GRIDWISE_GRID_MAX_ELEMENTS` (5,000) elements. Bodies over the limit are refused with
`413` before a route reads them, whether or not they declare a length.

### 9. Host check

The API answers only to the hosts in `GRIDWISE_ALLOWED_HOSTS` (default `localhost`,
`127.0.0.1`, `::1`). Without authentication, a web page could otherwise point its own
domain at 127.0.0.1 (DNS rebinding), become same-origin with the API and bypass CORS. The
page cannot choose the Host header its browser sends, so refusing unknown hosts closes this.
Wildcards are refused.

Cross-site HTML forms are kept out separately: they can send only `text/plain`,
form-encoded or multipart bodies without a preflight, and the API accepts JSON only. Both
are tested.

### 10. CORS

Configured origins may now send `POST`, `PUT`, `PATCH` and `DELETE` with `If-Match`, and read
`ETag` and `Location`. Origins are still listed explicitly; there is no wildcard.

## Failure semantics

| Situation                                   | Status          | `code`                                                     |
| ------------------------------------------- | --------------- | ---------------------------------------------------------- |
| Grid absent or another tenant's             | 404             | `grid_not_found`                                           |
| Element key absent                          | 404             | `asset_not_found`                                          |
| Asset type in the path not one of the seven | 422             | `validation_error` (a malformed path, like a malformed id) |
| Host header not configured                  | 400             | `invalid_host`                                             |
| Malformed request                           | 422             | `validation_error`                                         |
| The engine rejects the resulting grid       | 422             | `grid_validation_failed`                                   |
| More elements than allowed                  | 422             | `grid_too_large`                                           |
| Missing / malformed / stale `If-Match`      | 428 / 400 / 412 | see above                                                  |
| Name already used in the organisation       | 409             | `grid_name_conflict`                                       |
| Body too large                              | 413             | `request_too_large`                                        |
| No development tenant configured            | 503             | `development_tenant_not_configured`                        |
| Anything else                               | 500             | `internal_error`, logged; nothing stored                   |

## What this does not establish

- **Access control.** Anyone who can reach the API acts for the development tenant. The API
  must not be exposed beyond localhost until P6.
- **Results.** No power flow runs through the API. Runs and results are P1.3.

## Consequences

- The safety boundary's read-only test is replaced by an exact list of allowed routes and
  methods. The platform endpoints stay read-only; every write is under `/api/v1/grids` and
  changes stored simulation data only.
- A new route must be added to that list deliberately.
