"""Configuration of the engine tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest


@pytest.fixture(autouse=True)
async def end_what_the_test_left_running() -> AsyncIterator[None]:
    """End the tasks a test leaves behind.

    Most engine tests load automations and never stop them, so triggers are
    still waiting for a change when the test ends. Nothing waits for these
    tasks; they are cancelled here so that a test ends with nothing running.
    """
    yield
    current = asyncio.current_task()
    left = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    for task in left:
        task.cancel()
    await asyncio.gather(*left, return_exceptions=True)
