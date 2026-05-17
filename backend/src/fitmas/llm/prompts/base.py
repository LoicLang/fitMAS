from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptRender:
    system: str
    prompt: str
    max_tokens: int


def join_sections(*sections: str | None) -> str:
    return "\n\n".join(str(section).strip() for section in sections if str(section or "").strip())


def render_json_block(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
