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
`functools`, `itertools`, `operator`, `statistics`, `decimal`, `fractions`, `enum`, `dataclasses`, `html` and
`hass` (the running Home Assistant instance). More can be allowed in the integration's options.

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

Each automation has a log level of its own: set it on the Logs tab of the automation's page in the HAAnim
panel, or with the `haanim.set_log_level` service (`debug` while you write the automation, `error` once it
runs). The level is kept across restarts. With `Default` the automation follows Home Assistant's `logger`
configuration, where it logs under `custom_components.haanim.automation.<id>`. `print()` logs at `INFO`, so
it is silent from `warning` up. The Clear button next to the level, or `haanim.clear_log`, empties the log
the panel shows.

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

The automation fills its card in two steps: it **creates elements**, and it **adds them to the card**. An
element it keeps in a variable can be changed later with its setters, and only that element changes on the
card.

```python
alerts = haa.card.create_value("alerts", label="Alerts today", value=0)


@startup
def build_card(event: ActionEvent):
    haa.card.set_title("Climate")                 # the automation's name if never set
    haa.card.add_element(haa.card.create_text("intro", "## Climate\nKeeps the house between **19** and **23** °C."))
    haa.card.add_element(alerts)
    haa.card.add_element(haa.card.create_button("reset", label="Reset", action="reset_alerts"))


@on_state("sensor.temperature > 30")
def alert(event: StateEvent):
    alerts.set_value(alerts.value + 1)            # only this element changes on the card


@action
def reset_alerts(event: ActionEvent):
    alerts.set_value(0)
```

Every element has an ID, unique on the card. The card is emptied when the automation stops and `main.py`
runs again at every start, so elements are created at the top of the file or in `@startup`. Buttons name
actions, which exist only once the file has run: create buttons in `@startup`.

| Create it with                                              | It shows                                   | Change it with                                  |
| ----------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------- |
| `create_text(id, markdown)`                                 | Markdown text                              | `set_text`                                      |
| `create_html(id, html)`                                     | Raw HTML, shown as it is                   | `set_html`                                      |
| `create_image(id, asset=None, url=None, alt="", ...)`       | An image from `assets/`, from a URL, or a camera's live picture | `set_asset`, `set_url`, `set_entity`, `set_refresh`, `set_alt`, `set_size`, `set_align`, `set_caption` |
| `create_value(id, label, value, unit="")`                   | A labelled value                           | `set_value`, `set_label`, `set_unit`            |
| `create_entity(id, entity_id)`                              | The live state of an entity                | `set_entity`                                    |
| `create_icon(id, entity_id=None, icon=None, ...)`           | An icon, driven by an entity by default    | `set_icon`, `set_color`, `set_spin`, `set_label`, `set_entity`, `set_follow_entity` |
| `create_gauge(id, value=None, entity_id=None, ...)`         | A progress bar or a dial                   | `set_value`, `set_entity`, `set_range`, `set_label`, `set_unit`, `set_kind`, `set_color` |
| `create_badge(id, text=None, entity_id=None, ...)`          | A short text in a coloured pill            | `set_text`, `set_entity`, `set_icon`, `set_color` |
| `create_graph(id, entities=None, series=None, ...)`         | A graph of history or of your own numbers  | `set_series`, `set_entities`, `set_hours`, `set_kind`, `set_title`, `set_unit`, `set_range`, `set_marks` |
| `create_button(id, label, action, confirm=None, **data)`    | A button that runs an action               | `set_label`, `set_action`, `set_confirm`, `set_data` |

A setter that is given something invalid raises and leaves the element as it was. Markdown is sanitised:
raw HTML is removed. A button calls its action with its extra keyword arguments as `event.data`.

### Layout

`haa.card.layout` says where the elements are: rows, from the top. `add_element()` gives an element a row of
its own, and `split_row(n)` adds a row of `n` cells of equal width that is filled from the left:

```python
@startup
def build_card(event: ActionEvent):
    layout = haa.card.layout
    layout.add_element(haa.card.create_text("title", "## Pumps"))            # a row of its own

    buttons = layout.split_row(3)                                            # three side by side
    buttons.add_element(haa.card.create_button("on", label="On", action="pump", state="on"))
    buttons.add_element(haa.card.create_button("off", label="Off", action="pump", state="off"))
    buttons.add_element(haa.card.create_button("auto", label="Auto", action="pump", state="auto"))

    layout.add_element(haa.card.create_image("logo", asset="logo.png"))      # the next row


@action
def pump(event: ActionEvent):
    haa.set_message(f"Pump: {event.data['state']}")
```

- `haa.card.add_element()` is the layout's `add_element()`. Both, and a row's, return what they were called
  on, so calls can be chained: `layout.split_row(2).add_element(a).add_element(b)`.
- A row has 1 to 6 cells. Fewer elements leave cells empty; elements beyond the last cell are ignored.
- Adding an element that is already on the card moves it.
- `layout.remove_element(element)` (or its ID) takes an element off the card, `layout.clear()` everything;
  `haa.card.element(id)` finds an element by its ID.
- On a narrow card the cells of a row wrap onto further lines.
- A card has at most 50 elements.

### Title and fixed parts

`haa.card.set_title()` can be called at any time, so the title can say what is going on
(`haa.card.set_title(f"Climate: {count} alerts")`); `None` goes back to the automation's name. A title has at
most 100 characters.

The fixed parts can be hidden, each on its own, and shown again at any time:

```python
haa.card.configure(state=False, log=False)       # no state badge, no Log button
haa.card.configure(title=False, state=False, message=False, actions=False, log=False)   # only the content
```

### HTML

`create_html()` puts HTML of your own on the card, as it is: tables, inline styles, anything HTML and CSS
can do. Home Assistant's theme variables (`var(--primary-color)`, `var(--secondary-text-color)`, ...) work in
it.

```python
import html

rooms = {"Kitchen": 21.5, "Bedroom <north>": 18.0}
rows = "".join([f"<tr><td>{html.escape(room)}</td><td>{value} °C</td></tr>" for room, value in rooms.items()])
table = haa.card.create_html("rooms", f'<table style="width: 100%">{rows}</table>')
haa.card.add_element(table)
table.set_html("<em>No rooms</em>")
```

- Unlike markdown, HTML is **not sanitised**. Escape every text you did not write yourself (entity states,
  event data, names) with `html.escape()`, as above.
- A `<script>` element does not run.
- An element with `data-haanim="run"` and `data-action="<name>"` runs that action when clicked, like a
  button element: `<a data-haanim="run" data-action="refresh">Refresh</a>`. `data-payload` takes the data of
  the call as JSON, `data-confirm` a question to ask first.
- The card draws its content again whenever something on it changes, and the HTML with it: what a visitor
  typed into a form field or opened in it is not kept.
- An HTML element has at most 50 000 characters.

### Images

An image is drawn at its own size, at the left of its row, and never wider than the space it has. `width`,
`height`, `align` and `caption` change that:

```python
logo = haa.card.create_image("logo", asset="logo.png", width=120, align="center", caption="Pump house")
plan = haa.card.create_image("plan", url="https://example.com/plan.png", width="50%", align="right")
haa.card.add_element(logo)
haa.card.add_element(plan)
logo.set_size(width=200, height=100)      # fitted into 200 by 100, keeping its shape
logo.set_align("left")
logo.set_caption(None)
```

- `width` is pixels, or a percentage of the space the image has (`"50%"`); `height` is pixels.
- With only one of them the other side follows, so the image keeps its shape. With both, the image is
  fitted into that box and still keeps its shape.
- `align` is `"left"`, `"center"` or `"right"`; the caption (plain text, at most 200 characters) goes with
  the image.

With `entity_id=` the image is the live picture of a camera: the camera's current picture, fetched again
every `refresh` seconds (10 unless given; 1 to 3600) while the card is on screen. A click opens the camera's
own dialog, with its live stream. Size, alignment and caption work as for any image.

```python
door = haa.card.create_image("door", entity_id="camera.front_door", refresh=5, width="100%", caption="Front door")
haa.card.add_element(door)
door.set_refresh(1)                       # once a second, while somebody is at the door
door.set_entity("camera.garden")          # another camera, same place on the card
```

An image has exactly one source: `asset`, `url` or `entity_id`. `set_asset()`, `set_url()` and `set_entity()`
replace it.

### Icons

An icon is driven by its entity unless told otherwise: it is lit while the entity is active (on, open,
home, ...) and dimmed while it is not, turns only while it is active if `spin=True`, and shows the entity's
name and state. Without `icon=` it is the entity's own icon. A click opens the entity's dialog.

```python
fan = haa.card.create_icon("fan", "fan.bedroom", icon="mdi:fan", spin=True)     # follows fan.bedroom
door = haa.card.create_icon("door", "binary_sensor.front_door")                 # the entity's own icon
mode = haa.card.create_icon("mode", icon="mdi:snowflake", label="Cooling", color="primary")    # no entity
alarm = haa.card.create_icon("alarm", "fan.bedroom", icon="mdi:fan-alert", color="error",
                             follow_entity=False)                               # exactly this, whatever the fan does
icons = haa.card.layout.split_row(4)
icons.add_element(fan).add_element(door).add_element(mode).add_element(alarm)
mode.set_icon("mdi:fire")
mode.set_label("Heating")
```

### Gauges and badges

A gauge shows a number within a range (`min=0`, `max=100` unless given): `kind="bar"` is a progress bar,
`kind="dial"` a half-round dial. The number is either yours, changed with `set_value()`, or the state of an
entity, which the gauge then follows; the entity also gives the label and the unit unless you give them.

```python
done = haa.card.create_gauge("done", 0, label="Backup", unit="%")                       # a progress bar
battery = haa.card.create_gauge("battery", entity_id="sensor.phone_battery")            # follows the entity
load = haa.card.create_gauge("load", 1.2, min=0, max=5, unit="kW", kind="dial", color="warning")
haa.card.add_element(done)
haa.card.layout.split_row(2).add_element(battery).add_element(load)
done.set_value(40)
load.set_color("error")
```

A number outside the range is shown as it is, with the gauge empty or full. While an entity's state is not a
number (`unavailable`), the gauge is empty and shows the state.

A badge is a short text (at most 40 characters) in a coloured pill, with an icon if you name one. Like a
gauge it shows either a text of yours or the state of an entity:

```python
mode = haa.card.create_badge("mode", "Heating", icon="mdi:fire", color="warning")
door = haa.card.create_badge("door", entity_id="lock.front_door")                       # the lock's state
haa.card.layout.split_row(4).add_element(mode).add_element(door)
mode.set_text("Idle")
mode.set_icon(None)
mode.set_color("disabled")
```

Colours are the same as for icons: a theme colour (`primary`, `accent`, `success`, `warning`, `error`,
`disabled`), a colour name or `#rrggbb`. A click on a gauge or badge of an entity opens the entity's dialog.

There is no table element: rows split into cells, filled with texts, values and badges, make one.

### Graphs

A graph shows either the history of entities or numbers of the automation's own:

```python
# What Home Assistant recorded for the entities over the last hours; the graph then follows them
temps = haa.card.create_graph("temps", ["sensor.indoor", "sensor.outdoor"], hours=12, title="Temperature")

# The automation's own numbers; set_series() replaces them
alerts = haa.card.create_graph("alerts", series={"Alerts": [3, 0, 1, 4, 2]}, kind="bar", title="Alerts per day")
curve = haa.card.create_graph("curve", series={"Target": [(0, 18), (6, 21), (22, 18)]}, unit="°C", min=15, max=25)
power = haa.card.create_graph("power", series={"Power": [("2025-01-06T12:00:00+00:00", 120), ("2025-01-06T13:00:00+00:00", 90)]})
for graph in (temps, alerts, curve, power):
    haa.card.add_element(graph)
alerts.set_series({"Alerts": [3, 0, 1, 4, 2, 6]})
```

Numbers are drawn against a value axis marked with round numbers; `kind` is `"line"`, `"area"` or `"bar"`.
An entity or series whose values are states rather than numbers (`on`, `off`, `heat`, ...) is drawn as a
timeline instead: a row with a coloured segment for every state it was in. One graph can have both:

```python
haa.card.add_element(
    haa.card.create_graph("climate", ["sensor.temperature", "climate.living_room", "binary_sensor.window"], hours=24)
)
haa.card.add_element(haa.card.create_graph("pump", series={"Pump": [(0, "on"), (6, "off"), (8, "on"), (10, "on")]}))
```

Hovering over a graph shows the values of all its series at that position. The horizontal axis has labelled
marks with smaller ones between them, at round distances the card picks; `x_major` and `x_minor` set the
distances instead, as durations on a time axis and as numbers otherwise:

```python
temps = haa.card.create_graph("temps", "sensor.indoor", hours=6, x_major="01:00:00", x_minor="00:15:00")
curve = haa.card.create_graph("curve", series={"Target": [(0, 18), (6, 21), (22, 18)]}, x_major=6, x_minor=1)
curve.set_marks(x_major=4)
```

The points of a series are plain values (drawn one after the other), `(x, y)` pairs, or `(time, y)` pairs
with timezone-aware times; the values of one series are all numbers or all states, and `None` leaves a gap. A
state holds until the next point. A graph has at most 8 entities or series, a series at most 500 points, and
history goes back at most 720 hours. The card keeps nothing for the automation: what should survive a restart
belongs in persistent variables.

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
| Check the card and press its buttons        | `card.title`, `card.blocks`, `card.block(id)`, `card.layout`, `await press(id)` |
| Drive the lifecycle                         | `start=False`, then `load()`, `start()`, `stop()`, `reload()`   |
| Provide assets and stored variables         | `assets={"logo.png": b"..."}`, `variables={"count": 3}`         |

Time stands still in the harness until the test advances it, so a test of "five minutes later" takes
milliseconds.

For editors and type checkers, the same package gives completion and types for `from haanim import ...`.
