# Entity Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automations import hourly long-term statistics into their declared entities (usage → running sums, later rows shifted) and query the statistics of any entity.

**Architecture:** The engine validates rows and computes sums in `src/haanim/engine/statistics.py` and reaches Home Assistant only through a new optional `Host.statistics: StatisticsProvider`. The integration implements it with the recorder in `custom_components/haanim/ha/statistics.py`; the testing kit has an in-memory `FakeStatistics`.

**Tech Stack:** Python 3.14, Home Assistant recorder statistics API, pytest + `recorder_mock`.

**Spec:** `docs/superpowers/specs/2026-11-10-entity-statistics-design.md`

## Global Constraints

- Import only into the automation's own declared sensor entities with a `state_class`; query any entity.
- `measurement` → mean/min/max rows; `total`, `total_increasing` → `usage` in, `state`/`sum` stored.
- Import rows: whole hours that have ended; the hour check is on the UTC time (`minute == second == microsecond == 0`); a naive `start` (datetime or ISO text) is in the time zone of `clock.now()`.
- Repeated hours: the last row wins.
- Periods: `5minute`, `hour`, `day`, `week`, `month`.
- New public errors: `StatisticsUnavailableError` (no provider), `StatisticsError` (provider failure); both subclass `HAAnimError` and are in `PUBLIC_ERRORS`.
- Engine never imports `homeassistant`; no real time in the engine or its tests.

## Review Focus

1. **Backfilling hours that already have live rows, with live rows after them:** later sums shift by `new_end − old_end`, no spike or negative hour. Test in Task 1 (fake) and Task 3 (real recorder).
2. **The last stored row before the import is far older (weeks):** `base` still comes from it, not 0. Test in Task 1.
3. **A time zone with a half-hour offset (Asia/Kolkata):** `00:00` local is not the start of a UTC hour and is refused; `00:30` local is accepted. Test in Task 1.
4. **A naive `start`:** read in the clock's time zone, not UTC. Test in Task 1.
5. **Querying an entity that has no statistics or does not exist:** `[]`, not an error. Test in Task 2 (fake) and Task 3 (real).

---

### Task 1: Engine statistics core and the provider interface

**Files:**
- Create: `src/haanim/engine/statistics.py`
- Modify: `src/haanim/interfaces.py` (protocol, `Host.statistics: StatisticsProvider | None = None`)
- Modify: `src/haanim/engine/errors.py` (two errors, added to `PUBLIC_ERRORS`)
- Modify: `src/haanim/testing/fakes.py` (`FakeStatistics`; `make_host(statistics=...)`), `src/haanim/testing/__init__.py`
- Test: `tests/engine/test_statistics.py`

**Interfaces:**
- Produces:
  - `PERIODS = ("5minute", "hour", "day", "week", "month")`; `EPOCH = datetime(1970, 1, 1, tzinfo=UTC)`.
  - `StatisticsProvider` protocol:
    `async query(statistic_id: str, start: datetime, end: datetime, period: str, types: set[str]) -> list[dict[str, Any]]` (rows oldest first, `start`/`end` aware datetimes, only the asked types that exist);
    `async import_rows(metadata: StatisticsMetadata, rows: list[dict[str, Any]]) -> None`;
    `async adjust_sums(statistic_id: str, start: datetime, delta: float, unit: str | None) -> None`;
    `entity_statistic_id(platform: str, unique_id: str, default: str) -> str` (the entity's current entity ID, so a rename in Home Assistant is followed; `default` when the host cannot tell).
  - `@dataclass(frozen=True) StatisticsMetadata(statistic_id: str, name: str | None, unit: str | None, has_sum: bool)` (`has_sum=False` means an arithmetic mean).
  - `parse_rows(rows: list[dict], *, has_sum: bool, now: datetime) -> list[dict]` — validates per spec §1 and returns rows sorted by `start` (UTC), one per hour (last wins), measurement rows with `min`/`max` filled, sum rows as `{"start", "usage"}`. Raises `ValueError`; `total_increasing` negativity is checked by the caller-supplied flag `allow_negative: bool = True`.
  - `async import_statistics(provider: StatisticsProvider | None, metadata: StatisticsMetadata, rows: list[dict], *, total_increasing: bool, now: datetime) -> int` — the spec §2 algorithm; raises `StatisticsUnavailableError` when `provider is None`; wraps provider exceptions other than `ValueError` in `StatisticsError(str(err))`.
  - `async query_statistics(provider: StatisticsProvider | None, statistic_id: str, start: Any, end: Any, period: str, now: datetime) -> list[dict]` — parses `start`/`end` like rows, checks `period in PERIODS` and `start <= end`, asks for `{"mean", "min", "max", "state", "sum", "change"}`.
  - `FakeStatistics`: `rows: dict[str, list[dict]]` (hourly, by statistic ID; seedable), `metadata: dict[str, StatisticsMetadata]`, `entity_statistic_id(...) -> default`; `query` returns hourly rows for `hour` and aggregates them into day/week (weeks start Monday)/month in the time zone of `start` (`5minute` returns `[]`); for sums, a period's `sum`/`state` are those of its last hour and `change` = that `sum` − the last `sum` before the period (0 if none); means are averaged, `min`/`max` taken over the hours; `adjust_sums` adds `delta` to `sum` and `state` of rows with `start >= start`.

- [ ] **Step 1: Write the failing tests** (in `tests/engine/test_statistics.py`, with `FakeStatistics` and `now = datetime(2026, 11, 10, 12, tzinfo=UTC)`):

```python
H = lambda h, d=1: datetime(2026, 11, d, h, tzinfo=UTC)
SUM = StatisticsMetadata("sensor.energy", "energy", "kWh", has_sum=True)

async def test_sums_start_from_zero_without_history(fake):
    assert await import_statistics(fake, SUM, [{"start": H(0), "usage": 1.5}, {"start": H(1), "usage": 2}], total_increasing=True, now=NOW) == 2
    assert [(r["sum"], r["state"]) for r in fake.rows["sensor.energy"]] == [(1.5, 1.5), (3.5, 3.5)]

async def test_sums_continue_from_far_older_history(fake):        # Review Focus 2
    fake.rows["sensor.energy"] = [{"start": H(5, d=1) - timedelta(days=30), "state": 100.0, "sum": 100.0}]
    await import_statistics(fake, SUM, [{"start": H(0), "usage": 1}], total_increasing=True, now=NOW)
    assert fake.rows["sensor.energy"][-1]["sum"] == 101.0

async def test_later_rows_are_shifted(fake):                       # Review Focus 1
    fake.rows["sensor.energy"] = [row(H(0), 10), row(H(1), 11), row(H(2), 12), row(H(3), 13)]
    await import_statistics(fake, SUM, [{"start": H(1), "usage": 5}, {"start": H(2), "usage": 5}], total_increasing=True, now=NOW)
    assert [r["sum"] for r in fake.rows["sensor.energy"]] == [10, 15, 20, 21]

async def test_gap_counts_as_no_usage(fake): ...                   # H(0) usage 1, H(3) usage 1 → sums 1, 2
async def test_last_row_wins(fake): ...                            # two rows for H(0): usage 1 then 4 → sum 4
async def test_measurement_rows_default_min_max(fake): ...         # mean 3 → min 3, max 3, no sum
@pytest.mark.parametrize("rows, message", [
    ([], "no rows"),
    ([{"start": H(0, d=1).replace(minute=30), "usage": 1}], "start of an hour"),
    ([{"start": NOW, "usage": 1}], "ended"),                       # the current hour has not ended
    ([{"start": H(0), "mean": 1}], "usage"),
    ([{"start": H(0), "usage": float("nan")}], "finite"),
    ([{"start": H(0), "usage": -1}], "negative"),
])
async def test_invalid_rows(fake, rows, message): ...              # ValueError matching; fake.rows untouched
async def test_measurement_min_above_mean_refused(fake): ...
async def test_naive_start_is_in_clock_time_zone(fake):            # Review Focus 4
    now = datetime(2026, 11, 10, 12, tzinfo=ZoneInfo("America/Toronto"))
    await import_statistics(fake, SUM, [{"start": "2026-11-01T00:00:00", "usage": 1}], total_increasing=True, now=now)
    assert fake.rows["sensor.energy"][0]["start"] == datetime(2026, 11, 1, 4, tzinfo=UTC)
async def test_half_hour_time_zone(fake): ...                      # Review Focus 3, Asia/Kolkata
async def test_no_provider():                                      # StatisticsUnavailableError
async def test_provider_failure_is_statistics_error(): ...         # provider raising RuntimeError → StatisticsError
async def test_query_day_period_and_change(fake): ...              # 48 seeded hours → 2 day rows, change = usage per day
async def test_query_unknown_period_and_reversed_range(fake): ...  # ValueError
async def test_query_without_statistics_is_empty(fake): ...        # []
```

- [ ] **Step 2: Run** `uv run pytest tests/engine/test_statistics.py -q --no-cov -n 0` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** per Interfaces. `import_statistics` for sums: `history = await provider.query(id, EPOCH, last_hour + 1h, "hour", {"sum"})`; `base` = last row with `start < first_hour`, `old_end` = last row with `start <= last_hour`, both falling back as the spec says; import; then `adjust_sums(id, last_hour + 1h, new_end − old_end, unit)` only when the delta is not 0.
- [ ] **Step 4: Run** the tests, then `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS (public API tests list the two errors).
- [ ] **Step 5: Commit** `git commit -m "Statistics: row validation, usage to sums, provider interface"`

### Task 2: The automation API and the testing kit

**Files:**
- Modify: `src/haanim/engine/device_api.py` (`DeviceEntity.import_statistics`, `DeviceEntity.statistics`; the device needs the provider and the clock)
- Modify: `src/haanim/engine/haanim_api.py` (`HAAnim.statistics(entity_id, start, end=None, period="hour")`, passes `host.statistics` and `host.clock` into `HAAnimDevice`)
- Modify: `src/haanim/testing/harness.py` (constructor `statistics: dict[str, list[dict]] | None`, seeds a `FakeStatistics` given to `make_host`; `statistics(statistic_id) -> list[dict]` returns the stored hourly rows)
- Test: `tests/engine/test_statistics_api.py` (harness-driven)

**Interfaces:**
- Consumes: Task 1 (`import_statistics`, `query_statistics`, `StatisticsMetadata`, `FakeStatistics`).
- Produces: `async DeviceEntity.import_statistics(rows: list[dict]) -> int` — checks platform `sensor`, `declared`, `state_class` set (else `ValueError`), builds `StatisticsMetadata(provider.entity_statistic_id("sensor", unique_id, entity_id), name, unit, has_sum=state_class != "measurement")`, `total_increasing = state_class == "total_increasing"`; `async DeviceEntity.statistics(start, end=None, period="hour") -> list[dict]`; `async HAAnim.statistics(entity_id: str, start, end=None, period="hour") -> list[dict]`. `HAAnimDevice(store, name, statistics=None, clock=None)`.

- [ ] **Step 1: Write the failing tests** — automation with `@sensor_entity(unit="kWh", state_class="total_increasing") class energy` and `@sensor_entity(unit="°C", state_class="measurement") class outside`, `@sensor_entity class plain`, actions calling the API:
  `test_backfill_and_read_back` (import 3 hours, `h.statistics("sensor.haanim_demo_energy")` sums `[1, 2, 3]`, `await entity.statistics(start, period="day")` one row with `change == 3`);
  `test_measurement_import`; `test_entity_without_state_class_refused` (`ValueError` reaches the action); `test_leftover_refused`;
  `test_query_any_entity` (seed `statistics={"sensor.grid": [...]}`, `haa.statistics("sensor.grid", ...)`);
  `test_query_unknown_entity_is_empty` (Review Focus 5); `test_without_provider` (`AutomationHarness(..., statistics=False)` leaves the provider out → `StatisticsUnavailableError` reaches the action).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_statistics_api.py -q --no-cov -n 0` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; `statistics: dict | bool | None = None` in the harness (`False` = no provider).
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Statistics: haa.statistics, entity import and query, harness support"`

### Task 3: Home Assistant provider

**Files:**
- Create: `custom_components/haanim/ha/statistics.py` (`HAStatistics`)
- Modify: `custom_components/haanim/ha/host.py` (`build_host(..., statistics=HAStatistics(hass) if "recorder" in hass.config.components else None)`)
- Modify: `custom_components/haanim/manifest.json` only if `after_dependencies` needs `"recorder"` (add it, so the recorder is set up first when present)
- Test: `tests/integration/test_statistics.py`

**Interfaces:**
- Consumes: `StatisticsProvider`, `StatisticsMetadata` (Task 1).
- Produces: `HAStatistics(hass)`:
  - `query` → `get_instance(hass).async_add_executor_job(statistics_during_period, hass, start, end, {id}, period, None, types)`; convert the `start`/`end` floats (timestamps) to aware UTC datetimes; drop `None` fields and `last_reset`.
  - `import_rows` → `async_import_statistics(hass, StatisticMetaData(mean_type=NONE if has_sum else ARITHMETIC, has_sum=..., name=..., source="recorder", statistic_id=..., unit_class=(STATISTIC_UNIT_TO_UNIT_CONVERTER[unit].UNIT_CLASS if unit in it else None), unit_of_measurement=unit), rows)`, then `await get_instance(hass).async_block_till_done()`.
  - `adjust_sums` → `get_instance(hass).async_adjust_statistics(id, start, delta, unit)`, then `async_block_till_done()`.
  - `entity_statistic_id(platform, unique_id, default)` → `er.async_get(hass).async_get_entity_id(platform, "haanim", unique_id) or default`.

- [ ] **Step 1: Write the failing tests** (`recorder_mock` fixture before the integration setup; reuse `setup`/`write` from `tests/integration/test_device_entities.py`):
  `test_import_and_query_sums` (import 3 hours, `statistics_during_period` shows sums 1, 2, 3; `haa.statistics(..., period="day")` via an action gives `change == 3`);
  `test_later_live_rows_are_shifted` (seed hours 0–3 with `async_import_statistics` sums 10–13, import usage 5 for hours 1–2, stored sums `[10, 15, 20, 21]`) — Review Focus 1 against the real recorder;
  `test_measurement_import`; `test_renamed_entity_uses_its_new_id`; `test_query_unknown_entity_is_empty`;
  `test_without_recorder_no_provider` (no `recorder_mock`: `build_host(...).statistics is None`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_statistics.py -q --no-cov -n 0` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/integration -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Statistics: Home Assistant recorder provider"`

### Task 4: Docs, example, changelog

**Files:**
- Modify: `docs/AUTOMATIONS.md` ("Statistics" under "Device entities"; harness table row `statistics=`, `statistics(id)`)
- Modify: `examples/demo_entities/main.py` (`@sensor_entity(name="Energy", unit="kWh", device_class="energy", state_class="total_increasing") class energy`; `@action backfill` importing 24 hours of a fixed profile ending at the last full hour), `examples/tests/test_demo_entities.py` (`test_backfill`), `tests/engine/test_examples.py` if counts change
- Modify: `scripts/e2e-smoke.py` (call `haanim.run_action` `demo_entities.backfill`, then `recorder/statistics_during_period` over the websocket shows 24 hourly rows for `sensor.haanim_demo_entities_energy`)
- Modify: `CHANGELOG.md` (0.4.0 Added: statistics)

- [ ] **Step 1:** Add `test_backfill` to `examples/tests/test_demo_entities.py` (24 rows, last sum equals the profile total) and the doc examples.
- [ ] **Step 2: Run** `uv run pytest examples/tests/test_demo_entities.py tests/engine/test_docs.py -q --no-cov -n 0` — Expected: FAIL.
- [ ] **Step 3:** Write the example, docs, smoke check, changelog.
- [ ] **Step 4: Run** `uv run pytest -q -n auto` and `scripts/test-frontend.sh`; restart the container (`./stop.sh; ./clean.sh; ./start.sh`) and run `uv run python scripts/e2e-smoke.py` — Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "Statistics: docs, example and smoke test"`
