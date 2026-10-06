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
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from haanim.engine.assets import AssetStore
from haanim.interfaces import CardSink

__all__ = [
    "CARD_PARTS",
    "GRAPH_KINDS",
    "HAAnimCard",
    "MAX_BLOCKS",
    "MAX_GRAPH_HOURS",
    "MAX_GRAPH_POINTS",
    "MAX_GRAPH_SERIES",
    "MAX_GRAPH_STATE_LENGTH",
    "MAX_TEXT_LENGTH",
    "MAX_TITLE_LENGTH",
]

MAX_BLOCKS = 50
"""The most blocks a card can have."""

MAX_TEXT_LENGTH = 10_000
"""The most characters a text block can have."""

MAX_TITLE_LENGTH = 100
"""The most characters the card's title can have."""

MAX_GRAPH_SERIES = 8
"""The most lines a graph can have: entities, or series of the automation's own."""

MAX_GRAPH_POINTS = 500
"""The most points one series of a graph can have."""

MAX_GRAPH_STATE_LENGTH = 40
"""The most characters a state in a series of states can have."""

MAX_GRAPH_HOURS = 720
"""The longest entity history a graph can show: 30 days."""

GRAPH_KINDS = ("line", "area", "bar")
"""How a graph can be drawn."""

CARD_PARTS = ("title", "state", "message", "actions", "log")
"""The fixed parts of the card an automation can hide: all are shown unless it hides them."""


def _check_str(value: Any, what: str, *, empty: bool = True) -> str:
    """Return a string argument, checked."""
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a string, not {type(value).__name__}")
    if not empty and not value.strip():
        raise ValueError(f"{what} must not be empty")
    return value


def _check_entity_id(entity_id: Any) -> str:
    """Return an entity ID argument, checked to have the form ``domain.name``."""
    domain, dot, name = _check_str(entity_id, "entity_id").partition(".")
    if not dot or not domain or not name or "." in name or entity_id != entity_id.strip():
        raise ValueError(f"Invalid entity ID {entity_id!r}")
    return str(entity_id)


def _check_number(value: Any, what: str) -> float:
    """Return a numeric argument as a float, checked to be a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{what} must be a number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, not {value!r}")
    return float(value)


def _graph_x(value: Any, where: str) -> tuple[str, float]:
    """Return what kind of horizontal position a value is (``number`` or ``time``) and its number.

    A time becomes seconds since 1970, which is what the card draws along the axis.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{where}: {value!r} is not a time in ISO 8601 form") from None
    else:
        return "number", _check_number(value, where)
    if moment.tzinfo is None:
        raise ValueError(f"{where}: the time {value!r} has no time zone")
    return "time", moment.timestamp()


def _graph_entities(entities: Any, hours: Any) -> dict[str, Any]:
    """Check the entities and the time span of a history graph and return them as the block carries them."""
    span = _check_number(hours, "hours")
    if not 0 < span <= MAX_GRAPH_HOURS:
        raise ValueError(f"hours must be more than 0 and at most {MAX_GRAPH_HOURS}, not {span:g}")
    if isinstance(entities, (bytes, Mapping)) or not isinstance(entities, (str, Sequence)):
        raise TypeError(f"entities must be an entity ID or a list of them, not {type(entities).__name__}")
    names = [entities] if isinstance(entities, str) else list(entities)
    if not 1 <= len(names) <= MAX_GRAPH_SERIES:
        raise ValueError(f"A graph shows 1 to {MAX_GRAPH_SERIES} entities, not {len(names)}")
    checked = [_check_entity_id(name) for name in names]
    if len(set(checked)) != len(checked):
        raise ValueError("A graph shows each entity once")
    return {"entities": checked, "hours": span}


def _graph_point(point: Any, index: int, here: str) -> tuple[str, float, float | str | None]:
    """Check one point of a series.

    Returns:
        The kind of its horizontal position (``index``, ``number`` or ``time``), that
        position as a number, and its value: a number, a state as text, or None.
    """
    if isinstance(point, (list, tuple)):
        if len(point) != 2:
            raise ValueError(f"{here}: a point is a value or an (x, y) pair, not {point!r}")
        kind, horizontal = _graph_x(point[0], here)
        value = point[1]
    else:
        kind, horizontal, value = "index", float(index), point
    if value is None:
        return kind, horizontal, None
    if isinstance(value, str):
        if not value.strip() or len(value) > MAX_GRAPH_STATE_LENGTH:
            raise ValueError(
                f"{here}: a state is 1 to {MAX_GRAPH_STATE_LENGTH} characters of text, not {value!r}"
            )
        return kind, horizontal, value
    return kind, horizontal, _check_number(value, here)


def _graph_series(series: Any) -> dict[str, Any]:
    """Check the series of a graph and return them as the block carries them.

    Returns:
        ``series`` as ``{name: [[x, y], ...]}``, where ``x`` is a number and ``y`` a number,
        a state as text, or None; and ``x``: ``index`` if the points were plain values, else
        ``number`` or ``time``.
    """
    if not isinstance(series, Mapping):
        raise TypeError(f"series must be a dictionary of name to points, not {type(series).__name__}")
    if not 1 <= len(series) <= MAX_GRAPH_SERIES:
        raise ValueError(f"A graph shows 1 to {MAX_GRAPH_SERIES} series, not {len(series)}")
    kinds: set[str] = set()
    checked: dict[str, list[list[float | str | None]]] = {}
    for name, points in series.items():
        where = f"series {_check_str(name, 'a series name', empty=False)!r}"
        if isinstance(points, (str, bytes, Mapping)) or not isinstance(points, Sequence):
            raise TypeError(f"{where}: the points must be a list, not {type(points).__name__}")
        if len(points) > MAX_GRAPH_POINTS:
            raise ValueError(f"{where} has {len(points)} points; a series has at most {MAX_GRAPH_POINTS}")
        pairs: list[list[float | str | None]] = []
        forms: set[str] = set()
        for index, point in enumerate(points):
            kind, horizontal, value = _graph_point(point, index, f"{where}, point {index}")
            kinds.add(kind)
            if value is not None:
                forms.add("states" if isinstance(value, str) else "numbers")
            pairs.append([horizontal, value])
        if len(forms) > 1:
            raise ValueError(f"{where} mixes numbers and states; a series is one or the other")
        checked[name] = pairs
    if len(kinds) > 1:
        raise ValueError(
            "The points of a graph are all plain values, all (number, y) pairs or all (time, y) pairs; "
            f"these are mixed: {', '.join(sorted(kinds))}"
        )
    return {"series": checked, "x": kinds.pop() if kinds else "index"}


# An icon is "<set>:<name>", as in "mdi:fan"; a colour is a name or a hex value
_ICON = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*:[a-z0-9]+(-[a-z0-9]+)*")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+(-[a-zA-Z]+)*")


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
        _check_entity_id(entity_id)
        self._set(id, "entity", {"entity_id": entity_id})

    def icon(  # pylint: disable=too-many-positional-arguments
        self,
        id: str,  # pylint: disable=redefined-builtin
        entity_id: str | None = None,
        icon: str | None = None,
        label: str | None = None,
        color: str | None = None,
        spin: bool = False,
        follow_entity: bool = True,
    ) -> None:
        """Show an icon, by default driven by an entity.

        With an entity, the icon follows it: it is the entity's own icon
        unless ``icon`` names another, it is lit while the entity is active
        (on, open, home, ...) and dimmed while it is not, it spins only while
        the entity is active, and the entity's name and state are shown next
        to it. ``follow_entity=False`` turns all of that off: the icon is then
        exactly what the arguments say, and changes only when the automation
        sets the block again.

        Args:
            id: ID of the block.
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
        if entity_id is not None:
            _check_entity_id(entity_id)
        if not isinstance(follow_entity, bool):
            raise TypeError(f"follow_entity must be True or False, not {type(follow_entity).__name__}")
        if not isinstance(spin, bool):
            raise TypeError(f"spin must be True or False, not {type(spin).__name__}")
        follows = follow_entity and entity_id is not None
        if icon is None and not follows:
            raise ValueError("An icon block needs an icon, or an entity to follow")
        if icon is not None and not _ICON.fullmatch(_check_str(icon, "icon")):
            raise ValueError(f"Invalid icon {icon!r}: an icon is named like 'mdi:fan'")
        if color is not None and not _COLOR.fullmatch(_check_str(color, "color")):
            raise ValueError(f"Invalid color {color!r}: use a colour name or '#rrggbb'")
        if label is not None:
            _check_str(label, "label")
        self._set(
            id,
            "icon",
            {
                "entity_id": entity_id,
                "icon": icon,
                "label": label,
                "color": color,
                "spin": spin,
                "follow_entity": follows,
            },
        )

    def graph(
        self,
        id: str,  # pylint: disable=redefined-builtin
        entities: str | Sequence[str] | None = None,
        series: Mapping[str, Sequence[Any]] | None = None,
        *,
        hours: float = 24,
        kind: str = "line",
        title: str | None = None,
        unit: str | None = None,
        min: float | None = None,  # pylint: disable=redefined-builtin
        max: float | None = None,  # pylint: disable=redefined-builtin
    ) -> None:
        """Show a graph: the history of entities, or series of the automation's own (exactly one of the two).

        With ``entities`` the graph shows what Home Assistant recorded for
        them over the last ``hours`` and follows them from then on. With
        ``series`` it shows the values given; to change them, set the block
        again.

        Numbers are drawn against a value axis. An entity or series whose
        values are states, not numbers (``"on"``, ``"off"``, ``"heat"``), is
        drawn as a timeline: a row with a coloured segment for each state it
        was in. A graph can have both.

        Args:
            id: ID of the block.
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

        Raises:
            ValueError: Unless exactly one of ``entities`` and ``series`` is given,
                or an argument is not valid.
        """
        if (entities is None) == (series is None):
            raise ValueError("A graph needs exactly one of entities and series")
        if kind not in GRAPH_KINDS:
            raise ValueError(f"Invalid kind {kind!r}: a graph is one of {', '.join(GRAPH_KINDS)}")
        if title is not None:
            _check_str(title, "title")
        if unit is not None:
            _check_str(unit, "unit")
        low = _check_number(min, "min") if min is not None else None
        high = _check_number(max, "max") if max is not None else None
        if low is not None and high is not None and low >= high:
            raise ValueError(f"min ({low:g}) must be less than max ({high:g})")
        content: dict[str, Any] = {"kind": kind, "title": title, "unit": unit, "min": low, "max": high}
        content.update(_graph_entities(entities, hours) if entities is not None else _graph_series(series))
        self._set(id, "graph", content)

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
