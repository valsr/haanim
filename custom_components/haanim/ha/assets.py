"""Serving the assets of automations over HTTP.

An asset is reachable at ``/api/haanim/assets/<automation_id>/<name>`` by a
logged-in user, or by anyone holding a signed form of that path until it expires.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from aiohttp import web
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from custom_components.haanim.const import DOMAIN
from haanim.engine.assets import ASSET_URL_PREFIX, normalize_asset_name
from haanim.engine.discovery import ASSETS_DIRNAME


class HAAssetSigner:
    """Signs URL paths with Home Assistant's signed-path support."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the signer.

        Args:
            hass: Home Assistant instance.
        """
        self._hass = hass

    def sign(self, path: str, expires: float) -> str:
        """Return the path with a signature that is valid for ``expires`` seconds."""
        return async_sign_path(self._hass, path, timedelta(seconds=expires))


def resolve_asset_file(folder: Path, name: str) -> Path | None:
    """Return the file an asset name stands for, or None if there is none.

    Links are followed, and a file that ends up outside the automation's
    ``assets/`` folder is not an asset.

    Args:
        folder: The automation's folder.
        name: Path of the asset relative to ``assets/``, using ``/``.
    """
    try:
        normalized = normalize_asset_name(name)
    except ValueError:
        return None
    root = (folder / ASSETS_DIRNAME).resolve()
    path = root.joinpath(*normalized.split("/")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


class AssetView(HomeAssistantView):
    """Serves the files in the ``assets/`` folders of the loaded automations."""

    requires_auth = True
    url = ASSET_URL_PREFIX + "/{automation_id}/{name:.+}"
    name = f"api:{DOMAIN}:assets"

    async def get(self, request: web.Request, automation_id: str, name: str) -> web.StreamResponse:
        """Return an asset, or 404 if the automation or the file does not exist."""
        # Imported here: the manager module imports this package.
        from custom_components.haanim.automation_manager import (  # pylint: disable=import-outside-toplevel
            async_get_manager,
        )

        hass: HomeAssistant = request.app["hass"]
        manager = await async_get_manager(hass)
        context = manager.get_context_by_name(automation_id) if manager else None
        if context is None:
            raise web.HTTPNotFound
        path = await hass.async_add_executor_job(resolve_asset_file, context.folder, name)
        if path is None:
            raise web.HTTPNotFound
        return web.FileResponse(path)
