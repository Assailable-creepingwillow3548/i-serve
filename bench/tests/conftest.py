"""Put `bench/` on the import path for the tests that live in here.

The modules under `bench/` import each other by bare name -- `from roofline
import ...` -- because this repository has no packaging at all: no
`pyproject.toml`, no `__init__.py`, no install step. That is deliberate and it is
what the front page sells, `python3 bench/harness.py --dry-run` on a clean
machine with nothing fetched. Running a script from `bench/` puts that directory
on `sys.path` for free; running the tests from a subdirectory does not, so the
one line below restores it.

This file is the entire cost of keeping the tests in their own directory. If it
ever grows fixtures, they belong next to the thing they fixture.
"""

import pathlib
import sys

BENCH = pathlib.Path(__file__).resolve().parent.parent
ROOT = BENCH.parent

sys.path.insert(0, str(BENCH))
