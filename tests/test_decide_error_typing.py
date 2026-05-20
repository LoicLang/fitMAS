from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import patch

import anthropic
import httpx

import fitmas.llm.decision_legacy as llm


def _fake_response(status_code: int = 400) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code=status_code, request=request)


class DecideErrorTypingTest(unittest.TestCase):
    """Fix 3b — when `decide()` swallows an exception from the Anthropic
    call, the structured log must carry a `type=` classifier so
    operational failures (timeout, rate_limit, bad_request, auth,
    connection, api_other, json_parse, unknown) can be triaged
    separately. Behavior is preserved: all paths still return None.
    """

    def setUp(self) -> None:
        # Force `decide()` past the early `_client()` guard so the
        # try/except around the Anthropic call is exercised.
        self._client_patch = patch.object(llm, "_client", lambda: object())
        self._client_patch.start()

    def tearDown(self) -> None:
        self._client_patch.stop()

    def _call_decide_with_raising(self, exc: BaseException) -> logging.LogRecord | None:
        def raise_exc(*args, **kwargs):
            raise exc

        with patch.object(llm, "_request_json", side_effect=raise_exc), \
             patch.object(llm, "_request_json_with_tools", side_effect=raise_exc):
            with self.assertLogs("fitmas.llm", level="WARNING") as captured:
                result = llm.decide("user text", "plan summary")
        self.assertIsNone(result)
        for record in captured.records:
            if "decide_failed" in record.getMessage():
                return record
        return None

    def test_timeout_logs_type_timeout(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        exc = anthropic.APITimeoutError(request=request)
        record = self._call_decide_with_raising(exc)
        self.assertIsNotNone(record, "expected llm.decide_failed warning")
        self.assertIn("type=timeout", record.getMessage())

    def test_bad_request_logs_type_bad_request(self) -> None:
        exc = anthropic.BadRequestError("boom", response=_fake_response(400), body=None)
        record = self._call_decide_with_raising(exc)
        self.assertIsNotNone(record)
        self.assertIn("type=bad_request", record.getMessage())

    def test_rate_limit_logs_type_rate_limit(self) -> None:
        exc = anthropic.RateLimitError("too many", response=_fake_response(429), body=None)
        record = self._call_decide_with_raising(exc)
        self.assertIsNotNone(record)
        self.assertIn("type=rate_limit", record.getMessage())

    def test_json_decode_error_logs_type_json_parse(self) -> None:
        exc = json.JSONDecodeError("mal-formed", "{", 0)
        record = self._call_decide_with_raising(exc)
        self.assertIsNotNone(record)
        self.assertIn("type=json_parse", record.getMessage())

    def test_unknown_exception_logs_type_unknown(self) -> None:
        record = self._call_decide_with_raising(RuntimeError("surprise"))
        self.assertIsNotNone(record)
        self.assertIn("type=unknown", record.getMessage())


if __name__ == "__main__":
    unittest.main()
