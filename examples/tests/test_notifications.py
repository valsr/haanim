"""Tests for the notifications example: what it sends, and what its card shows."""

from __future__ import annotations

from pathlib import Path

from haanim.testing import AutomationHarness

NOTIFICATIONS = Path(__file__).parents[1] / "notifications"


async def test_send_message() -> None:
    """A message becomes a notification in Home Assistant, and the card counts it."""
    async with AutomationHarness(NOTIFICATIONS) as automation:
        assert await automation.call("send_message", text="Too hot", title="Climate") == "Too hot"
        (call,) = automation.service_calls("persistent_notification.create")
        assert call.data == {"message": "Too hot", "title": "Climate"}
        assert automation.card.block("sent")["value"] == 1
        assert automation.card.block("last")["markdown"] == "**Climate**: Too hot"
        assert automation.message == "Sent: Too hot"
        assert automation.get_variable("sent") == 1


async def test_message_without_text() -> None:
    """Without data, as from the test button on the card, a default text is sent."""
    async with AutomationHarness(NOTIFICATIONS) as automation:
        assert await automation.press("test") == "Hello from HAAnim"
        (call,) = automation.service_calls("persistent_notification.create")
        assert call.data == {"message": "Hello from HAAnim", "title": "HAAnim"}


async def test_count_is_kept_across_a_restart() -> None:
    """The number of messages is stored, and shown again when the automation starts."""
    async with AutomationHarness(NOTIFICATIONS, variables={"sent": 4}) as automation:
        assert automation.card.block("sent")["value"] == 4
        assert automation.card.block("last")["markdown"] == "_Nothing sent yet_"
        await automation.call("send_message", text="Five")
        assert automation.card.block("sent")["value"] == 5


async def test_card_at_startup() -> None:
    """The card has the count, the last message and a button that sends a test message."""
    async with AutomationHarness(NOTIFICATIONS) as automation:
        assert [(block["id"], block["type"]) for block in automation.card.blocks] == [
            ("sent", "value"),
            ("last", "text"),
            ("test", "button"),
        ]
        assert automation.card.block("sent")["value"] == 0
        assert automation.card.block("test")["action"] == "send_message"


async def test_messages_are_sent_in_order() -> None:
    """Several messages each become a notification, in the order they were asked for."""
    async with AutomationHarness(NOTIFICATIONS) as automation:
        for text in ("one", "two", "three"):
            await automation.call("send_message", text=text)
        sent = [call.data["message"] for call in automation.service_calls("persistent_notification.create")]
        assert sent == ["one", "two", "three"]
        assert automation.card.block("sent")["value"] == 3
        assert automation.card.block("last")["markdown"] == "**HAAnim**: three"
