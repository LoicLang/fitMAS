import sys

from fitmas.tools import registry as _impl

sys.modules[__name__] = _impl
