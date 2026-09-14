"""Shared canonical workspace builders for schema tests.

``tests/app/_helpers.py`` is the canonical definition (it also has the
template-aware ``make_workbook``/``set_cell`` used by read-gate tests). This
module re-exports it so the top-level ``_helpers`` name resolves to the same API
whichever test directory pytest happened to put on ``sys.path`` first —
otherwise a hand-picked subset like ``pytest tests/app tests/schema`` binds one
directory's helper and breaks imports from the other.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_APP_HELPERS = Path(__file__).resolve().parents[1] / "app" / "_helpers.py"
_spec = importlib.util.spec_from_file_location("ct_app_test_helpers", _APP_HELPERS)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

write_yaml = _module.write_yaml
build_project = _module.build_project
make_workbook = _module.make_workbook
set_cell = _module.set_cell

__all__ = ["build_project", "make_workbook", "set_cell", "write_yaml"]
