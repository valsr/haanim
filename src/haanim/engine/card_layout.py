"""What every element of a card is, and the layout that places the elements.

The kinds of element are in ``card_elements``. An automation places elements
with ``haa.card.add_element()`` or through ``haa.card.layout``::

    row = haa.card.layout.split_row(3)
    row.add_element(first).add_element(second)
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from haanim.engine.assets import AssetStore
from haanim.engine.card_checks import _check_str

__all__ = ["CardElement", "CardLayout", "CardRow", "MAX_BLOCKS", "MAX_ROW_CELLS"]

MAX_BLOCKS = 50
"""The most blocks a card can have."""

MAX_ROW_CELLS = 6
"""The most cells a row of the layout can be split into."""


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
    """One thing on a card: a text, an image, a value, a gauge, a badge, an icon, a graph, a button, ...

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
