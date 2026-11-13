"""The numerical configuration a job is submitted with."""

from dataclasses import dataclass

from gridwise_grid_engine import PowerFlowOptions
from gridwise_grid_engine.fingerprint import configuration_hash, configuration_text

_DEFAULTS = PowerFlowOptions()


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulationConfiguration:
    """AC Newton-Raphson options. Defaults are the engine's own."""

    tolerance_mva: float = _DEFAULTS.tolerance_mva
    max_iterations: int = _DEFAULTS.max_iterations

    def __post_init__(self) -> None:
        self.options()  # the engine's own bounds; raises ValueError when outside

    def options(self) -> PowerFlowOptions:
        return PowerFlowOptions(
            tolerance_mva=self.tolerance_mva, max_iterations=self.max_iterations
        )

    def text(self) -> str:
        return configuration_text(self.options())

    def hash(self) -> str:
        return configuration_hash(self.options())
