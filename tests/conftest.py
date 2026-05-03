from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

os.environ.setdefault("FITMAS_ENABLE_FINAL_REPLY_COMPOSER", "0")
