# Getting started

## Install

HAAnim has two parts: the integration (`custom_components/haanim`) and the `haanim` Python package with the
engine and the test harness. The integration requires the package at its own version.

!!! note
    The `haanim` package is not on PyPI yet. Until it is, install it into Home Assistant's Python
    environment yourself (`pip install .` from a checkout of the repository), or use the development
    container described in the repository's README, which does that for you.

1. Install the integration: with HACS (**HACS → ⋮ → Custom repositories**, add
   `https://github.com/valsr/haanim` as an **Integration**), or by copying `custom_components/haanim` into
   your configuration's `custom_components` folder.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → HAAnim**.

Automations live in `/config/haanim/automations/` by default.

## Your first automation

Create `/config/haanim/automations/hello/main.py`:

```python
from haanim import ActionEvent, action, haa, startup


@startup
def ready(event: ActionEvent):
    haa.card.add_element(haa.card.create_text("hello", "## Hello\nPress the button."))
    haa.card.add_element(haa.card.create_button("greet", label="Greet", action="greet"))


@action
async def greet(event: ActionEvent):
    await haa.service.persistent_notification.create(message="Hello from HAAnim")
```

The folder's name, `hello`, is the automation's ID. Within the rescan interval (ten seconds by default) the
automation is running: `sensor.haanim_hello` is `on`, and it is listed in the **HAAnim** panel in the
sidebar.

## Put its card on a dashboard

Add a card to a dashboard and choose **Manual**:

```yaml
type: custom:haanim-card
automation_id: hello
```

The card shows the text and the button the automation put there. Pressing **Greet** runs the action, which
creates a notification in Home Assistant.

## Change it

Edit `main.py` and save. The automation is reloaded at the next rescan; if the file has an error, the
automation's state is `error` and the panel says where.

## Test it

The same package that runs automations in Home Assistant tests them without it:

```sh
pip install haanim pytest pytest-asyncio
```

```python
from haanim.testing import AutomationHarness


async def test_greeting():
    async with AutomationHarness("automations/hello") as automation:
        await automation.press("greet")
        assert automation.service_calls("persistent_notification.create")[0].data == {
            "message": "Hello from HAAnim"
        }
```

The harness runs the automation with the same interpreter and triggers as Home Assistant, against a fake
Home Assistant whose clock only moves when the test moves it.

## Next

- [Writing automations](AUTOMATIONS.md): triggers, actions, `haa`, the card, testing.
- [Examples and demos](examples.md): complete automations, one for each part of HAAnim.
