"""Grid schema: grids and their electrical elements.

Eight tenant-owned tables that persist the engine's model (packages/grid-engine): a grid,
and its buses, lines, transformers, loads, generators, external grids and switches.

Every table follows the conventions of the baseline migration and decisions 0004 and 0006:

* ``organization_id`` on every row, and a row-level security policy for the runtime role;
* composite foreign keys that include ``organization_id`` and ``grid_id``, so a row cannot
  reference another tenant's or another grid's bus, even through a bug;
* the ``core.set_updated_at()`` trigger;
* privileges granted to the runtime role by name. No default privileges.

The database checks what can be decided from one row (signs, ranges, enumerations, values
that must be given together). Rules that span rows, such as voltage levels across a
transformer, belong to the engine's validation.

NaN and infinity: PostgreSQL orders NaN above every number, so ``CHECK (x > 0)`` alone
would accept it. Every numeric column therefore carries an explicit finite check.

No data is inserted here. The synthetic demonstration grid is created by a separate command
(``python -m gridwise_api.seed``), which refuses to run outside local and test environments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "gridwise_app"
SCHEMA = "grid"

# Creation order. Dropped in reverse.
ELEMENT_TABLES = (
    "buses",
    "lines",
    "transformers",
    "loads",
    "generators",
    "external_grids",
    "switches",
)
TABLES = ("grids", *ELEMENT_TABLES)


def _finite(*columns: str) -> list[sa.CheckConstraint]:
    """One check per column: neither NaN nor an infinity. NULL passes (optional columns)."""
    return [
        sa.CheckConstraint(
            f"{column} > '-Infinity'::float8 AND {column} < 'Infinity'::float8",
            name=f"{column}_finite",
        )
        for column in columns
    ]


def _check(name: str, expression: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(expression, name=name)


def _row_columns() -> list[sa.Column[object]]:
    return [
        # uuidv7() is built into PostgreSQL 18: time-ordered keys without an extension.
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _element_columns() -> list[sa.Column[object]]:
    return [
        *_row_columns(),
        sa.Column("grid_id", sa.Uuid(), nullable=False),
        # The element's stable identifier: the engine's element id, and what telemetry and
        # results refer to. Unique per grid within one element type.
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
    ]


def _element_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        # organization_id leads, on purpose. PostgreSQL checks uniqueness when the row is
        # inserted and foreign keys only afterwards. With (grid_id, key) alone, a tenant
        # inserting into another tenant's grid would get "duplicate key" for a key that
        # exists there and "foreign key" for one that does not, and could enumerate that
        # grid's element keys. Scoped to the tenant, the check only ever meets the tenant's
        # own rows. The index also serves every lookup by (organization_id, grid_id).
        sa.UniqueConstraint(
            "organization_id", "grid_id", "key", name=f"uq_{table}_tenant_grid_key"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "grid_id"],
            [f"{SCHEMA}.grids.organization_id", f"{SCHEMA}.grids.id"],
            name=f"fk_{table}_grid",
            ondelete="CASCADE",
        ),
        _check("key_not_blank", "length(btrim(key)) > 0"),
        _check("name_not_blank", "length(btrim(name)) > 0"),
    ]


def _bus_reference(table: str, column: str) -> sa.ForeignKeyConstraint:
    """A bus of the same grid and the same tenant.

    NO ACTION, not RESTRICT: both refuse to delete a bus that still has elements, but
    RESTRICT is checked immediately and would also refuse the cascade that deletes a whole
    grid, where buses and their elements go in one statement.
    """
    return sa.ForeignKeyConstraint(
        ["organization_id", "grid_id", column],
        [f"{SCHEMA}.buses.organization_id", f"{SCHEMA}.buses.grid_id", f"{SCHEMA}.buses.id"],
        name=f"fk_{table}_{column}",
    )


def _create_grids() -> None:
    op.create_table(
        "grids",
        *_row_columns(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("frequency_hz", sa.Double(), nullable=False),
        # Where the data comes from. Only synthetic data is allowed; widening this is a
        # deliberate migration, not a configuration change.
        sa.Column("data_origin", sa.Text(), server_default=sa.text("'synthetic'"), nullable=False),
        # Optimistic concurrency: incremented by every change to the grid or its elements.
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        # The engine's grid_hash of the stored topology (SHA-256, lower-case hex).
        sa.Column("topology_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_grids"),
        sa.UniqueConstraint("organization_id", "name", name="uq_grids_organization_name"),
        # Target of the children's composite foreign keys.
        sa.UniqueConstraint("organization_id", "id", name="uq_grids_organization_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["core.organizations.id"], name="fk_grids_organization"
        ),
        _check("name_not_blank", "length(btrim(name)) > 0"),
        _check("frequency_supported", "frequency_hz IN (50, 60)"),
        _check("data_origin_synthetic", "data_origin = 'synthetic'"),
        _check("version_positive", "version >= 1"),
        _check("topology_hash_format", "topology_hash ~ '^[0-9a-f]{64}$'"),
        schema=SCHEMA,
    )


def _create_buses() -> None:
    op.create_table(
        "buses",
        *_element_columns(),
        sa.Column("nominal_voltage_kv", sa.Double(), nullable=False),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # Schematic diagram position (arbitrary units). Not geographic, not electrical and
        # not part of the topology hash.
        sa.Column("diagram_x", sa.Double(), nullable=True),
        sa.Column("diagram_y", sa.Double(), nullable=True),
        *_element_constraints("buses"),
        # Target of the composite foreign keys of everything attached to a bus.
        sa.UniqueConstraint("organization_id", "grid_id", "id", name="uq_buses_tenant_grid_id"),
        *_finite("nominal_voltage_kv", "diagram_x", "diagram_y"),
        _check("nominal_voltage_positive", "nominal_voltage_kv > 0"),
        _check("diagram_position_complete", "(diagram_x IS NULL) = (diagram_y IS NULL)"),
        schema=SCHEMA,
    )


def _create_lines() -> None:
    op.create_table(
        "lines",
        *_element_columns(),
        sa.Column("from_bus_id", sa.Uuid(), nullable=False),
        sa.Column("to_bus_id", sa.Uuid(), nullable=False),
        sa.Column("length_km", sa.Double(), nullable=False),
        sa.Column("r_ohm_per_km", sa.Double(), nullable=False),
        sa.Column("x_ohm_per_km", sa.Double(), nullable=False),
        sa.Column("c_nf_per_km", sa.Double(), nullable=False),
        sa.Column("max_i_ka", sa.Double(), nullable=False),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_element_constraints("lines"),
        # Target of the switches' composite foreign key.
        sa.UniqueConstraint("organization_id", "grid_id", "id", name="uq_lines_tenant_grid_id"),
        _bus_reference("lines", "from_bus_id"),
        _bus_reference("lines", "to_bus_id"),
        *_finite("length_km", "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"),
        _check("ends_differ", "from_bus_id <> to_bus_id"),
        _check("length_positive", "length_km > 0"),
        _check("resistance_not_negative", "r_ohm_per_km >= 0"),
        _check("reactance_not_negative", "x_ohm_per_km >= 0"),
        _check("impedance_not_zero", "r_ohm_per_km > 0 OR x_ohm_per_km > 0"),
        _check("capacitance_not_negative", "c_nf_per_km >= 0"),
        _check("thermal_limit_positive", "max_i_ka > 0"),
        schema=SCHEMA,
    )
    op.create_index("ix_lines_from_bus_id", "lines", ["from_bus_id"], schema=SCHEMA)
    op.create_index("ix_lines_to_bus_id", "lines", ["to_bus_id"], schema=SCHEMA)


def _create_transformers() -> None:
    tap = (
        "tap_side, tap_neutral_position, tap_min_position, tap_max_position, "
        "tap_step_percent, tap_position"
    )
    op.create_table(
        "transformers",
        *_element_columns(),
        sa.Column("hv_bus_id", sa.Uuid(), nullable=False),
        sa.Column("lv_bus_id", sa.Uuid(), nullable=False),
        sa.Column("rated_power_mva", sa.Double(), nullable=False),
        sa.Column("rated_voltage_hv_kv", sa.Double(), nullable=False),
        sa.Column("rated_voltage_lv_kv", sa.Double(), nullable=False),
        sa.Column("short_circuit_voltage_percent", sa.Double(), nullable=False),
        sa.Column("short_circuit_resistive_percent", sa.Double(), nullable=False),
        sa.Column("iron_losses_kw", sa.Double(), nullable=False),
        sa.Column("no_load_current_percent", sa.Double(), nullable=False),
        sa.Column("phase_shift_degree", sa.Double(), server_default=sa.text("0"), nullable=False),
        # The optional ratio tap changer: all six columns, or none.
        sa.Column("tap_side", sa.Text(), nullable=True),
        sa.Column("tap_neutral_position", sa.Integer(), nullable=True),
        sa.Column("tap_min_position", sa.Integer(), nullable=True),
        sa.Column("tap_max_position", sa.Integer(), nullable=True),
        sa.Column("tap_step_percent", sa.Double(), nullable=True),
        sa.Column("tap_position", sa.Integer(), nullable=True),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_element_constraints("transformers"),
        sa.UniqueConstraint(
            "organization_id", "grid_id", "id", name="uq_transformers_tenant_grid_id"
        ),
        _bus_reference("transformers", "hv_bus_id"),
        _bus_reference("transformers", "lv_bus_id"),
        *_finite(
            "rated_power_mva",
            "rated_voltage_hv_kv",
            "rated_voltage_lv_kv",
            "short_circuit_voltage_percent",
            "short_circuit_resistive_percent",
            "iron_losses_kw",
            "no_load_current_percent",
            "phase_shift_degree",
            "tap_step_percent",
        ),
        _check("sides_differ", "hv_bus_id <> lv_bus_id"),
        _check("rated_power_positive", "rated_power_mva > 0"),
        _check("rated_voltage_lv_positive", "rated_voltage_lv_kv > 0"),
        _check("rated_voltage_hv_above_lv", "rated_voltage_hv_kv > rated_voltage_lv_kv"),
        _check("short_circuit_voltage_positive", "short_circuit_voltage_percent > 0"),
        _check(
            "short_circuit_resistive_in_range",
            "short_circuit_resistive_percent >= 0 "
            "AND short_circuit_resistive_percent <= short_circuit_voltage_percent",
        ),
        _check("iron_losses_not_negative", "iron_losses_kw >= 0"),
        # The no-load apparent power cannot be smaller than its active part, the iron
        # losses: i0 [%] >= iron losses [kW] / (10 * rated power [MVA]). Same rule and
        # same slack for rounded nameplate data as the engine's validation. Written as a
        # product: a division would raise "division by zero" for a rated power of 0
        # instead of reporting the check that row violates.
        _check(
            "no_load_current_covers_iron_losses",
            "no_load_current_percent >= 0 AND no_load_current_percent * rated_power_mva * 10 "
            ">= iron_losses_kw * (1 - 1e-9)",
        ),
        _check("tap_complete", f"num_nonnulls({tap}) IN (0, 6)"),
        _check("tap_side_known", "tap_side IN ('hv', 'lv')"),
        _check("tap_step_positive", "tap_step_percent > 0"),
        _check(
            "tap_range_ordered",
            "tap_min_position <= tap_neutral_position AND tap_neutral_position <= tap_max_position",
        ),
        _check(
            "tap_position_in_range",
            "tap_position >= tap_min_position AND tap_position <= tap_max_position",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_transformers_hv_bus_id", "transformers", ["hv_bus_id"], schema=SCHEMA)
    op.create_index("ix_transformers_lv_bus_id", "transformers", ["lv_bus_id"], schema=SCHEMA)


def _create_loads() -> None:
    op.create_table(
        "loads",
        *_element_columns(),
        sa.Column("bus_id", sa.Uuid(), nullable=False),
        sa.Column("p_mw", sa.Double(), nullable=False),
        sa.Column("q_mvar", sa.Double(), nullable=False),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_element_constraints("loads"),
        _bus_reference("loads", "bus_id"),
        *_finite("p_mw", "q_mvar"),
        _check("active_power_not_negative", "p_mw >= 0"),
        schema=SCHEMA,
    )
    op.create_index("ix_loads_bus_id", "loads", ["bus_id"], schema=SCHEMA)


def _create_generators() -> None:
    op.create_table(
        "generators",
        *_element_columns(),
        sa.Column("bus_id", sa.Uuid(), nullable=False),
        sa.Column("p_mw", sa.Double(), nullable=False),
        sa.Column("control_mode", sa.Text(), nullable=False),
        sa.Column("q_mvar", sa.Double(), nullable=True),
        sa.Column("voltage_setpoint_pu", sa.Double(), nullable=True),
        sa.Column("min_q_mvar", sa.Double(), nullable=True),
        sa.Column("max_q_mvar", sa.Double(), nullable=True),
        sa.Column("rated_power_mva", sa.Double(), nullable=True),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_element_constraints("generators"),
        _bus_reference("generators", "bus_id"),
        *_finite(
            "p_mw", "q_mvar", "voltage_setpoint_pu", "min_q_mvar", "max_q_mvar", "rated_power_mva"
        ),
        _check("active_power_not_negative", "p_mw >= 0"),
        _check("control_mode_known", "control_mode IN ('constant_power', 'voltage_control')"),
        # Each mode has its own fields; a field of the other mode is an error, not ignored.
        _check(
            "fields_match_control_mode",
            "(control_mode = 'constant_power' AND q_mvar IS NOT NULL "
            "AND voltage_setpoint_pu IS NULL AND min_q_mvar IS NULL AND max_q_mvar IS NULL) "
            "OR (control_mode = 'voltage_control' AND voltage_setpoint_pu IS NOT NULL "
            "AND q_mvar IS NULL)",
        ),
        _check("voltage_setpoint_positive", "voltage_setpoint_pu > 0"),
        _check("reactive_limits_paired", "(min_q_mvar IS NULL) = (max_q_mvar IS NULL)"),
        _check("reactive_limits_ordered", "min_q_mvar <= max_q_mvar"),
        _check("rated_power_positive", "rated_power_mva > 0"),
        _check(
            "setpoint_within_rating",
            "rated_power_mva IS NULL OR p_mw * p_mw + coalesce(q_mvar, 0) * coalesce(q_mvar, 0) "
            "<= power(rated_power_mva * (1 + 1e-9), 2)",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_generators_bus_id", "generators", ["bus_id"], schema=SCHEMA)


def _create_external_grids() -> None:
    op.create_table(
        "external_grids",
        *_element_columns(),
        sa.Column("bus_id", sa.Uuid(), nullable=False),
        sa.Column("voltage_pu", sa.Double(), server_default=sa.text("1"), nullable=False),
        sa.Column("voltage_angle_degree", sa.Double(), server_default=sa.text("0"), nullable=False),
        sa.Column("in_service", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_element_constraints("external_grids"),
        _bus_reference("external_grids", "bus_id"),
        *_finite("voltage_pu", "voltage_angle_degree"),
        _check("voltage_positive", "voltage_pu > 0"),
        schema=SCHEMA,
    )
    op.create_index("ix_external_grids_bus_id", "external_grids", ["bus_id"], schema=SCHEMA)


def _create_switches() -> None:
    def target(column: str, table: str) -> sa.ForeignKeyConstraint:
        # MATCH SIMPLE (the default): not checked while the column is NULL, which is the
        # case for the two targets a switch does not have.
        return sa.ForeignKeyConstraint(
            ["organization_id", "grid_id", column],
            [
                f"{SCHEMA}.{table}.organization_id",
                f"{SCHEMA}.{table}.grid_id",
                f"{SCHEMA}.{table}.id",
            ],
            name=f"fk_switches_{column}",
        )

    op.create_table(
        "switches",
        *_element_columns(),
        sa.Column("bus_id", sa.Uuid(), nullable=False),
        # What the switch connects its bus to: exactly one of these three.
        sa.Column("line_id", sa.Uuid(), nullable=True),
        sa.Column("transformer_id", sa.Uuid(), nullable=True),
        sa.Column("other_bus_id", sa.Uuid(), nullable=True),
        # A state of the simulated network. Not a command; nothing sends it to equipment.
        sa.Column("closed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'load_break_switch'"), nullable=False),
        *_element_constraints("switches"),
        _bus_reference("switches", "bus_id"),
        target("line_id", "lines"),
        target("transformer_id", "transformers"),
        target("other_bus_id", "buses"),
        _check("exactly_one_target", "num_nonnulls(line_id, transformer_id, other_bus_id) = 1"),
        _check("buses_differ", "other_bus_id <> bus_id"),
        _check(
            "kind_known",
            "kind IN ('circuit_breaker', 'load_break_switch', 'disconnector', 'load_switch')",
        ),
        schema=SCHEMA,
    )
    for column in ("bus_id", "line_id", "transformer_id", "other_bus_id"):
        op.create_index(f"ix_switches_{column}", "switches", [column], schema=SCHEMA)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")

    _create_grids()
    _create_buses()
    _create_lines()
    _create_transformers()
    _create_loads()
    _create_generators()
    _create_external_grids()
    _create_switches()

    for table in TABLES:
        op.execute(
            f"""
            CREATE TRIGGER set_updated_at BEFORE UPDATE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()
            """
        )
        # A runtime session reads and writes only rows of the organisation named by its
        # transaction's tenant context, and nothing at all without one. WITH CHECK makes
        # the same rule apply to rows it tries to create or move.
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {SCHEMA}.{table}
            FOR ALL TO {RUNTIME_ROLE}
            USING (organization_id = core.current_organization_id())
            WITH CHECK (organization_id = core.current_organization_id())
            """
        )

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {RUNTIME_ROLE}")
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO {RUNTIME_ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {SCHEMA}.{table}")
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {RUNTIME_ROLE}")
    op.execute(f"DROP SCHEMA {SCHEMA}")
