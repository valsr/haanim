# HAAnim Example Scripts

This folder contains example Python automation scripts for HAAnim.

## How to Use

1. Copy the desired example script(s) to your HAAnim scripts folder (default: `config/haanim/`)
2. Modify the entity IDs to match your Home Assistant setup
3. The scripts will be automatically loaded when Home Assistant starts or when you reload scripts

## Available Examples

### `basic_automation.py`
Simple examples demonstrating:
- `@scene` decorator for manual scenes
- `@scene("Name")` for custom display names
- `@state_trigger` for state-based automation
- Basic Home Assistant service calls

### `time_scenes.py`
Time-based automation examples showing:
- `@scene` decorator for scenes
- `@time_trigger` for scheduled automation
- `@time_active` for time constraints
- `@state_active` for state-based constraints
- Combined triggers and constraints

### `event_triggers.py`
Event-based automation examples featuring:
- `@event_trigger` for Home Assistant events
- Handling ZHA (Zigbee) button events
- Mobile app notification actions
- Complex event data processing

## Available Decorators

| Decorator | Purpose |
|-----------|---------|
| `@scene` | Mark function as a manually-triggerable scene |
| `@scene("Display Name")` | Scene with custom display name for UI |
| `@state_trigger("entity.id", new="state")` | Trigger on entity state change |
| `@time_trigger("HH:MM")` | Trigger at specific time |
| `@event_trigger("event_type")` | Trigger on Home Assistant event |
| `@time_active("mon,tue,wed")` | Only run during specified days/times |
| `@state_active("entity.id", "state")` | Only run when entity is in state |

## Available Globals

These variables are automatically available in your scripts:

| Variable | Type | Description |
|----------|------|-------------|
| `hass` | object | Home Assistant interface for service calls |
| `state` | StateManager | Access entity states |
| `log` | Logger | Logging functions (info, warning, error, debug) |

## Service Calls

```python
# Basic service call
hass.call_service("domain", "service", entity_id="entity.id")

# With additional parameters
hass.call_service(
    "light",
    "turn_on",
    entity_id="light.living_room",
    brightness=255,
    color_temp_kelvin=3000,
)
```

## State Access

```python
# Get entity state
light_state = state.get("light.living_room")

# Access state value
if light_state.state == "on":
    pass

# Access attributes
brightness = light_state.attributes.get("brightness")
```

## Logging

```python
log.debug("Debug message")
log.info("Info message")
log.warning("Warning message")
log.error("Error message")
```

## Tips

1. **Start Simple**: Begin with basic `@scene` functions to test your setup
2. **Test Manually**: Use the HAAnim panel to test scenes before adding triggers
3. **Check Logs**: Monitor Home Assistant logs for script errors
4. **Use Names**: Add `@scene("Name")` to make scenes easier to identify in the UI
5. **Combine Constraints**: Use `@time_active` and `@state_active` to prevent
   unwanted trigger execution
