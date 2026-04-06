import sys

from fitmas.skills.heartbeat import evaluation as _impl

sys.modules[__name__] = _impl
