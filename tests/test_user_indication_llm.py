from __future__ import annotations

from datetime import date

from fitmas.user_indication_llm import _prefer_richer_indication
from fitmas.user_indications import (
    IndicationTimeReference,
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
)


def test_prefers_fallback_when_it_has_richer_time_resolution():
    llm_indication = UserIndication(
        kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
        confidence=0.72,
        source_text="Cette semaine je voyage de mercredi a vendredi",
        scope=UserIndicationScope.UNKNOWN,
        polarity=UserIndicationPolarity.UNAVAILABLE,
        time_reference=None,
    )
    fallback = UserIndication(
        kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
        confidence=0.87,
        source_text="Cette semaine je voyage de mercredi a vendredi",
        scope=UserIndicationScope.WEEK,
        polarity=UserIndicationPolarity.UNAVAILABLE,
        time_reference=IndicationTimeReference(
            label="explicit_wednesday",
            resolved_date=date(2026, 4, 1),
            day_key="wednesday",
            relative_reference="explicit_wednesday",
            window=None,
        ),
    )

    selected = _prefer_richer_indication(llm_indication, fallback)

    assert selected == fallback
