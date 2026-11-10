"""Tests for declared entities in running automations, and the ``haa.device`` API."""

from __future__ import annotations

from pathlib import Path

import pytest

from haanim.engine.errors import NonExistingEntityError
from haanim.testing import AutomationHarness

MAIN = '''
from haanim import action, haa, sensor_entity, startup, switch_entity

@sensor_entity(unit="°C", initial=20)
class average_temp:
    pass

@switch_entity(name="Boost", icon="mdi:fire")
class boost:
    pass

@startup
def begin(event):
    haa.device.entity(average_temp).set_state(21.5)

@action
def warm(event):
    haa.device.entity("average_temp").set_state(event.data["value"])

@action
def describe(event):
    entity = haa.device.entity("boost")
    return {
        "id": haa.device.id,
        "name": haa.device.name,
        "entities": [e.object_id for e in haa.device.entities],
        "entity_id": entity.entity_id,
        "platform": entity.platform,
        "declared": entity.declared,
        "options": entity.options,
    }

@action
def label(event):
    haa.device.entity("average_temp").set_attributes(where="lounge")
    return haa.device.entity("average_temp").attributes

@action
def missing(event):
    haa.device.entity("nope")
'''


def write(folder: Path, source: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source)
    return folder


async def test_declared_entities_and_proxy(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        assert h.state == "on"
        entity = h.entity("average_temp")
        assert entity.entity_id == "sensor.haanim_climate_average_temp"
        assert entity.state == 21.5
        assert [e.object_id for e in h.entities] == ["average_temp", "boost"]


async def test_device_and_entity_properties(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        described = await h.call("describe")
        assert described == {
            "id": "climate",
            "name": "climate",
            "entities": ["average_temp", "boost"],
            "entity_id": "switch.haanim_climate_boost",
            "platform": "switch",
            "declared": True,
            "options": {},
        }


async def test_set_attributes(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        assert await h.call("label") == {"where": "lounge"}


async def test_unknown_entity_raises(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        with pytest.raises(NonExistingEntityError):
            await h.call("missing")


async def test_set_state_validation_error_reaches_code(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        with pytest.raises(ValueError):
            await h.call("warm", value="hot")
        assert h.entity("average_temp").state == 21.5


async def test_duplicate_object_id_is_a_load_error(tmp_path: Path) -> None:
    source = (
        "from haanim import sensor_entity\n"
        "@sensor_entity\nclass temp:\n    pass\n"
        "@sensor_entity(id='temp')\nclass other:\n    pass\n"
    )
    async with AutomationHarness(write(tmp_path / "climate", source), start=False) as h:
        assert await h.load()
        assert not await h.start()
        assert h.state == "error"
        assert "'temp'" in (h.error or "") and "'other'" in (h.error or "")


async def test_state_survives_restart(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        await h.call("warm", value=30)
        await h.restart()
        # @startup sets 21.5 again; before it, the stored 30 was there
        assert h.entity("average_temp").state == 21.5
        await h.stop()
        assert h.entity("average_temp").state == 21.5


async def test_leftover_after_class_removed(tmp_path: Path) -> None:
    folder = write(tmp_path / "climate", MAIN)
    async with AutomationHarness(folder) as h:
        write(folder, MAIN.replace("@switch_entity", "@sensor_entity"))
        await h.reload()
        boost = h.entity("boost")
        assert boost.platform == "sensor"
        assert [e.declared for e in h.entities if e.object_id == "boost"] == [True, False]


async def test_harness_seeded_entity_state(tmp_path: Path) -> None:
    source = (
        "from haanim import haa, startup, switch_entity\n"
        "@switch_entity\nclass boost:\n    pass\n"
        "@startup\ndef begin(event):\n    haa.set_variable('seen', haa.device.entity('boost').state)\n"
    )
    async with AutomationHarness(write(tmp_path / "climate", source), entities={"boost": True}) as h:
        assert h.variables["seen"] is True


async def test_entities_exist_while_stopped(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path / "climate", MAIN)) as h:
        await h.stop()
        assert h.entity("boost").declared
        with pytest.raises(NonExistingEntityError):
            h.entity("nope")
