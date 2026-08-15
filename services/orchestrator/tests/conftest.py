"""Makes `from app import ...` resolve regardless of how pytest is invoked
(bare `pytest`, `python -m pytest`, from a different cwd, etc.) by putting
the orchestrator's root -- the parent of this tests/ directory, which is
where the app/ package lives -- onto sys.path once, before any test module
imports app.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
