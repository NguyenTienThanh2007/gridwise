/**
 * TEST FIXTURES ONLY. Payloads shaped like the simulation API's documented responses
 * (decision 0013), for unit tests. Invented values; never imported by application code.
 */

import { FIXTURE_GRID_ID } from "@/test/fixtures/grids";

export const FIXTURE_JOB_ID = "01a1dd8f-0000-7000-8000-0000000000a1";
export const FIXTURE_SCENARIO_ID = "01a1dd8f-0000-7000-8000-0000000000b1";

export function fixtureJob(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: FIXTURE_JOB_ID,
    status: "queued",
    outcome: null,
    attempt: 0,
    max_attempts: 3,
    source: {
      grid_id: FIXTURE_GRID_ID,
      grid_version: 3,
      topology_hash: "ab".repeat(32),
      status: "current",
    },
    scenario: {
      id: null,
      spec_hash: "cd".repeat(32),
      specification: { schema: "gridwise.scenario/1", modifications: [] },
    },
    configuration: {
      algorithm: "newton_raphson",
      tolerance_mva: 1e-8,
      max_iterations: 10,
      hash: "ef".repeat(32),
    },
    engine: {
      requested_version: "0.3.0",
      executed_version: null,
      solver_name: null,
      solver_version: null,
      fingerprint: null,
    },
    input_snapshot_hash: "12".repeat(32),
    failure: null,
    created_at: "2026-11-15T04:58:00Z",
    started_at: null,
    finished_at: null,
    cancelled_at: null,
    links: {
      self: `/api/v1/simulations/${FIXTURE_JOB_ID}`,
      result: `/api/v1/simulations/${FIXTURE_JOB_ID}/result`,
      reproductions: `/api/v1/simulations/${FIXTURE_JOB_ID}/reproductions`,
    },
    attempts: [],
    ...overrides,
  };
}

export const COMPLETED = {
  status: "completed",
  outcome: "converged",
  attempt: 1,
  started_at: "2026-11-15T04:58:01Z",
  finished_at: "2026-11-15T04:58:02Z",
  engine: {
    requested_version: "0.3.0",
    executed_version: "0.3.0",
    solver_name: "pandapower",
    solver_version: "3.5.6",
    fingerprint: "34".repeat(32),
  },
  attempts: [
    {
      attempt: 1,
      started_at: "2026-11-15T04:58:01Z",
      ended_at: "2026-11-15T04:58:02Z",
      ended_by: "completed",
    },
  ],
};

export function fixtureScenario(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: FIXTURE_SCENARIO_ID,
    name: "Fixture peak",
    description: "Unit-test fixture.",
    spec_hash: "cd".repeat(32),
    specification: {
      schema: "gridwise.scenario/1",
      modifications: [
        { type: "scale_loads", factor: 1.2 },
        { type: "scale_generation", factor: 0, keys: ["pv-1"], control_mode: "constant_power" },
        { type: "set_in_service", element_type: "line", key: "l1", in_service: false },
        { type: "set_switch", key: "s1", closed: true },
      ],
    },
    created_at: "2026-11-15T04:00:00Z",
    ...overrides,
  };
}
