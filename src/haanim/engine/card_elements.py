"""The elements of a card and the layout that places them.

An automation creates elements with ``haa.card.create_*()``, places them with
``haa.card.add_element()`` or through ``haa.card.layout``, and changes them
afterwards with their setters::

    count = haa.card.create_value("count", label="Presses", value=0)
    haa.card.add_element(count)
    count.set_value(3)                      # only this changes on the card

Every element checks what it is given, at creation and in every setter: a value
that is not valid raises and leaves the element as it was.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar, Protocol

from haanim.engine.assets import AssetStore
from haanim.engine.durations import parse_duration

__all__ = [
    "ButtonElement",
    "CardElement",
    "CardLayout",
    "CardRow",
    "EntityElement",
    "GRAPH_KINDS",
    "GraphElement",
    "IconElement",
    "ImageElement",
    "MAX_BLOCKS",
    "MAX_GRAPH_HOURS",
    "MAX_GRAPH_POINTS",
    "MAX_GRAPH_SERIES",
    "MAX_GRAPH_STATE_LENGTH",
    "MAX_ROW_CELLS",
    "MAX_TEXT_LENGTH",
    "MAX_TITLE_LENGTH",
    "TextElement",
    "ValueElement",
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

MAX_ROW_CELLS = 6
"""The most cells a row of the layout can be split into."""


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


def _graph_marks(major: Any, minor: Any, *, time: bool) -> dict[str, float | None]:
    """Check the distances between the marks of the horizontal axis and return them as the block carries them.

    On a time axis a distance is a duration and is carried in seconds.
    """
    distances: dict[str, float | None] = {}
    for name, value in (("x_major", major), ("x_minor", minor)):
        if value is None:
            distances[name] = None
        elif time:
            try:
                distances[name] = parse_duration(value)
            except ValueError as err:
                raise ValueError(f"{name} is a duration on a time axis: {err}") from None
        else:
            distance = _check_number(value, name)
            if distance <= 0:
                raise ValueError(f"{name} must be more than 0, not {distance:g}")
            distances[name] = distance
    large, small = distances["x_major"], distances["x_minor"]
    if large is not None and small is not None and small >= large:
        raise ValueError(f"x_minor ({small:g}) must be less than x_major ({large:g})")
    return distances


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


def _optional(value: Any) -> str | None:
    """Return a value of an element's content that is text or nothing."""
    return None if value is None else str(value)


class _Card(Protocol):
    """What an element and the layout need of the card they belong to."""

    automation_id: str
    assets: AssetStore
    has_action: Callable[[str], bool]

    def changed(self) -> None:
        """Note that what the card shows has changed."""
        ...

    def shows(self, element: CardElement) -> bool:
        """Return whether an element is on the card."""
        ...


class CardElement:
    """One thing on a card: a text, an image, a value, an entity, an icon, a graph or a button.

    An element is created by the card (``haa.card.create_*()``) and shown once
    it has been added to the layout. Its setters change it in place.
    """

    TYPE: ClassVar[str] = ""

    def __init__(self, card: _Card, element_id: str, **arguments: Any) -> None:
        """Create the element. Automations use ``haa.card.create_*()`` instead.

        Args:
            card: The card the element belongs to.
            element_id: ID of the element, unique among the elements of the card's layout.
            **arguments: What the element shows, as its ``create_*`` method takes it.
        """
        self._card = card
        self._id = _check_str(element_id, "id", empty=False)
        self._arguments = arguments
        self._content = self._build(**arguments)

    def __repr__(self) -> str:
        """Return a short description."""
        return f"<{type(self).__name__} {self._id!r}>"

    @property
    def id(self) -> str:
        """The element's ID."""
        return self._id

    @property
    def type(self) -> str:
        """The kind of element, such as ``text``, ``value`` or ``button``."""
        return self.TYPE

    @property
    def content(self) -> dict[str, Any]:
        """What the element shows, as JSON values. A copy: changing it does not change the element."""
        return copy.deepcopy(self._content)

    def as_dict(self) -> dict[str, Any]:
        """Return the element as the card draws it: its ``id``, its ``type`` and its content."""
        return {"id": self._id, "type": self.TYPE, **copy.deepcopy(self._content)}

    def _build(self, **arguments: Any) -> dict[str, Any]:
        """Check the arguments and return the content they make. Raises if they are not valid."""
        raise NotImplementedError

    def _apply(self, **changes: Any) -> None:
        """Change some arguments. The element stays as it was if the result is not valid."""
        arguments = {**self._arguments, **changes}
        content = self._build(**arguments)
        self._arguments = arguments
        if content != self._content:
            self._content = content
            # An element that is not on the card changes nothing anybody sees
            if self._card.shows(self):
                self._card.changed()


class TextElement(CardElement):
    """Markdown text."""

    TYPE = "text"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        markdown = _check_str(arguments["markdown"], "markdown")
        if len(markdown) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"A text element can have at most {MAX_TEXT_LENGTH} characters, not {len(markdown)}"
            )
        return {"markdown": markdown}

    @property
    def text(self) -> str:
        """The markdown text."""
        return str(self._content["markdown"])

    def set_text(self, markdown: str) -> None:
        """Change the text.

        Raises:
            ValueError: If the text is longer than 10 000 characters.
        """
        self._apply(markdown=markdown)


class ImageElement(CardElement):
    """An image from the automation's ``assets/`` folder or from a URL."""

    TYPE = "image"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        asset, url = arguments["asset"], arguments["url"]
        if (asset is None) == (url is None):
            raise ValueError("An image needs exactly one of asset and url")
        alt = _check_str(arguments["alt"], "alt")
        if asset is not None:
            return {"asset": asset, "url": self._card.assets.url(asset), "alt": alt}
        return {"url": _check_str(url, "url", empty=False), "alt": alt}

    @property
    def asset(self) -> str | None:
        """The name of the asset the image is; None if it comes from a URL."""
        return _optional(self._content.get("asset"))

    @property
    def url(self) -> str:
        """The URL the image is loaded from."""
        return str(self._content["url"])

    @property
    def alt(self) -> str:
        """The text shown in place of the image."""
        return str(self._content["alt"])

    def set_asset(self, asset: str) -> None:
        """Show an image from the automation's ``assets/`` folder instead.

        Raises:
            ValueError: If the name resolves outside ``assets/``.
            FileNotFoundError: If the asset does not exist.
        """
        self._apply(asset=_check_str(asset, "asset"), url=None)

    def set_url(self, url: str) -> None:
        """Show an image from a URL instead."""
        self._apply(asset=None, url=_check_str(url, "url"))

    def set_alt(self, alt: str) -> None:
        """Change the text shown in place of the image."""
        self._apply(alt=alt)


class ValueElement(CardElement):
    """A labelled value: a string, number or boolean."""

    TYPE = "value"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        label = _check_str(arguments["label"], "label")
        unit = _check_str(arguments["unit"], "unit")
        value = arguments["value"]
        if not isinstance(value, (str, bool, int, float)):
            raise TypeError(f"value must be a string, number or boolean, not {type(value).__name__}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"value must be a finite number, not {value!r}")
        return {"label": label, "value": value, "unit": unit}

    @property
    def label(self) -> str:
        """The label."""
        return str(self._content["label"])

    @property
    def value(self) -> str | int | float | bool:
        """The value."""
        value: str | int | float | bool = self._content["value"]
        return value

    @property
    def unit(self) -> str:
        """The unit shown after the value."""
        return str(self._content["unit"])

    def set_value(self, value: str | int | float | bool) -> None:
        """Change the value."""
        self._apply(value=value)

    def set_label(self, label: str) -> None:
        """Change the label."""
        self._apply(label=label)

    def set_unit(self, unit: str) -> None:
        """Change the unit."""
        self._apply(unit=unit)


class EntityElement(CardElement):
    """The live state of a Home Assistant entity."""

    TYPE = "entity"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        return {"entity_id": _check_entity_id(arguments["entity_id"])}

    @property
    def entity_id(self) -> str:
        """The entity shown."""
        return str(self._content["entity_id"])

    def set_entity(self, entity_id: str) -> None:
        """Show another entity."""
        self._apply(entity_id=entity_id)


class IconElement(CardElement):
    """An icon, driven by an entity unless told otherwise."""

    TYPE = "icon"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        entity_id, icon = arguments["entity_id"], arguments["icon"]
        label, color = arguments["label"], arguments["color"]
        spin, follow_entity = arguments["spin"], arguments["follow_entity"]
        if entity_id is not None:
            _check_entity_id(entity_id)
        if not isinstance(follow_entity, bool):
            raise TypeError(f"follow_entity must be True or False, not {type(follow_entity).__name__}")
        if not isinstance(spin, bool):
            raise TypeError(f"spin must be True or False, not {type(spin).__name__}")
        follows = follow_entity and entity_id is not None
        if icon is None and not follows:
            raise ValueError("An icon element needs an icon, or an entity to follow")
        if icon is not None and not _ICON.fullmatch(_check_str(icon, "icon")):
            raise ValueError(f"Invalid icon {icon!r}: an icon is named like 'mdi:fan'")
        if color is not None and not _COLOR.fullmatch(_check_str(color, "color")):
            raise ValueError(f"Invalid color {color!r}: use a colour name or '#rrggbb'")
        if label is not None:
            _check_str(label, "label")
        return {
            "entity_id": entity_id,
            "icon": icon,
            "label": label,
            "color": color,
            "spin": spin,
            "follow_entity": follows,
        }

    @property
    def entity_id(self) -> str | None:
        """The entity the icon belongs to; None if it has none."""
        return _optional(self._content.get("entity_id"))

    @property
    def icon(self) -> str | None:
        """The icon, as ``"mdi:fan"``; None for the entity's own icon."""
        return _optional(self._content.get("icon"))

    @property
    def label(self) -> str | None:
        """The text next to the icon; None for the entity's name, or no text."""
        return _optional(self._content.get("label"))

    @property
    def color(self) -> str | None:
        """The colour of the icon; None for the default."""
        return _optional(self._content.get("color"))

    @property
    def spin(self) -> bool:
        """Whether the icon turns."""
        return bool(self._content["spin"])

    @property
    def follow_entity(self) -> bool:
        """Whether the entity drives the icon."""
        return bool(self._content["follow_entity"])

    def set_entity(self, entity_id: str | None) -> None:
        """Change the entity the icon belongs to; None for no entity (the icon then needs an ``icon``)."""
        self._apply(entity_id=entity_id)

    def set_icon(self, icon: str | None) -> None:
        """Change the icon; None for the entity's own icon."""
        self._apply(icon=icon)

    def set_label(self, label: str | None) -> None:
        """Change the text next to the icon."""
        self._apply(label=label)

    def set_color(self, color: str | None) -> None:
        """Change the colour of the icon; None for the default."""
        self._apply(color=color)

    def set_spin(self, spin: bool) -> None:
        """Make the icon turn, or stop it."""
        self._apply(spin=spin)

    def set_follow_entity(self, follow_entity: bool) -> None:
        """Let the entity drive the icon, or stop it from doing so."""
        self._apply(follow_entity=follow_entity)


class GraphElement(CardElement):
    """A graph of the history of entities, or of series of the automation's own."""

    TYPE = "graph"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        entities, series = arguments["entities"], arguments["series"]
        kind, title, unit = arguments["kind"], arguments["title"], arguments["unit"]
        if (entities is None) == (series is None):
            raise ValueError("A graph needs exactly one of entities and series")
        if kind not in GRAPH_KINDS:
            raise ValueError(f"Invalid kind {kind!r}: a graph is one of {', '.join(GRAPH_KINDS)}")
        if title is not None:
            _check_str(title, "title")
        if unit is not None:
            _check_str(unit, "unit")
        low = _check_number(arguments["min"], "min") if arguments["min"] is not None else None
        high = _check_number(arguments["max"], "max") if arguments["max"] is not None else None
        if low is not None and high is not None and low >= high:
            raise ValueError(f"min ({low:g}) must be less than max ({high:g})")
        content: dict[str, Any] = {"kind": kind, "title": title, "unit": unit, "min": low, "max": high}
        if entities is not None:
            content.update(_graph_entities(entities, arguments["hours"]))
        else:
            content.update(_graph_series(series))
        time = entities is not None or content.get("x") == "time"
        content.update(_graph_marks(arguments["x_major"], arguments["x_minor"], time=time))
        return content

    @property
    def entities(self) -> list[str] | None:
        """The entities whose history is drawn; None for a graph of the automation's own series."""
        entities = self._content.get("entities")
        return list(entities) if entities is not None else None

    @property
    def series(self) -> dict[str, list[list[Any]]] | None:
        """The automation's own series as ``{name: [[x, y], ...]}``; None for a graph of entities."""
        return copy.deepcopy(self._content.get("series"))

    @property
    def kind(self) -> str:
        """How numbers are drawn: ``line``, ``area`` or ``bar``."""
        return str(self._content["kind"])

    @property
    def title(self) -> str | None:
        """The heading above the graph."""
        return _optional(self._content.get("title"))

    def set_series(self, series: Mapping[str, Sequence[Any]]) -> None:
        """Draw these series of the automation's own instead of what the graph showed."""
        if series is None:
            raise ValueError("A graph needs exactly one of entities and series")
        self._apply(series=series, entities=None)

    def set_entities(self, entities: str | Sequence[str], hours: float | None = None) -> None:
        """Draw the history of these entities instead of what the graph showed.

        Args:
            entities: One entity ID or up to eight.
            hours: How far back the history goes; as it was if omitted.
        """
        if entities is None:
            raise ValueError("A graph needs exactly one of entities and series")
        changes: dict[str, Any] = {"entities": entities, "series": None}
        if hours is not None:
            changes["hours"] = hours
        self._apply(**changes)

    def set_hours(self, hours: float) -> None:
        """Change how far back the history of entities goes."""
        self._apply(hours=hours)

    def set_kind(self, kind: str) -> None:
        """Change how numbers are drawn: ``line``, ``area`` or ``bar``."""
        self._apply(kind=kind)

    def set_title(self, title: str | None) -> None:
        """Change the heading above the graph; None for no heading."""
        self._apply(title=title)

    def set_unit(self, unit: str | None) -> None:
        """Change the unit of the values; None for the first entity's own."""
        self._apply(unit=unit)

    def set_range(
        self,
        min: float | None = None,  # pylint: disable=redefined-builtin
        max: float | None = None,  # pylint: disable=redefined-builtin
    ) -> None:
        """Fix the ends of the value axis; None leaves an end to the data."""
        self._apply(min=min, max=max)

    def set_marks(self, x_major: float | str | None = None, x_minor: float | str | None = None) -> None:
        """Set the distances between the marks of the horizontal axis; None lets the card pick."""
        self._apply(x_major=x_major, x_minor=x_minor)


class ButtonElement(CardElement):
    """A button that runs one of the automation's actions."""

    TYPE = "button"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        label = _check_str(arguments["label"], "label")
        action = _check_str(arguments["action"], "action")
        confirm = arguments["confirm"]
        if confirm is not None:
            _check_str(confirm, "confirm")
        if not self._card.has_action(action):
            raise ValueError(f"Automation '{self._card.automation_id}' has no action '{action}'")
        try:
            data = json.loads(json.dumps(arguments["data"], allow_nan=False))
        except (TypeError, ValueError) as err:
            raise TypeError(f"The data of a button must be JSON values: {err}") from None
        return {"label": label, "action": action, "confirm": confirm, "data": data}

    @property
    def label(self) -> str:
        """The text on the button."""
        return str(self._content["label"])

    @property
    def action(self) -> str:
        """The action the button runs."""
        return str(self._content["action"])

    @property
    def confirm(self) -> str | None:
        """The question the card asks before running the action; None for none."""
        return _optional(self._content.get("confirm"))

    @property
    def data(self) -> dict[str, Any]:
        """What the action gets as ``event.data``. A copy."""
        return copy.deepcopy(self._content["data"])

    def set_label(self, label: str) -> None:
        """Change the text on the button."""
        self._apply(label=label)

    def set_action(self, action: str) -> None:
        """Run another action.

        Raises:
            ValueError: If the automation has no action by that name.
        """
        self._apply(action=action)

    def set_confirm(self, confirm: str | None) -> None:
        """Change the question asked before running the action; None for none."""
        self._apply(confirm=confirm)

    def set_data(self, **data: Any) -> None:
        """Replace what the action gets as ``event.data``; JSON values."""
        self._apply(data=data)


class CardRow:
    """A row of the layout, split into cells of equal width.

    Elements fill the cells from the left. A row that is full ignores
    further elements.
    """

    def __init__(self, layout: CardLayout, cells: int) -> None:
        """Create a row. Automations use ``layout.split_row()`` instead."""
        self._layout = layout
        self._cells = cells
        self._elements: list[CardElement] = []

    def __repr__(self) -> str:
        """Return a short description."""
        return f"<CardRow {len(self._elements)}/{self._cells}>"

    @property
    def cells(self) -> int:
        """How many cells the row has."""
        return self._cells

    @property
    def elements(self) -> list[CardElement]:
        """The elements in the row, from the left."""
        return list(self._elements)

    @property
    def is_full(self) -> bool:
        """Whether every cell has an element."""
        return len(self._elements) >= self._cells

    def add_element(self, element: CardElement) -> CardRow:
        """Put an element into the next free cell. Does nothing if the row is full.

        An element that is elsewhere on the card is moved here.

        Returns:
            The row, so that calls can be chained.

        Raises:
            ValueError: If the card already has another element with that ID, or 50 elements.
        """
        self._layout.place(element, self)
        return self


class CardLayout:
    """Where the elements of a card are: a list of rows, from the top.

    ``add_element()`` gives an element a row of its own. ``split_row(n)`` adds
    a row of ``n`` cells of equal width, to be filled with ``add_element()``
    on the row. On a narrow card the cells of a row wrap onto further lines.
    """

    def __init__(self, card: _Card) -> None:
        """Create an empty layout. Automations use ``haa.card.layout``."""
        self._card = card
        self._rows: list[CardRow] = []

    def __repr__(self) -> str:
        """Return a short description."""
        return f"<CardLayout {len(self._rows)} rows, {len(self.elements)} elements>"

    @property
    def rows(self) -> list[CardRow]:
        """The rows, from the top."""
        return list(self._rows)

    @property
    def elements(self) -> list[CardElement]:
        """Every element on the card, row by row."""
        return [element for row in self._rows for element in row.elements]

    def element(self, element_id: str) -> CardElement | None:
        """Return the element with an ID, or None if the card has none."""
        return next((element for element in self.elements if element.id == element_id), None)

    def add_element(self, element: CardElement) -> CardLayout:
        """Add an element in a row of its own, below what is there.

        An element that is elsewhere on the card is moved.

        Returns:
            The layout, so that calls can be chained.

        Raises:
            ValueError: If the card already has another element with that ID, or 50 elements.
        """
        row = CardRow(self, 1)
        self._rows.append(row)
        try:
            self.place(element, row)
        finally:
            self._drop_empty_single_rows()
        return self

    def split_row(self, cells: int) -> CardRow:
        """Add a row of cells of equal width, below what is there, and return it.

        Args:
            cells: How many cells the row has, 1 to 6.

        Raises:
            ValueError: If the number of cells is not 1 to 6.
        """
        if isinstance(cells, bool) or not isinstance(cells, int):
            raise TypeError(f"cells must be a whole number, not {type(cells).__name__}")
        if not 1 <= cells <= MAX_ROW_CELLS:
            raise ValueError(f"A row has 1 to {MAX_ROW_CELLS} cells, not {cells}")
        row = CardRow(self, cells)
        self._rows.append(row)
        return row

    def place(self, element: CardElement, row: CardRow) -> None:
        """Put an element into a row of this layout; used by the rows. A full row ignores it."""
        if not isinstance(element, CardElement):
            raise TypeError(f"Only elements can be added to a card, not {type(element).__name__}")
        if element._card is not self._card:  # pylint: disable=protected-access
            raise ValueError(f"Element '{element.id}' belongs to another card")
        here = self._row_of(element)
        if row.is_full and here is not row:
            return
        other = self.element(element.id)
        if other is not None and other is not element:
            raise ValueError(f"The card already has an element '{element.id}'")
        if here is None and len(self.elements) >= MAX_BLOCKS:
            raise ValueError(f"A card can have at most {MAX_BLOCKS} elements")
        if here is row and row._elements[-1] is element:  # pylint: disable=protected-access
            return
        if here is not None:
            here._elements.remove(element)  # pylint: disable=protected-access
        row._elements.append(element)  # pylint: disable=protected-access
        self._drop_empty_single_rows()
        self._card.changed()

    def remove_element(self, element: CardElement | str) -> None:
        """Take an element off the card. Does nothing if it is not on it.

        Args:
            element: The element, or its ID.
        """
        found = self.element(element) if isinstance(element, str) else element
        if not isinstance(found, CardElement) and found is not None:
            raise TypeError(f"remove_element takes an element or its ID, not {type(element).__name__}")
        row = self._row_of(found) if found is not None else None
        if row is None or found is None:
            return
        row._elements.remove(found)  # pylint: disable=protected-access
        self._drop_empty_single_rows()
        self._card.changed()

    def clear(self) -> None:
        """Take everything off the card: every element and every row."""
        if self._rows:
            self._rows = []
            self._card.changed()

    def as_list(self) -> list[dict[str, Any]]:
        """Return the layout as the card draws it: for each row that has elements, its cells and their IDs."""
        return [
            {"cells": row.cells, "elements": [element.id for element in row.elements]}
            for row in self._rows
            if row.elements
        ]

    def _row_of(self, element: CardElement | None) -> CardRow | None:
        return next((row for row in self._rows if any(one is element for one in row.elements)), None)

    def _drop_empty_single_rows(self) -> None:
        """Forget rows of one cell that have lost their element; split rows stay, to be filled again."""
        self._rows = [row for row in self._rows if row.cells > 1 or row.elements]
