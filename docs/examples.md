# Examples and demos

The repository's [`examples/`](https://github.com/valsr/haanim/tree/main/examples) folder has complete automations. Each folder is one automation: copy it
into your automations folder (`/config/haanim/automations/` by default) and it is loaded at the next rescan.

## Automations that do something

| Automation | What it shows |
| --- | --- |
| [`climate`](https://github.com/valsr/haanim/tree/main/examples/climate/main.py) | Time, state and interval triggers, constraints, persistent storage, calling another automation, `@startup` and `@shutdown` |
| [`motion_light`](https://github.com/valsr/haanim/tree/main/examples/motion_light/main.py) | A state trigger with a time-of-day constraint, `haa.wait_for()` with a timeout, the `CANCEL` execution mode, an action that takes data |
| [`notifications`](https://github.com/valsr/haanim/tree/main/examples/notifications/main.py) | An action other automations call, the `QUEUE` execution mode, and a card that follows what the automation does |

## Demos: one for each part of HAAnim

Each demo is there to show one thing, mostly on its card. Put the card of a demo on a dashboard and read its
`main.py` next to it:

```yaml
type: custom:haanim-card
automation_id: demo_basics
```

| Automation | What it shows |
| --- | --- |
| [`demo_basics`](https://github.com/valsr/haanim/tree/main/examples/demo_basics/main.py) | Where to start: text, a value and buttons; actions with data, a result and a confirmation; the title and the status message |
| [`demo_controls`](https://github.com/valsr/haanim/tree/main/examples/demo_controls/main.py) | Values, entities, icons, gauges (bar and dial) and badges, set by the automation or following an entity |
| [`demo_layout`](https://github.com/valsr/haanim/tree/main/examples/demo_layout/main.py) | Rows and cells, a table made of rows, and moving, removing and rebuilding elements |
| [`demo_graphs`](https://github.com/valsr/haanim/tree/main/examples/demo_graphs/main.py) | Graphs of numbers, of pairs, over time, of states as a timeline, and of the history of entities |
| [`demo_images`](https://github.com/valsr/haanim/tree/main/examples/demo_images/main.py) | Images from `assets/` and from an address; size, alignment and caption; the live picture of a camera |
| [`demo_html`](https://github.com/valsr/haanim/tree/main/examples/demo_html/main.py) | Raw HTML: a table, styled boxes, links that run actions, and escaping text from outside |
| [`demo_errors`](https://github.com/valsr/haanim/tree/main/examples/demo_errors/main.py) | What happens when an action raises, times out or is dropped; catching that; a failure in a trigger |
| [`demo_calls`](https://github.com/valsr/haanim/tree/main/examples/demo_calls/main.py) | Reading entities, changing them through services, and calling other automations |

The demos use a few entities: `sensor.temperature`, `input_number.temperature`, `input_boolean.fan`,
`sun.sun` and `camera.demo`. Where one is missing the card says so; nothing fails.

## Tests

[`examples/tests/`](https://github.com/valsr/haanim/tree/main/examples/tests) has a test file per automation, written with the test harness. They are a
good place to see how an automation is tested, and they run without Home Assistant:

```sh
pip install haanim pytest pytest-asyncio
pytest examples/tests
```
