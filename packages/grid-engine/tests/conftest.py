import pytest

from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver


@pytest.fixture(scope="session")
def solver() -> PandapowerSolver:
    """One instance for the whole session, on purpose: it must hold no state between solves."""
    return PandapowerSolver()
