"""Back-compat shim. The read-side snapshot adapter was promoted (tranche #2 S1)
to `fitmas.runtime_v0.adapters.current_db_snapshot`.

Kept so the eval scripts that still import `scripts.v0_eval.real_snapshot`
(compare_app_vs_v0.py, spike_real_turn.py) keep resolving to the real impl.
Import the adapter directly in new code.
"""

from fitmas.runtime_v0.adapters.current_db_snapshot import (  # noqa: F401
    CapturedSession,
    MaterializedV0Snapshot,
    SnapshotSource,
    materialize_v0_db,
    materialize_v0_db_for_turn,
)

__all__ = [
    "CapturedSession",
    "MaterializedV0Snapshot",
    "SnapshotSource",
    "materialize_v0_db",
    "materialize_v0_db_for_turn",
]
