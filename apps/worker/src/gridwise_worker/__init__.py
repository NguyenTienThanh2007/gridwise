"""GRIDWISE simulation worker (decision 0011).

The parent process claims jobs and talks to the database; it never imports a numerical
library. A spawned child process loads the solver and computes; it never opens a database
connection. Only ``gridwise_worker.child`` imports the solver adapter.
"""

__version__ = "0.1.0"
