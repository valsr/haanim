"""Notification queues by key, shared by the state and the event manager.

A subscriber gets a queue. It receives the notifications for its key (an entity
ID or an event type), or every notification if it subscribed without a key, and
``None`` when the manager shuts down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Generic, TypeVar

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

QUEUE_SIZE = 100
"""How many notifications a subscriber can fall behind before further ones are dropped for it."""


class Subscriptions(Generic[T]):
    """The queues of the subscribers, by key and for everything."""

    def __init__(self, what: str) -> None:
        """Initialize with no subscribers.

        Args:
            what: What the notifications are, for the log: ``"state"`` or ``"event"``.
        """
        self._what = what
        self._by_key: dict[str, list[tuple[asyncio.Queue[T | None], Callable[[T], bool] | None]]] = {}
        self._all: list[asyncio.Queue[T | None]] = []

    def add(self, key: str | None, accepts: Callable[[T], bool] | None = None) -> asyncio.Queue[T | None]:
        """Add a subscriber and return its queue.

        Args:
            key: What to subscribe to; None for everything.
            accepts: Only notifications for which this returns True are delivered to the subscriber.
        """
        queue: asyncio.Queue[T | None] = asyncio.Queue(maxsize=QUEUE_SIZE)
        if key:
            self._by_key.setdefault(key, []).append((queue, accepts))
        else:
            self._all.append(queue)
        return queue

    def remove(self, queue: asyncio.Queue[T | None], key: str | None) -> None:
        """Remove a subscriber. ``key`` is what it subscribed with. Does nothing if it is not there."""
        if key and key in self._by_key:
            self._by_key[key] = [entry for entry in self._by_key[key] if entry[0] is not queue]
        elif queue in self._all:
            self._all.remove(queue)

    def has_key(self, key: str) -> bool:
        """Return whether a key was ever subscribed to."""
        return key in self._by_key

    def deliver(self, key: str, notification: T) -> None:
        """Deliver a notification to the subscribers of its key that accept it."""
        for queue, accepts in self._by_key.get(key, []):
            if accepts is None or accepts(notification):
                self._put(queue, notification, key)

    def deliver_to_all(self, notification: T) -> None:
        """Deliver a notification to the subscribers of everything."""
        for queue in self._all:
            self._put(queue, notification, "everything")

    def _put(self, queue: asyncio.Queue[T | None], notification: T, key: str) -> None:
        try:
            queue.put_nowait(notification)
        except asyncio.QueueFull:
            _LOGGER.warning("%s notification queue full for %s", self._what.capitalize(), key)

    async def close(self) -> None:
        """Tell every subscriber that there is nothing more to come, and forget them."""
        for entries in self._by_key.values():
            for queue, _ in entries:
                await queue.put(None)
        self._by_key.clear()
        for queue in self._all:
            await queue.put(None)
        self._all.clear()
