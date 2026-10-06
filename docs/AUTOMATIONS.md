# Writing HAAnim automations

This guide covers what an automation can do. For three complete automations with tests, see
[`examples/`](../examples/README.md).

## An automation is a folder

```text
/config/haanim/automations/
└── climate/
    ├── main.py          # required: the entry point
    ├── metadata.json    # optional: name, description, author, version
    ├── helpers.py       # optional: more code, reached with relative imports
    └── assets/          # optional: images, sounds and data files
```

- A folder is an automation only if `main.py` is directly in it.
- The **automation ID** is the folder name in lower case, with every run of characters other than letters
  and digits turned into one `_` (`My Lights` becomes `my_lights`). If two folders give the same ID, the one whose name sorts first
  is loaded and the other is reported as a repair issue.
- Every `.py` file in the folder is part of the automation, except in `assets/` and in folders whose name
  starts with a dot or two underscores. Keep tests outside the folder.
- `metadata.json` holds `name`, `description`, `author` and `version`, all optional strings.
- Files are watched: a change reloads the automation, a new folder is loaded, a removed one is unloaded.

## The lifecycle

| State         | Meaning                                                   |
| ------------- | --------------------------------------------------------- |
| `on`          | Running: triggers are registered, actions can be called   |
| `off`         | Loaded but stopped, or disabled                           |
| `error`       | Could not be loaded or started; the message says why      |
| `unavailable` | Not loaded                                                |

Starting runs `main.py` from top to bottom, then `@startup`, then registers the triggers. Stopping
unregisters the triggers, gives running actions a short grace period, cancels what is left, and runs
`@shutdown`. Each automation has the entity `sensor.haanim_<id>` with its state and the attributes `enabled`,
`message`, `last_run`, `running_actions`, `last_action`, `last_action_time` and `last_error`.

```python
from haanim import ActionEvent, haa, shutdown, startup


@startup
def begin(event: ActionEvent):
    haa.set_message("Ready")


@shutdown
def end(event: ActionEvent):
    haa.set_variable("stopped_at", haa.now().isoformat())
```

## Imports and Python

Everything comes from the `haanim` module: `haa`, the decorators, the event classes, `ActionMode`, the error
classes, and `logging`. Besides it and relative imports within the folder, these modules can be imported:
`asyncio`, `datetime`, `json`, `logging`, `math`, `random`, `re`, `time`, `typing`, `collections`,
`functools`, `itertools`, `operator`, `statistics`, `decimal`, `fractions`, `enum`, `dataclasses` and `hass`
(the running Home Assistant instance). More can be allowed in the integration's options.

Automation code is run by HAAnim's interpreter, on Home Assistant's event loop. Blocking calls
(`time.sleep`, file and network I/O, threads, subprocesses) are not available; use `await haa.sleep()` and
services instead. Generators (`yield`) are not supported. Loops and function calls yield to the event loop
regularly, so a long loop does not freeze Home Assistant.

## Actions

An action is a function that can be called: from the panel or card, with `haanim.run_action`, by another
automation, or by a trigger. It takes no parameters or one, the event.

```python
from haanim import ActionEvent, ActionMode, action, haa


@action
def set_scene(event: ActionEvent):
    room = event.data["room"]                  # the caller's keyword arguments
    level = event.data.get("level", 100)
    return f"{room} set to {level}"            # returned to the caller


@action(name="blink", aliases=["flash"], description="Blink the porch light",
        execution_mode=ActionMode.QUEUE, timeout=30)
async def blink_porch(event: ActionEvent):
    await haa.service.light.toggle(entity_id="light.porch")
    await haa.sleep(1)
    await haa.service.light.toggle(entity_id="light.porch")
```

`event.source` is `"manual"`, `"automation"` (then `event.caller` is the calling automation's ID) or
`"trigger"`. `event.call_time` and `event.automation_id` are always there.

**Execution modes** decide what happens to a request while the same action is still running:

| Mode             | The new request                              | Its caller gets                                   |
| ---------------- | -------------------------------------------- | ------------------------------------------------- |
| `DROP` (default) | is discarded                                 | `ActionDroppedError`                              |
| `QUEUE`          | waits its turn                               | the result, or `QueueFullError`                   |
| `CANCEL`         | cancels the running one and starts           | the result; the cancelled caller gets `ActionCancelledError` |

An action that raises: the exception reaches whoever called it. When a trigger called it, there is nobody to
raise to, so the failure is logged with its traceback, kept in the entity's `last_error`, and announced with
a `haanim_action_error` event; the automation keeps running.

## Triggers

A trigger decorator makes a function run when something happens. Trigger functions are actions too, so they
can also be called by hand, and `@action(...)` can be stacked on one to set its mode or timeout.

```python
from haanim import (CronEvent, EventTriggerEvent, IntervalEvent, StateEvent, TimeEvent,
                    on_cron, on_event, on_interval, on_state, on_time)


@on_time("09:00")                                   # every day at 09:00
def morning(event: TimeEvent): ...

@on_time("sunset - 30 minutes", day_of_week="weekdays")
def dusk(event: TimeEvent): ...

@on_interval("00:05:00")                            # every five minutes; or a number of seconds
def poll(event: IntervalEvent): ...                 # event.execution_count counts the runs

@on_cron("0 */2 * * *")                             # the five standard cron fields
def every_two_hours(event: CronEvent): ...

@on_event("zha_event", data={"command": "toggle"})  # only events whose data matches
def button(event: EventTriggerEvent): ...           # event.event_data, event.event_type

@on_state("sensor.temperature > 30")                # when the expression becomes true
def hot(event: StateEvent): ...                     # event.entity_id, event.old_state, event.new_state

@on_state("binary_sensor.door == 'on'", hold="00:02:00")   # only once it has been true for two minutes
def door_left_open(event: StateEvent): ...
```

- **Times** are `"HH:MM"`, `"HH:MM:SS"`, `"9am"`, `"5:47pm"`, `"noon"`, `"midnight"`, `"sunrise"`, `"sunset"`,
  optionally with a date (`"2025-12-25 09:00"`) or an offset (`"sunset + 30 minutes"`). `on_time` also takes
  `day_of_week` (`"mon,wed"`, `"weekdays"`, `"weekends"`) and `day_of_month` (`"1,15"`).
- **Durations** (`on_interval`, its `delay`, and `hold`) are seconds or `"HH:MM:SS"` with all three parts.
- **State triggers** fire when the expression goes from false to true. An automation started while it is
  already true fires only after it has been false again. `every_change=True` fires on every change while it
  is true.

### State expressions

`sensor.temperature` is the entity's state and `light.kitchen['brightness']` an attribute. States are text and
are converted for comparisons, so `sensor.temperature > 30` compares numbers. Use `==`, `!=`, `<`, `<=`, `>`,
`>=`, `and`, `or`, `not`, `in`, and parentheses:

```python
@on_state("binary_sensor.motion == 'on' and light.hall == 'off' and sun.sun == 'below_horizon'")
```

If an entity in an expression is missing, `unknown` or `unavailable`, the whole expression is false; it is not an error.

### Constraints

Every trigger decorator takes these keyword arguments. The trigger fires only if all of them allow it.

| Argument                   | The trigger fires only                                   |
| -------------------------- | -------------------------------------------------------- |
| `start_time`, `end_time`   | from, and before, a time of day (`"22:00"` to `"06:00"` wraps past midnight; `"sunset"` works) |
| `start_date`, `end_date`   | from, and before, a date (`"November 1"` to `"March 1"` wraps past New Year) |
| `day_of_week`              | on these days                                            |
| `when`, `when_not`         | while a state expression is true, or false               |

## `haa`

### Entities

```python
temperature = float(haa.entity.sensor.temperature)        # converts the state; raises if it is not a number
if haa.entity.light.kitchen == "on" and haa.entity.light.kitchen["brightness"] > 100:
    ...
printer = haa.entity["sensor.3d_printer"]                 # for IDs that are not Python names
raw = haa.state("sensor.temperature")                      # the state as text, or None
```

### Services

```python
call = await haa.service.light.turn_on(entity_id="light.kitchen", brightness=200)
if not call.success:
    print(call.error)

forecast = await haa.service.weather.get_forecasts(entity_id="weather.home", type="daily",
                                                   return_response=True)
print(forecast.response_data)
```

A service that does not exist raises `NonExistingServiceError`. A call that fails does not raise: the result
has `success` set to `False` and the reason in `error`.

### Waiting

```python
await haa.sleep(30)                 # seconds, or "00:00:30"
opened = await haa.wait_for("binary_sensor.door == 'on'", timeout=300)   # False if the time ran out
```

Use `haa.now()` for the current time: it is timezone-aware and follows the clock the triggers use.

### Persistent variables

```python
count = haa.get_variable("count", 0)
haa.set_variable("count", count + 1)       # any JSON value
haa.unset_variable("count")
haa.clear_variables()
```

Variables belong to one automation and survive restarts and reloads. Module-level variables in `main.py` do
not: every start runs the file again.

### Other automations

```python
@action
def set_level(event: ActionEvent):
    return event.data["level"]


@action
async def coordinate(event: ActionEvent):
    result = await haa.automation("notifications").call("send_message", text="Hello")
    level = await haa.call("set_level", level=3)      # an action of this automation
    await haa.automation("irrigation").stop()
    for other in haa.automations():
        print(other.id, other.state)
```

The automation controls itself with `await haa.stop()`, `haa.restart()` and `haa.disable()`.

### Status and logging

```python
from haanim import haa, logging

haa.set_message("Watering zone 2")       # shown on the entity, the card and the panel
logging.info("Zone %s done", 2)          # debug, info, warning, error, critical
print("Also logged, at INFO")
```

Each automation logs under `custom_components.haanim.automation.<id>`, so its level can be set in Home
Assistant's `logger` configuration.

### Assets

```python
phrases = await haa.read_asset("phrases.json", text=True)     # str; without text=True, bytes
url = haa.asset_url("chime.mp3", expires=300)                 # works without login for five minutes
```

Names are relative to the automation's `assets/` folder. An automation reaches only its own assets.

## The card

Each automation has a card for dashboards, `custom:haanim-card` with `automation_id: <id>`. The card shows
a title, what the automation is doing (the name of the action that is running, or Idle) and the status
message, then whatever the automation puts there, and two buttons:
**Actions** opens a popup with all of the automation's actions, and **Log** goes to the automation's log in
the HAAnim panel. Enabling, stopping and restarting are done on the automation's page in the panel.

```python
@startup
def build_card(event: ActionEvent):
    haa.card.set_title("Climate")                 # the automation's name if never set
    haa.card.text("intro", "## Climate\nKeeps the house between **19** and **23** °C.")
    haa.card.image("logo", asset="logo.png", alt="Logo")
    haa.card.value("alerts", label="Alerts today", value=0)
    haa.card.entity("temp", "sensor.temperature")
    haa.card.icon("fan", "fan.bedroom", icon="mdi:fan", spin=True)
    haa.card.button("reset", label="Reset", action="reset_alerts", confirm="Reset the counter?")


@action
def reset_alerts(event: ActionEvent):
    haa.card.value("alerts", label="Alerts today", value=0)     # replaces the block in place
```

`haa.card.set_title()` can be called at any time, so the title can say what is going on
(`haa.card.set_title(f"Climate: {count} alerts")`); `None` goes back to the automation's name.

An **icon** is driven by its entity unless told otherwise: it is lit while the entity is active (on, open,
home, ...) and dimmed while it is not, turns only while it is active if `spin=True`, and shows the entity's
name and state. Without `icon=` it is the entity's own icon. A click opens the entity's dialog.

```python
haa.card.icon("fan", "fan.bedroom", icon="mdi:fan", spin=True)     # follows fan.bedroom
haa.card.icon("door", "binary_sensor.front_door")                  # the entity's own icon
haa.card.icon("mode", icon="mdi:snowflake", label="Cooling", color="primary")    # no entity
haa.card.icon("fan", "fan.bedroom", icon="mdi:fan-alert", color="error",
              follow_entity=False)                                 # exactly this, whatever the fan does
```

A **graph** shows either the history of entities or numbers of the automation's own:

```python
# What Home Assistant recorded for the entities over the last hours; the graph then follows them
haa.card.graph("temps", ["sensor.indoor", "sensor.outdoor"], hours=12, title="Temperature")

# The automation's own numbers; set the block again to change them
haa.card.graph("alerts", series={"Alerts": [3, 0, 1, 4, 2]}, kind="bar", title="Alerts per day")
haa.card.graph("curve", series={"Target": [(0, 18), (6, 21), (22, 18)]}, unit="°C", min=15, max=25)
haa.card.graph("power", series={"Power": [("2025-01-06T12:00:00+00:00", 120), ("2025-01-06T13:00:00+00:00", 90)]})
```

Numbers are drawn against a value axis marked with round numbers; `kind` is `"line"`, `"area"` or `"bar"`.
An entity or series whose values are states rather than numbers (`on`, `off`, `heat`, ...) is drawn as a
timeline instead: a row with a coloured segment for every state it was in. One graph can have both:

```python
haa.card.graph("climate", ["sensor.temperature", "climate.living_room", "binary_sensor.window"], hours=24)
haa.card.graph("pump", series={"Pump": [(0, "on"), (6, "off"), (8, "on"), (10, "on")]})
```

Hovering over a graph shows the values of all its series at that position. The horizontal axis has labelled
marks with smaller ones between them, at round distances the card picks; `x_major` and `x_minor` set the
distances instead, as durations on a time axis and as numbers otherwise:

```python
haa.card.graph("temps", "sensor.indoor", hours=6, x_major="01:00:00", x_minor="00:15:00")
haa.card.graph("curve", series={"Target": [(0, 18), (6, 21), (22, 18)]}, x_major=6, x_minor=1)
```

The points of a series are plain values (drawn one after the other), `(x, y)` pairs, or `(time, y)` pairs
with timezone-aware times; the values of one series are all numbers or all states, and `None` leaves a gap. A
state holds until the next point. A graph has at most 8 entities or series, a series at most 500 points, and
history goes back at most 720 hours. The card keeps nothing for the automation: what should survive a restart
belongs in persistent variables.

The fixed parts can be hidden, each on its own, and shown again at any time:

```python
haa.card.configure(state=False, log=False)       # no state badge, no Log button
haa.card.configure(title=False, state=False, message=False, actions=False, log=False)   # only the content
```

Each block has an ID. Setting an ID again replaces that block in place, which is how a value is updated;
`haa.card.remove(id)` and `haa.card.clear()` take blocks away. A button calls one of the automation's actions,
with its extra keyword arguments as `event.data`. The card is emptied when the automation stops, so build it
in `@startup`. A card has at most 50 blocks, a text block at most 10 000 characters and a title at most 100. Markdown is
sanitised: raw HTML is removed.

## Testing

Install the package (`pip install haanim pytest pytest-asyncio`) and test the automation with the harness,
which runs it exactly as Home Assistant does, against a fake Home Assistant:

```python
from haanim.testing import AutomationHarness


async def test_high_temperature_alert():
    async with AutomationHarness("automations/climate") as automation:
        automation.set_state("sensor.temperature", "25")
        automation.set_state("sensor.temperature", "31")

        await automation.wait_idle()
        assert automation.service_calls("notify.mobile_app")[0].data["message"].startswith("High")
        assert automation.get_variable("alert_count") == 1


async def test_morning_routine_only_when_home():
    async with AutomationHarness("automations/climate", now="2025-01-06 08:59:00") as automation:
        automation.set_state("person.john", "away")
        await automation.advance_time(minutes=2)
        assert automation.service_calls("light.turn_on") == []
```

| With the harness you can                    | Using                                                           |
| ------------------------------------------- | --------------------------------------------------------------- |
| Set states and fire events                  | `set_state`, `remove_state`, `fire_event`                       |
| Control time                                | `now=`, `advance_time(minutes=5)`, `set_sun(sunset="18:30")`    |
| Wait for the automation to finish reacting  | `await wait_idle()`                                             |
| Call actions                                | `await call("name", level=3)`, with `caller=` or `source="trigger"` |
| See what it did                             | `service_calls()`, `events()`, `logs()`, `message`, `state`, `variables`, `last_error` |
| Decide what services do                     | `stub_service("weather.get_forecasts", response={...})`, `success=False`, `remove_service` |
| Stand in for other automations              | `stub_automation("notifications", send_message="sent")`, `automation_calls()` |
| Check the card and press its buttons        | `card.title`, `card.blocks`, `card.block(id)`, `await press(id)` |
| Drive the lifecycle                         | `start=False`, then `load()`, `start()`, `stop()`, `reload()`   |
| Provide assets and stored variables         | `assets={"logo.png": b"..."}`, `variables={"count": 3}`         |

Time stands still in the harness until the test advances it, so a test of "five minutes later" takes
milliseconds.

For editors and type checkers, the same package gives completion and types for `from haanim import ...`.
