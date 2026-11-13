import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from gridwise_api.config import Settings
from gridwise_api.main import create_app
from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION
from tests.integration.conftest import TestDatabase

pytestmark = pytest.mark.integration


async def _ready(database_url: str) -> httpx.Response:
    """Readiness exactly as deployed: through the app, connected as the runtime role."""
    settings = Settings(
        _env_file=None,
        environment="test",
        log_format="json",
        log_level="INFO",
        database_url=database_url,
    )
    app = create_app(settings)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.get("/health/ready")
    finally:
        await app.state.engine.dispose()


async def test_not_ready_before_migrations(database: TestDatabase) -> None:
    response = await _ready(database.app_url)
    assert response.status_code == 503
    assert response.json()["database"] == "not_migrated"


async def test_ready_after_migrations(alembic_config: Config, database: TestDatabase) -> None:
    command.upgrade(alembic_config, "head")
    response = await _ready(database.app_url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "schema_revision": EXPECTED_SCHEMA_REVISION,
        "expected_schema_revision": EXPECTED_SCHEMA_REVISION,
    }


@pytest.mark.parametrize("applied", ["0000", "9999"], ids=["behind", "ahead"])
async def test_not_ready_when_the_applied_revision_differs(
    alembic_config: Config, database: TestDatabase, owner_engine: Engine, applied: str
) -> None:
    command.upgrade(alembic_config, "head")
    with owner_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": applied})

    response = await _ready(database.app_url)
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "schema_mismatch",
        "schema_revision": applied,
        "expected_schema_revision": EXPECTED_SCHEMA_REVISION,
    }


async def test_not_ready_after_downgrade_to_base(
    alembic_config: Config, database: TestDatabase
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    response = await _ready(database.app_url)
    assert response.status_code == 503
    assert response.json()["database"] == "not_migrated"


async def test_wrong_password_is_unavailable_and_never_echoed(
    alembic_config: Config, database: TestDatabase, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "head")
    wrong = "definitely-not-the-password"
    url = database.app_url.replace(database.app_url.split(":")[2].split("@")[0], wrong)
    response = await _ready(url)
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    output = capsys.readouterr()
    assert wrong not in response.text
    assert wrong not in output.out + output.err
