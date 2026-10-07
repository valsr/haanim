# In Home Assistant

What HAAnim adds to Home Assistant, apart from running your automations.

## The card

Every automation has a card for dashboards:

```yaml
type: custom:haanim-card
automation_id: hello
```

The card has a title, a badge with the automation's state (the action that is running, or `Idle`), the
automation's status message, whatever the automation put on it, an **Actions** button that lists its actions
with a run button each, and a **Log** button that opens its log in the panel. The automation decides the
content and can hide each of the fixed parts: see [The card](AUTOMATIONS.md#the-card) in the guide.

## The panel

**HAAnim** in the sidebar:

- **Automations**: every automation with its state, version and status message, and the controls that
  apply to it: Enable or Disable, Start, Stop, Restart. A click on a row opens the automation.
- **An automation's page**: its state, controls and metadata, and three tabs: **Preview** (its card),
  **Actions** (run any of them) and **Logs**.
- **Configuration**: the integration's version and options.
- **Reload all** rescans the automations folder now.

## Logs and log levels

The Logs tab shows the latest 200 records of the automation: what it logged and printed, and the tracebacks
of actions that failed.

- **Log level**: choose `Debug` while you write an automation and `Error` once it runs. The level belongs to
  that automation and is kept across restarts. `Default` follows Home Assistant's `logger` configuration,
  where the automation logs under `custom_components.haanim.automation.<id>`.
- **Clear** empties the log shown. Home Assistant's own log file is not touched.

## The entity

Each automation has a sensor, `sensor.haanim_<id>`, whose state is `on`, `off` or `error`. Its attributes
include the status message, whether the automation is enabled, the actions that are running, the last action
and the last error, so dashboards and Home Assistant's own automations can follow a HAAnim automation.

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

A call that fails raises a service error that names the HAAnim error, as `<ErrorType>: <message>`. What an
action itself raises reaches the caller of `haanim.run_action` unchanged.

An action that fails when a trigger ran it has no caller: HAAnim logs it, keeps it in the entity's
`last_error` attribute, and fires a `haanim_action_error` event with `automation_id`, `action`, `error_type`
and `message`.

## Options

Under **Settings → Devices & services → HAAnim → Configure**. Changing an option reloads the integration.

| Option                     | Default                       | What it is                                             |
| -------------------------- | ----------------------------- | ------------------------------------------------------ |
| Automations folder         | `/config/haanim/automations`  | Where automations are discovered                       |
| Rescan interval            | 10 seconds                    | How often the folder is scanned for changes            |
| Concurrency limit          | 20                            | Most actions executing at once                         |
| Action queue size          | 100                           | Most queued requests per `QUEUE` action                |
| Default action timeout     | 0 (none)                      | Timeout for actions that do not set one                |
| Startup timeout            | 30 seconds                    | Time limit for `@startup`                              |
| Shutdown timeout           | 10 seconds                    | Time limit for `@shutdown`                             |
| Stop grace period          | 0.5 seconds                   | Time running actions get to finish before cancellation |
| Additional allowed imports | (empty)                       | Module names added to the import allowlist             |
| Allow all imports          | Off                           | Turns the import allowlist off                         |
