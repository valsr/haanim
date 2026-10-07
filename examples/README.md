# HAAnim examples

Each folder is one automation: copy it into your automations folder (`/config/haanim/automations/` by
default) and it is loaded at the next rescan.

| Folder          | What it shows                                                                               |
| --------------- | ------------------------------------------------------------------------------------------- |
| `climate/`      | The Complete Example of the design: time, state and interval triggers, constraints, persistent storage, calling another automation, `@startup` and `@shutdown` |
| `motion_light/` | A state trigger with a time-of-day constraint, `haa.wait_for()` with a timeout, the `CANCEL` execution mode, and an action that takes data |
| `notifications/` | An action other automations call (`climate/` and `demo_calls/` do), the `QUEUE` execution mode, and a card that follows what the automation does |

## Demos

The `demo_` folders are automations too, but each is there to show one part of HAAnim, mostly on its card.
Put the card of a demo on a dashboard (`type: custom:haanim-card`, `automation_id: demo_basics`) and read its
`main.py` next to it.

| Folder           | What it shows                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------ |
| `demo_basics/`   | Where to start: text, a value and buttons on a card; actions with data, a result and a confirmation; the title and the status message; hiding the card's fixed parts; an event and a cron trigger |
| `demo_controls/` | The elements that show a state: values, entities, icons, gauges (bar and dial) and badges, driven by the automation or following an entity |
| `demo_layout/`   | Rows and cells: `split_row()`, rows that are not full, a table made of rows, and moving, removing and rebuilding |
| `demo_graphs/`   | Graphs of plain numbers, of pairs, over time, of states as a timeline, and of the history of entities; changing a graph in place |
| `demo_images/`   | Images from `assets/` and from an address; width, height, alignment and caption; the live picture of a camera |
| `demo_html/`     | Raw HTML: a table, styled boxes, links and swatches that run actions, and escaping text from outside |
| `demo_errors/`   | What happens when an action raises, times out or is dropped; catching those in an automation; a failure in a trigger, `last_error` and the `haanim_action_error` event |
| `demo_calls/`    | Reading entities, changing them by calling services, calling other automations and using what they return, and a state trigger that does all three |

The demos use a few entities: `sensor.temperature`, `input_number.temperature`, `input_boolean.fan`, `sun.sun`
and `camera.demo`. Where one is missing the card says so; nothing fails.

## Testing an example

`tests/` holds a test file per example, written with the harness that comes with the `haanim` package. They
run without Home Assistant:

```sh
pip install haanim pytest pytest-asyncio
pytest examples/tests
```

The tests are outside the automation folders on purpose: every `.py` file in an automation's folder is part
of the automation.
