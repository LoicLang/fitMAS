from __future__ import annotations

import sys

from fitmas.llm import gateway as _gateway

sys.modules[__name__] = _gateway
