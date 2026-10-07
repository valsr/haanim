"""Tests for assets: the files in an automation's ``assets/`` folder.

See "Assets" in the design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from haanim.engine.assets import ASSET_URL_PREFIX, AssetStore, asset_url_path, normalize_asset_name
from haanim.engine.haanim_api import HAAnim
from haanim.interfaces import Host
from haanim.testing import FakeAssetSigner, FakeAutomationRegistry, FakeFileSystem, make_host
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

FOLDER = Path("/automations/lights")
PNG = b"\x89PNG\r\n\x1a\n\x00\xff"


@pytest.fixture
def files() -> FakeFileSystem:
    """Two automations with assets, held in memory."""
    files = FakeFileSystem()
    files.write(FOLDER / "main.py", "x = 1")
    files.write(FOLDER / "secret.txt", "not an asset")
    files.write(FOLDER / "assets/phrases.json", '{"hello": "héllo"}')
    files.write(FOLDER / "assets/icons/bell.png", PNG)
    files.write(FOLDER / "assets/my file#1.mp3", b"ID3")
    files.write(Path("/automations/other/assets/private.txt"), "theirs")
    return files


@pytest.fixture
def host(files: FakeFileSystem) -> Host:
    """A fake host with those files."""
    return make_host(files=files)


@pytest.fixture
def haa(host: Host) -> HAAnim:
    """The haa object of the lights automation."""
    return HAAnim(host, "lights", FakeAutomationRegistry(), folder=FOLDER)


OUTSIDE = [
    "..",
    "../secret.txt",
    "../main.py",
    "../../other/assets/private.txt",
    "icons/../../secret.txt",
    "icons/../../../other/assets/private.txt",
    "/automations/other/assets/private.txt",
    "/etc/passwd",
    "..\\secret.txt",
    "icons\\bell.png",
    "C:/windows/win.ini",
    "",
    ".",
    "icons/..",
    "a\0b",
]


class TestNames:
    """Rule: a name is a path relative to assets/, using /; outside assets/ raises ValueError."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("phrases.json", "phrases.json"),
            ("icons/bell.png", "icons/bell.png"),
            ("./phrases.json", "phrases.json"),
            ("icons//bell.png", "icons/bell.png"),
            ("icons/../phrases.json", "phrases.json"),
            ("icons/./bell.png", "icons/bell.png"),
            ("..hidden", "..hidden"),
            ("a/..b/c", "a/..b/c"),
        ],
    )
    def test_names_inside(self, name: str, expected: str) -> None:
        """Test a name inside assets/ is brought to its shortest form."""
        assert normalize_asset_name(name) == expected

    @pytest.mark.parametrize("name", OUTSIDE, ids=repr)
    def test_names_outside_are_rejected(self, name: str) -> None:
        """Test a name that is not a file inside assets/ raises ValueError."""
        with pytest.raises(ValueError, match="Invalid asset name"):
            normalize_asset_name(name)

    @pytest.mark.parametrize("name", [None, 1, b"phrases.json", Path("phrases.json")], ids=repr)
    def test_name_must_be_a_string(self, name: Any) -> None:
        """Test a name that is not a string raises TypeError."""
        with pytest.raises(TypeError, match="Asset name must be a string"):
            normalize_asset_name(name)


class TestReadAsset:
    """Rule: read_asset returns bytes, or str with text=True; the read is awaited."""

    async def test_bytes(self, haa: HAAnim) -> None:
        """Test an asset is read as bytes by default."""
        assert await haa.read_asset("icons/bell.png") == PNG

    async def test_text_file_as_bytes(self, haa: HAAnim) -> None:
        """Test a text file read without text=True gives its UTF-8 bytes."""
        assert await haa.read_asset("phrases.json") == '{"hello": "héllo"}'.encode("utf-8")

    async def test_text(self, haa: HAAnim) -> None:
        """Test text=True gives a string decoded as UTF-8."""
        content = await haa.read_asset("phrases.json", text=True)
        assert content == '{"hello": "héllo"}'
        assert isinstance(content, str)

    async def test_binary_as_text_fails(self, haa: HAAnim) -> None:
        """Test a file that is not UTF-8 cannot be read as text."""
        with pytest.raises(UnicodeDecodeError):
            await haa.read_asset("icons/bell.png", text=True)

    async def test_normalized_name(self, haa: HAAnim) -> None:
        """Test a name with . and .. parts that stays inside assets/ is read."""
        assert await haa.read_asset("icons/../icons/./bell.png") == PNG

    async def test_every_read_sees_the_file_as_it_is_now(self, haa: HAAnim, files: FakeFileSystem) -> None:
        """Test assets are not cached."""
        assert await haa.read_asset("phrases.json", text=True) == '{"hello": "héllo"}'
        files.write(FOLDER / "assets/phrases.json", "[]")
        assert await haa.read_asset("phrases.json", text=True) == "[]"

    @pytest.mark.parametrize("name", ["missing.txt", "icons/missing.png", "nowhere/at/all.txt", "icons"])
    async def test_missing_file(self, haa: HAAnim, name: str) -> None:
        """Test a file that does not exist, or a folder, raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Automation 'lights' has no asset"):
            await haa.read_asset(name)

    @pytest.mark.parametrize("name", OUTSIDE, ids=repr)
    async def test_traversal(self, haa: HAAnim, name: str) -> None:
        """Test a name outside assets/ raises ValueError, also when the file exists."""
        with pytest.raises(ValueError):
            await haa.read_asset(name)

    async def test_unreadable_file(self, haa: HAAnim, files: FakeFileSystem) -> None:
        """Test an error of the file system reaches the automation."""
        files.make_unreadable(FOLDER / "assets/phrases.json")
        with pytest.raises(PermissionError):
            await haa.read_asset("phrases.json")
        with pytest.raises(PermissionError):
            await haa.read_asset("phrases.json", text=True)


class TestOwnAssetsOnly:
    """Rule: an automation can only reach its own assets."""

    async def test_other_automations_assets(self, host: Host) -> None:
        """Test each automation reads from its own folder."""
        other = HAAnim(host, "other", FakeAutomationRegistry(), folder=Path("/automations/other"))
        assert await other.read_asset("private.txt", text=True) == "theirs"
        with pytest.raises(FileNotFoundError):
            await other.read_asset("phrases.json")

    async def test_same_name_is_not_shared(self, haa: HAAnim) -> None:
        """Test another automation's asset is not found by its name."""
        with pytest.raises(FileNotFoundError):
            await haa.read_asset("private.txt")
        with pytest.raises(FileNotFoundError):
            haa.asset_url("private.txt")

    async def test_no_folder_no_assets(self, host: Host) -> None:
        """Test an automation without a folder has no assets."""
        haa = HAAnim(host, "lights", FakeAutomationRegistry())
        with pytest.raises(FileNotFoundError):
            await haa.read_asset("phrases.json")

    def test_assets_are_read_only(self, haa: HAAnim) -> None:
        """Test haa has no way to write an asset."""
        assert [name for name in dir(haa) if "asset" in name and not name.startswith("_")] == [
            "asset_url",
            "read_asset",
        ]


class TestAssetUrl:
    """Rule: asset_url returns a path under /api/haanim/assets/<automation_id>/, signed with expires."""

    def test_plain_url(self, haa: HAAnim, host: Host) -> None:
        """Test without expires the path is returned as it is, unsigned."""
        assert haa.asset_url("icons/bell.png") == "/api/haanim/assets/lights/icons/bell.png"
        assert host.asset_signer.signed == []  # type: ignore[union-attr]

    def test_url_is_quoted(self, haa: HAAnim) -> None:
        """Test characters that mean something in a URL are escaped."""
        assert haa.asset_url("my file#1.mp3") == "/api/haanim/assets/lights/my%20file%231.mp3"

    def test_url_uses_the_normalized_name(self, haa: HAAnim) -> None:
        """Test . and .. parts do not appear in the URL."""
        assert haa.asset_url("icons/../phrases.json") == f"{ASSET_URL_PREFIX}/lights/phrases.json"

    @pytest.mark.parametrize("expires", [300, 0.5, 86400.0])
    def test_signed_url(self, haa: HAAnim, host: Host, expires: float) -> None:
        """Test with expires the host signs the path for that many seconds."""
        url = haa.asset_url("phrases.json", expires=expires)
        assert url == f"/api/haanim/assets/lights/phrases.json?signed={expires:g}"
        assert host.asset_signer.signed == [  # type: ignore[union-attr]
            ("/api/haanim/assets/lights/phrases.json", float(expires))
        ]

    @pytest.mark.parametrize("expires", [0, -1, -0.5, float("inf"), float("nan")])
    def test_expires_must_be_positive(self, haa: HAAnim, expires: float) -> None:
        """Test a lifetime that is not a positive number of seconds raises ValueError."""
        with pytest.raises(ValueError, match="expires must be a positive number"):
            haa.asset_url("phrases.json", expires=expires)

    @pytest.mark.parametrize("expires", ["300", True, [300]], ids=repr)
    def test_expires_must_be_a_number(self, haa: HAAnim, expires: Any) -> None:
        """Test a lifetime that is not a number raises TypeError."""
        with pytest.raises(TypeError, match="expires must be a number of seconds"):
            haa.asset_url("phrases.json", expires=expires)

    def test_missing_file(self, haa: HAAnim) -> None:
        """Test a file that does not exist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            haa.asset_url("missing.mp3")
        with pytest.raises(FileNotFoundError):
            haa.asset_url("missing.mp3", expires=300)

    @pytest.mark.parametrize("name", OUTSIDE, ids=repr)
    def test_traversal(self, haa: HAAnim, name: str) -> None:
        """Test a name outside assets/ raises ValueError."""
        with pytest.raises(ValueError):
            haa.asset_url(name)

    def test_host_that_cannot_sign(self, files: FakeFileSystem) -> None:
        """Test a signed URL from a host without a signer raises, a plain one works."""
        store = AssetStore("lights", FOLDER, files, None)
        assert store.url("phrases.json") == "/api/haanim/assets/lights/phrases.json"
        with pytest.raises(RuntimeError, match="Signed asset URLs are not available"):
            store.url("phrases.json", expires=300)

    def test_url_path_of_an_automation(self) -> None:
        """Test the path is built from the automation ID and the name."""
        assert asset_url_path("climate_2", "a/b.png") == "/api/haanim/assets/climate_2/a/b.png"

    def test_fake_signer_records(self) -> None:
        """Test the fake signer keeps what it signed."""
        signer = FakeAssetSigner()
        assert signer.sign("/x", 5) == "/x?signed=5"
        assert signer.signed == [("/x", 5)]


SOURCE = """
from haanim import haa, action

@action
async def announce(event):
    phrases = await haa.read_asset("phrases.json", text=True)
    icon = await haa.read_asset("icons/bell.png")
    return [phrases, len(icon), haa.asset_url("chime.mp3", expires=300), haa.asset_url("chime.mp3")]

@action
async def escape(event):
    return await haa.read_asset("../main.py", text=True)
"""


class TestInAnAutomation:
    """The design's example, run by the interpreter on real files."""

    async def test_example(self, world: World) -> None:
        """Test an automation reads and links to the files in its assets/ folder."""
        folder = world.write("announcer", SOURCE)
        (folder / "assets/icons").mkdir(parents=True)
        (folder / "assets/phrases.json").write_text('["hi"]', encoding="utf-8")
        (folder / "assets/icons/bell.png").write_bytes(PNG)
        (folder / "assets/chime.mp3").write_bytes(b"ID3")
        automation = await world.started("announcer", SOURCE)

        assert await automation.call_action("announce") == [
            '["hi"]',
            len(PNG),
            "/api/haanim/assets/announcer/chime.mp3?signed=300",
            "/api/haanim/assets/announcer/chime.mp3",
        ]

    async def test_traversal_from_an_automation(self, world: World) -> None:
        """Test an automation cannot read its own code as an asset."""
        automation = await world.started("announcer", SOURCE)
        with pytest.raises(ValueError, match="outside assets/"):
            await automation.call_action("escape")

    async def test_assets_are_not_code(self, world: World) -> None:
        """Test a Python file in assets/ is not checked or run, and can be read."""
        folder = world.write("announcer", SOURCE)
        (folder / "assets").mkdir()
        (folder / "assets/broken.py").write_text("this is not python (", encoding="utf-8")
        automation = await world.started("announcer", SOURCE)
        assert await automation.context._haa.read_asset("broken.py", text=True) == "this is not python ("
