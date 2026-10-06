"""Tests for the api.py module."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.haanim.api import async_register_api
from custom_components.haanim.ha.assets import AssetView


class TestAsyncRegisterAPI:
    """Tests for async_register_api function."""

    def test_registers_the_asset_view(self) -> None:
        """Test the assets are the only thing served over plain HTTP."""
        hass = MagicMock()
        hass.http.register_view = MagicMock()

        async_register_api(hass)

        (call,) = hass.http.register_view.call_args_list
        assert isinstance(call.args[0], AssetView)
