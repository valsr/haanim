"""Sends messages for other automations.

Other automations call ``send_message`` instead of a notify service of their
own, so there is one place that says where messages go::

    await haa.automation("notifications").call("send_message", text="Hello")

The climate example does. Here a message becomes a notification in Home
Assistant; the card shows how many were sent and the last of them.
"""

from haanim import ActionEvent, ActionMode, action, haa, startup

DEFAULT_TEXT = "Hello from HAAnim"

sent = haa.card.create_value("sent", label="Messages sent", value=0)
last = haa.card.create_text("last", "_Nothing sent yet_")


@startup
def build_card(event: ActionEvent) -> None:
    """Show the stored count; card content is not kept across restarts."""
    sent.set_value(int(haa.get_variable("sent", 0)))
    haa.card.add_element(sent)
    haa.card.add_element(last)
    haa.card.add_element(haa.card.create_button("test", label="Send a test message", action="send_message"))


@action(execution_mode=ActionMode.QUEUE, description="Send a message as a notification in Home Assistant")
async def send_message(event: ActionEvent) -> str:
    """Send ``text`` (and ``title``, if given) and return what was sent.

    Messages that arrive while one is being sent wait their turn (``QUEUE``).
    """
    text = str(event.data.get("text", DEFAULT_TEXT))
    title = str(event.data.get("title", "HAAnim"))
    await haa.service.persistent_notification.create(message=text, title=title)

    count = int(haa.get_variable("sent", 0)) + 1
    haa.set_variable("sent", count)
    sent.set_value(count)
    last.set_text(f"**{title}**: {text}")
    haa.set_message(f"Sent: {text}")
    return text
