"""Card content: what an automation shows on its card through ``haa.card``.

The automation creates elements (``create_text``, ``create_value``, ...), places
them on the card (``add_element``, or through ``layout``), and changes them
afterwards with their setters. The content lives in memory with the running
automation and is handed to the host's ``CardSink`` whenever it has changed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from haanim.engine.assets import AssetStore
from haanim.engine import card_elements as _elements
from haanim.engine.card_elements import MAX_TITLE_LENGTH, CardElement, CardLayout, _check_str
from haanim.interfaces import CardSink

# pylint: disable=redefined-builtin

__all__ = ["CARD_PARTS", "HAAnimCard"]

CARD_PARTS = ("title", "state", "message", "actions", "log")
"""The fixed parts of the card an automation can hide: all are shown unless it hides them."""


# One create method per kind of element; "id" is what an element's ID is called everywhere
# pylint: disable-next=too-many-public-methods
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
        self.automation_id = automation_id
        self.assets = assets
        self.has_action = has_action
        self._sink = sink
        self._layout = CardLayout(self)
        self._title: str | None = None
        self._hidden: set[str] = set()
        self._pending: asyncio.Handle | None = None

    def __repr__(self) -> str:
        """Return a short description."""
        return f"<HAAnimCard {self.automation_id}: {len(self._layout.elements)} elements>"

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
            self.changed()

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
            self.changed()

    # --- Creating elements ------------------------------------------------------

    def create_text(self, id: str, markdown: str) -> _elements.TextElement:
        """Create markdown text. It is shown once it has been added to the card.

        Raises:
            ValueError: If the text is longer than 10 000 characters.
        """
        return _elements.TextElement(self, id, markdown=markdown)

    def create_image(
        self,
        id: str,
        asset: str | None = None,
        url: str | None = None,
        alt: str = "",
    ) -> _elements.ImageElement:
        """Create an image from the automation's ``assets/`` folder or from a URL.

        Raises:
            ValueError: Unless exactly one of ``asset`` and ``url`` is given, or
                the asset name resolves outside ``assets/``.
            FileNotFoundError: If the asset does not exist.
        """
        return _elements.ImageElement(self, id, asset=asset, url=url, alt=alt)

    def create_value(
        self,
        id: str,
        label: str,
        value: str | int | float | bool,
        unit: str = "",
    ) -> _elements.ValueElement:
        """Create a labelled value: a string, number or boolean."""
        return _elements.ValueElement(self, id, label=label, value=value, unit=unit)

    def create_entity(self, id: str, entity_id: str) -> _elements.EntityElement:
        """Create an element that shows the live state of a Home Assistant entity."""
        return _elements.EntityElement(self, id, entity_id=entity_id)

    def create_icon(  # pylint: disable=too-many-positional-arguments
        self,
        id: str,
        entity_id: str | None = None,
        icon: str | None = None,
        label: str | None = None,
        color: str | None = None,
        spin: bool = False,
        follow_entity: bool = True,
    ) -> _elements.IconElement:
        """Create an icon, by default driven by an entity.

        With an entity, the icon follows it: it is the entity's own icon
        unless ``icon`` names another, it is lit while the entity is active
        (on, open, home, ...) and dimmed while it is not, it spins only while
        the entity is active, and the entity's name and state are shown next
        to it. ``follow_entity=False`` turns all of that off: the icon is then
        exactly what the arguments say, and changes only when the automation
        changes the element.

        Args:
            id: ID of the element.
            entity_id: The entity that drives the icon.
            icon: The icon, as ``"mdi:fan"``. Needed without an entity, and with ``follow_entity=False``.
            label: Text next to the icon. The entity's name if the icon follows an entity.
            color: Colour of the icon: a theme colour (``primary``, ``accent``, ``success``,
                ``warning``, ``error``, ``disabled``), a colour name or ``#rrggbb``. Following an
                entity, it is the colour while the entity is active.
            spin: Whether the icon turns. Following an entity, only while the entity is active.
            follow_entity: Whether the entity drives the icon.

        Raises:
            ValueError: If there is neither an entity to follow nor an icon, or the icon,
                the colour or the entity ID is not valid.
        """
        return _elements.IconElement(
            self,
            id,
            entity_id=entity_id,
            icon=icon,
            label=label,
            color=color,
            spin=spin,
            follow_entity=follow_entity,
        )

    def create_graph(
        self,
        id: str,
        entities: str | Sequence[str] | None = None,
        series: Mapping[str, Sequence[Any]] | None = None,
        *,
        hours: float = 24,
        kind: str = "line",
        title: str | None = None,
        unit: str | None = None,
        min: float | None = None,
        max: float | None = None,
        x_major: float | str | None = None,
        x_minor: float | str | None = None,
    ) -> _elements.GraphElement:
        """Create a graph of the history of entities, or of series of the automation's own.

        Exactly one of ``entities`` and ``series`` is given.

        With ``entities`` the graph shows what Home Assistant recorded for
        them over the last ``hours`` and follows them from then on. With
        ``series`` it shows the values given; ``set_series()`` on the element
        replaces them.

        Numbers are drawn against a value axis. An entity or series whose
        values are states, not numbers (``"on"``, ``"off"``, ``"heat"``), is
        drawn as a timeline: a row with a coloured segment for each state it
        was in. A graph can have both.

        Args:
            id: ID of the element.
            entities: One entity ID or up to eight, whose states are drawn over time.
            series: Up to eight named series, ``{"Name": points}``. The points of a series are
                values (drawn one after the other), or ``(x, y)`` pairs where every ``x`` is a
                number, or every ``x`` is a time (a timezone-aware datetime or ISO 8601 text). The
                values of a series are all numbers or all states (text); None leaves a gap. A
                state holds until the next point. At most 500 points per series.
            hours: How far back the history of entities goes; at most 720 (30 days).
            kind: How numbers are drawn: ``"line"``, ``"area"`` or ``"bar"``.
            title: A heading above the graph.
            unit: The unit of the values. For entities it defaults to the first entity's own.
            min: The lowest value of the vertical axis; a round number below the data if omitted.
            max: The highest value of the vertical axis; a round number above the data if omitted.
            x_major: The distance between the labelled marks of the horizontal axis. On a
                time axis (entities, or series over time) a duration: seconds or ``"HH:MM:SS"``;
                otherwise a number. Round distances are chosen if omitted.
            x_minor: The distance between the small marks between them, in the same form;
                it must be less than ``x_major``.

        Raises:
            ValueError: Unless exactly one of ``entities`` and ``series`` is given,
                or an argument is not valid.
        """
        return _elements.GraphElement(
            self,
            id,
            entities=entities,
            series=series,
            hours=hours,
            kind=kind,
            title=title,
            unit=unit,
            min=min,
            max=max,
            x_major=x_major,
            x_minor=x_minor,
        )

    def create_button(
        self,
        id: str,
        label: str,
        action: str,
        confirm: str | None = None,
        **data: Any,
    ) -> _elements.ButtonElement:
        """Create a button that runs one of the automation's actions.

        Args:
            id: ID of the element.
            label: Text on the button.
            action: A name of the action to run.
            confirm: A question the card asks before running the action.
            **data: Passed to the action as ``event.data``; JSON values.

        Raises:
            ValueError: If the automation has no action by that name.
        """
        return _elements.ButtonElement(self, id, label=label, action=action, confirm=confirm, data=data)

    # --- Placing elements --------------------------------------------------------

    @property
    def layout(self) -> CardLayout:
        """Where the elements are on the card: rows from the top, which can be split into cells."""
        return self._layout

    def add_element(self, element: CardElement) -> CardLayout:
        """Add an element to the card in a row of its own, below what is there.

        The same as ``layout.add_element()``. An element that is already on
        the card is moved.

        Returns:
            The layout, so that calls can be chained.

        Raises:
            ValueError: If the card already has another element with that ID, or 50 elements.
        """
        return self._layout.add_element(element)

    def remove_element(self, element: CardElement | str) -> None:
        """Take an element off the card, given the element or its ID. Does nothing if it is not on it."""
        self._layout.remove_element(element)

    def clear(self) -> None:
        """Take every element off the card. The title and the hidden parts stay as they are."""
        self._layout.clear()

    def element(self, id: str) -> CardElement | None:
        """Return the element on the card with an ID, or None if there is none."""
        return self._layout.element(_check_str(id, "id"))

    @property
    def elements(self) -> list[CardElement]:
        """The elements on the card, row by row."""
        return self._layout.elements

    @property
    def blocks(self) -> list[dict[str, Any]]:
        """What the card draws: every element on it in order, each as a dictionary.

        A dictionary has the element's ``id``, its ``type`` and its content.
        The list is a copy: changing it does not change the card.
        """
        return [element.as_dict() for element in self._layout.elements]

    # --- Internals ---------------------------------------------------------------

    def shows(self, element: CardElement) -> bool:
        """Return whether an element is on the card."""
        return self._layout.element(element.id) is element

    def changed(self) -> None:
        """Arrange for the sink to get the content the next time the event loop runs.

        Called by the layout and the elements. Changes made without an await
        or checkpoint between them reach the sink as one update.
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
            self._sink.card_changed(
                self.automation_id,
                {
                    "blocks": self.blocks,
                    "title": self._title,
                    "options": self.options,
                    "layout": self._layout.as_list(),
                },
            )

    def close(self) -> None:
        """Empty the card and tell the sink at once: the automation has stopped."""
        had_content = bool(self._layout.rows) or self._title is not None or bool(self._hidden)
        waiting = self._pending is not None
        self._title = None
        self._hidden = set()
        self._layout = CardLayout(self)
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if had_content or waiting:
            self._deliver()
