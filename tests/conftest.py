from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _StubGenerativeModel:
    def __init__(self, **_: object) -> None:  # pragma: no cover - trivial stub
        pass


def _configure_stub(**_: object) -> None:  # pragma: no cover - trivial stub
    pass


stub_module = ModuleType("google.generativeai")
stub_module.configure = _configure_stub  # type: ignore[attr-defined]
stub_module.GenerativeModel = _StubGenerativeModel  # type: ignore[attr-defined]

sys.modules.setdefault("google.generativeai", stub_module)


mysql_module = ModuleType("mysql")
mysql_connector = ModuleType("mysql.connector")
mysql_connector.connect = lambda **_: None  # type: ignore[attr-defined]
mysql_module.connector = mysql_connector  # type: ignore[attr-defined]

sys.modules.setdefault("mysql", mysql_module)
sys.modules.setdefault("mysql.connector", mysql_connector)
