# Safety boundary and data provenance

## What GRIDWISE must never do

GRIDWISE is a simulation, monitoring and decision-support product. It must not:

- issue real-world switching commands,
- operate substations or control breakers,
- write to SCADA or any other operational-technology system.

This is a design constraint, not a configuration option. There is no outbound integration
to any control system, and none may be added without a new, explicitly approved decision
record.

How the boundary is kept visible:

- `GET /api/v1/system/info` states the operating mode, and the web shell shows it on every
  page.
- A test asserts that the P0 API exposes read-only endpoints only
  (`apps/api/tests/unit/test_system.py`). When write endpoints arrive, that test is replaced
  by an explicit allow-list, not deleted.
- Simulation "actions" (for example opening a switch in a scenario) change simulated state
  only and are named and labelled as simulation.

## Data provenance

- Every grid and every measurement carries a non-null provenance: `synthetic`,
  `public_dataset` or `customer`.
- Synthetic values are never presented as measured values. The UI labels them.
- Illustrative animation is kept separate from power-flow results; only the latter are shown
  as numbers.
- Model metrics computed on synthetic data describe the generator, not a real network, and
  are labelled that way.

## Current security posture (P0)

| Area               | State                                                                                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authentication     | **None.** Planned for P6. Do not expose the API beyond localhost.                                                                                                               |
| Authorisation      | None.                                                                                                                                                                           |
| Tenant isolation   | **Not complete.** The database mechanism is in place and tested on one table (decisions 0004, 0006); no API code sets tenant context yet.                                       |
| Database roles     | The API connects as `gridwise_app`: no superuser, no `BYPASSRLS`, owns nothing, explicit grants only. Migrations use `gridwise_owner`. The superuser is used by no application. |
| Network exposure   | Compose binds every port to `127.0.0.1`.                                                                                                                                        |
| Secrets            | `.env` is git-ignored; `.env.example` holds local-only values. No credential defaults in code. Each container receives only its own role's credentials.                         |
| Secret leakage     | Database URLs are `SecretStr`; validation errors never echo input; SQL parameters are hidden from error messages; tracebacks are logged without local variables.                |
| Web build          | The web app reads one public value from `.env`, never the file as a whole. `pnpm check:bundle` fails if a sensitive name or value appears in the build output.                  |
| Error responses    | One JSON shape with a request ID. No stack traces, exception messages or echoed input.                                                                                          |
| Logs               | Every line from the API and migration containers is JSON, including uvicorn and Alembic output and unhandled exceptions.                                                        |
| CORS               | Explicit origin list; `*` is rejected at startup. GET only.                                                                                                                     |
| Web headers        | Content-Security-Policy, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy` on every page.                                                    |
| Log injection      | Caller request IDs are accepted only if they match a strict pattern.                                                                                                            |
| Containers         | API and web run as non-root users.                                                                                                                                              |
| Database telemetry | TimescaleDB usage reporting is switched off (decision 0003).                                                                                                                    |
| Dependencies       | pip-audit and pnpm audit in CI; Dependabot weekly.                                                                                                                              |

### Known gaps (accepted for P0, tracked)

- The Content-Security-Policy allows inline scripts (`script-src 'unsafe-inline'`), which
  Next.js needs without a per-request nonce. It still blocks third-party scripts, framing,
  plugins and connections to any origin other than the API.
- No `Strict-Transport-Security`: there is no HTTPS deployment yet.
- `/docs` and `/openapi.json` are served in every environment.
- Passwords are interpolated into connection URLs without encoding (decision 0006).
- The database connection is not encrypted (single-host development stack).
- A crash before logging is configured (for example invalid settings at start-up) prints a
  plain Python traceback, not JSON.
- GitHub Actions and base images are pinned by tag, not by digest.
