"""Demo: images.

An image comes from the automation's ``assets/`` folder, from an address, or
is the live picture of a camera. It can be given a width, a height, a place
in its row and a caption, and all of that can be changed afterwards.

The buttons change the first image in place: its size, where it is, and its
caption. The camera's picture is fetched again every few seconds; a click on
it opens the camera's own dialog.
"""

from haanim import ActionEvent, action, haa, startup

CAMERA = "camera.demo"  # any camera; while there is none, the card shows the image's alt text
SIZES = [64, 96, 144]
ALIGNMENTS = ["left", "center", "right"]

# An image from assets/, with everything it can be given
logo = haa.card.create_image(
    "logo", asset="logo.svg", alt="HAAnim logo", width=96, align="center", caption="96 pixels wide, centred"
)
camera = haa.card.create_image(
    "camera",
    entity_id=CAMERA,
    refresh=5,
    alt="No camera",
    width="100%",
    caption="camera.demo, every 5 seconds",
)


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    card.add_element(
        card.create_text("intro", "## Images\nFrom `assets/`, with a size, a place and a caption:")
    )
    card.add_element(logo)
    buttons = card.layout.split_row(3)
    buttons.add_element(card.create_button("size", label="Size", action="next_size"))
    buttons.add_element(card.create_button("align", label="Align", action="next_align"))
    buttons.add_element(card.create_button("fast", label="Camera speed", action="camera_speed"))

    # The same asset at three widths, side by side. Only a width is given: the height follows.
    card.add_element(card.create_text("sizes", "The same image at three widths; and by percentage:"))
    row = card.layout.split_row(3)
    for index, width in enumerate([32, 48, 64]):
        row.add_element(card.create_image(f"w{index}", asset="logo.svg", width=width, caption=f"{width} px"))
    card.add_element(
        card.create_image("half", asset="logo.svg", width="50%", align="right", caption="50%, right")
    )

    # An image from an address: here one that Home Assistant serves itself
    card.add_element(card.create_text("from_url", "From an address, fitted into 64 by 32 pixels:"))
    card.add_element(
        card.create_image(
            "favicon", url="/static/icons/favicon-192x192.png", alt="Home Assistant", width=64, height=32
        )
    )

    card.add_element(card.create_text("live", "The live picture of a camera:"))
    card.add_element(camera)
    haa.set_message("A click on the camera opens it")


@action(description="Draw the logo at the next size")
def next_size(event: ActionEvent) -> int:
    """Change the width of the logo; its height follows."""
    current = int(str(logo.width).removesuffix("px"))
    width = SIZES[(SIZES.index(current) + 1) % len(SIZES)] if current in SIZES else SIZES[0]
    logo.set_size(width=width)
    logo.set_caption(f"{width} pixels wide, {logo.align}")
    return width


@action(description="Move the logo to the left, the middle or the right")
def next_align(event: ActionEvent) -> str:
    """Change where the logo is in its row; the caption goes with it."""
    align = ALIGNMENTS[(ALIGNMENTS.index(logo.align) + 1) % len(ALIGNMENTS)]
    logo.set_align(align)
    logo.set_caption(f"{logo.width} wide, {align}")
    return align


@action(description="Fetch the camera's picture every second, or every five")
def camera_speed(event: ActionEvent) -> float:
    """Switch between a picture a second and one every five seconds."""
    seconds = 5.0 if camera.refresh == 1 else 1.0
    camera.set_refresh(seconds)
    camera.set_caption(
        f"camera.demo, every {seconds:g} seconds" if seconds > 1 else "camera.demo, every second"
    )
    return seconds
