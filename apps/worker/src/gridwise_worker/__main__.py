"""``python -m gridwise_worker``: run the simulation worker until SIGTERM or SIGINT."""

import signal
import sys
from types import FrameType

from gridwise_api.logging import configure_logging
from gridwise_worker.database import WorkerDatabase, connect
from gridwise_worker.loop import Worker
from gridwise_worker.settings import WorkerSettings
from gridwise_worker.supervisor import ChildSupervisor


def main() -> int:
    settings = WorkerSettings()
    configure_logging(settings)
    engine = connect(settings)
    worker = Worker(
        settings,
        WorkerDatabase(
            engine, worker_id=settings.worker_id, lease_seconds=settings.worker_lease_seconds
        ),
        ChildSupervisor(solver=settings.worker_solver),
    )

    def stop(signum: int, frame: FrameType | None) -> None:
        worker.request_stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
