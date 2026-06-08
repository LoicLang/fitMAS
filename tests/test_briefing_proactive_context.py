"""TTL guard sur `_recent_proactive_context` (heartbeat).

Symptome 2026-05-02 : le briefing matin a hallucine "2 sorties offplan cette
semaine" alors que zero offplan existe en DB. Cause racine = la query
recuperait les 2 derniers messages proactifs sans filtre temporel, donc un
briefing d'une semaine anterieure (avec ses chiffres d'epoque) ressortait
dans le prompt actuel et le LLM recopiait ces chiffres comme s'ils
s'appliquaient a la semaine en cours.

Le fix Chantier 0 (2 mai 2026) ajoute un filtre `created_at >= now - TTL`
sur la query. Ces tests verrouillent que :

- un message proactif >24h n'est jamais reinjecte
- un message proactif <24h reste injecte normalement
- la fenetre TTL est parametrable (default 24h)
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

os.environ.setdefault(
    "FITMAS_DB_PATH",
    tempfile.mktemp(prefix="fitmas-proactive-ttl-", suffix=".db"),
)

from fitmas.legacy.core import orm as s
from fitmas.legacy.core.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.skills.heartbeat.heartbeat import (
    RECENT_PROACTIVE_TTL_HOURS,
    _recent_proactive_context,
)


def _utc_now_naive() -> datetime:
    return datetime.now(dt_timezone.utc).replace(tzinfo=None)


class RecentProactiveContextTTLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            coach_name="FitMAS",
            coach_style="direct",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def _add_proactive(self, text: str, *, created_at: datetime) -> s.CoachMessage:
        msg = s.CoachMessage(
            user_id=self.user.id,
            role="agent",
            text=text,
            proactive=True,
            created_at=created_at,
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def test_proactive_within_ttl_is_included(self) -> None:
        now = _utc_now_naive()
        self._add_proactive("Briefing matin recent", created_at=now - timedelta(hours=2))

        result = _recent_proactive_context(self.db, self.user)

        self.assertIn("Briefing matin recent", result)

    def test_proactive_older_than_ttl_is_excluded(self) -> None:
        # Bug 2 mai 2026 : un proactif J-7 etait reinjecte et le LLM recopiait
        # ses chiffres d'epoque comme s'ils s'appliquaient a aujourd'hui.
        now = _utc_now_naive()
        self._add_proactive(
            "Tu as fait 2 sorties offplan cette semaine",
            created_at=now - timedelta(days=7),
        )

        result = _recent_proactive_context(self.db, self.user)

        self.assertEqual(result, "")
        self.assertNotIn("offplan", result)

    def test_old_and_recent_mixed_only_recent_kept(self) -> None:
        now = _utc_now_naive()
        self._add_proactive(
            "Vieux proactif J-7 avec chiffres perimes",
            created_at=now - timedelta(days=7),
        )
        self._add_proactive(
            "Briefing d'hier",
            created_at=now - timedelta(hours=20),
        )

        result = _recent_proactive_context(self.db, self.user)

        self.assertIn("Briefing d'hier", result)
        self.assertNotIn("Vieux proactif", result)
        self.assertNotIn("J-7", result)

    def test_proactive_just_outside_ttl_is_excluded(self) -> None:
        now = _utc_now_naive()
        self._add_proactive(
            f"Briefing {RECENT_PROACTIVE_TTL_HOURS + 1}h",
            created_at=now - timedelta(hours=RECENT_PROACTIVE_TTL_HOURS + 1),
        )

        result = _recent_proactive_context(self.db, self.user)

        self.assertEqual(result, "")

    def test_ttl_is_configurable(self) -> None:
        now = _utc_now_naive()
        self._add_proactive(
            "Briefing 12h",
            created_at=now - timedelta(hours=12),
        )

        # TTL serre a 6h : exclu
        tight = _recent_proactive_context(self.db, self.user, ttl_hours=6)
        self.assertEqual(tight, "")

        # TTL large a 48h : inclu
        large = _recent_proactive_context(self.db, self.user, ttl_hours=48)
        self.assertIn("Briefing 12h", large)

    def test_non_proactive_messages_ignored_even_recent(self) -> None:
        now = _utc_now_naive()
        msg = s.CoachMessage(
            user_id=self.user.id,
            role="agent",
            text="Reponse conversation recente",
            proactive=False,
            created_at=now - timedelta(hours=1),
        )
        self.db.add(msg)
        self.db.commit()

        result = _recent_proactive_context(self.db, self.user)

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
