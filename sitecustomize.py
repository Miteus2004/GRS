"""Runtime shims for the bundled Ryu/eventlet combination."""

from __future__ import annotations

import importlib


def _patch_eventlet_already_handled() -> None:
    try:
        eventlet_wsgi = importlib.import_module("eventlet.wsgi")
    except Exception:
        return

    if not hasattr(eventlet_wsgi, "ALREADY_HANDLED"):
        eventlet_wsgi.ALREADY_HANDLED = object()


_patch_eventlet_already_handled()
