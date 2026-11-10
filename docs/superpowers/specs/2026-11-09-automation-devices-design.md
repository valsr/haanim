# Automation devices and declared entities

Date: 2026-11-09
Status: approved design, awaiting implementation plan

## Goal

Each HAAnim automation becomes a device in Home Assistant. An automation declares entities on its device
in code, reads and writes their state through the `haa` API, and reacts to commands users send from Home
Assistant (toggling a switch, setting a number). The automation page in the HAAnim panel lists the
entities and lets the owner remove leftovers and purge stored data.

## Decisions

| Topic | Decision |
| --- | --- |
| Data flow | Both directions: output entities and controls |
| Entity types | `sensor`, `binary_sensor`, `switch`, `number`, `select`, `button`, `text` |
| Out of scope | `light`, `climate`, `cover`, `fan`; entities created at runtime |
| Declaration | Class decorators, evaluated when `main.py` runs |
| State owner | HAAnim (engine), not the class and not Home Assistant |
| Lifetime | Permanent: an entity outlives its declaration until removed in the panel |
| Leftover entities | Unavailable in Home Assistant, marked "leftover" in the panel |
| Runtime changes | Only state and attributes; all other properties come from the decorator |
| Missing hook | Warning in the automation log; the command is a no-op |
| Entity domain | Real HA platform domains; `haanim` is part of the object ID, not the domain |

## 1. Architecture and data flow

```
automation code ──@sensor_entity/@switch_entity──► DeviceStore (engine, per automation)
      ▲   haa.device.entity("x").set_state(...)        │  persists declarations + state (StorageBackend)
      │                                                ▼
   hooks (turn_on, set_value…)  ◄── command ──  EntitySink (Host protocol)
                                                       │
                                     custom_components/haanim/entities.py
                                       ├─ device registry: 1 device per automation
                                       └─ platforms: sensor, binary_sensor, switch,
                                          number, select, button, text
```

The engine (`src/haanim`) owns declarations and state in a `DeviceStore` per automation and stays free of
Home Assistant. The `Host` gets a new optional member `entities: EntitySink | None`, modelled on `CardSink`.
The integration implements the sink: it registers the device and the entities and forwards commands back.

- **Declaration.** The decorators record a declaration while `main.py` runs. After `main.py` finishes, the
  `DeviceStore` reconciles the declarations with the stored entities:
  - a declaration with no stored entity creates one, with state `initial` (or `unknown`);
  - a declaration with a stored entity keeps its stored state and attributes, and takes the new
    declaration (name, icon, options);
  - a stored entity with no declaration becomes a **leftover**: kept, unavailable in Home Assistant.
- **State writes.** `set_state()` and `set_attributes()` change the store synchronously, schedule a batched
  save (as persistent variables do) and push the change to the sink, which writes the HA state.
- **Commands from Home Assistant.** An HA entity's command method passes the command to the sink, and the
  engine runs the class's hook as an action: it appears in the running actions and the action log. A hook
  does not change state by itself; it confirms with `entity.set_state()`, so it can refuse or adjust.
- **Device.** One per automation: identifiers `(haanim, <automation_id>)`, name from the automation's
  metadata, manufacturer "HAAnim". The existing status sensor `sensor.haanim_<id>` joins the device; its
  entity ID and unique ID do not change.
- **Stopped automation.** Declared entities stay available with their last state. Commands log a warning
  (`"boost" ignored turn_on: automation is not running`) and are no-ops.
- **IDs.** Entity ID `<platform>.haanim_<automation_id>_<object_id>`; unique ID
  `haanim_<automation_id>_<object_id>`. The platform is not in the unique ID; if a declaration changes an
  entity's platform, the stored entity of the old platform becomes a leftover and a new entity is created.

## 2. The automation API

### Decorators

Exported from `haanim`. Every decorator takes these options:

| Option | Meaning |
| --- | --- |
| `name=` | Friendly name; default: the class name with `_` replaced by spaces |
| `icon=` | `mdi:` icon |
| `id=` | Object ID; default: the class name, slugged with the automation ID rule |
| `attributes=` | Initial attributes, used when the entity is created |
| `initial=` | State used when the entity is created or purged |
| `action_mode=` | Action mode of the hooks; default `ActionMode.DROP`, as for actions |

| Decorator | Extra options | Hooks |
| --- | --- | --- |
| `@sensor_entity` | `device_class`, `unit`, `state_class`, `precision` | none |
| `@binary_sensor_entity` | `device_class` | none |
| `@switch_entity` | `device_class` | `turn_on`, `turn_off` |
| `@number_entity` | `min`, `max`, `step`, `unit`, `mode`, `device_class` | `set_value` |
| `@select_entity` | `options` (required) | `select_option` |
| `@button_entity` | `device_class` | `press` |
| `@text_entity` | `min_length`, `max_length`, `pattern`, `mode` | `set_value` |

Hooks have the signature `(self, entity, event)`, may be sync or async, and receive the entity proxy and an
`EntityCommandEvent` with `entity_id`, `command`, `value` and `context`. The class is instantiated once per
start; `self` may hold helpers, but state that matters belongs in the entity.

```python
from haanim import haa, on_state, sensor_entity, switch_entity


@sensor_entity(device_class="temperature", unit="°C", state_class="measurement")
class average_temp:
    """Output only: no hooks."""


@switch_entity(name="Boost", icon="mdi:fire", initial=False)
class boost:
    async def turn_on(self, entity, event):
        await haa.service.climate.set_temperature(entity_id="climate.living_room", temperature=23)
        entity.set_state(True)

    async def turn_off(self, entity, event):
        entity.set_state(False)


@on_state("sensor.living_room_temp")
def update(event):
    haa.device.entity(average_temp).set_state(21.5)
```

### The entity proxy

`haa.device.entity(key)` takes the object ID or the decorated class. It raises `NonExistingEntityError`
for an unknown object ID.

| Member | Meaning |
| --- | --- |
| `entity_id` | `"switch.haanim_climate_boost"` |
| `object_id`, `platform` | As declared |
| `state` | Stored state, typed: `float` for numeric sensors and numbers, `bool` for binary sensors and switches, `str` otherwise; `None` when unknown |
| `attributes` | Copy of the attributes |
| `declared` | `False` for a leftover |
| `options` | Read-only declaration: `device_class`, `unit`, `min`, `max`, `options`, ... |
| `set_state(value)` | Validates and writes the state |
| `set_attributes(**attrs)` | Merges attributes; a value of `None` removes the key |

`haa.device` also has `id`, `name` and `entities` (every proxy, leftovers included).

### Validation

`set_state` raises `ValueError` with a clear message for:

- a value outside `min`/`max` of a number;
- an option not in `options` of a select;
- text that fails `pattern`, `min_length` or `max_length`;
- a non-number for a sensor with a `unit` or a numeric `state_class`, and for a number;
- anything but a bool (or the strings `"on"`/`"off"`) for binary sensors and switches;
- a value that is not JSON.

`set_state` is not allowed on a button (it has no state) or on a leftover. Attributes must be JSON.

### Other automations

Other automations read these entities like any HA entity (`haa.entity[...]`, `@on_state`). Only the
owning automation writes them.

## 3. Integration side

### Home Assistant entities

- `custom_components/haanim/entities.py` implements the `EntitySink`, the device registration and a
  generic `DeclaredEntity` base. Thin subclasses live in the platform files: a new class in `sensor.py`, and
  new `binary_sensor.py`, `switch.py`, `number.py`, `select.py`, `button.py`, `text.py`. `PLATFORMS` lists
  them all.
- HA entities hold no state of their own: their properties read the declaration and state from the store.
  Command methods (`async_turn_on`, `async_set_native_value`, `async_select_option`, `async_press`,
  `async_set_value`) forward to the sink.
- When Home Assistant starts, the entities are created from the **stored** declarations before automations
  run, so dashboards show the last known values instead of "unavailable".
- The device is registered when the automation is first loaded. Deleting the automation's folder removes the
  device and all its entities, as it removes the status sensor today.
- When a declaration changes, the entity's capabilities are updated on the next start. Customizations made in
  Home Assistant (entity ID, name, area) are kept because the unique ID is stable.

### Panel

A new **Entities** tab on the automation page, at `/haanim/automation/<id>/entities`, lists every entity:
entity ID and name, type, state, status (declared or leftover), and actions. Entity rows open Home
Assistant's more-info dialog; the tab links to the device page. The list updates live.

| Status | Actions |
| --- | --- |
| declared | **Purge data**; Remove is disabled with the hint "delete the class first" |
| leftover | **Remove** |

- **Remove** deletes the leftover from the entity registry and from storage.
- **Purge data** drops the stored state and attributes and resets the entity to `initial` (or `unknown`),
  written to Home Assistant at once. The registry entry, entity ID, customizations and history are kept. It
  works whether the automation runs or not; a running automation sees the reset state on its next read.

### WebSocket commands

| Command | Data | Result |
| --- | --- | --- |
| `haanim/entities/list` | `automation_id` | Declarations, states and statuses |
| `haanim/entities/remove` | `automation_id`, `object_id` | Removes a leftover; refuses a declared entity |
| `haanim/entities/purge` | `automation_id`, `object_id` | Resets a declared entity's stored data |

`haanim/automations/get` also returns the number of entities, for the tab badge.

### Storage

One key per automation, `device.<automation_id>`, separate from the variables so `haa.clear_variables()`
cannot remove entities, and an index key `devices` listing the automation IDs that have stored entities, so
the integration can create every entity when Home Assistant starts, before any automation is loaded. Saves are batched like variables (`SAVE_DELAY_SECONDS`) and always made when the
automation stops.

```json
{
  "version": 1,
  "entities": {
    "boost": {
      "platform": "switch",
      "options": {"name": "Boost", "icon": "mdi:fire"},
      "state": true,
      "attributes": {},
      "declared": true,
      "last_changed": "2026-11-09T10:00:00+00:00"
    }
  }
}
```

If a stored state fails validation against the current declaration when the automation loads (text stored
for a sensor that now has a unit, a value no longer in `options`), the entity is reset to `initial` and a
warning is logged.

## 4. Error handling

| Situation | Result |
| --- | --- |
| Two classes with the same object ID | Load error naming both; the automation goes to `error` |
| Bad declaration (unknown `device_class`, `min > max`, empty `options`, invalid `initial`) | Load error with the class name and line |
| Missing hook for a command | Warning in the automation log; command is a no-op |
| Command while the automation is stopped | Warning in the automation log; command is a no-op |
| Exception in a hook | Logged with traceback as for actions, `last_error` set; the HA command still succeeds; state unchanged |
| `remove`/`purge` of an unknown entity, `remove` of a declared one | WebSocket error; the panel shows the message |

## 5. Testing

- **Engine unit tests:** declaration parsing and validation for each type; reconciliation (new, kept,
  leftover, platform change); `set_state` validation; reset of incompatible stored state; batched
  persistence; hook dispatch, including the missing-hook warning, the stopped-automation warning, hook
  exceptions and action modes.
- **Testing kit:** `FakeHost` gets a fake `EntitySink` that records writes and sends commands
  (`harness.command("boost", "turn_on")`), so authors test their entities without Home Assistant.
- **Integration contract tests:** device registration; one entity of each platform with the right
  capabilities; startup from stored declarations before automations run; commands reaching hooks; remove,
  purge, and removal of an automation folder; the WebSocket commands.
- **Docs and examples:** a "Device entities" section in `docs/AUTOMATIONS.md`, and an example automation
  with tests in `examples/`.

## Delivery stages

1. **Output entities:** device, `DeviceStore`, `EntitySink`, `sensor` and `binary_sensor`, the proxy,
   the panel tab with Remove and Purge data, the WebSocket commands, docs and an example.
2. **Controls:** `switch`, `number`, `select`, `button`, `text`, hooks and `EntityCommandEvent`, the testing
   kit's `command()`, and their docs and example.
