# HAAnim

[![CI](https://github.com/valsr/haanim/actions/workflows/ci.yml/badge.svg)](https://github.com/valsr/haanim/actions/workflows/ci.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License](https://img.shields.io/github/license/valsr/haanim.svg)](LICENSE)

Write Home Assistant automations in Python. An automation is a folder with a `main.py`; decorators say when
its functions run, and the `haa` object reaches entities, services, storage and the automation's own
dashboard card.

```python
from haanim import StateEvent, TimeEvent, haa, on_state, on_time


@on_state("sensor.temperature > 30")
async def high_temperature(event: StateEvent):
    await haa.service.notify.mobile_app(message=f"It is {float(haa.entity.sensor.temperature)}°C")


@on_time("09:00", day_of_week="weekdays", when="person.john == 'home'")
async def morning(event: TimeEvent):
    await haa.service.light.turn_on(entity_id="light.bedroom", brightness=150)
```

## What you get

- **Triggers**: time (including sunrise and sunset), interval, cron, Home Assistant events and state
  expressions, each with optional constraints (time of day, date range, day of week, state).
- **Actions** that can be run by hand, by a service, by another automation or by a trigger, with `DROP`,
  `QUEUE` and `CANCEL` execution modes, timeouts and a concurrency limit.
- **`haa`**: entity access, service calls, `sleep` and `wait_for`, persistent variables, assets, calling and
  controlling other automations.
- **A sensor per automation** (`sensor.haanim_<id>`: `on`, `off`, `error`) with status attributes.
- **A dashboard card** (`custom:haanim-card`) that the automation titles and fills with text, images,
  values, live entities and buttons, plus a management panel in the sidebar with each automation's
  controls, actions and log.
- **Hot reload**: edit a file and the automation is reloaded.
- **A test harness**: test an automation with `pytest`, with no Home Assistant running.

The interpreter keeps automations from blocking Home Assistant by accident (no blocking I/O, an import
allowlist, loops that yield). It is a guard rail, not a sandbox: an automation can do whatever Home Assistant
can. Only install automations you trust.

## Installation

HAAnim has two parts: the integration (`custom_components/haanim`) and the `haanim` Python package with the
engine and the test harness. The integration requires the package at its own version.

> **Note:** the `haanim` package is not on PyPI yet. Until it is, install it into Home Assistant's Python
> environment yourself (`pip install .` from a checkout of this repository), or use the development container
> below, which does that for you.

1. Install the integration: with HACS (**HACS → ⋮ → Custom repositories**, add
   `https://github.com/valsr/haanim` as an **Integration**), or by copying `custom_components/haanim` into
   your configuration's `custom_components` folder.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → HAAnim**.

Automations live in `/config/haanim/automations/` by default. The folder, the rescan interval, the limits and
the import options are set under **Configure** on the integration.

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

Within the rescan interval the automation is running: `sensor.haanim_hello` is `on`, and the action can be run
from the HAAnim panel, with the `haanim.run_action` service, or from the automation's card:

```yaml
type: custom:haanim-card
automation_id: hello
```

The [automation guide](docs/AUTOMATIONS.md) covers everything an automation can do, and
[`examples/`](examples/README.md) has three complete automations with tests.

## Testing an automation

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

The harness runs the automation with the same interpreter and triggers as Home Assistant, against a fake Home
Assistant whose clock only moves when the test moves it. Installing the package does not install Home
Assistant.

## Services

| Service                   | Data                              | What it does                                             |
| ------------------------- | --------------------------------- | -------------------------------------------------------- |
| `haanim.run_action`       | `automation_id`, `action`, `data` | Runs an action; returns its result as response data      |
| `haanim.enable`           | `automation_id`                   | Enables and starts the automation                        |
| `haanim.disable`          | `automation_id`                   | Stops and disables the automation                        |
| `haanim.start`            | `automation_id`                   | Starts the automation                                    |
| `haanim.stop`             | `automation_id`                   | Stops the automation                                     |
| `haanim.restart`          | `automation_id`                   | Restarts the automation                                  |
| `haanim.reload`           | `automation_id` (optional)        | Rescans now and reloads one automation, or all           |
| `haanim.list_automations` | -                                 | Returns ID, name, state and enabled flag of every one    |
| `haanim.list_actions`     | `automation_id`                   | Returns the automation's actions                         |
| `haanim.clear_log`        | `automation_id` (optional)        | Empties the log HAAnim keeps for one automation, or all  |
| `haanim.set_log_level`    | `automation_id`, `level`          | Sets the automation's log level; `default` takes it away |

## Development

```sh
git clone https://github.com/valsr/haanim.git
cd haanim
uv sync --all-extras

uv run pytest                                         # Python tests, frontend tests and the coverage gate
uv run python scripts/check-public-api-coverage.py    # the automation-facing API must be at 100%
scripts/test-frontend.sh                              # only the JavaScript tests (needs node 22+)
uv run black --check . && uv run pylint custom_components src
uv run mypy custom_components src && uv run pyright src custom_components examples
```

A Home Assistant with the integration, the package and the examples, in a container:

```sh
./build-and-run.sh                     # http://localhost:8123, user admin, password admin
uv run python scripts/e2e-smoke.py     # end-to-end checks against that container
```

The repository:

| Path                        | What is there                                                              |
| --------------------------- | -------------------------------------------------------------------------- |
| `src/haanim/`               | The engine: interpreter, triggers, dispatcher, `haa`. No Home Assistant imports |
| `src/haanim/testing/`       | The test harness and the fakes it is built on                              |
| `custom_components/haanim/` | The integration: entity, services, options, websocket commands, frontend   |
| `examples/`                 | Example automations and their harness tests                                |
| `tests/`                    | `engine/` (no Home Assistant), `integration/`, `frontend/`                 |
| `docs/`                     | The automation guide and notes on the development environment              |

See [CONTRIBUTING.md](CONTRIBUTING.md) before sending a pull request.

## License

MIT, see [LICENSE](LICENSE). HAAnim is a custom integration and is not supported by the Home Assistant
project.
