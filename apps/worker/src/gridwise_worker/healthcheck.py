"""Container health check: the worker loop touched its health file recently.

Exit 0 when the file is younger than ``worker_health_max_age_seconds``, 1 otherwise. The
loop touches it on every pass and on every heartbeat, so a stalled loop turns unhealthy.
"""

import sys
import time
from pathlib import Path

from gridwise_worker.settings import WorkerSettings


def main() -> int:
    settings = WorkerSettings()
    try:
        age = time.time() - Path(settings.worker_health_file).stat().st_mtime
    except OSError:
        return 1
    return 0 if age <= settings.worker_health_max_age_seconds else 1


if __name__ == "__main__":
    sys.exit(main())
