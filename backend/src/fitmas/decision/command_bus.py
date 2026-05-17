from __future__ import annotations

from typing import Protocol, Sequence

from .outcome import Command, CommandResult


class CommandBus(Protocol):
    def apply(self, commands: Sequence[Command]) -> tuple[CommandResult, ...]:
        ...
