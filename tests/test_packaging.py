"""Packaging checks for bundled assets (ADBKeyboard IME, Agent Skill payload)."""

from __future__ import annotations

from importlib import resources

import pytest

_ASSETS = resources.files("qirabot.assets")
_APK = _ASSETS.joinpath("ADBKeyboard.apk")


@pytest.mark.skipif(not _APK.is_file(), reason="APK not vendored in this checkout")
class TestBundledApk:
    def test_apk_is_a_zip(self):
        with _APK.open("rb") as f:
            assert f.read(4) == b"PK\x03\x04"

    def test_license_and_provenance_ship_alongside(self):
        license_file = _ASSETS.joinpath("ADBKEYBOARD_LICENSE.txt")
        assert license_file.is_file()
        text = license_file.read_text(encoding="utf-8")
        assert "GNU GENERAL PUBLIC LICENSE" in text
        assert "github.com/senzhk/ADBKeyBoard" in text
        assert "SHA-256" in text

    def test_apk_matches_recorded_sha256(self):
        import hashlib
        import re

        recorded = re.search(
            r"SHA-256:\s*([0-9a-f]{64})",
            _ASSETS.joinpath("ADBKEYBOARD_LICENSE.txt").read_text(encoding="utf-8"),
        )
        assert recorded
        with _APK.open("rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        assert actual == recorded.group(1)


_SKILL = resources.files("qirabot").joinpath("skill-data")


@pytest.mark.skipif(not _SKILL.is_dir(), reason="skill payload not vendored in this checkout")
class TestBundledSkill:
    def test_payload_ships_complete(self):
        for rel in (
            "SKILL.md",
            "references/REFERENCE.md",
            "references/CLI.md",
            "scripts/preflight.py",
            "templates/browser.py",
        ):
            assert _SKILL.joinpath(rel).is_file(), rel
