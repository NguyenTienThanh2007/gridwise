"""Stable error codes. They are part of the engine's contract: never rename one.

Documented in docs/domain/grid-engine.md; a test fails if that table and this enum differ.
"""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    # --- identifiers and numbers ---
    INVALID_IDENTIFIER = "invalid_identifier"
    DUPLICATE_ELEMENT_ID = "duplicate_element_id"
    INVALID_NUMBER = "invalid_number"
    INVALID_IN_SERVICE_FLAG = "invalid_in_service_flag"

    # --- grid ---
    INVALID_FREQUENCY = "invalid_frequency"
    NO_BUSES = "no_buses"
    MISSING_EXTERNAL_GRID = "missing_external_grid"

    # --- bus ---
    INVALID_NOMINAL_VOLTAGE = "invalid_nominal_voltage"

    # --- references ---
    UNKNOWN_BUS_REFERENCE = "unknown_bus_reference"

    # --- line ---
    LINE_CONNECTS_BUS_TO_ITSELF = "line_connects_bus_to_itself"
    LINE_VOLTAGE_MISMATCH = "line_voltage_mismatch"
    INVALID_LINE_LENGTH = "invalid_line_length"
    NEGATIVE_LINE_RESISTANCE = "negative_line_resistance"
    NEGATIVE_LINE_REACTANCE = "negative_line_reactance"
    ZERO_LINE_IMPEDANCE = "zero_line_impedance"
    NEGATIVE_LINE_CAPACITANCE = "negative_line_capacitance"
    INVALID_LINE_THERMAL_LIMIT = "invalid_line_thermal_limit"

    # --- load ---
    NEGATIVE_LOAD_ACTIVE_POWER = "negative_load_active_power"

    # --- external grid ---
    INVALID_EXTERNAL_GRID_VOLTAGE = "invalid_external_grid_voltage"
    MULTIPLE_EXTERNAL_GRIDS_ON_BUS = "multiple_external_grids_on_bus"

    # --- transformer ---
    TRANSFORMER_CONNECTS_BUS_TO_ITSELF = "transformer_connects_bus_to_itself"
    TRANSFORMER_VOLTAGE_MISMATCH = "transformer_voltage_mismatch"
    INVALID_TRANSFORMER_RATED_POWER = "invalid_transformer_rated_power"
    INVALID_TRANSFORMER_RATED_VOLTAGE = "invalid_transformer_rated_voltage"
    INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE = "invalid_transformer_short_circuit_voltage"
    NEGATIVE_TRANSFORMER_IRON_LOSSES = "negative_transformer_iron_losses"
    INVALID_TRANSFORMER_NO_LOAD_CURRENT = "invalid_transformer_no_load_current"
    INVALID_TAP_CHANGER = "invalid_tap_changer"

    # --- generator ---
    NEGATIVE_GENERATOR_ACTIVE_POWER = "negative_generator_active_power"
    INVALID_GENERATOR_CONTROL_MODE = "invalid_generator_control_mode"
    INVALID_GENERATOR_PARAMETERS = "invalid_generator_parameters"
    INVALID_GENERATOR_VOLTAGE_SETPOINT = "invalid_generator_voltage_setpoint"
    INVALID_GENERATOR_REACTIVE_LIMITS = "invalid_generator_reactive_limits"
    INVALID_GENERATOR_RATED_POWER = "invalid_generator_rated_power"
    GENERATOR_EXCEEDS_RATED_POWER = "generator_exceeds_rated_power"
    MULTIPLE_VOLTAGE_CONTROLLERS_ON_BUS = "multiple_voltage_controllers_on_bus"

    # --- switch ---
    INVALID_SWITCH_STATE = "invalid_switch_state"
    INVALID_SWITCH_ELEMENT_TYPE = "invalid_switch_element_type"
    INVALID_SWITCH_KIND = "invalid_switch_kind"
    UNKNOWN_SWITCH_TARGET = "unknown_switch_target"
    SWITCH_NOT_AT_ELEMENT_TERMINAL = "switch_not_at_element_terminal"
    SWITCH_CONNECTS_BUS_TO_ITSELF = "switch_connects_bus_to_itself"
    SWITCH_VOLTAGE_MISMATCH = "switch_voltage_mismatch"
    DUPLICATE_SWITCH = "duplicate_switch"

    # --- solving ---
    POWER_FLOW_NOT_CONVERGED = "power_flow_not_converged"
    SOLVER_FAILED = "solver_failed"
    INCONSISTENT_SOLUTION = "inconsistent_solution"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationIssue:
    """One reason a grid cannot be solved."""

    code: ErrorCode
    message: str
    element_type: str | None = None
    element_id: str | None = None
    field: str | None = None


class GridEngineError(Exception):
    """Base class of every error the engine raises deliberately."""


class GridValidationError(GridEngineError):
    """The grid is not a valid input. Carries every issue found, not just the first."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        codes = ", ".join(sorted({issue.code.value for issue in issues}))
        super().__init__(f"Grid is invalid ({len(issues)} issue(s)): {codes}")

    @property
    def codes(self) -> frozenset[ErrorCode]:
        return frozenset(issue.code for issue in self.issues)


class SolverExecutionError(GridEngineError):
    """The solver crashed or returned something that cannot be a valid solution.

    Distinct from non-convergence, which is an expected outcome reported in the result.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")
