"""Tests for the images demo: the images on its card, and how the buttons change them."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

DEMO = Path(__file__).parents[1] / "demo_images"


async def test_card_is_built_at_startup() -> None:
    """The card has images from assets, one from an address and the picture of a camera."""
    async with AutomationHarness(DEMO) as automation:
        images = [block["id"] for block in automation.card.blocks if block["type"] == "image"]
        assert images == ["logo", "w0", "w1", "w2", "half", "favicon", "camera"]
        assert {"cells": 3, "elements": ["w0", "w1", "w2"]} in automation.card.layout
        assert automation.message == "A click on the camera opens it"


async def test_logo_from_assets() -> None:
    """The logo comes from the automation's assets, with a size, a place and a caption."""
    async with AutomationHarness(DEMO) as automation:
        logo = automation.card.block("logo")
        assert (logo["asset"], logo["url"]) == ("logo.svg", "/api/haanim/assets/demo_images/logo.svg")
        assert (logo["width"], logo["height"], logo["align"]) == ("96px", None, "center")
        assert logo["caption"] == "96 pixels wide, centred"


async def test_widths() -> None:
    """A width is pixels or a percentage; with a width and a height the image is fitted into the box."""
    async with AutomationHarness(DEMO) as automation:
        assert [automation.card.block(f"w{index}")["width"] for index in range(3)] == ["32px", "48px", "64px"]
        assert (automation.card.block("half")["width"], automation.card.block("half")["align"]) == (
            "50%",
            "right",
        )
        favicon = automation.card.block("favicon")
        assert favicon["url"] == "/static/icons/favicon-192x192.png"
        assert (favicon["width"], favicon["height"]) == ("64px", "32px")


async def test_camera() -> None:
    """The camera's picture is fetched every five seconds, and the button makes that every second."""
    async with AutomationHarness(DEMO) as automation:
        camera = automation.card.block("camera")
        assert (camera["entity_id"], camera["refresh"], camera["width"]) == ("camera.demo", 5.0, "100%")
        assert await automation.press("fast") == 1.0
        assert automation.card.block("camera")["refresh"] == 1.0
        assert automation.card.block("camera")["caption"] == "camera.demo, every second"
        assert await automation.press("fast") == 5.0
        assert automation.card.block("camera")["caption"] == "camera.demo, every 5 seconds"


async def test_size_goes_round() -> None:
    """The size button draws the logo at the next width; its height is left to the image."""
    async with AutomationHarness(DEMO) as automation:
        assert [await automation.press("size") for _ in range(3)] == [144, 64, 96]
        logo = automation.card.block("logo")
        assert (logo["width"], logo["height"], logo["caption"]) == ("96px", None, "96 pixels wide, center")


async def test_align_goes_round() -> None:
    """The align button moves the logo to the right, the left and the middle again."""
    async with AutomationHarness(DEMO) as automation:
        assert [await automation.press("align") for _ in range(3)] == ["right", "left", "center"]
        assert automation.card.block("logo")["align"] == "center"
        assert automation.card.block("logo")["caption"] == "96px wide, center"
