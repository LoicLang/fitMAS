from __future__ import annotations

import asyncio

from fitmas import telegram_api


def test_api_post_uses_long_default_timeout_for_slow_coach_turns(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, json, timeout):
            recorded["url"] = url
            recorded["json"] = json
            recorded["timeout"] = timeout
            return FakeResponse()

    monkeypatch.delenv("FITMAS_API_POST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(telegram_api.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(telegram_api.api_post("/api/v0/messages", {"text": "lent"}))

    assert result == {"ok": True}
    assert recorded["timeout"] == 180
