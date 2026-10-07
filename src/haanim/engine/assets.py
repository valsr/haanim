"""Assets: the files in an automation's ``assets/`` folder.

An automation reads its assets with ``haa.read_asset()`` and links to them
with ``haa.asset_url()``. Names are paths relative to ``assets/`` written with
``/``; a name can never reach outside that folder, so an automation only
reaches its own assets.
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from urllib.parse import quote

from haanim.engine.discovery import ASSETS_DIRNAME
from haanim.interfaces import AssetSigner, FileSystem

__all__ = ["ASSET_URL_PREFIX", "AssetStore", "asset_url_path", "normalize_asset_name"]

ASSET_URL_PREFIX = "/api/haanim/assets"
"""Where the host serves assets: ``<prefix>/<automation_id>/<name>``."""


def normalize_asset_name(name: str) -> str:
    """Return an asset name in its shortest form, checked to stay inside ``assets/``.

    Args:
        name: Path of the asset relative to ``assets/``, using ``/``.

    Returns:
        The name without ``.`` and ``..`` parts and without repeated slashes.

    Raises:
        TypeError: If the name is not a string.
        ValueError: If the name is empty, absolute, names the folder itself,
            or resolves outside ``assets/``.
    """
    if not isinstance(name, str):
        raise TypeError(f"Asset name must be a string, not {type(name).__name__}")
    if not name or "\0" in name:
        raise ValueError(f"Invalid asset name {name!r}")
    if "\\" in name:
        raise ValueError(f"Invalid asset name {name!r}: use '/' to separate folders")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ValueError(f"Invalid asset name {name!r}: it must be relative to {ASSETS_DIRNAME}/")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Invalid asset name {name!r}: it is outside {ASSETS_DIRNAME}/")
    if normalized == ".":
        raise ValueError(f"Invalid asset name {name!r}: it does not name a file")
    return normalized


def asset_url_path(automation_id: str, name: str) -> str:
    """Return the URL path of an asset of an automation.

    Raises:
        TypeError: If the name is not a string.
        ValueError: If the name is not valid.
    """
    return f"{ASSET_URL_PREFIX}/{quote(automation_id, safe='')}/{quote(normalize_asset_name(name))}"


class AssetStore:
    """Read-only access to the assets of one automation."""

    def __init__(
        self,
        automation_id: str,
        folder: Path | None,
        files: FileSystem,
        signer: AssetSigner | None = None,
    ) -> None:
        """Initialize the store.

        Args:
            automation_id: ID of the automation that owns the assets.
            folder: The automation's folder, which holds ``assets/``. None if
                the automation has no folder; it then has no assets.
            files: File access.
            signer: Makes URL paths usable without login. None if the host cannot.
        """
        self._automation_id = automation_id
        self._root = None if folder is None else Path(folder) / ASSETS_DIRNAME
        self._files = files
        self._signer = signer

    def path(self, name: str) -> Path:
        """Return the path of an existing asset.

        Raises:
            TypeError: If the name is not a string.
            ValueError: If the name is not valid or resolves outside ``assets/``.
            FileNotFoundError: If there is no such file.
        """
        normalized = normalize_asset_name(name)
        if self._root is not None:
            path = self._root.joinpath(*normalized.split("/"))
            if self._files.exists(path) and not self._files.is_dir(path):
                return path
        raise FileNotFoundError(f"Automation '{self._automation_id}' has no asset '{normalized}'")

    async def read(self, name: str, text: bool = False) -> bytes | str:
        """Return the contents of an asset as it is on disk now.

        Args:
            name: Path of the asset relative to ``assets/``, using ``/``.
            text: Return a string decoded as UTF-8 instead of bytes.

        Raises:
            ValueError: If the name is not valid or resolves outside ``assets/``.
            FileNotFoundError: If there is no such file.
        """
        path = self.path(name)
        if text:
            return await self._files.read_text(path)
        return await self._files.read_bytes(path)

    def url(self, name: str, expires: float | None = None) -> str:
        """Return the URL path of an asset.

        Args:
            name: Path of the asset relative to ``assets/``, using ``/``.
            expires: Seconds for which the URL works without login. Without
                it the URL needs a logged-in session.

        Raises:
            ValueError: If the name is not valid or ``expires`` is not positive.
            FileNotFoundError: If there is no such file.
            RuntimeError: If ``expires`` is given and the host cannot sign URLs.
        """
        if expires is not None:
            if isinstance(expires, bool) or not isinstance(expires, (int, float)):
                raise TypeError(f"expires must be a number of seconds, not {type(expires).__name__}")
            if not 0 < expires < float("inf"):
                raise ValueError(f"expires must be a positive number of seconds, not {expires!r}")
        self.path(name)
        url = asset_url_path(self._automation_id, name)
        if expires is None:
            return url
        if self._signer is None:
            raise RuntimeError("Signed asset URLs are not available")
        return self._signer.sign(url, float(expires))
