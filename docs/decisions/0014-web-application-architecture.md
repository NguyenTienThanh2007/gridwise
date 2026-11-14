# 0014 — Web application architecture (P1.4)

- Status: accepted (P1.4 plan, 2026-11-14). Uses the APIs of decisions 0009 and 0013 as they are.

## Context

P1.4 turns the web shell into a working 2D grid and simulation application: grids, the
network diagram, asset tables, scenarios, simulation jobs and their results. The backend
needs no change. The web app must stay honest about what it shows (synthetic grids,
simulated results, no values where the engine has none), must not look like a control
system, and must not suggest that the fixed development tenant is sign-in.

## Decisions

### 1. Data is fetched in the browser, through one client

Pages are server components that render a client view. Views fetch from the API in the
browser, as the dashboard already does: `NEXT_PUBLIC_API_URL` is the browser's address for
the API, and a server-side fetch would need a second, container-internal one. Nothing the
API returns is cached at build time.

Every call goes through `src/lib/http/client.ts`: one timeout, `If-Match` and
`Idempotency-Key` headers, the version from a strong `ETag`, and the API's error envelope
decoded into one `ApiFailure` with these kinds:

| Kind            | When                                                                  |
| --------------- | --------------------------------------------------------------------- |
| `unreachable`   | Network error, CORS refusal or timeout                                |
| `not_available` | FastAPI's own `404 not_found`: the routes are absent (not local/test) |
| `no_tenant`     | `503 development_tenant_not_configured`                               |
| `not_found`     | A resource `404` (`grid_not_found`, `job_not_found`, …)               |
| `conflict`      | `409`, or `412` with the current version from its `ETag`              |
| `invalid`       | `400`, `422` or `428`, with the API's `details`                       |
| `server`        | `5xx`: only the request id is shown                                   |
| `unexpected`    | Any other status, or a body of the wrong shape                        |
| `aborted`       | The caller cancelled (the page was left)                              |

The client never retries by itself.

### 2. D1 — Hand-written decoders, no validation library

Responses are decoded field by field (`src/lib/resources/decode.ts`). A field of the wrong
type, a non-finite number or an unknown enum value makes the whole payload fail to decode,
which the UI shows as an `unexpected` failure: never a partly decoded object, never a
guessed value. `data_origin` is decoded, not assumed, so a future origin cannot be shown
under the wrong label. This keeps the runtime dependencies at `next`, `react` and
`react-dom`.

### 3. Honest content

- No mock data in the application. Test fixtures live in `src/test/fixtures`, say so, and a
  unit test fails if application code imports them.
- Grids show their `data_origin` ("Synthetic data"); results will be labelled "Simulated
  result, not a measurement".
- `null` from the API is shown as "–" with its reason (for example de-energised), never as
  zero. A run that did not converge shows no numbers at all.
- No voltage bands or other limits the engine does not model; only "above 100 % of its own
  rating", which the summary reports.
- No control vocabulary: switches have a "model position", set in the stored simulation
  model; nothing is "operated", "tripped" or "sent".
- Every page with tenant data shows the development-mode notice: there is no sign-in, the
  build acts for one fixed development organisation, and it is not access control.

### 4. D2 — Results on the diagram only for the solved topology

There is no endpoint for the topology a job solved. Loading is drawn on the network diagram
only when the grid's current `topology_hash` equals the job's `source.topology_hash`;
otherwise results are shown as tables, with the reason. Scenario changes are named next to
the diagram.

### 5. D3 — End-to-end tests run against a seeded stack

The CI end-to-end job seeds the synthetic demonstration grid
(`docker compose run --rm -e GRIDWISE_ENVIRONMENT=local migrate python -m gridwise_api.seed`)
from P1.4a, and starts the worker profile from P1.4d, when tests first need jobs solved.

### 6. D4 — Tests that write use their own grids

End-to-end tests that change data copy the demonstration topology into their own uniquely
named grid through the API and delete it afterwards; they never change the shared
demonstration grid. Jobs and scenarios they create remain, recognisable by their names.

### 7. D5 — Grid editing is limited to what the UI can do safely

The UI renames a grid, edits its description and deletes it (with confirmation). It does
not create grids or replace a topology: both take a whole network as JSON and stay API-only.

### 8. D6 — Assets are per grid

Asset tables live under `/grid/[id]/assets`, because every asset belongs to one grid
version; `/assets` lets the user choose a grid.

### 9. Polling

A job page polls its job every second for the first ten seconds, then every two seconds,
then every five, pauses while the tab is hidden, keeps at most one request in flight, and
stops at a terminal status. Lists refresh on request.

## Consequences

- P1.4 is five PRs (roadmap): a foundations and grids, b network explorer, c asset
  management, d simulation workspace, e results and reproductions.
- A new runtime dependency needs its own decision.
- The same routes are absent outside local and test; the UI says "Not available in this
  environment" rather than showing an error.
