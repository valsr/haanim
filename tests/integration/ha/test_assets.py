"""Tests for serving assets over HTTP: the view and signed paths.

See "Assets" in the design.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.haanim.ha.assets import AssetView, HAAssetSigner, resolve_asset_file
from custom_components.haanim.ha.host import HAFileSystem
from haanim.engine.assets import AssetStore

PNG = b"\x89PNG\r\n\x1a\n\x00\xff"


class Manager:
    """Stands in for the automation manager: it knows the folders of the automations."""

    def __init__(self, folders: dict[str, Path]) -> None:
        self._folders = folders

    def get_context_by_name(self, automation_id: str) -> Any:
        """Return something with the automation's folder, or None."""
        folder = self._folders.get(automation_id)
        return None if folder is None else SimpleNamespace(folder=folder)


@pytest.fixture
def folders(tmp_path: Path) -> dict[str, Path]:
    """Two automations on disk, each with assets."""
    lights = tmp_path / "lights"
    (lights / "assets/icons").mkdir(parents=True)
    (lights / "main.py").write_text("secret = 1", encoding="utf-8")
    (lights / "assets/phrases.json").write_text('["hi"]', encoding="utf-8")
    (lights / "assets/icons/bell.png").write_bytes(PNG)
    (lights / "assets/my file.txt").write_text("spaced", encoding="utf-8")
    other = tmp_path / "other"
    (other / "assets").mkdir(parents=True)
    (other / "assets/private.txt").write_text("theirs", encoding="utf-8")
    return {"lights": lights, "other": other}


@pytest.fixture
async def served(hass: HomeAssistant, folders: dict[str, Path]) -> Any:
    """Home Assistant's HTTP server with the asset view registered."""
    assert await async_setup_component(hass, "http", {})
    hass.http.register_view(AssetView())
    with patch(
        "custom_components.haanim.automation_manager.async_get_manager",
        return_value=Manager(folders),
    ):
        yield


@pytest.mark.usefixtures("served")
class TestView:
    """Rule: assets are served under /api/haanim/assets/<automation_id>/ to a logged-in session."""

    async def test_returns_the_file(self, hass_client: Any) -> None:
        """Test a logged-in client gets the file with its content type."""
        client = await hass_client()
        response = await client.get("/api/haanim/assets/lights/icons/bell.png")
        assert response.status == 200
        assert await response.read() == PNG
        assert response.content_type == "image/png"

    async def test_text_file_and_quoted_name(self, hass_client: Any) -> None:
        """Test a name with a space is found through its quoted URL."""
        client = await hass_client()
        assert await (await client.get("/api/haanim/assets/lights/phrases.json")).text() == '["hi"]'
        assert await (await client.get("/api/haanim/assets/lights/my%20file.txt")).text() == "spaced"

    async def test_each_automation_has_its_own(self, hass_client: Any) -> None:
        """Test an asset is only found under the automation that owns it."""
        client = await hass_client()
        assert (await client.get("/api/haanim/assets/other/private.txt")).status == 200
        assert (await client.get("/api/haanim/assets/lights/private.txt")).status == 404

    @pytest.mark.parametrize(
        "path",
        [
            "lights/missing.png",
            "lights/icons",
            "unknown/phrases.json",
            "lights/%2e%2e/main.py",
            "lights/icons/%2e%2e/%2e%2e/main.py",
            "lights/..%5Cmain.py",
        ],
    )
    async def test_not_found(self, hass_client: Any, path: str) -> None:
        """Test a missing file, a folder, an unknown automation and a way out of assets/ give 404."""
        client = await hass_client()
        response = await client.get(f"/api/haanim/assets/{path}")
        assert response.status == 404

    async def test_filtered_by_home_assistant(self, hass_client: Any) -> None:
        """Test a path Home Assistant itself takes for an attack never reaches a file."""
        client = await hass_client()
        response = await client.get("/api/haanim/assets/lights/%2e%2e%2f%2e%2e%2fother/assets/private.txt")
        assert response.status == 400

    async def test_unauthorized(self, hass_client_no_auth: Any) -> None:
        """Test a client that is not logged in gets 401, for a missing file too."""
        client = await hass_client_no_auth()
        assert (await client.get("/api/haanim/assets/lights/phrases.json")).status == 401
        assert (await client.get("/api/haanim/assets/lights/missing.png")).status == 401

    async def test_read_only(self, hass_client: Any, folders: dict[str, Path]) -> None:
        """Test an asset cannot be written through the view."""
        client = await hass_client()
        assert (await client.put("/api/haanim/assets/lights/phrases.json", data=b"x")).status == 405
        assert (await client.delete("/api/haanim/assets/lights/phrases.json")).status == 405
        assert (folders["lights"] / "assets/phrases.json").read_text(encoding="utf-8") == '["hi"]'


@pytest.mark.usefixtures("served")
class TestSignedUrl:
    """Rule: with expires the URL works without login until it expires."""

    @pytest.fixture
    def store(self, hass: HomeAssistant, folders: dict[str, Path]) -> AssetStore:
        """The assets of the lights automation on the real host parts."""
        return AssetStore("lights", folders["lights"], HAFileSystem(hass), HAAssetSigner(hass))

    async def test_works_without_login(self, store: AssetStore, hass_client_no_auth: Any) -> None:
        """Test a signed URL gives the file to a client that is not logged in."""
        url = store.url("icons/bell.png", expires=300)
        assert url.startswith("/api/haanim/assets/lights/icons/bell.png?authSig=")
        client = await hass_client_no_auth()
        response = await client.get(url)
        assert response.status == 200
        assert await response.read() == PNG

    async def test_expires(
        self, store: AssetStore, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
    ) -> None:
        """Test a signed URL works until its time is over and not after."""
        url = store.url("phrases.json", expires=300)
        client = await hass_client_no_auth()
        freezer.tick(timedelta(seconds=290))
        assert (await client.get(url)).status == 200
        freezer.tick(timedelta(seconds=20))
        assert (await client.get(url)).status == 401

    async def test_signature_is_for_one_file(self, store: AssetStore, hass_client_no_auth: Any) -> None:
        """Test the signature of one asset does not open another."""
        signature = store.url("phrases.json", expires=300).split("?", 1)[1]
        client = await hass_client_no_auth()
        assert (await client.get(f"/api/haanim/assets/lights/icons/bell.png?{signature}")).status == 401
        assert (await client.get(f"/api/haanim/assets/other/private.txt?{signature}")).status == 401

    async def test_unsigned_url_needs_login(self, store: AssetStore, hass_client_no_auth: Any) -> None:
        """Test the URL without expires is the plain path, which needs a session."""
        url = store.url("phrases.json")
        assert url == "/api/haanim/assets/lights/phrases.json"
        client = await hass_client_no_auth()
        assert (await client.get(url)).status == 401

    async def test_quoted_name(self, store: AssetStore, hass_client_no_auth: Any) -> None:
        """Test a signed URL of a name that needs quoting works."""
        client = await hass_client_no_auth()
        response = await client.get(store.url("my file.txt", expires=60))
        assert response.status == 200
        assert await response.text() == "spaced"


class TestResolve:
    """Which file an asset name stands for on disk."""

    def test_file(self, folders: dict[str, Path]) -> None:
        """Test an existing asset is found."""
        found = resolve_asset_file(folders["lights"], "icons/bell.png")
        assert found == (folders["lights"] / "assets/icons/bell.png").resolve()

    @pytest.mark.parametrize("name", ["missing", "icons", "../main.py", "/etc/passwd", "", "a\\b"])
    def test_no_file(self, folders: dict[str, Path], name: str) -> None:
        """Test a missing file, a folder and a name outside assets/ give None."""
        assert resolve_asset_file(folders["lights"], name) is None

    def test_link_out_of_assets(self, folders: dict[str, Path]) -> None:
        """Test a link that leads out of assets/ is not served."""
        (folders["lights"] / "assets/code.py").symlink_to(folders["lights"] / "main.py")
        (folders["lights"] / "assets/theirs").symlink_to(folders["other"] / "assets")
        assert resolve_asset_file(folders["lights"], "code.py") is None
        assert resolve_asset_file(folders["lights"], "theirs/private.txt") is None

    def test_link_inside_assets(self, folders: dict[str, Path]) -> None:
        """Test a link that stays inside assets/ is served."""
        (folders["lights"] / "assets/alias.png").symlink_to(folders["lights"] / "assets/icons/bell.png")
        assert resolve_asset_file(folders["lights"], "alias.png") is not None

    def test_no_assets_folder(self, tmp_path: Path) -> None:
        """Test an automation without an assets/ folder has no assets."""
        assert resolve_asset_file(tmp_path, "anything.txt") is None


class TestFileSystemBytes:
    """HAFileSystem.read_bytes, which read_asset uses."""

    async def test_read_bytes(self, hass: HomeAssistant, folders: dict[str, Path]) -> None:
        """Test a file is read as bytes through the executor."""
        files = HAFileSystem(hass)
        assert await files.read_bytes(folders["lights"] / "assets/icons/bell.png") == PNG
        with pytest.raises(FileNotFoundError):
            await files.read_bytes(folders["lights"] / "assets/missing")
