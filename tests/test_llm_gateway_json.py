from __future__ import annotations

import unittest
from types import SimpleNamespace

import fitmas.llm_gateway as gw


def _fake_text_response(text: str) -> SimpleNamespace:
    """Mimic the shape Anthropic SDK responses expose to our gateway."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
    )


class LLMGatewayJsonTest(unittest.TestCase):
    """Gateway-level JSON parsing must be as robust as llm._request_json.

    Both request_json() (which re-enters via request_text) and
    message_json() (which reads an already-returned response object)
    feed downstream deterministic parsers; a raw json.loads() there
    silently drops valid-but-slightly-messy LLM outputs."""

    def test_request_json_repairs_truncated_tail(self) -> None:
        original_request_text = gw.request_text
        try:
            gw.request_text = lambda **kwargs: (
                '{"adaptations":[{"action":"replace","session_id":8,"new_duration_min":25,'
                '"rationale":"ok"}],"message":"Je coupe la natation'
            )
            data = gw.request_json(system="x", prompt="y")
        finally:
            gw.request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["adaptations"][0]["session_id"], 8)
        self.assertEqual(data["message"], "Je coupe la natation")

    def test_request_json_extracts_balanced_prefix_before_tail_noise(self) -> None:
        original_request_text = gw.request_text
        try:
            gw.request_text = lambda **kwargs: (
                '{"mutation_type":"no_change","rationale":"ok",'
                '"fitmas_message":"Bien recu."}\nnotes bavardes du modele'
            )
            data = gw.request_json(system="x", prompt="y")
        finally:
            gw.request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["mutation_type"], "no_change")

    def test_message_json_repairs_truncated_tail(self) -> None:
        response = _fake_text_response(
            '{"verdict":"ok","items":[{"id":1,"label":"a"},{"id":2,"label":"b"'
        )
        data = gw.message_json(response)

        self.assertIsNotNone(data)
        self.assertEqual(data["verdict"], "ok")
        self.assertEqual(data["items"][0]["id"], 1)
        self.assertEqual(data["items"][1]["id"], 2)

    def test_message_json_extracts_balanced_prefix_before_tail_noise(self) -> None:
        response = _fake_text_response(
            '{"mutation_type":"no_change","rationale":"ok",'
            '"fitmas_message":"Bien recu."}\nnotes bavardes du modele'
        )
        data = gw.message_json(response)

        self.assertIsNotNone(data)
        self.assertEqual(data["mutation_type"], "no_change")


if __name__ == "__main__":
    unittest.main()
