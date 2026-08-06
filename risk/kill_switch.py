"""A halt switch for the order-slicing simulator: once tripped, no
further child orders are submitted for the rest of that run. Manual reset
only -- nothing in this codebase calls `reset()` automatically, and
`reset()` itself refuses to run without an explicit `confirm=True`, so a
reset can't happen by accident (a stray call, a retry loop, etc.).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class KillSwitchEvent:
    timestamp: datetime
    reason: str


class KillSwitch:
    def __init__(self):
        self._event: KillSwitchEvent | None = None

    @property
    def is_tripped(self) -> bool:
        return self._event is not None

    @property
    def event(self) -> KillSwitchEvent | None:
        return self._event

    def trip(self, reason: str, timestamp: datetime) -> None:
        """First trip wins -- if already tripped, the original reason and
        timestamp are kept rather than overwritten by a later cause."""
        if self._event is None:
            self._event = KillSwitchEvent(timestamp=timestamp, reason=reason)

    def reset(self, confirm: bool = False) -> None:
        if not confirm:
            raise ValueError(
                "reset() requires confirm=True -- this is a manual-only control, "
                "not something a retry loop or default argument should trigger"
            )
        self._event = None
