"""state_tx — the single shared sync+holder transaction envelope (KLC-057).

`state_tx(ticket, paths, msg)` is a context manager wrapping a lifecycle verb's
body in the `pull → body → CAS-push (with rollback)` envelope exactly once
(ADR Option B). Each verb supplies only its body and enters the wrapper INSIDE
its existing `with acquire_lock(ticket):` critical section.

When `state_feature.enabled()` is False (single-user mode) the wrapper is a pure
pass-through: no pull, no push, no holder writes — the verb behaves exactly as
today (AC-8). It yields `None` in that case so callers can gate holder writes on
`if tx is not None:` and keep the feature-off path byte-for-byte identical.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import state_feature
from _paths import klc_dir


class _TxHandle:
    """Truthy marker yielded when the feature is ON (distinguishes from None)."""


@contextmanager
def state_tx(ticket, paths, msg, remote=None):
    if not state_feature.enabled():
        # AC-8 no-op: run the body, touch no git, write no holder.
        yield None
        return
    # feature-on envelope is completed in step-3.
    raise NotImplementedError("state_tx feature-on path not yet implemented")
