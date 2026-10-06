# HAAnim examples

Each folder is one automation: copy it into your automations folder (`/config/haanim/automations/` by
default) and it is loaded at the next rescan.

| Folder          | What it shows                                                                               |
| --------------- | ------------------------------------------------------------------------------------------- |
| `climate/`      | The Complete Example of the design: time, state and interval triggers, constraints, persistent storage, calling another automation, `@startup` and `@shutdown` |
| `motion_light/` | A state trigger with a time-of-day constraint, `haa.wait_for()` with a timeout, the `CANCEL` execution mode, and an action that takes data |
| `notifications/` | An action other automations call (`climate/` does), the `QUEUE` execution mode, and a card that follows what the automation does |
| `dashboard/`    | Card content with `haa.card`: a title that changes, text, an image from `assets/`, values, a live entity, buttons with data and a confirmation, and hiding the card's fixed parts; event, interval and cron triggers |

## Testing an example

`tests/` holds a test file per example, written with the harness that comes with the `haanim` package. They
run without Home Assistant:

```sh
pip install haanim pytest pytest-asyncio
pytest examples/tests
```

The tests are outside the automation folders on purpose: every `.py` file in an automation's folder is part
of the automation.
