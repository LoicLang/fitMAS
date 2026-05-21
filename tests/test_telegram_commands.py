from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from fitmas.coach_messages import CoachDraft
import fitmas.app.telegram.commands as telegram_commands
from fitmas.app.telegram.debounce import reset_state


class _FakeJob:
    def __init__(self, *, name: str, chat_id: int, data: dict | None = None):
        self.name = name
        self.chat_id = chat_id
        self.data = data or {}
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class _FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, list[_FakeJob]] = {}
        self.last_job: _FakeJob | None = None
        self.last_when = None
        self.last_callback = None

    def get_jobs_by_name(self, name: str) -> list[_FakeJob]:
        return list(self.jobs.get(name, []))

    def run_once(self, callback, when, data=None, name=None, chat_id=None, user_id=None, job_kwargs=None):
        job = _FakeJob(name=name or "job", chat_id=int(chat_id or 0), data=data)
        self.jobs.setdefault(job.name, []).append(job)
        self.last_job = job
        self.last_when = when
        self.last_callback = callback
        return job


class TelegramCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        reset_state(42)

    async def test_handle_message_batches_quick_messages_into_single_api_call(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(text="Premier message", message_id=1001, reply_text=AsyncMock()),
            effective_chat=SimpleNamespace(id=42),
        )
        second_update = SimpleNamespace(
            message=SimpleNamespace(text="Second message", message_id=1002, reply_text=AsyncMock()),
            effective_chat=SimpleNamespace(id=42),
        )
        job_queue = _FakeJobQueue()
        context = SimpleNamespace(job_queue=job_queue)
        bot = SimpleNamespace(send_message=AsyncMock())
        flush_context = SimpleNamespace(job_queue=job_queue, bot=bot, job=None)

        original_api_post = telegram_commands.api_post
        api_post_mock = AsyncMock(return_value={"assistant_message": {"text": "Réponse groupée"}})
        telegram_commands.api_post = api_post_mock
        try:
            await telegram_commands.handle_message(update, context)
            first_job = job_queue.last_job
            await telegram_commands.handle_message(second_update, context)
            second_job = job_queue.last_job
            flush_context.job = second_job
            await telegram_commands._flush_debounced_messages(flush_context)
        finally:
            telegram_commands.api_post = original_api_post

        self.assertIsNotNone(first_job)
        self.assertTrue(first_job.removed)
        self.assertIsNotNone(second_job)
        self.assertEqual(job_queue.last_when, telegram_commands._DEBOUNCE_SECONDS)
        api_post_mock.assert_awaited_once_with(
            "/api/v0/messages",
            {
                "text": "Premier message\nSecond message",
                "client_message_key": "telegram:42:1001-1002",
                "source": "telegram",
            },
        )
        bot.send_message.assert_awaited_once_with(chat_id=42, text="Réponse groupée")

    async def test_handle_message_falls_back_to_immediate_forward_without_job_queue(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(text="Message seul", message_id=1003, reply_text=AsyncMock()),
            effective_chat=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(job_queue=None)

        original_api_post = telegram_commands.api_post
        api_post_mock = AsyncMock(return_value={"assistant_message": {"text": "Réponse immédiate"}})
        telegram_commands.api_post = api_post_mock
        try:
            await telegram_commands.handle_message(update, context)
        finally:
            telegram_commands.api_post = original_api_post

        api_post_mock.assert_awaited_once_with(
            "/api/v0/messages",
            {
                "text": "Message seul",
                "client_message_key": "telegram:42:1003",
                "source": "telegram",
            },
        )
        update.message.reply_text.assert_awaited_once_with("Réponse immédiate")

    async def test_handle_message_retries_same_client_key_after_lost_api_response(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(text="Remplace les natations", message_id=1004, reply_text=AsyncMock()),
            effective_chat=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(job_queue=None)
        payload = {
            "text": "Remplace les natations",
            "client_message_key": "telegram:42:1004",
            "source": "telegram",
        }

        original_api_post = telegram_commands.api_post
        api_post_mock = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("lost response after commit"),
                {"assistant_message": {"text": "Réponse récupérée"}},
            ]
        )
        telegram_commands.api_post = api_post_mock
        try:
            await telegram_commands.handle_message(update, context)
        finally:
            telegram_commands.api_post = original_api_post

        self.assertEqual(api_post_mock.await_count, 2)
        api_post_mock.assert_any_await("/api/v0/messages", payload)
        update.message.reply_text.assert_awaited_once_with("Réponse récupérée")

    async def test_cmd_heartbeat_routes_manual_cutover_through_runtime(self) -> None:
        import os

        import fitmas.skills.heartbeat.runtime_adapter as adapter

        draft = CoachDraft(text="Runtime heartbeat", proactive=True)
        calls: list[dict[str, object]] = []
        persisted: list[CoachDraft] = []
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace()

        original_flag = os.environ.get("FITMAS_HEARTBEAT_RUNTIME_CUTOVER")
        original_run = adapter.run_heartbeat_trigger
        original_persist = telegram_commands.persist_draft_for_owner

        def fake_run(**kwargs):
            calls.append(kwargs)
            event = adapter.build_heartbeat_input_event(
                user_id=0,
                trigger=kwargs["trigger"],
                source=kwargs["source"],
                delivery_channel=kwargs["delivery_channel"],
                manual=kwargs["manual"],
            )
            return adapter.HeartbeatRuntimeResult(
                event=event,
                outcome=adapter.heartbeat_draft_to_outcome(draft, trigger=kwargs["trigger"]),
                draft=draft,
                reply_text=draft.text,
            )

        try:
            os.environ["FITMAS_HEARTBEAT_RUNTIME_CUTOVER"] = "1"
            adapter.run_heartbeat_trigger = fake_run
            telegram_commands.persist_draft_for_owner = lambda value: persisted.append(value)

            await telegram_commands.cmd_heartbeat(update, context)
        finally:
            if original_flag is None:
                os.environ.pop("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", None)
            else:
                os.environ["FITMAS_HEARTBEAT_RUNTIME_CUTOVER"] = original_flag
            adapter.run_heartbeat_trigger = original_run
            telegram_commands.persist_draft_for_owner = original_persist

        self.assertEqual(calls[0]["trigger"], "morning_briefing")
        self.assertEqual(calls[0]["source"], "telegram")
        self.assertTrue(calls[0]["manual"])
        update.message.reply_text.assert_awaited_once_with("Runtime heartbeat", parse_mode="Markdown")
        self.assertEqual(persisted, [draft])
