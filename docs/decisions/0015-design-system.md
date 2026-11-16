# 0015 — Design system: Industrial Minimalism

- Status: accepted (UI redesign, 2026-11-15). Extends decision 0014. Frontend only.

## Context

GRIDWISE is engineering software for simulation and decision support. By P1.4d the web app
worked but read as a generic dashboard: ten colour tokens and nothing else, three radii used
interchangeably, no type scale, a box around almost every section, one teal colour for links,
tabs, selection, buttons and success alike, the development notice repeated on every page,
four copies of the label-and-value row and two copies of the table.

A read-only audit (baseline screenshots of 13 pages at 1440, 1280, 768 and 390 px) led to a
redesign in five reviewable PRs: UI-1 tokens, shell and primitives; UI-2 dashboard and grid
list; UI-3 grid overview and network explorer; UI-4 assets and settings; UI-5 simulation
workspace. The result views are built with P1.4e on this system, not speculatively.

## Decisions

### 1. Tokens

All in `apps/web/src/app/globals.css` (`@theme`). Components use the tokens, never raw
colours.

| Group      | Tokens                                                                                                                                                     |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Neutrals   | `surface` (page), `panel`, `sunken` (table headers, strips), `line`, `line-strong`, `ink`, `muted`, `subtle`, `rail`, `rail-ink`, `rail-line`              |
| Accent     | `accent` (#1F5FBF), `accent-hover`, `accent-subtle`: primary actions, current navigation and tab, selection, focus only                                    |
| Semantic   | `ok`, `warn`, `bad`, each with `-subtle`                                                                                                                   |
| Provenance | `provenance`, `provenance-subtle`: "Synthetic data" is where data comes from, not a warning                                                                |
| Type       | System sans and monospace stacks (no web font); roles `text-page-title` (20 px), `text-section-title` (12 px, uppercase), `text-label` (13 px); body 14 px |
| Geometry   | `rounded-control` 2 px, `rounded-panel` 4 px; nothing rounder; 1 px borders; no shadows                                                                    |
| Density    | Controls 32 px high (28 small), table rows 36 px, sticky table headers                                                                                     |
| Motion     | Colour changes at most 100 ms; none under `prefers-reduced-motion`                                                                                         |

The theme is light first; the tokens are named so a dark theme can be added later.

### 2. Components

One of each, in `src/components/ui` unless noted:

- **Shell** (`app-shell.tsx`): a 216 px graphite rail from 1024 px, a drawer below (menu
  button, focus moves into it, Escape and navigation close it). Working sections first;
  sections that are still placeholders grouped under "Planned" with their roadmap phase.
  One strip above every page states "Simulation and decision support only" and the
  development mode, so pages no longer repeat the notice.
- **PageHeader** (`page-header.tsx`): breadcrumb, title, meta (provenance, version, status),
  summary, actions, and tabs attached to its bottom edge.
- **Button** with `buttonClass` for links that act as buttons: primary, secondary, ghost,
  danger; sizes sm and md.
- **Chip**: one shape for status, service state, model position and provenance; the text
  always states the state.
- **Section** (a title, no box) and **Panel** (a box, only where a boundary means something).
- **PropertyList / Property**: every label-and-value list.
- **DataTable**: every table, including the asset inventory; numeric columns right-aligned
  with tabular figures; scrolls inside its own box on narrow screens.
- **Fields**, **Tabs**, **Notice** (a coloured edge, not a coloured box), **EmptyState**,
  **LoadingState** (a quiet line, nothing that moves), **ErrorState**.
- **Icons** (`icons.tsx`): at most ten, drawn here, 1.5 px stroke; navigation and canvas
  controls only. No icon or UI library.

### 3. Verification

Every redesign PR is checked in a real browser against a throwaway local stack (real API,
worker and database, real sample jobs): screenshots of every changed page at the four
widths, inspected and compared with the baseline, defects fixed and captured again. The
end-to-end suite asserts that no page scrolls sideways and none logs a console error at any
of the four widths (`e2e/layout.spec.ts`). There are no pixel-diff assertions: they are
brittle across operating systems and fonts.

### 4. What the redesign never changes

API contracts, decoders, simulation behaviour, the safety and provenance wording, the
"no values" rules, and accessible names that tests rely on (a deliberate text change updates
its test in the same PR).

## Consequences

- New UI uses these components and tokens; a new variant is added to the component, not
  written inline.
- A dark theme, if wanted, is a token change, not a component change.
