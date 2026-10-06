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
from collections.abc import Mapping, Sequence
from typing import Any

from haanim.engine.card_layout import MAX_BLOCKS, MAX_ROW_CELLS, CardElement, CardLayout, CardRow
from haanim.engine.card_checks import (
    IMAGE_ALIGNMENTS,
    MAX_CAMERA_REFRESH,
    MAX_CAPTION_LENGTH,
    MAX_GRAPH_HOURS,
    MAX_GRAPH_POINTS,
    MAX_GRAPH_SERIES,
    MAX_GRAPH_STATE_LENGTH,
    MAX_IMAGE_SIZE,
    _check_color,
    _check_entity_id,
    _check_icon,
    _check_number,
    _check_str,
    _graph_entities,
    _graph_marks,
    _graph_series,
    _image_camera,
    _image_look,
)

__all__ = [
    "BadgeElement",
    "ButtonElement",
    "CardElement",
    "CardLayout",
    "CardRow",
    "EntityElement",
    "GAUGE_KINDS",
    "GRAPH_KINDS",
    "GaugeElement",
    "GraphElement",
    "HtmlElement",
    "IMAGE_ALIGNMENTS",
    "IconElement",
    "ImageElement",
    "MAX_BADGE_LENGTH",
    "MAX_BLOCKS",
    "MAX_CAMERA_REFRESH",
    "MAX_CAPTION_LENGTH",
    "MAX_GRAPH_HOURS",
    "MAX_GRAPH_POINTS",
    "MAX_GRAPH_SERIES",
    "MAX_GRAPH_STATE_LENGTH",
    "MAX_HTML_LENGTH",
    "MAX_IMAGE_SIZE",
    "MAX_ROW_CELLS",
    "MAX_TEXT_LENGTH",
    "MAX_TITLE_LENGTH",
    "TextElement",
    "ValueElement",
]

MAX_TEXT_LENGTH = 10_000
"""The most characters a text block can have."""

MAX_HTML_LENGTH = 50_000
"""The most characters an HTML element can have."""

MAX_TITLE_LENGTH = 100
"""The most characters the card's title can have."""

GRAPH_KINDS = ("line", "area", "bar")
"""How a graph can be drawn."""

GAUGE_KINDS = ("bar", "dial")
"""How a gauge can be drawn: a progress bar, or a dial."""

MAX_BADGE_LENGTH = 40
"""The most characters the text of a badge can have."""


def _optional(value: Any) -> str | None:
    """Return a value of an element's content that is text or nothing."""
    return None if value is None else str(value)


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


class HtmlElement(CardElement):
    """HTML of the automation's own, put on the card as it is."""

    TYPE = "html"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        html = _check_str(arguments["html"], "html")
        if len(html) > MAX_HTML_LENGTH:
            raise ValueError(
                f"An HTML element can have at most {MAX_HTML_LENGTH} characters, not {len(html)}"
            )
        return {"html": html}

    @property
    def html(self) -> str:
        """The HTML."""
        return str(self._content["html"])

    def set_html(self, html: str) -> None:
        """Change the HTML.

        Raises:
            ValueError: If the HTML is longer than 50 000 characters.
        """
        self._apply(html=html)


class ImageElement(CardElement):
    """An image from the automation's ``assets/`` folder, from a URL, or the live picture of a camera."""

    TYPE = "image"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        asset, url, entity_id = arguments["asset"], arguments["url"], arguments["entity_id"]
        if sum(source is not None for source in (asset, url, entity_id)) != 1:
            raise ValueError("An image needs exactly one of asset, url and entity_id")
        look = {"alt": _check_str(arguments["alt"], "alt"), **_image_look(arguments)}
        camera = _image_camera(entity_id, arguments["refresh"])
        if camera:
            return {**camera, **look}
        if asset is not None:
            return {"asset": asset, "url": self._card.assets.url(asset), **look}
        return {"url": _check_str(url, "url", empty=False), **look}

    @property
    def asset(self) -> str | None:
        """The name of the asset the image is; None if it comes from a URL."""
        return _optional(self._content.get("asset"))

    @property
    def url(self) -> str | None:
        """The URL the image is loaded from; None for the picture of a camera."""
        return _optional(self._content.get("url"))

    @property
    def entity_id(self) -> str | None:
        """The camera whose picture is shown; None for an image from an asset or a URL."""
        return _optional(self._content.get("entity_id"))

    @property
    def refresh(self) -> float | None:
        """The seconds between two pictures of the camera; None for an image from an asset or a URL."""
        refresh: float | None = self._content.get("refresh")
        return refresh

    @property
    def alt(self) -> str:
        """The text shown in place of the image."""
        return str(self._content["alt"])

    @property
    def width(self) -> str | None:
        """The width the image is drawn at, as ``"120px"`` or ``"50%"``; None for its own."""
        return _optional(self._content["width"])

    @property
    def height(self) -> str | None:
        """The height the image is drawn at, as ``"80px"``; None for its own."""
        return _optional(self._content["height"])

    @property
    def align(self) -> str:
        """Where the image is in its row: ``left``, ``center`` or ``right``."""
        return str(self._content["align"])

    @property
    def caption(self) -> str | None:
        """The text under the image; None for no caption."""
        return _optional(self._content["caption"])

    def set_asset(self, asset: str) -> None:
        """Show an image from the automation's ``assets/`` folder instead.

        Raises:
            ValueError: If the name resolves outside ``assets/``.
            FileNotFoundError: If the asset does not exist.
        """
        self._apply(asset=_check_str(asset, "asset"), url=None, entity_id=None)

    def set_url(self, url: str) -> None:
        """Show an image from a URL instead."""
        self._apply(asset=None, url=_check_str(url, "url"), entity_id=None)

    def set_entity(self, entity_id: str, refresh: float | None = None) -> None:
        """Show the live picture of a camera instead.

        Args:
            entity_id: A ``camera.*`` entity.
            refresh: The seconds between two pictures; as it was if omitted.
        """
        changes: dict[str, Any] = {"asset": None, "url": None, "entity_id": _check_entity_id(entity_id)}
        if refresh is not None:
            changes["refresh"] = refresh
        self._apply(**changes)

    def set_refresh(self, refresh: float) -> None:
        """Change the seconds between two pictures of a camera."""
        self._apply(refresh=refresh)

    def set_alt(self, alt: str) -> None:
        """Change the text shown in place of the image."""
        self._apply(alt=alt)

    def set_size(self, width: int | str | None = None, height: int | None = None) -> None:
        """Change the size the image is drawn at; None leaves a side to the image.

        Args:
            width: Pixels, or a percentage of the space the image has, as ``"50%"``.
            height: Pixels.
        """
        self._apply(width=width, height=height)

    def set_align(self, align: str) -> None:
        """Change where the image is in its row: ``left``, ``center`` or ``right``."""
        self._apply(align=align)

    def set_caption(self, caption: str | None) -> None:
        """Change the text under the image; None for no caption."""
        self._apply(caption=caption)


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
        if icon is not None:
            _check_icon(icon)
        if color is not None:
            _check_color(color)
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


class GaugeElement(CardElement):
    """A number within a range, drawn as a progress bar or as a dial."""

    TYPE = "gauge"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        value, entity_id = arguments["value"], arguments["entity_id"]
        label, unit, color, kind = (
            arguments["label"],
            arguments["unit"],
            arguments["color"],
            arguments["kind"],
        )
        if (value is None) == (entity_id is None):
            raise ValueError("A gauge needs exactly one of value and entity_id")
        if kind not in GAUGE_KINDS:
            raise ValueError(f"Invalid kind {kind!r}: a gauge is one of {', '.join(GAUGE_KINDS)}")
        low, high = _check_number(arguments["min"], "min"), _check_number(arguments["max"], "max")
        if low >= high:
            raise ValueError(f"min ({low:g}) must be less than max ({high:g})")
        if label is not None:
            _check_str(label, "label")
        if unit is not None:
            _check_str(unit, "unit")
        return {
            "value": None if value is None else _check_number(value, "value"),
            "entity_id": None if entity_id is None else _check_entity_id(entity_id),
            "min": low,
            "max": high,
            "label": label,
            "unit": unit,
            "kind": kind,
            "color": None if color is None else _check_color(color),
        }

    @property
    def value(self) -> float | None:
        """The number shown; None if the gauge shows an entity."""
        value: float | None = self._content["value"]
        return value

    @property
    def entity_id(self) -> str | None:
        """The entity whose state is shown; None if the gauge shows a value of the automation's own."""
        return _optional(self._content["entity_id"])

    @property
    def min(self) -> float:
        """The value at which the gauge is empty."""
        return float(self._content["min"])

    @property
    def max(self) -> float:
        """The value at which the gauge is full."""
        return float(self._content["max"])

    @property
    def label(self) -> str | None:
        """The text next to the gauge; None for the entity's name, or no text."""
        return _optional(self._content["label"])

    @property
    def unit(self) -> str | None:
        """The unit shown after the number; None for the entity's own, or no unit."""
        return _optional(self._content["unit"])

    @property
    def kind(self) -> str:
        """How the gauge is drawn: ``bar`` or ``dial``."""
        return str(self._content["kind"])

    @property
    def color(self) -> str | None:
        """The colour of the filled part; None for the default."""
        return _optional(self._content["color"])

    def set_value(self, value: float) -> None:
        """Show this number, instead of the number or the entity the gauge showed."""
        if value is None:
            raise ValueError("A gauge needs exactly one of value and entity_id")
        self._apply(value=value, entity_id=None)

    def set_entity(self, entity_id: str) -> None:
        """Show the state of this entity, instead of the number or the entity the gauge showed."""
        if entity_id is None:
            raise ValueError("A gauge needs exactly one of value and entity_id")
        self._apply(value=None, entity_id=entity_id)

    def set_range(self, min: float, max: float) -> None:  # pylint: disable=redefined-builtin
        """Change the values at which the gauge is empty and full."""
        self._apply(min=min, max=max)

    def set_label(self, label: str | None) -> None:
        """Change the text next to the gauge."""
        self._apply(label=label)

    def set_unit(self, unit: str | None) -> None:
        """Change the unit shown after the number."""
        self._apply(unit=unit)

    def set_kind(self, kind: str) -> None:
        """Change how the gauge is drawn: ``bar`` or ``dial``."""
        self._apply(kind=kind)

    def set_color(self, color: str | None) -> None:
        """Change the colour of the filled part; None for the default."""
        self._apply(color=color)


class BadgeElement(CardElement):
    """A short text in a coloured pill, with an icon if wanted."""

    TYPE = "badge"

    def _build(self, **arguments: Any) -> dict[str, Any]:
        text, entity_id = arguments["text"], arguments["entity_id"]
        icon, color = arguments["icon"], arguments["color"]
        if (text is None) == (entity_id is None):
            raise ValueError("A badge needs exactly one of text and entity_id")
        if text is not None and len(_check_str(text, "text", empty=False)) > MAX_BADGE_LENGTH:
            raise ValueError(f"A badge can have at most {MAX_BADGE_LENGTH} characters, not {len(text)}")
        return {
            "text": text,
            "entity_id": None if entity_id is None else _check_entity_id(entity_id),
            "icon": None if icon is None else _check_icon(icon),
            "color": None if color is None else _check_color(color),
        }

    @property
    def text(self) -> str | None:
        """The text of the badge; None if it shows the state of an entity."""
        return _optional(self._content["text"])

    @property
    def entity_id(self) -> str | None:
        """The entity whose state the badge shows; None if it shows a text of the automation's own."""
        return _optional(self._content["entity_id"])

    @property
    def icon(self) -> str | None:
        """The icon before the text, as ``"mdi:check"``; None for no icon."""
        return _optional(self._content["icon"])

    @property
    def color(self) -> str | None:
        """The colour of the badge; None for the default."""
        return _optional(self._content["color"])

    def set_text(self, text: str) -> None:
        """Show this text, instead of the text or the entity the badge showed.

        Raises:
            ValueError: If the text is empty or longer than 40 characters.
        """
        if text is None:
            raise ValueError("A badge needs exactly one of text and entity_id")
        self._apply(text=text, entity_id=None)

    def set_entity(self, entity_id: str) -> None:
        """Show the state of this entity, instead of the text or the entity the badge showed."""
        if entity_id is None:
            raise ValueError("A badge needs exactly one of text and entity_id")
        self._apply(text=None, entity_id=entity_id)

    def set_icon(self, icon: str | None) -> None:
        """Change the icon before the text; None for no icon."""
        self._apply(icon=icon)

    def set_color(self, color: str | None) -> None:
        """Change the colour of the badge; None for the default."""
        self._apply(color=color)


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
