"""Demo: when things go wrong.

What happens to a failure depends on who asked for the action:

- **Somebody called it** (a button, the panel, a service, another automation):
  the exception goes back to that caller. Press "Fail" or "Too slow" and the
  card tells you what the action raised. The automation keeps running.
- **A trigger fired it**: there is nobody to tell. HAAnim logs the failure
  with its traceback, keeps it as the entity's ``last_error``, and fires a
  ``haanim_action_error`` event. "Fail in a trigger" arms a trigger that then
  fails within five seconds; this automation listens for the event itself and
  counts it on the card.

An automation deals with failures like any Python code: ``try`` and
``except``. The other buttons run actions that expect a failure and say what
they caught: an exception of their own, a timeout, a request that was dropped
because the action was busy, and an automation and a service that do not
exist.
"""

import asyncio

from haanim import (
    ActionDroppedError,
    ActionEvent,
    ActionMode,
    ActionTimeOutError,
    EventTriggerEvent,
    IntervalEvent,
    NonExistingAutomationError,
    NonExistingServiceError,
    action,
    haa,
    on_event,
    on_interval,
    startup,
)

seen = haa.card.create_value("seen", label="Trigger failures seen", value=0)
result = haa.card.create_text("result", "_Press a button_")
status = haa.card.create_badge("status", "Nothing yet", color="disabled")


def report(text: str, good: bool = True) -> str:
    """Say on the card what happened. The text is markdown; the status message is plain text."""
    result.set_text(text)
    status.set_text("Handled" if good else "Failed")
    status.set_icon("mdi:check" if good else "mdi:alert")
    status.set_color("success" if good else "error")
    haa.set_message(text.replace("`", ""))
    return text


@startup
def build_card(event: ActionEvent) -> None:
    """Lay the card out."""
    card = haa.card
    layout = card.layout
    card.add_element(card.create_text("intro", "## Errors"))
    layout.split_row(2).add_element(seen).add_element(status)
    card.add_element(result)

    card.add_element(card.create_text("t_raise", "**Not handled**: the card shows what the action raised"))
    raising = layout.split_row(2)
    raising.add_element(card.create_button("fail", label="Fail", action="fail"))
    raising.add_element(card.create_button("slow", label="Too slow", action="slow"))

    card.add_element(card.create_text("t_handled", "**Handled** by the automation, with try and except"))
    handled = layout.split_row(2)
    handled.add_element(card.create_button("careful", label="Catch an error", action="careful"))
    handled.add_element(card.create_button("patient", label="Catch a timeout", action="patient"))
    more = layout.split_row(2)
    more.add_element(card.create_button("twice", label="Busy action", action="twice"))
    more.add_element(card.create_button("missing", label="Missing things", action="missing"))

    card.add_element(
        card.create_text("t_trigger", "**In a trigger**: logged, kept as last error, and announced")
    )
    card.add_element(card.create_button("arm", label="Fail in a trigger", action="arm"))
    seen.set_value(int(haa.get_variable("seen", 0)))


# --- Failures that are not handled: the caller gets them -------------------------------------


@action(description="Always fails: whoever called it gets the exception")
def fail(event: ActionEvent) -> None:
    """Raise. The automation keeps running, and nothing is recorded: the caller was told."""
    raise ValueError("This action always fails")


@action(timeout=2, description="Takes longer than its timeout of two seconds")
async def slow(event: ActionEvent) -> str:
    """Sleep past the timeout. The caller gets ActionTimeOutError after two seconds."""
    await haa.sleep(60)
    return "never returned"


@action(
    execution_mode=ActionMode.DROP, description="Takes three seconds; a second request meanwhile is dropped"
)
async def busy(event: ActionEvent) -> str:
    """Work for three seconds. ``DROP`` is the default mode: while this runs, another request is refused."""
    await haa.sleep(3)
    return "done"


# --- Failures the automation handles -------------------------------------------------------------


@action(description="Calls an action that fails, and catches what it raises")
async def careful(event: ActionEvent) -> str:
    """Call ``fail`` and handle its exception, as with any Python function."""
    try:
        await haa.call("fail")
    except ValueError as error:
        return report(f"Caught `ValueError`: {error}")
    return report("Nothing was raised", good=False)


@action(description="Calls an action that takes too long, and catches the timeout")
async def patient(event: ActionEvent) -> str:
    """Call ``slow`` and handle its timeout."""
    try:
        await haa.call("slow")
    except ActionTimeOutError as error:
        return report(f"Caught `ActionTimeOutError`: {error}")
    return report("It was fast enough", good=False)


@action(description="Asks twice for an action that is busy: the second request is dropped")
async def twice(event: ActionEvent) -> str:
    """Start ``busy`` twice at once. The first runs; the second is refused with ActionDroppedError."""
    answers = await asyncio.gather(haa.call("busy"), haa.call("busy"), return_exceptions=True)
    dropped = [answer for answer in answers if isinstance(answer, ActionDroppedError)]
    finished = [answer for answer in answers if answer == "done"]
    return report(f"{len(finished)} finished, {len(dropped)} dropped with `ActionDroppedError`")


@action(description="Calls an automation and a service that do not exist")
async def missing(event: ActionEvent) -> str:
    """Both raise an error of their own, which says what is missing."""
    caught = []
    try:
        await haa.automation("no_such_automation").call("anything")
    except NonExistingAutomationError as error:
        caught.append(f"`NonExistingAutomationError`: {error}")
    try:
        await haa.service.no_such_domain.no_such_service()
    except NonExistingServiceError as error:
        caught.append(f"`NonExistingServiceError`: {error}")
    return report("Caught " + " and ".join(caught))


# --- A failure in a trigger: nobody to raise to ----------------------------------------------------


@action(description="Make the trigger below fail the next time it fires, within five seconds")
def arm(event: ActionEvent) -> str:
    """Arm the watchdog."""
    haa.set_variable("armed", True)
    return report("Armed: the trigger fails within five seconds")


@on_interval("00:00:05")
def watchdog(event: ActionEvent) -> None:
    """Fires every five seconds, and fails if it was armed.

    Nobody called it, so the failure is logged, kept as ``last_error`` and
    announced with a ``haanim_action_error`` event. The automation stays on.
    """
    if isinstance(event, IntervalEvent) and haa.get_variable("armed", False):
        haa.set_variable("armed", False)
        raise RuntimeError("The watchdog was armed")


@on_event("haanim_action_error", data={"automation_id": "demo_errors"})
def failure_seen(event: ActionEvent) -> None:
    """Count the failures HAAnim announces for this automation, and show the last one."""
    if not isinstance(event, EventTriggerEvent):
        return
    count = int(haa.get_variable("seen", 0)) + 1
    haa.set_variable("seen", count)
    seen.set_value(count)
    data = event.event_data
    report(
        f"`{data['action']}` failed in a trigger with `{data['error_type']}`: {data['message']}", good=False
    )
