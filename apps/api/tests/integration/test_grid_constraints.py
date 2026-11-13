"""Row checks of the grid schema: the database refuses what one row can show to be wrong.

Each case takes a valid stored grid and changes one value. The update must fail with a
check violation. The untouched grid is the control: it was stored through the same
constraints.

Rules that span several rows (voltage levels across a transformer, one voltage controller
per bus, a switch at a terminal of its element) are not database rules; the engine's
validation owns them.
"""

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids
from gridwise_api.tenancy import tenant_transaction
from tests.support.grids import SAMPLE_COORDINATES, sample_grid

pytestmark = pytest.mark.integration

CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
NOT_NULL_VIOLATION = "23502"


@pytest.fixture
async def grid_id(tenants: dict[str, uuid.UUID], owner_async_engine: AsyncEngine) -> uuid.UUID:
    async with tenant_transaction(owner_async_engine, tenants["alpha"]) as session:
        record = await grids.create_grid(
            session, sample_grid(), diagram_coordinates=SAMPLE_COORDINATES
        )
    return record.id


def _violation(engine: Engine, statement: str) -> str | None:
    """SQLSTATE of the integrity error a statement causes, or None if it succeeds."""
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    except IntegrityError as error:
        return getattr(error.orig, "sqlstate", None)
    return None


NOT_FINITE = ("'NaN'", "'Infinity'", "'-Infinity'")

# (table, column) of every double precision column in the schema.
NUMERIC_COLUMNS = [
    ("buses", "nominal_voltage_kv"),
    ("buses", "diagram_x"),
    ("buses", "diagram_y"),
    ("lines", "length_km"),
    ("lines", "r_ohm_per_km"),
    ("lines", "x_ohm_per_km"),
    ("lines", "c_nf_per_km"),
    ("lines", "max_i_ka"),
    ("transformers", "rated_power_mva"),
    ("transformers", "rated_voltage_hv_kv"),
    ("transformers", "rated_voltage_lv_kv"),
    ("transformers", "short_circuit_voltage_percent"),
    ("transformers", "short_circuit_resistive_percent"),
    ("transformers", "iron_losses_kw"),
    ("transformers", "no_load_current_percent"),
    ("transformers", "phase_shift_degree"),
    ("transformers", "tap_step_percent"),
    ("loads", "p_mw"),
    ("loads", "q_mvar"),
    ("generators", "p_mw"),
    ("generators", "q_mvar"),
    ("generators", "voltage_setpoint_pu"),
    ("generators", "min_q_mvar"),
    ("generators", "max_q_mvar"),
    ("generators", "rated_power_mva"),
    ("external_grids", "voltage_pu"),
    ("external_grids", "voltage_angle_degree"),
]


def test_the_numeric_column_list_is_complete(migrated: None, owner_engine: Engine) -> None:
    """A new numeric column must be added to the list above, and so get its finite check."""
    with owner_engine.connect() as connection:
        actual = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'grid' AND data_type = 'double precision' "
                "AND table_name <> 'grids'"
            )
        ).all()
    assert sorted(tuple(row) for row in actual) == sorted(NUMERIC_COLUMNS)


@pytest.mark.parametrize(("table", "column"), NUMERIC_COLUMNS)
@pytest.mark.parametrize("value", NOT_FINITE)
def test_nan_and_infinity_are_rejected_in_every_numeric_column(
    grid_id: uuid.UUID, owner_engine: Engine, table: str, column: str, value: str
) -> None:
    statement = f"UPDATE grid.{table} SET {column} = {value}::float8"  # noqa: S608
    assert _violation(owner_engine, statement) == CHECK_VIOLATION


def test_nan_would_pass_a_plain_range_check(migrated: None, owner_engine: Engine) -> None:
    """Why the explicit finite checks exist: PostgreSQL orders NaN above every number."""
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT 'NaN'::float8 > 0")).scalar_one() is True


@pytest.mark.parametrize(
    "statement",
    [
        # grids
        "UPDATE grid.grids SET name = '   '",
        "UPDATE grid.grids SET frequency_hz = 55",
        "UPDATE grid.grids SET frequency_hz = 'NaN'::float8",
        "UPDATE grid.grids SET data_origin = 'measured'",
        "UPDATE grid.grids SET data_origin = 'real'",
        "UPDATE grid.grids SET version = 0",
        "UPDATE grid.grids SET topology_hash = 'not-a-hash'",
        "UPDATE grid.grids SET topology_hash = upper(topology_hash)",
        # every element
        "UPDATE grid.buses SET key = ' '",
        "UPDATE grid.buses SET name = ''",
        "UPDATE grid.switches SET name = '   '",
        # buses
        "UPDATE grid.buses SET nominal_voltage_kv = 0",
        "UPDATE grid.buses SET nominal_voltage_kv = -20",
        "UPDATE grid.buses SET diagram_x = NULL WHERE key = 'a'",  # y stays set
        "UPDATE grid.buses SET diagram_y = 1 WHERE key = 'd'",  # x stays null
        # lines
        "UPDATE grid.lines SET length_km = 0",
        "UPDATE grid.lines SET r_ohm_per_km = -0.1",
        "UPDATE grid.lines SET x_ohm_per_km = -0.1",
        "UPDATE grid.lines SET r_ohm_per_km = 0, x_ohm_per_km = 0",
        "UPDATE grid.lines SET c_nf_per_km = -1",
        "UPDATE grid.lines SET max_i_ka = 0",
        "UPDATE grid.lines SET to_bus_id = from_bus_id",
        # transformers
        "UPDATE grid.transformers SET rated_power_mva = 0",
        "UPDATE grid.transformers SET rated_voltage_lv_kv = 0, rated_voltage_hv_kv = 1",
        "UPDATE grid.transformers SET rated_voltage_hv_kv = rated_voltage_lv_kv",
        "UPDATE grid.transformers SET short_circuit_voltage_percent = 0, "
        "short_circuit_resistive_percent = 0",
        "UPDATE grid.transformers SET short_circuit_resistive_percent = -0.1",
        "UPDATE grid.transformers SET short_circuit_resistive_percent = 12.5",
        "UPDATE grid.transformers SET iron_losses_kw = -1",
        "UPDATE grid.transformers SET no_load_current_percent = -0.01, iron_losses_kw = 0",
        "UPDATE grid.transformers SET no_load_current_percent = 0.05",  # 14 kW needs 0.056 %
        "UPDATE grid.transformers SET lv_bus_id = hv_bus_id",
        "UPDATE grid.transformers SET tap_side = NULL",  # five of six tap columns left
        "UPDATE grid.transformers SET tap_side = 'mv'",
        "UPDATE grid.transformers SET tap_step_percent = 0",
        "UPDATE grid.transformers SET tap_position = 10",
        "UPDATE grid.transformers SET tap_position = -10",
        "UPDATE grid.transformers SET tap_neutral_position = 12",
        "UPDATE grid.transformers SET tap_min_position = 5, tap_max_position = -5, "
        "tap_neutral_position = 0, tap_position = 0",
        # loads
        "UPDATE grid.loads SET p_mw = -1",
        # generators
        "UPDATE grid.generators SET p_mw = -1",
        "UPDATE grid.generators SET control_mode = 'droop'",
        "UPDATE grid.generators SET q_mvar = NULL WHERE key = 'pv'",
        "UPDATE grid.generators SET voltage_setpoint_pu = 1 WHERE key = 'pv'",
        "UPDATE grid.generators SET max_q_mvar = 1, min_q_mvar = -1 WHERE key = 'pv'",
        "UPDATE grid.generators SET voltage_setpoint_pu = NULL WHERE key = 'chp'",
        "UPDATE grid.generators SET q_mvar = 0.5 WHERE key = 'chp'",
        "UPDATE grid.generators SET voltage_setpoint_pu = 0 WHERE key = 'chp'",
        "UPDATE grid.generators SET min_q_mvar = NULL WHERE key = 'chp'",
        "UPDATE grid.generators SET min_q_mvar = 1, max_q_mvar = -1 WHERE key = 'chp'",
        "UPDATE grid.generators SET rated_power_mva = 0 WHERE key = 'pv'",
        "UPDATE grid.generators SET rated_power_mva = 0.29 WHERE key = 'pv'",  # p is 0.3
        # external grids
        "UPDATE grid.external_grids SET voltage_pu = 0",
        # switches
        "UPDATE grid.switches SET kind = 'fuse'",
        "UPDATE grid.switches SET line_id = NULL WHERE key = 's-bc'",  # no target left
        "UPDATE grid.switches SET other_bus_id = bus_id WHERE key = 's-bc'",  # two targets
        "UPDATE grid.switches SET other_bus_id = bus_id WHERE key = 'coupler'",
    ],
)
def test_an_invalid_row_is_rejected(
    grid_id: uuid.UUID, owner_engine: Engine, statement: str
) -> None:
    assert _violation(owner_engine, statement) == CHECK_VIOLATION


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE grid.lines SET r_ohm_per_km = 0",  # reactive only
        "UPDATE grid.lines SET x_ohm_per_km = 0",  # resistive only
        "UPDATE grid.loads SET q_mvar = -5",  # capacitive
        "UPDATE grid.transformers SET no_load_current_percent = 0.056",  # exactly enough
        "UPDATE grid.transformers SET short_circuit_resistive_percent = 12",  # all resistive
        "UPDATE grid.transformers SET tap_side = NULL, tap_neutral_position = NULL, "
        "tap_min_position = NULL, tap_max_position = NULL, tap_step_percent = NULL, "
        "tap_position = NULL",
        "UPDATE grid.generators SET rated_power_mva = 0.3 WHERE key = 'pv'",  # exactly p
        "UPDATE grid.generators SET min_q_mvar = 0.2, max_q_mvar = 0.2 WHERE key = 'chp'",
        "UPDATE grid.generators SET min_q_mvar = NULL, max_q_mvar = NULL WHERE key = 'chp'",
        "UPDATE grid.buses SET diagram_x = NULL, diagram_y = NULL",
        "UPDATE grid.grids SET frequency_hz = 60",
        "UPDATE grid.switches SET closed = NOT closed",
    ],
)
def test_boundary_values_that_are_valid_are_accepted(
    grid_id: uuid.UUID, owner_engine: Engine, statement: str
) -> None:
    assert _violation(owner_engine, statement) is None


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        # Two elements of one type cannot share a key within a grid.
        ("UPDATE grid.buses SET key = 'a' WHERE key = 'b'", UNIQUE_VIOLATION),
        ("UPDATE grid.lines SET key = 'ab' WHERE key = 'bc'", UNIQUE_VIOLATION),
        # A bus with elements attached cannot be deleted from under them.
        ("DELETE FROM grid.buses WHERE key = 'b'", FOREIGN_KEY_VIOLATION),
        ("DELETE FROM grid.lines WHERE key = 'bc'", FOREIGN_KEY_VIOLATION),  # a switch is on it
        ("DELETE FROM grid.transformers", FOREIGN_KEY_VIOLATION),
        # References must exist.
        ("UPDATE grid.loads SET bus_id = uuidv7()", FOREIGN_KEY_VIOLATION),
        ("UPDATE grid.switches SET line_id = uuidv7() WHERE key = 's-bc'", FOREIGN_KEY_VIOLATION),
        ("UPDATE grid.grids SET organization_id = uuidv7()", FOREIGN_KEY_VIOLATION),
        # Required values.
        ("UPDATE grid.buses SET name = NULL", NOT_NULL_VIOLATION),
        ("UPDATE grid.grids SET topology_hash = NULL", NOT_NULL_VIOLATION),
        ("UPDATE grid.switches SET closed = NULL", NOT_NULL_VIOLATION),
    ],
)
def test_keys_and_references_are_enforced(
    grid_id: uuid.UUID, owner_engine: Engine, statement: str, expected: str
) -> None:
    assert _violation(owner_engine, statement) == expected


def test_grid_names_are_unique_per_organisation_not_globally(
    grid_id: uuid.UUID, tenants: dict[str, uuid.UUID], owner_engine: Engine
) -> None:
    insert = (
        "INSERT INTO grid.grids (organization_id, name, frequency_hz, topology_hash) "
        "SELECT '{organization}', name, 50, topology_hash FROM grid.grids WHERE id = '{grid}'"
    )
    same = insert.format(organization=tenants["alpha"], grid=grid_id)
    other = insert.format(organization=tenants["bravo"], grid=grid_id)
    assert _violation(owner_engine, same) == UNIQUE_VIOLATION
    assert _violation(owner_engine, other) is None


def test_the_same_key_may_be_used_by_different_element_types(
    grid_id: uuid.UUID, owner_engine: Engine
) -> None:
    assert _violation(owner_engine, "UPDATE grid.lines SET key = 'a' WHERE key = 'ab'") is None


def test_defaults(grid_id: uuid.UUID, owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        grid = connection.execute(
            text("SELECT id, version, data_origin, description FROM grid.grids")
        ).one()
        bus_id = connection.execute(text("SELECT id FROM grid.buses LIMIT 1")).scalar_one()
    assert (grid.version, grid.data_origin, grid.description) == (1, "synthetic", "")
    assert grid.id.version == 7  # generated by the database, time-ordered
    assert bus_id.version == 7


def test_updated_at_is_maintained_on_grid_tables(grid_id: uuid.UUID, owner_engine: Engine) -> None:
    select = text("SELECT created_at, updated_at FROM grid.buses WHERE key = 'a'")
    with owner_engine.connect() as connection:
        created_at, initial = connection.execute(select).one()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE grid.buses SET name = 'Renamed', updated_at = '2000-01-01Z' WHERE key = 'a'"
            )
        )
    with owner_engine.connect() as connection:
        created_after, updated = connection.execute(select).one()
    assert created_after == created_at
    assert updated > initial  # the trigger overrode the backdated value
