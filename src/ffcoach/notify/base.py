"""What a notification is, and what any channel must be able to do.

One interface, deliberately channel-agnostic. `Notification` carries a **tier**
rather than a number, because every service scales urgency differently -- ntfy
uses 1-5, Pushover -2..2, APNs something else again. Mapping a tier to a
service's own scale is the channel's job; deciding what deserves to interrupt
someone is not.

The two tiers are D-016's: an **interrupt** is allowed to buzz a phone during
dinner, a **digest** is not. There are deliberately only two. A third would be
a slider nobody calibrates, and the whole value of the interrupt tier is that
it stays rare enough to still mean something.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class DeliveryError(Exception):
    """The message could not be delivered.

    Distinct from a failed *check* (D-024). A check that cannot run and a check
    that ran and could not be delivered are different problems with different
    fixes, and collapsing them means the alert you never got looks identical to
    the week where nothing was wrong.
    """


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    # "interrupt" | "digest". Never a raw priority number: see module docstring.
    tier: str = "digest"

    @property
    def is_interrupt(self) -> bool:
        return self.tier == "interrupt"


@runtime_checkable
class Notifier(Protocol):
    """Anything that can deliver a `Notification`.

    `name` exists so a delivery failure can say *which* channel failed without
    the caller having to know the concrete type.
    """

    name: str

    def send(self, notification: Notification) -> None:
        """Deliver, or raise `DeliveryError`. Never fail silently."""
        ...
