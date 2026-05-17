from __future__ import annotations


def test_api_messages_exports_target_router() -> None:
    import fitmas.api_messages as legacy_module
    from fitmas.app.api import routes_messages

    assert legacy_module.router is routes_messages.router
    assert legacy_module.post_message is routes_messages.post_message


def test_routes_messages_keeps_post_endpoint_registered() -> None:
    from fitmas.app.api.routes_messages import router

    routes = {(route.path, tuple(sorted(route.methods))) for route in router.routes}

    assert ("/api/v0/messages", ("POST",)) in routes
