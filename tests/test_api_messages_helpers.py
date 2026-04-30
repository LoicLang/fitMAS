from __future__ import annotations

from fitmas import api_messages


def test_future_confirmation_helper_removed_from_runtime() -> None:
    assert not hasattr(api_messages, "_maybe_future_session_confirmation_reply")
