# Getting started

## Install

HAAnim needs Home Assistant 2026.9 or newer.

1. Install the integration with HACS: **HACS → ⋮ → Custom repositories**, add
   `https://github.com/valsr/haanim` as an **Integration**, then download HAAnim.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → HAAnim**.

A release of the integration has the HAAnim engine in it, so no Python package has to be installed into
Home Assistant.

!!! note "Installing by hand"
    Download `haanim.zip` from a [release](https://github.com/valsr/haanim/releases) and unpack it into
    `<config>/custom_components/haanim`. The `custom_components/haanim` folder of the repository itself does
    not have the engine in it.

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

The engine is also a Python package, `haanim`, for your own machine. It is not needed in Home Assistant; it
gives your editor completion and types for `from haanim import ...`, and the test harness:

```sh
pip install haanim pytest pytest-asyncio
```

The package needs Python 3.14, the Python that Home Assistant 2026.9 runs on.

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
