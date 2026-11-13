"""Architecture rules, enforced.

1. Only ``adapters/pandapower_adapter.py`` imports pandapower.
2. The engine imports no web, database or frontend-serving library.
3. Importing the engine (models, validation, results) does not load pandapower.
4. The API never imports pandapower or the adapter: power flows run in a worker process.
5. The API never imports the worker.
6. In the worker, only the solver child process (``child.py``) imports the adapter; the
   parent process that talks to the database never loads a numerical library.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_SRC = REPO_ROOT / "packages/grid-engine/src"
ENGINE_PACKAGE = ENGINE_SRC / "gridwise_grid_engine"
API_PACKAGE = REPO_ROOT / "apps/api/src/gridwise_api"
WORKER_PACKAGE = REPO_ROOT / "apps/worker/src/gridwise_worker"

ADAPTER = ENGINE_PACKAGE / "adapters/pandapower_adapter.py"
ADAPTER_MODULE = "gridwise_grid_engine.adapters.pandapower_adapter"

FORBIDDEN_IN_ENGINE = {
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pydantic",
    "pydantic_settings",
    "structlog",
    "httpx",
    "requests",
    "gridwise_api",
}
#: Scientific libraries may only be reached through the adapter as well: the domain layer
#: must stay plain Python so its behaviour does not depend on their versions.
NUMERIC_LIBRARIES = {"pandapower", "pandas", "numpy", "scipy", "networkx", "numba"}


def imported_modules(path: Path) -> set[str]:
    """Every module a file imports, at any nesting depth, including inside functions."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def top_level(modules: set[str]) -> set[str]:
    return {module.split(".")[0] for module in modules}


def python_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.py"))
    assert files, f"no Python files under {root}"
    return files


def test_the_adapter_exists_and_imports_pandapower() -> None:
    assert "pandapower" in top_level(imported_modules(ADAPTER))


@pytest.mark.parametrize(
    "path",
    [p for p in python_files(ENGINE_PACKAGE) if p != ADAPTER],
    ids=lambda p: str(p.relative_to(ENGINE_PACKAGE)),
)
def test_no_other_engine_module_imports_a_numeric_library(path: Path) -> None:
    assert top_level(imported_modules(path)) & NUMERIC_LIBRARIES == set()


@pytest.mark.parametrize(
    "path", python_files(ENGINE_PACKAGE), ids=lambda p: str(p.relative_to(ENGINE_PACKAGE))
)
def test_the_engine_imports_no_web_or_database_library(path: Path) -> None:
    assert top_level(imported_modules(path)) & FORBIDDEN_IN_ENGINE == set()


def test_only_the_selfcheck_reaches_for_the_adapter_inside_the_engine() -> None:
    importers = {
        str(path.relative_to(ENGINE_PACKAGE))
        for path in python_files(ENGINE_PACKAGE)
        if ADAPTER_MODULE in imported_modules(path)
    }
    assert importers == {"selfcheck.py"}


def test_the_engine_declares_no_dependency_besides_pandapower() -> None:
    import tomllib

    project = tomllib.loads((REPO_ROOT / "packages/grid-engine/pyproject.toml").read_text())
    names = {
        dep.split(">")[0].split("<")[0].split("=")[0].strip()
        for dep in project["project"]["dependencies"]
    }
    assert names == {"pandapower"}


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    """A fresh interpreter that can see the engine source and the installed libraries."""
    environment = {**os.environ, "PYTHONPATH": str(ENGINE_SRC)}
    return subprocess.run(  # noqa: S603  (fixed interpreter, code defined in this file)
        [sys.executable, "-c", code], capture_output=True, text=True, env=environment, check=False
    )


def test_importing_the_engine_does_not_load_pandapower() -> None:
    code = (
        "import sys, gridwise_grid_engine as engine\n"
        "from gridwise_grid_engine import validate_grid, GridModel, Bus\n"
        "validate_grid(GridModel(name='g', frequency_hz=50.0, "
        "buses=(Bus(id='a', name='A', nominal_voltage_kv=20.0),)))\n"
        "loaded = sorted(m for m in ('pandapower','pandas','numpy','scipy') if m in sys.modules)\n"
        "print(loaded)\n"
    )
    completed = _run_isolated(code)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]"


def test_importing_the_adapter_is_what_loads_pandapower() -> None:
    """The control for the test above: the probe does detect pandapower when it is loaded."""
    completed = _run_isolated(f"import sys, {ADAPTER_MODULE}\nprint('pandapower' in sys.modules)\n")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "True"


@pytest.mark.parametrize(
    "path", python_files(API_PACKAGE), ids=lambda p: str(p.relative_to(API_PACKAGE))
)
def test_the_api_never_imports_pandapower_or_the_adapter(path: Path) -> None:
    modules = imported_modules(path)
    assert top_level(modules) & NUMERIC_LIBRARIES == set()
    assert not any(module.startswith("gridwise_grid_engine.adapters") for module in modules)


@pytest.mark.parametrize(
    "path", python_files(API_PACKAGE), ids=lambda p: str(p.relative_to(API_PACKAGE))
)
def test_the_api_never_imports_the_worker(path: Path) -> None:
    assert "gridwise_worker" not in top_level(imported_modules(path))


def test_only_the_solver_child_imports_the_adapter_in_the_worker() -> None:
    importers = {
        str(path.relative_to(WORKER_PACKAGE))
        for path in python_files(WORKER_PACKAGE)
        if ADAPTER_MODULE in imported_modules(path)
    }
    assert importers == {"child.py"}


@pytest.mark.parametrize(
    "path",
    [p for p in python_files(WORKER_PACKAGE) if p.name != "child.py"],
    ids=lambda p: str(p.relative_to(WORKER_PACKAGE)),
)
def test_the_worker_parent_imports_no_numerical_library(path: Path) -> None:
    modules = imported_modules(path)
    assert top_level(modules) & NUMERIC_LIBRARIES == set()
    assert not any(module.startswith("gridwise_grid_engine.adapters") for module in modules)
