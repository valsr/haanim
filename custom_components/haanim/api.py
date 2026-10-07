"""HTTP views of HAAnim.

The panel and the card talk to HAAnim over the websocket commands and the services; the one thing served
over plain HTTP is the assets of the automations.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from custom_components.haanim.ha.assets import AssetView

_LOGGER = logging.getLogger(__name__)


def async_register_api(hass: HomeAssistant) -> None:
    """Register the HTTP views.

    Args:
        hass: Home Assistant instance.
    """
    hass.http.register_view(AssetView())

    _LOGGER.debug("HAAnim API views registered")
