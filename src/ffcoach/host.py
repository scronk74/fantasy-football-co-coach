"""Which machine is this, and is it the one that is supposed to be alerting?

**The failure this prevents.** Alert history lives in the local SQLite file and
the heartbeat pings on any successful run, so two machines running the check
produce two independent sets of strikes -- every alert twice -- and, far worse,
a laptop that checks occasionally keeps the heartbeat green while the scheduler
machine is face-down. That defeats E3 entirely: the dead-man's switch cannot
tell "the iMac is fine" from "the laptop pinged for it".

Names are normalised before comparison because macOS is inconsistent about
them: `gethostname()` returns `MacBook-Air.local` on one network and
`MacBook-Air` on another, and a guard that fires spuriously after a Wi-Fi
change is a guard that gets deleted.
"""

from __future__ import annotations

import socket

# mDNS suffixes macOS attaches and removes depending on the network.
_SUFFIXES = (".local", ".lan", ".home", ".localdomain")


def normalize_host(name: str) -> str:
    name = (name or "").strip().lower().rstrip(".")
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def this_host() -> str:
    return normalize_host(socket.gethostname())


def is_scheduler_host(configured: str) -> bool:
    """Whether this machine may send alerts and ping the heartbeat.

    An **unset** value means yes. One machine is the common case, and a guard
    that has to be configured before anything works would be a setup step that
    buys nothing until a second machine exists.
    """
    if not configured.strip():
        return True
    return normalize_host(configured) == this_host()
