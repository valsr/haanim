"""Card content: the blocks an automation puts on its card through ``haa.card``.

The content is an ordered list of blocks, each with an ID that is unique within
the card. It lives in memory with the running automation and is handed to the
host's ``CardSink`` whenever it has changed.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
from collections.abc import Callable
from typing import Any

from haanim.engine.assets import AssetStore
from haanim.interfaces import CardSink

__all__ = ["CARD_PARTS", "HAAnimCard", "MAX_BLOCKS", "MAX_TEXT_LENGTH", "MAX_TITLE_LENGTH"]

MAX_BLOCKS = 50
"""The most blocks a card can have."""

MAX_TEXT_LENGTH = 10_000
"""The most characters a text block can have."""

MAX_TITLE_LENGTH = 100
"""The most characters the card's title can have."""

CARD_PARTS = ("title", "state", "message", "actions", "log")
"""The fixed parts of the card an automation can hide: all are shown unless it hides them."""


def _check_str(value: Any, what: str, *, empty: bool = True) -> str:
    """Return a string argument, checked."""
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a string, not {type(value).__name__}")
    if not empty and not value.strip():
        raise ValueError(f"{what} must not be empty")
    return value


class HAAnimCard:
    """The content of one automation's card.

    Every method is synchronous. A method that raises leaves the card as it was.
    """

    def __init__(
        self,
        automation_id: str,
        assets: AssetStore,
        has_action: Callable[[str], bool],
        sink: CardSink | None = None,
    ) -> None:
        """Initialize an empty card.

        Args:
            automation_id: ID of the automation the card belongs to.
            assets: The automation's assets, for images.
            has_action: Tells whether the automation has an action by a name.
            sink: Receives the content whenever it has changed. None if nobody shows it.
        """
        self._automation_id = automation_id
        self._assets = assets
        self._has_action = has_action
        self._sink = sink
        self._blocks: dict[str, dict[str, Any]] = {}
        self._title: str | None = None
        self._hidden: set[str] = set()
        self._pending: asyncio.Handle | None = None

    def __repr__(self) -> str:
        """Return a short description."""
        return f"<HAAnimCard {self._automation_id}: {len(self._blocks)} blocks>"

    # --- Title -------------------------------------------------------------------

    @property
    def title(self) -> str | None:
        """The title the automation gave its card; None while the card shows the automation's name."""
        return self._title

    def set_title(self, title: str | None) -> None:
        """Set the title shown at the top of the card.

        Without a title the card shows the automation's name. The title can be
        set again at any time, so it can follow what the automation does.

        Args:
            title: The title, or None to go back to the automation's name.

        Raises:
            ValueError: If the title is empty or longer than 100 characters.
        """
        if title is not None:
            _check_str(title, "title", empty=False)
            if len(title) > MAX_TITLE_LENGTH:
                raise ValueError(
                    f"A card title can have at most {MAX_TITLE_LENGTH} characters, not {len(title)}"
                )
        if title != self._title:
            self._title = title
            self._changed()

    # --- The fixed parts ---------------------------------------------------------

    @property
    def options(self) -> dict[str, bool]:
        """Which fixed parts of the card are shown: ``title``, ``state``, ``message``, ``actions``, ``log``.

        The dictionary is a copy: changing it does not change the card.
        """
        return {part: part not in self._hidden for part in CARD_PARTS}

    def configure(
        self,
        *,
        title: bool | None = None,
        state: bool | None = None,
        message: bool | None = None,
        actions: bool | None = None,
        log: bool | None = None,
    ) -> None:
        """Show or hide the fixed parts of the card.

        Every part is shown until it is hidden. A part that is not named
        keeps its setting, so ``configure(log=False)`` hides only the log
        button. With all five hidden the card is a bare box with the
        automation's content.

        Args:
            title: The title at the top.
            state: The state badge (Running, Stopped, ...).
            message: The status message set with ``haa.set_message()``.
            actions: The button that opens the automation's actions.
            log: The button that goes to the automation's log.

        Raises:
            TypeError: If a value is not True, False or None.
        """
        given = {"title": title, "state": state, "message": message, "actions": actions, "log": log}
        for part, shown in given.items():
            if shown is not None and not isinstance(shown, bool):
                raise TypeError(f"{part} must be True or False, not {type(shown).__name__}")
        hidden = set(self._hidden)
        for part, shown in given.items():
            if shown is True:
                hidden.discard(part)
            elif shown is False:
                hidden.add(part)
        if hidden != self._hidden:
            self._hidden = hidden
            self._changed()

    # --- Blocks ------------------------------------------------------------------

    def text(self, id: str, markdown: str) -> None:  # pylint: disable=redefined-builtin
        """Show markdown text.

        Raises:
            ValueError: If the text is longer than 10 000 characters.
        """
        _check_str(markdown, "markdown")
        if len(markdown) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"A text block can have at most {MAX_TEXT_LENGTH} characters, not {len(markdown)}"
            )
        self._set(id, "text", {"markdown": markdown})

    def image(
        self,
        id: str,  # pylint: disable=redefined-builtin
        asset: str | None = None,
        url: str | None = None,
        alt: str = "",
    ) -> None:
        """Show an image from the automation's ``assets/`` folder or from a URL.

        Raises:
            ValueError: Unless exactly one of ``asset`` and ``url`` is given, or
                the asset name resolves outside ``assets/``.
            FileNotFoundError: If the asset does not exist.
        """
        if (asset is None) == (url is None):
            raise ValueError("An image needs exactly one of asset and url")
        _check_str(alt, "alt")
        if asset is not None:
            self._set(id, "image", {"asset": asset, "url": self._assets.url(asset), "alt": alt})
        else:
            self._set(id, "image", {"url": _check_str(url, "url", empty=False), "alt": alt})

    def value(
        self,
        id: str,  # pylint: disable=redefined-builtin
        label: str,
        value: Any,
        unit: str = "",
    ) -> None:
        """Show a labelled value: a string, number or boolean."""
        _check_str(label, "label")
        _check_str(unit, "unit")
        if not isinstance(value, (str, bool, int, float)):
            raise TypeError(f"value must be a string, number or boolean, not {type(value).__name__}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"value must be a finite number, not {value!r}")
        self._set(id, "value", {"label": label, "value": value, "unit": unit})

    def entity(self, id: str, entity_id: str) -> None:  # pylint: disable=redefined-builtin
        """Show the live state of a Home Assistant entity."""
        domain, dot, name = _check_str(entity_id, "entity_id").partition(".")
        if not dot or not domain or not name or "." in name or entity_id != entity_id.strip():
            raise ValueError(f"Invalid entity ID {entity_id!r}")
        self._set(id, "entity", {"entity_id": entity_id})

    def button(
        self,
        id: str,  # pylint: disable=redefined-builtin
        label: str,
        action: str,
        confirm: str | None = None,
        **data: Any,
    ) -> None:
        """Show a button that runs one of the automation's actions.

        Args:
            id: ID of the block.
            label: Text on the button.
            action: A name of the action to run.
            confirm: A question the card asks before running the action.
            **data: Passed to the action as ``event.data``; JSON values.

        Raises:
            ValueError: If the automation has no action by that name.
        """
        _check_str(label, "label")
        _check_str(action, "action")
        if confirm is not None:
            _check_str(confirm, "confirm")
        if not self._has_action(action):
            raise ValueError(f"Automation '{self._automation_id}' has no action '{action}'")
        try:
            data = json.loads(json.dumps(data, allow_nan=False))
        except (TypeError, ValueError) as err:
            raise TypeError(f"The data of a button must be JSON values: {err}") from None
        self._set(id, "button", {"label": label, "action": action, "confirm": confirm, "data": data})

    def remove(self, id: str) -> None:  # pylint: disable=redefined-builtin
        """Remove a block. Does nothing if the ID is not present."""
        if self._blocks.pop(_check_str(id, "id"), None) is not None:
            self._changed()

    def clear(self) -> None:
        """Remove all blocks."""
        if self._blocks:
            self._blocks = {}
            self._changed()

    @property
    def blocks(self) -> list[dict[str, Any]]:
        """The current blocks in order, each a dictionary with ``id``, ``type`` and its content.

        The list is a copy: changing it does not change the card.
        """
        return copy.deepcopy(list(self._blocks.values()))

    # --- Internals ---------------------------------------------------------------

    def _set(self, block_id: str, kind: str, content: dict[str, Any]) -> None:
        """Replace the block with this ID in place, or append a new one."""
        _check_str(block_id, "id", empty=False)
        block = {"id": block_id, "type": kind, **content}
        if block_id not in self._blocks and len(self._blocks) >= MAX_BLOCKS:
            raise ValueError(f"A card can have at most {MAX_BLOCKS} blocks")
        if self._blocks.get(block_id) == block:
            return
        self._blocks[block_id] = block
        self._changed()

    def _changed(self) -> None:
        """Arrange for the sink to get the content the next time the event loop runs.

        Changes made without an await or checkpoint between them reach the
        sink as one update.
        """
        if self._sink is None or self._pending is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._deliver()
            return
        self._pending = loop.call_soon(self._deliver)

    def _deliver(self) -> None:
        """Hand the current content to the sink."""
        self._pending = None
        if self._sink is not None:
            self._sink.card_changed(self._automation_id, self.blocks, self._title, self.options)

    def close(self) -> None:
        """Empty the card and tell the sink at once: the automation has stopped."""
        had_blocks = bool(self._blocks) or self._title is not None or bool(self._hidden)
        self._title = None
        self._hidden = set()
        waiting = self._pending is not None
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        self._blocks = {}
        if had_blocks or waiting:
            self._deliver()
