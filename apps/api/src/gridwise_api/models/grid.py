"""The ``grid`` schema: a grid and its electrical elements.

These tables persist the engine's model (packages/grid-engine). Units are in the column
names, exactly as in the engine. Every row belongs to an organisation, and every reference
between rows carries ``organization_id`` and ``grid_id``, so it cannot leave its grid or
its tenant.

Row checks (signs, ranges, enumerations, finite numbers) are defined in migration 0002 and
exercised by tests/integration/test_grid_constraints.py. They are not repeated here: these
classes describe columns, keys and indexes, which is what the model-drift test compares.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Double,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gridwise_api.models.base import Base

SCHEMA = "grid"


class _Row:
    """Columns every table in the schema has."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    # Maintained by the core.set_updated_at() trigger, never by application code.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), server_onupdate=FetchedValue()
    )


class _Element(_Row):
    """Columns every electrical element has."""

    grid_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: The element's stable identifier: the engine's element id.
    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)


def _element_args(
    table: str,
) -> tuple[PrimaryKeyConstraint | UniqueConstraint | ForeignKeyConstraint, ...]:
    return (
        PrimaryKeyConstraint("id", name=f"pk_{table}"),
        # organization_id first: see migration 0002 (no cross-tenant existence oracle).
        UniqueConstraint("organization_id", "grid_id", "key", name=f"uq_{table}_tenant_grid_key"),
        ForeignKeyConstraint(
            ["organization_id", "grid_id"],
            [f"{SCHEMA}.grids.organization_id", f"{SCHEMA}.grids.id"],
            name=f"fk_{table}_grid",
            ondelete="CASCADE",
        ),
    )


def _reference(table: str, column: str, target: str = "buses") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", "grid_id", column],
        [
            f"{SCHEMA}.{target}.organization_id",
            f"{SCHEMA}.{target}.grid_id",
            f"{SCHEMA}.{target}.id",
        ],
        name=f"fk_{table}_{column}",
    )


def _tenant_grid_id(table: str) -> UniqueConstraint:
    """Target of composite foreign keys that point at this table."""
    return UniqueConstraint("organization_id", "grid_id", "id", name=f"uq_{table}_tenant_grid_id")


class Grid(_Row, Base):
    __tablename__ = "grids"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_grids"),
        UniqueConstraint("organization_id", "name", name="uq_grids_organization_name"),
        UniqueConstraint("organization_id", "id", name="uq_grids_organization_id"),
        ForeignKeyConstraint(
            ["organization_id"], ["core.organizations.id"], name="fk_grids_organization"
        ),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    frequency_hz: Mapped[float] = mapped_column(Double)
    #: Only "synthetic" is allowed (a database check).
    data_origin: Mapped[str] = mapped_column(Text, server_default=text("'synthetic'"))
    #: Optimistic concurrency: incremented by every change to the grid or its elements.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    #: The engine's grid_hash of the stored topology.
    topology_hash: Mapped[str] = mapped_column(Text)


class Bus(_Element, Base):
    __tablename__ = "buses"

    __table_args__ = (*_element_args("buses"), _tenant_grid_id("buses"), {"schema": SCHEMA})

    nominal_voltage_kv: Mapped[float] = mapped_column(Double)
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    #: Schematic diagram position. Not geographic, not electrical, not hashed.
    diagram_x: Mapped[float | None] = mapped_column(Double)
    diagram_y: Mapped[float | None] = mapped_column(Double)


class Line(_Element, Base):
    __tablename__ = "lines"

    __table_args__ = (
        *_element_args("lines"),
        _tenant_grid_id("lines"),
        _reference("lines", "from_bus_id"),
        _reference("lines", "to_bus_id"),
        Index("ix_lines_from_bus_id", "from_bus_id"),
        Index("ix_lines_to_bus_id", "to_bus_id"),
        {"schema": SCHEMA},
    )

    from_bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    to_bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    length_km: Mapped[float] = mapped_column(Double)
    r_ohm_per_km: Mapped[float] = mapped_column(Double)
    x_ohm_per_km: Mapped[float] = mapped_column(Double)
    c_nf_per_km: Mapped[float] = mapped_column(Double)
    max_i_ka: Mapped[float] = mapped_column(Double)
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Transformer(_Element, Base):
    __tablename__ = "transformers"

    __table_args__ = (
        *_element_args("transformers"),
        _tenant_grid_id("transformers"),
        _reference("transformers", "hv_bus_id"),
        _reference("transformers", "lv_bus_id"),
        Index("ix_transformers_hv_bus_id", "hv_bus_id"),
        Index("ix_transformers_lv_bus_id", "lv_bus_id"),
        {"schema": SCHEMA},
    )

    hv_bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lv_bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rated_power_mva: Mapped[float] = mapped_column(Double)
    rated_voltage_hv_kv: Mapped[float] = mapped_column(Double)
    rated_voltage_lv_kv: Mapped[float] = mapped_column(Double)
    short_circuit_voltage_percent: Mapped[float] = mapped_column(Double)
    short_circuit_resistive_percent: Mapped[float] = mapped_column(Double)
    iron_losses_kw: Mapped[float] = mapped_column(Double)
    no_load_current_percent: Mapped[float] = mapped_column(Double)
    phase_shift_degree: Mapped[float] = mapped_column(Double, server_default=text("0"))
    # The optional ratio tap changer: all six, or none (a database check).
    tap_side: Mapped[str | None] = mapped_column(Text)
    tap_neutral_position: Mapped[int | None] = mapped_column(Integer)
    tap_min_position: Mapped[int | None] = mapped_column(Integer)
    tap_max_position: Mapped[int | None] = mapped_column(Integer)
    tap_step_percent: Mapped[float | None] = mapped_column(Double)
    tap_position: Mapped[int | None] = mapped_column(Integer)
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Load(_Element, Base):
    __tablename__ = "loads"

    __table_args__ = (
        *_element_args("loads"),
        _reference("loads", "bus_id"),
        Index("ix_loads_bus_id", "bus_id"),
        {"schema": SCHEMA},
    )

    bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    p_mw: Mapped[float] = mapped_column(Double)
    q_mvar: Mapped[float] = mapped_column(Double)
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Generator(_Element, Base):
    __tablename__ = "generators"

    __table_args__ = (
        *_element_args("generators"),
        _reference("generators", "bus_id"),
        Index("ix_generators_bus_id", "bus_id"),
        {"schema": SCHEMA},
    )

    bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    p_mw: Mapped[float] = mapped_column(Double)
    control_mode: Mapped[str] = mapped_column(Text)
    q_mvar: Mapped[float | None] = mapped_column(Double)
    voltage_setpoint_pu: Mapped[float | None] = mapped_column(Double)
    min_q_mvar: Mapped[float | None] = mapped_column(Double)
    max_q_mvar: Mapped[float | None] = mapped_column(Double)
    rated_power_mva: Mapped[float | None] = mapped_column(Double)
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ExternalGrid(_Element, Base):
    __tablename__ = "external_grids"

    __table_args__ = (
        *_element_args("external_grids"),
        _reference("external_grids", "bus_id"),
        Index("ix_external_grids_bus_id", "bus_id"),
        {"schema": SCHEMA},
    )

    bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    voltage_pu: Mapped[float] = mapped_column(Double, server_default=text("1"))
    voltage_angle_degree: Mapped[float] = mapped_column(Double, server_default=text("0"))
    in_service: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Switch(_Element, Base):
    __tablename__ = "switches"

    __table_args__ = (
        *_element_args("switches"),
        _reference("switches", "bus_id"),
        _reference("switches", "line_id", "lines"),
        _reference("switches", "transformer_id", "transformers"),
        _reference("switches", "other_bus_id"),
        Index("ix_switches_bus_id", "bus_id"),
        Index("ix_switches_line_id", "line_id"),
        Index("ix_switches_transformer_id", "transformer_id"),
        Index("ix_switches_other_bus_id", "other_bus_id"),
        {"schema": SCHEMA},
    )

    bus_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # Exactly one of the three targets is set (a database check).
    line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    transformer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    other_bus_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: A state of the simulated network. Not a command; nothing sends it to equipment.
    closed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    kind: Mapped[str] = mapped_column(Text, server_default=text("'load_break_switch'"))
