# Automation Devices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each HAAnim automation becomes a Home Assistant device whose entities the automation declares with class decorators, writes through `haa.device`, and controls through hooks; the panel lists them and removes leftovers or purges data.

**Architecture:** The engine (`src/haanim`) owns declarations and state in a `DeviceStore` per automation, all held by one `DeviceRegistry` that persists through the existing `StorageBackend` and pushes changes to a new optional `Host.entities: EntitySink`. The integration implements the sink: it registers one device per automation and one generic entity class per HA platform, and forwards HA commands back to `Automation.entity_command`, which runs hooks through the existing `ActionDispatcher`.

**Tech Stack:** Python 3.13, Home Assistant entity platforms and device registry, pytest + pytest-homeassistant-custom-component, node `--test` for the panel.

**Spec:** `docs/superpowers/specs/2026-11-09-automation-devices-design.md`

## Global Constraints

- Entity ID `<platform>.haanim_<automation_id>_<object_id>`; unique ID `haanim_<automation_id>_<object_id>` (no platform in it).
- Object ID default: the class name slugged with `haanim.engine.automation_ids.automation_id` (same rule as automation IDs); `id=` overrides.
- Device identifiers `("haanim", <automation_id>)`, name = automation name, manufacturer `"HAAnim"`.
- Storage keys: `device.<automation_id>` per automation, `devices` index (sorted list of automation IDs). Document `{"version": 1, "entities": {<object_id>: {"platform", "options", "state", "attributes", "declared", "last_changed"}}}`.
- Saves batched with `haanim.engine.variables.SAVE_DELAY_SECONDS`; flushed when an automation stops.
- Hook default action mode `ActionMode.DROP`.
- Log copy (exact): missing hook `"<object_id>" has no <command> hook; command ignored`; stopped `"<object_id>" ignored <command>: automation is not running`. Both at WARNING on the automation's logger.
- Panel hint copy (exact): `delete the class first`.
- Engine code never imports `homeassistant` (`tests/engine/test_package_boundary.py` enforces it).
- New public names (decorators, `EntityCommandEvent`, `HAAnimDevice`, `DeviceEntity`) are exported from the `haanim` module and listed wherever `tests/engine/test_public_api.py` and `scripts/check-public-api-coverage.py` require.
- Version 0.4.0 (`custom_components/haanim/manifest.json`, `src/haanim/__init__.py`, `tests/integration/test_const.py`, CHANGELOG).

## Review Focus

1. **Automation renamed/reloaded while HA has its entities:** a hot reload must keep entity state and must not flicker entities to removed; only folder deletion removes the device. Test in Task 6.
2. **Stored state from an older declaration:** a stored text state for a sensor that now has a `unit`, or a select value no longer in `options`, resets to `initial` with a warning instead of failing the start. Test in Task 3.
3. **Hook calls `set_state` with an invalid value:** the `ValueError` is a hook failure (logged, `last_error`), HA's command still succeeds, state unchanged. Test in Task 5.
4. **Two automations with the same object ID:** `switch.haanim_a_boost` and `switch.haanim_b_boost` are independent (store keyed per automation; proxies never cross). Test in Task 3.
5. **Purge or remove while a save is pending:** the pending batched save must not resurrect purged/removed data. Test in Task 3.

---

### Task 1: Entity declarations and decorators

**Files:**
- Create: `src/haanim/engine/device_entities.py`
- Test: `tests/engine/test_device_entities.py`

**Interfaces:**
- Produces:
  - `PLATFORMS: dict[str, PlatformSpec]` for `"sensor", "binary_sensor", "switch", "number", "select", "button", "text"`; `PlatformSpec(options: frozenset[str], hooks: tuple[str, ...], stateful: bool)`. Hooks per spec table (`button` → `("press",)`, `stateful=False`).
  - `@dataclass(frozen=True) EntityDeclaration(object_id: str, platform: str, name: str, icon: str | None, options: dict[str, Any], attributes: dict[str, Any], initial: Any, action_mode: ActionMode, cls: type, line: int | None)`; `declaration.as_stored() -> dict`: what goes in the document's `"options"` — `name`, `icon`, `initial`, `initial_attributes` and the platform options.
  - `ENTITY_ATTRIBUTE = "_haanim_entity"`; `get_declaration(cls) -> EntityDeclaration | None`.
  - Decorator factories `sensor_entity`, `binary_sensor_entity`, `switch_entity`, `number_entity`, `select_entity`, `button_entity`, `text_entity`, each `(**options) -> Callable[[type], type]`; also usable bare (`@sensor_entity` without parentheses).
  - `DECORATORS: dict[str, Callable]` by import name, for Task 4.
- Validation (raises `AutomationDefinitionError` with the class name): target not a class; unknown option for the platform; `device_class` not in HA's list for the platform (keep a frozenset per platform in this file — the engine cannot import HA; copy from HA's `SensorDeviceClass`, `BinarySensorDeviceClass`, `SwitchDeviceClass`, `NumberDeviceClass`, `ButtonDeviceClass`); `state_class` not in `measurement`, `total`, `total_increasing`; `min > max`; `step <= 0`; `select` without non-empty `options` list of strings; `number.mode` not in `auto`, `box`, `slider`; `text.mode` not in `text`, `password`; invalid `pattern` regex; `initial` failing `validate_state` (Task 2) — call it at decoration time; `initial` on a `button`.

- [ ] **Step 1: Write failing tests**

```python
def test_class_name_is_object_id_and_name():
    @sensor_entity(unit="°C", device_class="temperature")
    class average_temp: ...
    d = get_declaration(average_temp)
    assert (d.object_id, d.platform, d.name) == ("average_temp", "sensor", "average temp")
    assert d.options == {"unit": "°C", "device_class": "temperature"}

def test_id_override_and_slug():
    @switch_entity(id="Boost Mode")
    class Anything: ...
    assert get_declaration(Anything).object_id == "boost_mode"

def test_bare_decorator():
    @binary_sensor_entity
    class door: ...
    assert get_declaration(door).platform == "binary_sensor"

def test_default_action_mode_is_drop():
    @button_entity
    class ring: ...
    assert get_declaration(ring).action_mode is ActionMode.DROP

@pytest.mark.parametrize("decorate, message", [
    (lambda: number_entity(min=5, max=1), "min"),
    (lambda: select_entity(options=[]), "options"),
    (lambda: sensor_entity(device_class="nope"), "device_class"),
    (lambda: switch_entity(unit="W"), "unit"),
    (lambda: text_entity(pattern="("), "pattern"),
    (lambda: number_entity(min=0, max=10, initial=11), "initial"),
])
def test_bad_declarations(decorate, message):
    with pytest.raises(AutomationDefinitionError, match=message):
        decorate()(type("thing", (), {}))

def test_decorating_a_function_fails():
    with pytest.raises(AutomationDefinitionError, match="class"):
        sensor_entity()(lambda: None)
```

- [ ] **Step 2: Run** `uv run pytest tests/engine/test_device_entities.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement `device_entities.py`** per the Interfaces block. `line` comes from `inspect.getsourcelines` is not available in the interpreter — take it from `cls.__dict__.get("__firstlineno__")` if present, else None; the interpreter's `_eval_class_def` sets `__firstlineno__` in the class namespace (add `class_scope.set("__firstlineno__", node.lineno)` in `src/haanim/engine/ast_evaluator.py:_eval_class_def`).
- [ ] **Step 4: Run** the tests — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Entity declarations and their decorators"`

### Task 2: State validation

**Files:**
- Modify: `src/haanim/engine/device_entities.py`
- Test: `tests/engine/test_device_entities.py`

**Interfaces:**
- Produces: `validate_state(declaration_or_parts, value) -> Any` returning the normalized stored value; signature `validate_state(platform: str, options: Mapping[str, Any], value: Any) -> Any`. Raises `ValueError` with a message naming the entity's rule. `None` is always allowed (unknown).
- Rules (spec §2 Validation): numeric sensor (has `unit` or `state_class`) and `number` → `float` (bool rejected); `binary_sensor`/`switch` → `bool`, accepting `"on"`/`"off"`; `select` → member of `options`; `text` → `str` within `min_length`/`max_length` (defaults 0/255, HA's) and matching `pattern` (`re.fullmatch`); other sensors → JSON value via `haanim.engine.variables._check_json`; `number` within `min`/`max` (defaults 0/100, HA's); `button` → `ValueError("a button has no state")`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("platform, options, value, expected", [
    ("sensor", {"unit": "°C"}, 21, 21.0),
    ("sensor", {}, "hello", "hello"),
    ("binary_sensor", {}, "on", True),
    ("switch", {}, False, False),
    ("number", {"min": 0, "max": 10}, "5", 5.0),
    ("select", {"options": ["a", "b"]}, "b", "b"),
    ("text", {"pattern": "[a-z]+"}, "abc", "abc"),
    ("sensor", {"unit": "°C"}, None, None),
])
def test_valid_states(platform, options, value, expected):
    assert validate_state(platform, options, value) == expected

@pytest.mark.parametrize("platform, options, value", [
    ("sensor", {"unit": "°C"}, "warm"),
    ("number", {"min": 0, "max": 10}, 11),
    ("number", {}, True),
    ("switch", {}, "yes"),
    ("select", {"options": ["a"]}, "z"),
    ("text", {"max_length": 2}, "abc"),
    ("button", {}, 1),
    ("sensor", {}, object()),
])
def test_invalid_states(platform, options, value):
    with pytest.raises(ValueError):
        validate_state(platform, options, value)
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement `validate_state`.**
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_device_entities.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Validation of declared entity states"`

### Task 3: DeviceStore, DeviceRegistry and the EntitySink protocol

**Files:**
- Create: `src/haanim/engine/devices.py`
- Modify: `src/haanim/interfaces.py` (add `EntitySink` protocol; `Host.entities: EntitySink | None = None`)
- Modify: `src/haanim/testing/fakes.py` (add `FakeEntitySink`), `src/haanim/testing/__init__.py` exports
- Test: `tests/engine/test_devices.py`

**Interfaces:**
- Consumes: `EntityDeclaration`, `validate_state` (Tasks 1–2); `StorageBackend`, `Clock`; `SAVE_DELAY_SECONDS`.
- Produces:
  - `EntitySink` protocol: `entity_changed(automation_id: str, object_id: str) -> None` (created, state, attributes, declaration or declared flag changed); `entity_removed(automation_id: str, object_id: str) -> None`; `device_removed(automation_id: str) -> None`.
  - `@dataclass StoredEntity(key, object_id, platform, options: dict, state: Any, attributes: dict, declared: bool, last_changed: datetime | None)`, with `entity_id(automation_id) -> str` and `unique_id(automation_id) -> str`.
  - `DeviceStore` (one automation): `automation_id`; `entities() -> list[StoredEntity]` (sorted by object ID); `get(object_id) -> StoredEntity | None`; `reconcile(declarations: list[EntityDeclaration]) -> list[str]` (returns warning messages for reset states; new → state `initial`, attributes from declaration; existing same platform → keep state/attributes, take options, `declared=True`, reset to `initial` + warning if `validate_state` fails; existing with another platform → the old entry moves to document key `<object_id>@<old platform>` with `declared=False` (its `object_id` field, entity ID and unique ID are unchanged; HA's registry keeps unique IDs per domain, so both coexist) and a new entry is created; undeclared → `declared=False`). Document keys are therefore not always object IDs: `StoredEntity.object_id` is the object ID, `StoredEntity.key` the document key, and `get`/`purge`/`remove` take the key; `set_state(object_id, value)` (validates, raises `ValueError` for leftover or button, sets `last_changed` from the clock when the value changes); `set_attributes(object_id, **attrs)` (merge, `None` removes); `purge(key)` (state ← stored `options["initial"]`, attributes ← `options["initial_attributes"]`; refuses an unknown key with `KeyError` and a leftover with `ValueError`); `remove(key)` (refuses declared with `ValueError`, unknown with `KeyError`).
  - `DeviceRegistry(storage: StorageBackend, clock: Clock, sink: EntitySink | None)`: `async load_all()` (reads `devices` index, then each `device.<id>`); `store(automation_id) -> DeviceStore` (creates empty on first use); `automation_ids() -> list[str]`; `async remove_device(automation_id)` (drops the document — save `None` — and index entry, calls `sink.device_removed`); `async flush(automation_id | None = None)`. Every change in a store schedules one batched save of that document (and of the index when the set of IDs changes) and calls the sink.
  - `FakeEntitySink`: records calls in `changes: list[tuple[str, str, str]]` (`("changed"|"removed"|"device_removed", automation_id, object_id)`).

- [ ] **Step 1: Write failing tests** (use `FakeStorage`, `FakeClock`, `FakeEntitySink`; declarations built with the Task 1 decorators):

```python
async def test_new_declaration_gets_initial_state_and_is_saved(registry, storage, clock):
    store = registry.store("climate")
    store.reconcile([decl(switch_entity(initial=True), "boost")])
    assert store.get("boost").state is True
    await clock.advance(seconds=SAVE_DELAY_SECONDS)
    assert (await storage.load("device.climate"))["entities"]["boost"]["state"] is True
    assert await storage.load("devices") == ["climate"]

async def test_existing_entity_keeps_state(registry): ...         # reconcile twice, set_state between
async def test_undeclared_becomes_leftover(registry): ...         # declared False; set_state raises ValueError
async def test_platform_change_keeps_old_as_leftover(registry):
    # sensor "x" then number "x": get("x").platform == "number"; get("x@sensor").declared is False
async def test_incompatible_stored_state_resets_with_warning(registry):
    # store text "warm" for sensor; reconcile with unit="°C" → state None/initial, one warning returned
async def test_purge_resets_to_initial(registry): ...
async def test_remove_refuses_declared(registry): ...             # ValueError; leftover removal works, sink "removed"
async def test_pending_save_does_not_resurrect_removed(registry, storage, clock):
    # set_state, remove leftover before SAVE_DELAY elapses, advance → stored doc has no entity
async def test_two_automations_are_independent(registry): ...     # same object_id in "a" and "b"
async def test_load_all_reads_index(storage, clock): ...          # pre-seed storage; new registry sees both
async def test_remove_device_drops_document_and_index(registry, storage, clock): ...
async def test_sink_told_of_every_change(registry, sink): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/engine/test_devices.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `devices.py`, the protocol, `Host.entities`, `FakeEntitySink`. Batching: copy `VariableStore`'s `_write_later`/`flush` pattern (timer via `clock.call_later`); serialize the document at write time, not at schedule time, so later changes (including removal) win.
- [ ] **Step 4: Run** the tests, then `uv run pytest tests/engine -q` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Device store and registry for declared entities"`

### Task 4: Declarations in automations and the `haa.device` API

**Files:**
- Modify: `src/haanim/engine/automation_context.py` (constructor `device_store: DeviceStore | None = None`; when None build `DeviceRegistry(host.storage, host.clock, host.entities).store(id)` lazily in `_build_modules` so harness contexts work; after `_extract_definitions`, collect declarations from `self._decorators.functions` that have `get_declaration`, raise `AutomationDefinitionError("Entity '<id>' is declared by both '<A>' and '<B>'")` on duplicate object IDs, call `store.reconcile`, log each returned warning at WARNING on the automation logger; keep `self.entity_classes: dict[str, tuple[EntityDeclaration, object]]` mapping object ID → (declaration, instance); `discard()` clears it)
- Create: `src/haanim/engine/device_api.py` (`HAAnimDevice`, `DeviceEntity`)
- Modify: `src/haanim/engine/haanim_api.py` (`HAAnim.__init__` takes `device_store`; property `device -> HAAnimDevice`)
- Modify: `src/haanim/engine/haanim_module.py` (`DECORATORS.update(device_entities.DECORATORS)`; export `HAAnimDevice`, `DeviceEntity`)
- Modify: `src/haanim/__init__.py`, public-API lists
- Modify: `src/haanim/testing/harness.py` (create a `FakeEntitySink`, pass it as `entities=` to `make_host` — `src/haanim/testing/fakes.py:make_host` gains the argument; `entity(object_id) -> DeviceEntity`; `entities -> list[DeviceEntity]`; constructor `entities: dict[str, Any] | None` seeding stored states, e.g. `{"boost": True}`, applied before start)
- Test: `tests/engine/test_device_api.py` (harness-driven, with `tmp_path` automation folders)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `HAAnimDevice(store, automation_id, name_getter)`: `id: str`, `name: str`, `entities: list[DeviceEntity]`, `entity(key: str | type) -> DeviceEntity` (class → its declaration's object ID; unknown → `NonExistingEntityError`).
  - `DeviceEntity`: `entity_id`, `object_id`, `platform`, `state`, `attributes` (copy), `declared`, `options` (copy, without `name`, `icon`, `initial`, `initial_attributes`), `set_state(value)`, `set_attributes(**attrs)` — thin delegation to `DeviceStore`.
  - `AutomationContext.entity_classes` (used by Task 5).
  - Each class is instantiated once per `execute()`, with no arguments.

- [ ] **Step 1: Write failing tests**

```python
MAIN = '''
from haanim import haa, sensor_entity, switch_entity, startup

@sensor_entity(unit="°C", initial=20)
class average_temp: ...

@switch_entity(name="Boost")
class boost: ...

@startup
def begin(event):
    haa.device.entity(average_temp).set_state(21.5)
'''

async def test_declared_entities_and_proxy(tmp_path):
    folder = write_automation(tmp_path, "climate", MAIN)
    async with AutomationHarness(folder) as h:
        assert h.state == "on"
        e = h.entity("average_temp")
        assert e.entity_id == "sensor.haanim_climate_average_temp" and e.state == 21.5

async def test_duplicate_object_id_is_a_load_error(tmp_path): ...   # h.state == "error", message names both classes
async def test_unknown_entity_raises(tmp_path): ...                  # haa.device.entity("nope") → NonExistingEntityError
async def test_set_state_validation_error_reaches_code(tmp_path): ...# ValueError inside an action
async def test_state_survives_restart(tmp_path): ...                 # set, h.restart(), still set
async def test_leftover_after_class_removed(tmp_path): ...           # rewrite main.py without boost, h.reload(); declared False
async def test_harness_seeded_entity_state(tmp_path): ...           # entities={"boost": True}; state True at @startup
```

- [ ] **Step 2: Run** `uv run pytest tests/engine/test_device_api.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. Reconcile runs inside `execute()` after `_extract_definitions()` and before `@startup`, so `@startup` sees stored states.
- [ ] **Step 4: Run** the tests and `uv run pytest tests/engine -q` (public API, boundary, docs tests included) — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Automations declare entities and reach them through haa.device"`

### Task 5: Commands from Home Assistant run hooks

**Files:**
- Modify: `src/haanim/events.py` (`EntityCommandEvent(ActionEvent)`: `entity_id: str`, `command: str`, `value: Any = None`, `context: Any = None`; `source="entity"`, add `SOURCE_ENTITY = "entity"`)
- Modify: `src/haanim/engine/lifecycle.py` (`Automation.entity_command`)
- Modify: `src/haanim/engine/haanim_module.py` (export `EntityCommandEvent`)
- Modify: `src/haanim/testing/harness.py` (`async command(object_id, command, value=None) -> None`, driving `Automation.entity_command` through `_drive`)
- Test: `tests/engine/test_entity_commands.py`

**Interfaces:**
- Consumes: `AutomationContext.entity_classes`, `DeviceStore`, `ActionDispatcher.dispatch`, `record_action_failure`.
- Produces: `async Automation.entity_command(object_id: str, command: str, value: Any = None, context: Any = None) -> None`. Never raises for automation-side problems:
  - not `accepts_calls()` → stopped warning (exact copy, Global Constraints), return;
  - object ID not declared, or command not in the platform's hooks → `KeyError` (this is a caller bug, not an automation problem);
  - class lacks the hook → missing-hook warning, return;
  - else dispatch `getattr(instance, command)` with arguments `(DeviceEntity, EntityCommandEvent)` via `self._dispatcher.dispatch(automation_id, f"{object_id}.{command}", hook, proxy, event, mode=declaration.action_mode, timeout=None)`; any exception (including `ActionDroppedError` and a `ValueError` from `set_state`) → `self.record_action_failure(f"{object_id}.{command}", err)`.

- [ ] **Step 1: Write failing tests**

```python
async def test_turn_on_runs_hook_and_hook_confirms(tmp_path):
    # hook: entity.set_state(True); after command state is True; event.command == "turn_on"
async def test_missing_hook_warns_and_is_noop(tmp_path, caplog):
    # switch without turn_off; command turn_off → state unchanged;
    # log contains '"boost" has no turn_off hook; command ignored'
async def test_stopped_automation_warns(tmp_path):
    # h.stop(); command → '"boost" ignored turn_on: automation is not running'
async def test_hook_exception_is_recorded_not_raised(tmp_path):
    # hook raises RuntimeError → h.last_error.action == "boost.turn_on"; command returns None
async def test_hook_invalid_set_state_is_failure(tmp_path): ...   # Review Focus 3
async def test_number_set_value_passes_value(tmp_path): ...       # event.value == 7.0
async def test_drop_mode_drops_concurrent_command(tmp_path): ...  # slow hook, second command → last_error ActionDroppedError, WARNING
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/engine -q` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "HA commands run the hooks of declared entities"`

### Task 6: Integration — device, sink, sensor and binary_sensor

**Files:**
- Create: `custom_components/haanim/entities.py` (`HAEntitySink`, `DeclaredEntity`, `async_setup_declared_platform(hass, entry, async_add_entities, platform, entity_cls)`)
- Create: `custom_components/haanim/binary_sensor.py`
- Modify: `custom_components/haanim/sensor.py` (add `DeclaredSensor`; status sensor gets `device_info` for `("haanim", automation_id)`)
- Modify: `custom_components/haanim/ha/host.py` (`build_host` gets `entities=HAEntitySink(hass)`)
- Modify: `custom_components/haanim/automation_manager.py` (own a `DeviceRegistry(host.storage, host.clock, host.entities)`; `await registry.load_all()` in `async_setup` **before** platforms are forwarded; pass `registry.store(id)` to each `AutomationContext`; in `remove()` call `await registry.remove_device(id)`; flush on stop; method `async_entity_command(automation_id, object_id, command, value, context)` → `self._automation(automation_id).entity_command(...)`, and when the automation is not loaded log the stopped warning on its logger)
- Modify: `custom_components/haanim/__init__.py` (`PLATFORMS` adds `BINARY_SENSOR`; ensure manager setup/`load_all` precedes `async_forward_entry_setups`)
- Test: `tests/integration/test_device_entities.py`

**Interfaces:**
- Consumes: `DeviceRegistry`, `StoredEntity`, `EntitySink`.
- Produces:
  - `HAEntitySink`: implements `EntitySink`; keeps `platform → add_entities callback` registered by each platform's setup and a `dict[(automation_id, object_id), DeclaredEntity]`; on `entity_changed` creates the entity if the platform is set up and it is new, otherwise `async_write_ha_state()`; `entity_removed` → remove from entity registry by unique ID; `device_removed` → `device_registry.async_remove_device`; registers the device with `device_registry.async_get_or_create(config_entry_id=..., identifiers={("haanim", id)}, name=..., manufacturer="HAAnim")` the first time an automation's entity appears or the status sensor is added.
  - `DeclaredEntity(Entity)`: `_attr_should_poll = False`, `_attr_has_entity_name = False`, `unique_id`, `entity_id` from Global Constraints, `device_info`; `available` = `stored.declared`; `name`/`icon` from stored options; `extra_state_attributes` = stored attributes. Subclasses map options to HA attributes (`native_unit_of_measurement`, `device_class`, `state_class`, `suggested_display_precision`, `native_min_value`, ...).
  - `AutomationManager.devices: DeviceRegistry`, `async_entity_command(...)`.

- [ ] **Step 1: Write failing tests** (pytest-homeassistant-custom-component, follow `tests/integration/test_sensor.py` setup fixtures):

```python
async def test_device_and_entities_created(hass, setup_with_automation):
    # automation "climate" declares sensor average_temp (°C) and binary_sensor door
    state = hass.states.get("sensor.haanim_climate_average_temp")
    assert state.attributes["unit_of_measurement"] == "°C"
    device = dr.async_get(hass).async_get_device({("haanim", "climate")})
    assert device.manufacturer == "HAAnim"
    entry = er.async_get(hass).async_get("sensor.haanim_climate_average_temp")
    assert entry.device_id == device.id
    assert er.async_get(hass).async_get("sensor.haanim_climate").device_id == device.id

async def test_entities_exist_from_storage_before_automations_load(hass, hass_storage): ...
    # seed hass_storage["haanim.devices"] and ["haanim.device.climate"]; set up with HA not started;
    # state present with stored value before EVENT_HOMEASSISTANT_STARTED
async def test_set_state_writes_ha_state(hass, ...): ...
async def test_leftover_is_unavailable(hass, ...): ...
async def test_reload_keeps_entities(hass, ...): ...           # Review Focus 1: touch main.py, state unchanged, entity not removed
async def test_folder_removal_removes_device(hass, ...): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/test_device_entities.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/integration -q` — Expected: PASS (existing `test_sensor.py` still passes with the status sensor on the device).
- [ ] **Step 5: Commit** `git commit -m "Automations are devices with sensor and binary sensor entities"`

### Task 7: Integration — control platforms

**Files:**
- Create: `custom_components/haanim/switch.py`, `number.py`, `select.py`, `button.py`, `text.py`
- Modify: `custom_components/haanim/__init__.py` (`PLATFORMS` adds them)
- Test: `tests/integration/test_device_entities.py`

**Interfaces:**
- Consumes: `DeclaredEntity`, `async_setup_declared_platform`, `AutomationManager.async_entity_command`.
- Produces: one subclass per platform; command methods forward `(command, value, self._context)` to `async_entity_command`: `async_turn_on`→`("turn_on", None)`, `async_turn_off`→`("turn_off", None)`, `async_set_native_value(v)`→`("set_value", v)` (number), `async_select_option(o)`→`("select_option", o)`, `async_press`→`("press", None)`, `async_set_value(v)`→`("set_value", v)` (text). State: switch `is_on`, number `native_value`, select `current_option` + `options`, text `native_value` + `native_min`/`native_max`/`pattern`/`mode`. Button has no state.

- [ ] **Step 1: Write failing tests** — for each platform, call the HA service (`switch.turn_on`, `number.set_value`, `select.select_option`, `button.press`, `text.set_value`) and assert the hook ran (hook sets state or a variable) and the HA state updated; `test_switch_without_hook_snaps_back` (state stays off, warning logged); `test_command_while_stopped_is_noop`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/integration -q` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Switch, number, select, button and text entities with hooks"`

### Task 8: WebSocket commands

**Files:**
- Modify: `custom_components/haanim/websocket.py`
- Test: `tests/integration/test_websocket.py`

**Interfaces:**
- Consumes: `AutomationManager.devices`.
- Produces:
  - `haanim/entities/list {automation_id}` → `{"device_id": str | None, "entities": [{"key", "object_id", "entity_id", "platform", "name", "state", "declared"}]}` (`entity_id` from the entity registry by unique ID, so HA renames show; fall back to the default ID).
  - `haanim/entities/remove {automation_id, key}` → `{}`; error codes `not_found`, `declared` (message `delete the class first`).
  - `haanim/entities/purge {automation_id, key}` → `{}`; errors `not_found`, `leftover` (purge is for declared entities only).
  - `haanim/automations/get` result gains `"entity_count": int`.
  - `haanim/entities/subscribe {automation_id}` — the panel needs live updates; sends the list on every sink change for that automation (sink gains listener registration).

- [ ] **Step 1: Write failing tests** — list shape; remove leftover then gone from registry and list; remove declared → error `declared`; purge resets state in HA; purge unknown → `not_found`; `entity_count`; subscribe receives an update after `set_state`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_websocket.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "WebSocket commands to list, remove and purge entities"`

### Task 9: Panel Entities tab

**Files:**
- Modify: `custom_components/haanim/ui/haanim-panel.js` (tab `entities` in `DETAIL_TABS`, route `/haanim/automation/<id>/entities`, pane `tab-entities`, subscribe on open/unsubscribe on leave like the log tab, Remove/Purge buttons calling the WebSocket commands; device-page link `/config/devices/device/<device_id>` from the list result; more-info via `hass-more-info` event)
- Modify: `custom_components/haanim/ui/haanim-render.js` (`renderEntities(entities)` pure function: table rows; declared rows → Purge data button + disabled Remove with `title="delete the class first"`; leftover rows → Remove; tab label shows `entity_count`)
- Test: `tests/frontend/render.test.mjs`, `tests/frontend/panel.test.mjs`

- [ ] **Step 1: Write failing tests** — `renderEntities` output for one declared and one leftover entity (buttons, hint, escaping of names); panel opens `entities` tab from the URL, sends `haanim/entities/subscribe`, clicking Remove sends `haanim/entities/remove` with the entity's key.
- [ ] **Step 2: Run** `scripts/test-frontend.sh` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `scripts/test-frontend.sh` — Expected: PASS with the 80% coverage gates.
- [ ] **Step 5: Commit** `git commit -m "Panel: entities tab with remove and purge"`

### Task 10: Docs, example, version

**Files:**
- Modify: `docs/AUTOMATIONS.md` (section "Device entities": decorators table, proxy, hooks, leftovers, Remove/Purge, IDs)
- Create: `examples/demo_entities/main.py`, `metadata.json`, `examples/tests/test_demo_entities.py` (follow existing `examples/tests` style)
- Modify: `tests/engine/test_examples.py` (`NAMES` list), README examples list if it enumerates demos
- Modify: `CHANGELOG.md`, version → 0.4.0 in the files listed in Global Constraints

- [ ] **Step 1:** Add the example test (sensor updated by `@on_interval`, switch with hooks, `h.command("boost", "turn_on")`).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_examples.py examples/tests/test_demo_entities.py -v` — Expected: FAIL until the example exists.
- [ ] **Step 3:** Write the example, docs, changelog, version bump.
- [ ] **Step 4: Run** the full suite `uv run pytest -q` and `scripts/test-frontend.sh` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Version 0.4.0: automations are devices with their own entities"`
