from __future__ import annotations


from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_api_messages_wrapper_is_deleted() -> None:
    assert not (ROOT / "backend/src/fitmas/api_messages.py").exists()


def test_routes_messages_keeps_post_endpoint_registered() -> None:
    from fitmas.app.api.routes_messages import router

    routes = {(route.path, tuple(sorted(route.methods))) for route in router.routes}

    assert ("/api/v0/messages", ("POST",)) in routes
