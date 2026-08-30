"""Puts mission/eval/ on sys.path so tests can `import eval_lib` without
touching the root pytest.ini's `pythonpath = tools` (that's tools/'s own
convention, not mission/'s — keeping this self-contained avoids a
cross-folder edit to shared config for a single owner's test suite)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
