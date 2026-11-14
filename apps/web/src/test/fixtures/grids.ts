/**
 * TEST FIXTURES ONLY. Payloads shaped like the API's documented responses (decision 0009),
 * for unit tests. Not data: never imported by application code (a test checks that), and
 * the names and values are invented for tests.
 */

export const FIXTURE_GRID_ID = "0a0a0a0a-0000-4000-8000-0000000000f1";

export function fixtureGrid(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: FIXTURE_GRID_ID,
    name: "Fixture feeder",
    description: "Unit-test fixture, not a real network.",
    frequency_hz: 50.0,
    data_origin: "synthetic",
    version: 3,
    topology_hash: "ab".repeat(32),
    element_counts: {
      buses: 4,
      lines: 3,
      transformers: 1,
      loads: 2,
      generators: 1,
      external_grids: 1,
      switches: 1,
    },
    created_at: "2026-11-14T10:00:00.000000Z",
    updated_at: "2026-11-14T11:30:00.000000Z",
    ...overrides,
  };
}

export function fixtureGridPage(items: Record<string, unknown>[], total = items.length) {
  return { items, total, limit: 25, offset: 0 };
}

export function fixtureTopology(): Record<string, unknown> {
  return {
    grid_id: FIXTURE_GRID_ID,
    version: 3,
    topology_hash: "ab".repeat(32),
    data_origin: "synthetic",
    topology: {
      frequency_hz: 50.0,
      buses: [
        {
          key: "hv",
          name: "HV",
          nominal_voltage_kv: 110.0,
          in_service: true,
          diagram: { x: 0, y: 2 },
        },
        { key: "a", name: "A", nominal_voltage_kv: 20.0, in_service: true, diagram: null },
      ],
      lines: [
        {
          key: "l1",
          name: "L1",
          from_bus_key: "a",
          to_bus_key: "b",
          length_km: 1.5,
          r_ohm_per_km: 0.5,
          x_ohm_per_km: 0.4,
          c_nf_per_km: 10.0,
          max_i_ka: 0.3,
          in_service: true,
        },
      ],
      transformers: [
        {
          key: "t1",
          name: "T1",
          hv_bus_key: "hv",
          lv_bus_key: "a",
          rated_power_mva: 25.0,
          rated_voltage_hv_kv: 110.0,
          rated_voltage_lv_kv: 20.0,
          short_circuit_voltage_percent: 12.0,
          short_circuit_resistive_percent: 0.4,
          iron_losses_kw: 14.0,
          no_load_current_percent: 0.07,
          phase_shift_degree: 0.0,
          tap: {
            side: "hv",
            neutral_position: 0,
            min_position: -9,
            max_position: 9,
            step_percent: 1.5,
            position: 0,
          },
          in_service: true,
        },
      ],
      loads: [
        { key: "load-a", name: "Load A", bus_key: "a", p_mw: 2.0, q_mvar: 0.5, in_service: true },
      ],
      generators: [
        {
          key: "pv",
          name: "PV",
          bus_key: "a",
          p_mw: 0.5,
          control_mode: "constant_power",
          q_mvar: 0.0,
          voltage_setpoint_pu: null,
          min_q_mvar: null,
          max_q_mvar: null,
          rated_power_mva: null,
          in_service: true,
        },
      ],
      external_grids: [
        {
          key: "upstream",
          name: "Upstream",
          bus_key: "hv",
          voltage_pu: 1.0,
          voltage_angle_degree: 0.0,
          in_service: true,
        },
      ],
      switches: [
        {
          key: "s1",
          name: "S1",
          bus_key: "a",
          element_type: "line",
          element_key: "l1",
          closed: false,
          kind: "load_break_switch",
        },
      ],
    },
  };
}
