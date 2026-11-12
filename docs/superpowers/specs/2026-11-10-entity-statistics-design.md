# Long-term statistics for declared entities

Date: 2026-11-10
Status: approved design, awaiting implementation plan
Builds on: `2026-11-09-automation-devices-design.md`

## Goal

An automation imports long-term statistics into the entities it declares, for instance to backfill
past meter readings so the Energy dashboard and statistics graphs show history the entity never had
live, and queries the long-term statistics of any entity to compute on them.

## Decisions

| Topic | Decision |
| --- | --- |
| Import | Into the automation's own declared entities only |
| Query | Any entity |
| External statistics (`haanim:<name>`) | Out of scope |
| Statistic kind | From the declaration's `state_class`: `measurement` → mean/min/max; `total`, `total_increasing` → sums |
| Sum import | Usage per hour; HAAnim computes the running sums and shifts later rows |
| Granularity of import | Whole hours that ended at least 15 minutes ago (Home Assistant compiles each hour just after it ends; importing first makes it roll back that compile) |
| Repeated hours in one import | The last row wins |
| Reaching Home Assistant | A new optional host interface, not service calls |

## 1. The automation API

### Import

```python
energy = haa.device.entity("energy")        # @sensor_entity(unit="kWh", state_class="total_increasing")
await energy.import_statistics([
    {"start": "2026-11-01T00:00:00-05:00", "usage": 0.42},
    {"start": "2026-11-01T01:00:00-05:00", "usage": 0.31},
])

temp = haa.device.entity("outside")         # @sensor_entity(unit="°C", state_class="measurement")
await temp.import_statistics([
    {"start": "2026-11-01T00:00:00-05:00", "mean": 3.2, "min": 2.9, "max": 3.6},
])
```

`DeviceEntity.import_statistics(rows) -> int` returns the number of hours written (for sums, every hour from the first to the last row).

| Field | Entities | Meaning |
| --- | --- | --- |
| `start` | all | `datetime` or ISO text; the start of an hour that has ended; a naive time is in Home Assistant's time zone |
| `usage` | `total`, `total_increasing` | What was used within the hour (required) |
| `mean` | `measurement` | Mean over the hour (required) |
| `min`, `max` | `measurement` | Default to `mean` |

Values are in the entity's declared `unit`. Rows need not be in order and may leave gaps; a gap in sum
statistics counts as no usage. When two rows name the same hour, the last one wins.

`ValueError` is raised, and nothing is imported, for:

- an entity without a `state_class`, a leftover entity, or a non-sensor entity;
- a `start` that is not the start of an hour, or an hour that did not end at least 15 minutes ago;
- for sums, an entity Home Assistant does not record live yet (no 5-minute statistics after the range): its own sum would restart at zero after the import;
- a missing required field, or a field of the other kind (`usage` for a measurement, `mean` for a sum);
- a negative `usage` for `total_increasing`;
- a number that is not finite, or `min > mean` or `mean > max`;
- no rows.

### Query

```python
rows = await haa.statistics("sensor.grid_energy", start=haa.now() - timedelta(days=7), period="day")
rows = await energy.statistics(start=..., end=..., period="hour")
```

`haa.statistics(entity_id, start, end=None, period="hour") -> list[dict]` and
`DeviceEntity.statistics(start, end=None, period="hour")`, which queries the entity's own ID.

- `period`: `5minute`, `hour`, `day`, `week` or `month`; `end` defaults to now.
- Each row is a dictionary with `start` and `end` (`datetime`) and the fields the statistic has: `mean`,
  `min`, `max` for a measurement; `state`, `sum` and `change` (usage within the period) for a sum.
- An entity without statistics gives an empty list.
- `start` after `end`, or an unknown period, raises `ValueError`.

## 2. Architecture

```
haa.statistics(...) / entity.statistics(...)  ─┐
entity.import_statistics(rows)                 ├─► StatisticsProvider (Host protocol, optional)
                                               │      ├─ FakeStatistics (testing kit, in memory)
engine: validation, usage → sums (pure code)  ─┘      └─ HAStatistics (custom_components/haanim/ha/statistics.py)
```

### The host interface

`Host.statistics: StatisticsProvider | None`, with:

| Method | Does |
| --- | --- |
| `async query(statistic_id, start, end, period, types) -> list[dict]` | Rows of a period, oldest first |
| `async import_rows(metadata, rows) -> None` | Writes hourly rows, replacing rows of the same hours; returns once written |
| `async adjust_sums(statistic_id, start, delta, unit) -> None` | Adds `delta` to every sum from `start` on, in hourly and 5-minute rows; returns once written |
| `entity_statistic_id(platform, unique_id, default) -> str` | The statistic ID of an entity: its current entity ID, `default` if unknown |

Without a provider, the statistics calls raise `StatisticsUnavailableError`, a new public error.

### Importing sums

The engine turns usage into sums, so the logic is tested without Home Assistant:

1. Sort the rows by hour; a later row for the same hour replaces an earlier one.
2. `base` = the last stored sum before the first imported hour, or 0.
3. `old_end` = the stored sum at the last imported hour before the import; if that hour has no row, the
   last stored sum before it; or `base`.
4. Every hour from the first to the last imported one gets `sum` = `base` + the usage of every imported
   hour up to and including it (a missing hour has no usage), and `state` = `sum`.
5. Import the rows, then adjust every stored sum after the last imported hour by
   `new_end − old_end`, so later history (and what Home Assistant records live) still joins up.

Measurement rows are imported as given, with `min` and `max` defaulting to `mean`.

The stored sums are read in the declared unit; statistics Home Assistant keeps in another unit (a
display unit the owner chose) get the rows converted to that unit.

### Metadata

From the declaration: `statistic_id` = the entity's statistic ID (a rename by the user is followed),
`source` = `recorder`, a sum for `total` and `total_increasing` or a mean for `measurement`, the
declared `unit`, and the entity's name.

### The Home Assistant side

`HAStatistics` uses the recorder: `statistics_during_period` for queries and the stored sums, run on
the recorder's executor; `async_import_statistics` and `Recorder.async_adjust_statistics`, then
`async_block_till_done` on the recorder, so an import is written before it returns. Without the
recorder the host has no provider.

## 3. Errors

| Situation | Result |
| --- | --- |
| Invalid rows or entity | `ValueError` in the calling code; nothing imported |
| No statistics provider (no recorder) | `StatisticsUnavailableError` |
| The recorder fails | `StatisticsError` with Home Assistant's message |

All are raised in the calling action and recorded like any action failure when not caught.

## 4. Testing

- **Engine:** each validation rule; repeated hours; the sum computation with no history, history before,
  history after (shifted), and gaps; measurement rows; queries and their arguments.
- **Testing kit:** `FakeStatistics` keeps hourly rows in memory and derives 5-minute (none), day, week
  and month periods; the harness takes `statistics={"sensor.x": [rows]}` and offers
  `h.statistics("sensor.x")` to read the stored rows.
- **Integration:** against Home Assistant's recorder (in-memory SQLite in the tests): import into a sum
  and a measurement entity, query hour and day periods, and the shift of a stored row after the range.
- **Docs and example:** a "Statistics" part of "Device entities" in `docs/AUTOMATIONS.md`; `demo_entities`
  gains an energy sensor and a backfill action.
