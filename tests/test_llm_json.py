from __future__ import annotations

import unittest

import fitmas.llm as llm


class LLMJsonRepairTest(unittest.TestCase):
    def test_request_json_repairs_truncated_tail(self) -> None:
        original_request_text = llm._request_text
        try:
            llm._request_text = lambda **kwargs: (
                '{"adaptations":[{"action":"replace","session_id":8,"new_duration_min":25,'
                '"rationale":"ok"}],"message":"Je coupe la natation'
            )
            data = llm._request_json(system="x", prompt="y")
        finally:
            llm._request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["adaptations"][0]["session_id"], 8)
        self.assertEqual(data["message"], "Je coupe la natation")

    def test_request_json_extracts_balanced_prefix_before_tail_noise(self) -> None:
        original_request_text = llm._request_text
        try:
            llm._request_text = lambda **kwargs: '{"mutation_type":"no_change","rationale":"ok","fitmas_message":"Bien recu."}\nnotes'
            data = llm._request_json(system="x", prompt="y")
        finally:
            llm._request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["mutation_type"], "no_change")


if __name__ == "__main__":
    unittest.main()
