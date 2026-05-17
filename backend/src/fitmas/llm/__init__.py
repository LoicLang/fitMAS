from __future__ import annotations

from pathlib import Path
import sys

from . import decision_legacy as _decision_legacy

_decision_legacy.__path__ = [str(Path(__file__).resolve().parent)]  # type: ignore[attr-defined]
_decision_legacy.__package__ = __name__
sys.modules[__name__] = _decision_legacy
