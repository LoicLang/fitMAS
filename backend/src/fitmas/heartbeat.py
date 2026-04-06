import sys

from fitmas.skills.heartbeat import heartbeat as _impl

sys.modules[__name__] = _impl
