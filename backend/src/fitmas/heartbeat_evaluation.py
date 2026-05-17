import sys

from fitmas.legacy.heartbeat_skill_bridge import evaluation as _impl

sys.modules[__name__] = _impl
