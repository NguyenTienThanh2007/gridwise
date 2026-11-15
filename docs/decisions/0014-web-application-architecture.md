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

### 10. The network diagram (P1.4b)

The explorer draws the stored network as SVG, with no graphics library.

- **Positions.** Buses use their stored diagram positions when every bus has one; y is
  flipped (it grows upwards in the data) and the drawing is scaled so the closest buses are
  80 units apart. If any bus has no position, every bus is placed by the fallback layout,
  with a notice: mixing stored and computed positions would look arbitrary.
- **Fallback layout.** Buses joined by lines, transformers and bus couplers form connected
  parts. Parts with an external grid come first, then by smallest key. Each part is laid out
  in layers by breadth-first search from its external-grid buses (or its smallest key),
  visiting neighbours in natural key order; a layer is ordered by parent, then key. Parts
  sit side by side. The same network always gives the same drawing.
- **What is drawn.** Exactly the stored relationships: each line, transformer and bus
  coupler between its own buses (parallel ones fanned out); each line or transformer switch
  on its element, a quarter of the way from the bus it sits at; loads, generators and
  external grids next to their bus (four per type per bus, then a "+n" badge). Connections
  are drawn whatever their service state or switch position, so the drawing does not move
  when a switch changes.
- **What is not computed.** Energisation, supply paths or any other electrical state from
  switch positions: that is the solver's job and comes with results (P1.4e).
- **Broken references** (impossible for a grid the engine accepted) are listed and nothing
  is drawn, rather than guessing a connection.
- **Interaction.** Click an element, or choose it in the element list, which is the keyboard
  path; the inspector shows its stored values and selects what it refers to. The selection
  is kept in the address (`?element=lines:line-6-7`). Zoom in, zoom out and fit are buttons;
  dragging pans; the mouse wheel scrolls the page, never the diagram.
- **States** are told apart by shape and dash as well as colour: an open switch is a hollow
  square, a closed one filled; out-of-service elements are dashed and named so.

### 11. Editing (P1.4c)

- **Where.** Each grid has three tabs with their own addresses: Overview (details and the
  network explorer), Assets and Settings. Grid and topology are loaded together for every
  tab and reloaded together after a write, keeping the last answer on screen meanwhile, so
  the header, table, inspector and diagram always show one version and open forms keep their
  text. The explorer's inspector stays read-only and links to the Assets tab.
- **What.** Exactly what the API accepts: an element's name, and either its service state
  or, for a switch, its position in the stored simulation model. Electrical parameters are
  not editable in the web app. The grid's name (a rename changes its topology hash) and
  description are edited in Settings.
- **How.** Limits as in the API (name 1–200 characters and not blank, description up to
  2000). Save stays disabled until something changes, because every write moves the
  version on. A service-state or model-position change shows a review step first: it
  changes the stored simulation model only and sends nothing to any equipment.
- **Versions.** Every write sends `If-Match` with the version the user saw. On `412` the
  draft is kept, the current version is shown, and nothing is resent until the user has
  reloaded and pressed Save again. Engine refusals (`422 grid_validation_failed`) and name
  conflicts (`409`) are shown with the API's reasons.
- **Deleting a grid** needs its exact name typed, says that it cannot be undone and that
  simulation jobs keep their own copies, sends `If-Match`, and returns to the grid list.
- **Filters** live in the component and are copied to the address, built from the live URL:
  reading them back from the router would lose keystrokes made before it caught up.

## Consequences

- P1.4 is five PRs (roadmap): a foundations and grids, b network explorer, c asset
  management, d simulation workspace, e results and reproductions.
- A new runtime dependency needs its own decision.
- The same routes are absent outside local and test; the UI says "Not available in this
  environment" rather than showing an error.
