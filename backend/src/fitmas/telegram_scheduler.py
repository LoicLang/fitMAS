from __future__ import annotations

import sys

from fitmas.app.telegram import scheduler as _impl
from fitmas.app.telegram.scheduler import *  # noqa: F401,F403

sys.modules[__name__] = _impl
