from gridwise_grid_engine import PowerFlowOptions
from gridwise_grid_engine.fingerprint import (
    configuration_hash,
    configuration_text,
    engine_fingerprint,
)


def _fingerprint(**changes: object) -> str:
    values: dict[str, object] = {
        "engine_version": "0.3.0",
        "solver_name": "pandapower",
        "solver_version": "3.5.6",
        "options": PowerFlowOptions(),
        **changes,
    }
    return engine_fingerprint(**values)  # type: ignore[arg-type]


def test_the_configuration_hash_is_stable_and_exact() -> None:
    assert configuration_hash(PowerFlowOptions()) == configuration_hash(PowerFlowOptions())
    assert configuration_hash(PowerFlowOptions(tolerance_mva=1e-8)) != configuration_hash(
        PowerFlowOptions(tolerance_mva=1e-10)
    )
    assert configuration_hash(PowerFlowOptions(max_iterations=10)) != configuration_hash(
        PowerFlowOptions(max_iterations=11)
    )
    assert '"algorithm":"newton_raphson"' in configuration_text(PowerFlowOptions())


def test_every_part_of_the_engine_fingerprint_matters() -> None:
    base = _fingerprint()
    assert _fingerprint() == base
    for changes in (
        {"engine_version": "0.3.1"},
        {"solver_name": "other"},
        {"solver_version": "3.5.7"},
        {"options": PowerFlowOptions(max_iterations=20)},
    ):
        assert _fingerprint(**changes) != base, changes
