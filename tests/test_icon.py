"""Tests for the HAAnim icon module."""

from __future__ import annotations

from custom_components.haanim.icon import ICON


class TestIcon:
    """Tests for icon constants."""

    def test_icon_defined(self) -> None:
        """Test that ICON constant is defined."""
        assert ICON is not None
        assert isinstance(ICON, str)

    def test_icon_is_mdi(self) -> None:
        """Test that icon uses Material Design Icons format."""
        assert ICON.startswith("mdi:")
