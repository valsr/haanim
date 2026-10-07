"""Demo: layout. Where the elements are on the card.

The layout is a list of rows from the top. An element added to the card gets
a row of its own; ``split_row(n)`` adds a row of ``n`` cells of equal width,
filled from the left. On a narrow card the cells of a row wrap.

The card shows rows of two, three, four and six cells, a row that is not
full, and a table made of rows. Its buttons move an element from one row to
another, take an element off the card and put it back, and build the whole
card again.
"""

from haanim import ActionEvent, CardRow, action, haa, startup

TABLE = [("Kitchen", "21.5 °C", "Heating", "warning"), ("Bedroom", "18.0 °C", "Idle", "disabled")]

# The element the Move button moves, and the one the Hide button takes off the card
marker = haa.card.create_badge("marker", "Move me", icon="mdi:cursor-move", color="accent")
note = haa.card.create_text(
    "note", "_This note can be taken off the card and put back; it then goes to the bottom._"
)

# The two rows the marker moves between; filled when the card is built
rows: dict[str, CardRow] = {}


def build() -> None:
    """Lay the card out from the top."""
    card = haa.card
    layout = card.layout

    # A row of its own: card.add_element() and layout.add_element() are the same
    card.add_element(card.create_text("intro", "## Layout\nRows of 2, 3, 4 and 6 cells:"))

    # Calls can be chained: every add_element() returns what it was called on
    layout.split_row(2).add_element(card.create_value("a", "Left", 1)).add_element(
        card.create_value("b", "Right", 2)
    )

    three = layout.split_row(3)
    for name in ["One", "Two", "Three"]:
        three.add_element(card.create_badge(f"three_{name.lower()}", name))

    four = layout.split_row(4)
    for index, icon in enumerate(["mdi:home", "mdi:lightbulb", "mdi:fan", "mdi:lock"]):
        four.add_element(card.create_icon(f"four_{index}", icon=icon))

    six = layout.split_row(6)
    for index in range(6):
        six.add_element(card.create_badge(f"six_{index}", str(index + 1), color="primary"))
    # A row takes as many elements as it has cells: this seventh one is ignored, without an error
    six.add_element(card.create_badge("six_extra", "7"))

    # Fewer elements than cells: the other cells stay empty. The marker starts in the first of two rows.
    card.add_element(
        card.create_text("t_move", "Two rows of three cells, not full. The badge moves between them:")
    )
    rows["first"] = (
        layout.split_row(3).add_element(card.create_badge("first", "First row")).add_element(marker)
    )
    rows["second"] = layout.split_row(3).add_element(card.create_badge("second", "Second row"))

    # A table is rows with the same number of cells
    card.add_element(card.create_text("t_table", "A table is rows with the same number of cells:"))
    head = layout.split_row(3)
    for column in ["Room", "Temperature", "State"]:
        head.add_element(card.create_text(f"head_{column.lower()}", f"**{column}**"))
    for index, (room, temperature, state, color) in enumerate(TABLE):
        line = layout.split_row(3)
        line.add_element(card.create_text(f"room_{index}", room))
        line.add_element(card.create_text(f"temperature_{index}", temperature))
        line.add_element(card.create_badge(f"state_{index}", state, color=color))

    card.add_element(note)
    buttons = layout.split_row(3)
    buttons.add_element(card.create_button("move", label="Move", action="move"))
    buttons.add_element(card.create_button("hide", label="Hide / show", action="hide"))
    buttons.add_element(card.create_button("rebuild", label="Rebuild", action="rebuild"))


@startup
def build_card(event: ActionEvent) -> None:
    """Build the card. Card content is not kept across restarts."""
    build()
    haa.set_message(f"{len(haa.card.elements)} elements in {len(haa.card.layout.rows)} rows")


@action(description="Move the badge to the other row")
def move(event: ActionEvent) -> str:
    """Adding an element that is already on the card moves it: here into the other of the two rows."""
    target = "second" if marker in rows["first"].elements else "first"
    rows[target].add_element(marker)
    haa.set_message(f"The badge is in the {target} row")
    return target


@action(description="Take the note off the card, or put it back")
def hide(event: ActionEvent) -> bool:
    """Remove the note, or add it again: an added element gets a row of its own at the bottom."""
    shown = haa.card.element("note") is not None
    if shown:
        haa.card.remove_element(note)
    else:
        haa.card.add_element(note)
    haa.set_message("The note is off the card" if shown else "The note is back, at the bottom")
    return not shown


@action(description="Clear the card and lay it out again")
def rebuild(event: ActionEvent) -> int:
    """Take everything off the card and build it again, which puts every element back where it started."""
    haa.card.clear()
    build()
    haa.set_message("Built again")
    return len(haa.card.elements)
