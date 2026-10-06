"""The checks of what an automation gives the elements of its card.

Each returns the value in the form the card carries it, or raises: ``TypeError``
for a wrong type, ``ValueError`` for a value that is not valid.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from haanim.engine.durations import parse_duration

IMAGE_ALIGNMENTS = ("left", "center", "right")
"""Where an image can be in its row."""

MAX_IMAGE_SIZE = 4000
"""The largest width or height an image can be given, in pixels."""

MAX_CAPTION_LENGTH = 200
"""The most characters the caption of an image can have."""

MAX_GRAPH_SERIES = 8
"""The most lines a graph can have: entities, or series of the automation's own."""

MAX_GRAPH_POINTS = 500
"""The most points one series of a graph can have."""

MAX_GRAPH_STATE_LENGTH = 40
"""The most characters a state in a series of states can have."""

MAX_GRAPH_HOURS = 720
"""The longest entity history a graph can show: 30 days."""


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


def _check_icon(icon: Any) -> str:
    """Return an icon name argument, checked to have the form ``mdi:fan``."""
    if not _ICON.fullmatch(_check_str(icon, "icon")):
        raise ValueError(f"Invalid icon {icon!r}: an icon is named like 'mdi:fan'")
    return str(icon)


def _check_color(color: Any) -> str:
    """Return a colour argument, checked to be a colour name or a hex value."""
    if not _COLOR.fullmatch(_check_str(color, "color")):
        raise ValueError(f"Invalid color {color!r}: use a colour name or '#rrggbb'")
    return str(color)


_PERCENT = re.compile(r"(100|[1-9][0-9]?)%")


def _image_size(value: Any, what: str, *, percent: bool) -> str | None:
    """Return the width or height of an image as the block carries it: ``"120px"`` or ``"50%"``.

    A size is a whole number of pixels; a width can also be a percentage of the
    space the image has, as ``"50%"``.
    """
    if value is None:
        return None
    if percent and isinstance(value, str):
        if not _PERCENT.fullmatch(value):
            raise ValueError(f"{what} as text is a percentage from '1%' to '100%', not {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        form = (
            "a whole number of pixels or a percentage like '50%'" if percent else "a whole number of pixels"
        )
        raise TypeError(f"{what} must be {form}, not {type(value).__name__}")
    if not 1 <= value <= MAX_IMAGE_SIZE:
        raise ValueError(f"{what} must be from 1 to {MAX_IMAGE_SIZE} pixels, not {value}")
    return f"{value}px"


def _image_look(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Check the size, the alignment and the caption of an image and return them as the block carries them."""
    align, caption = arguments["align"], arguments["caption"]
    if align not in IMAGE_ALIGNMENTS:
        raise ValueError(f"Invalid align {align!r}: an image is aligned {', '.join(IMAGE_ALIGNMENTS)}")
    if caption is not None and len(_check_str(caption, "caption")) > MAX_CAPTION_LENGTH:
        raise ValueError(f"A caption can have at most {MAX_CAPTION_LENGTH} characters, not {len(caption)}")
    return {
        "width": _image_size(arguments["width"], "width", percent=True),
        "height": _image_size(arguments["height"], "height", percent=False),
        "align": align,
        "caption": caption,
    }
