"""Tests for the Home Assistant host implementations (ha/host.py).

Behaviour shared with the fakes is covered by ``tests/integration/test_contracts.py``;
these tests cover what is specific to Home Assistant.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.ha.host import (
    HAClock,
    HAFileSystem,
    HAServiceCaller,
    HASunProvider,
    build_host,
)
from custom_components.haanim.ha.state import StateManager
from haanim.interfaces import Host


async def _noop(call: ServiceCall) -> None:  # noqa: ARG001  pylint: disable=unused-argument
    """Service handler that does nothing."""


class TestServiceDescriptions:
    """Tests for the description cache of HAServiceCaller."""

    def test_no_descriptions_before_refresh(self, hass: HomeAssistant) -> None:
        """Test services are listed with empty metadata until descriptions are loaded."""
        hass.services.async_register("contract", "do", _noop)
        caller = HAServiceCaller(hass)
        (info,) = [info for info in caller.services() if info.domain == "contract"]
        assert (info.name, info.description, info.fields) == ("do", "", {})

    async def test_refresh_loads_descriptions(self, hass: HomeAssistant) -> None:
        """Test a refresh fills in descriptions and fields."""
        hass.services.async_register("contract", "do", _noop)
        caller = HAServiceCaller(hass)
        descriptions: dict[str, dict[str, Any]] = {
            "contract": {"do": {"description": "Does it", "fields": {"level": {"required": True}}}}
        }
        with patch(
            "custom_components.haanim.ha.host.async_get_all_descriptions", return_value=descriptions
        ) as mock_get:
            await caller.async_refresh_descriptions()

        mock_get.assert_called_once_with(hass)
        (info,) = [info for info in caller.services() if info.domain == "contract"]
        assert info.description == "Does it"
        assert info.fields == {"level": {"required": True}}

    async def test_service_registered_after_refresh(self, hass: HomeAssistant) -> None:
        """Test a service registered after the refresh is listed with empty metadata."""
        caller = HAServiceCaller(hass)
        with patch("custom_components.haanim.ha.host.async_get_all_descriptions", return_value={}):
            await caller.async_refresh_descriptions()
        hass.services.async_register("contract", "late", _noop)
        (info,) = [info for info in caller.services() if info.domain == "contract"]
        assert (info.name, info.description, info.fields) == ("late", "", {})

    async def test_description_entry_without_text(self, hass: HomeAssistant) -> None:
        """Test a description entry that is None or lacks keys gives empty metadata."""
        hass.services.async_register("contract", "do", _noop)
        hass.services.async_register("contract", "other", _noop)
        caller = HAServiceCaller(hass)
        with patch(
            "custom_components.haanim.ha.host.async_get_all_descriptions",
            return_value={"contract": {"do": None, "other": {"description": None, "fields": None}}},
        ):
            await caller.async_refresh_descriptions()
        infos = {info.name: info for info in caller.services() if info.domain == "contract"}
        assert (infos["do"].description, infos["do"].fields) == ("", {})
        assert (infos["other"].description, infos["other"].fields) == ("", {})


class TestBuildHost:
    """Tests for build_host."""

    def test_bundles_home_assistant_implementations(self, hass: HomeAssistant) -> None:
        """Test the host uses the given managers and Home Assistant implementations for the rest."""
        state_manager = StateManager(hass)
        event_manager = EventManager(hass)

        host = build_host(hass, state_manager, event_manager)

        assert isinstance(host, Host)
        assert host.states is state_manager
        assert host.events is event_manager
        assert isinstance(host.services, HAServiceCaller)
        assert isinstance(host.clock, HAClock)
        assert isinstance(host.sun, HASunProvider)
        assert isinstance(host.files, HAFileSystem)
