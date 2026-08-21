"""Shared pytest setup.

Python 3.9's ``asyncio.Lock()`` grabs ``get_event_loop()`` at construction time, and
every Textual widget builds one in ``Widget.__init__``. ``asyncio.run()`` clears the
thread's loop when it finishes, so any test that constructs a widget outside a running
app (``PromptArea()``, ``MemoryPickerScreen(...)``) blew up with "There is no current
event loop" as soon as a pilot test had run before it. Hand every test a current loop.
No-op on 3.10+, where ``Lock()`` no longer touches the policy.
"""

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _current_event_loop():
    try:
        asyncio.get_event_loop_policy().get_event_loop()
        opened = None
    except RuntimeError:
        opened = asyncio.new_event_loop()
        asyncio.set_event_loop(opened)
    try:
        yield
    finally:
        if opened is not None:
            asyncio.set_event_loop(None)
            opened.close()
