import sys

from fitmas.legacy.heartbeat_skill_bridge import heartbeat as _impl

sys.modules[__name__] = _impl
