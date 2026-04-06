import sys

from fitmas.tools import metrics as _impl

sys.modules[__name__] = _impl
