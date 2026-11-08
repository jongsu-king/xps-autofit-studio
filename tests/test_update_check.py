"""Release check against GitHub (offline tests with a fake fetcher)."""

from __future__ import annotations

import json

import pytest

from xps_autofit import __version__, update_check
from xps_autofit.cli import main
from xps_autofit.update_check import (
    UpdateCheckError,
    check_for_update,
    describe,
    disabled_by_environment,
    is_newer,
    parse_version,
    pick_platform_asset,
)

RELEASE = {
    "tag_name": "v9.8.7",
    "html_url": "https://github.com/jongsu-king/xps-autofit-studio/releases/tag/v9.8.7",
    "published_at": "2030-01-01T00:00:00Z",
    "body": "notes",
    "assets": [
        {"name": "XPS-AutoFit-Studio-9.8.7-Windows-x64-Setup.exe", "browser_download_url": "w"},
        {"name": "XPS-AutoFit-Studio-9.8.7-Windows-x64.zip", "browser_download_url": "wz"},
        {"name": "XPS-AutoFit-Studio-9.8.7-macOS-arm64.dmg", "browser_download_url": "m"},
        {"name": "xps-autofit-studio_9.8.7_amd64.deb", "browser_download_url": "d"},
        {"name": "XPS-AutoFit-Studio-9.8.7-Linux-x86_64.tar.gz", "browser_download_url": "l"},
    ],
}


def test_parse_and_compare_versions():
    assert parse_version("v0.4.0") == (0, 4, 0)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version("0.4.0rc1") == (0, 4, 0, -1, 1)
    assert is_newer("0.4.0", "0.3.9")
    assert is_newer("v1.0.0", "0.99.0")
    assert not is_newer("0.3.0", "0.3.0")
    assert not is_newer("0.4.0rc1", "0.4.0")
    assert is_newer("0.4.0", "0.4.0rc1")
    assert not is_newer("not-a-version", "0.3.0")
    with pytest.raises(ValueError):
        parse_version("abc")


def test_check_for_update_with_fake_release(monkeypatch):
    calls = []

    def fetch(url: str, timeout: float) -> dict:
        calls.append((url, timeout))
        return RELEASE

    info = check_for_update("0.3.0", timeout=1.5, fetch=fetch)
    assert calls == [(update_check.API_URL, 1.5)]
    assert info.is_newer and info.latest == "9.8.7" and info.current == "0.3.0"
    assert len(info.assets) == 5
    monkeypatch.setattr(update_check.platform, "system", lambda: "Windows")
    assert pick_platform_asset(info.assets) == (
        "XPS-AutoFit-Studio-9.8.7-Windows-x64-Setup.exe",
        "w",
    )
    monkeypatch.setattr(update_check.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(update_check.platform, "machine", lambda: "arm64")
    assert pick_platform_asset(info.assets) == ("XPS-AutoFit-Studio-9.8.7-macOS-arm64.dmg", "m")
    monkeypatch.setattr(update_check.platform, "system", lambda: "Linux")
    assert pick_platform_asset(info.assets) == ("xps-autofit-studio_9.8.7_amd64.deb", "d")
    assert pick_platform_asset({}) is None
    text = describe(info)
    assert "9.8.7 is available" in text and "pip install" in text
    d = info.to_dict()
    assert d["is_newer"] is True and d["platform_asset"].endswith(".deb")


def test_up_to_date_and_errors():
    info = check_for_update("9.8.7", fetch=lambda u, t: RELEASE)
    assert not info.is_newer
    assert "up to date" in describe(info)
    with pytest.raises(UpdateCheckError):
        check_for_update(fetch=lambda u, t: {"assets": []})

    def broken(url: str, timeout: float) -> dict:
        raise UpdateCheckError("offline")

    with pytest.raises(UpdateCheckError):
        check_for_update(fetch=broken)


def test_environment_switch(monkeypatch):
    monkeypatch.delenv("XPS_AUTOFIT_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("XPS_AUTOFIT_SMOKE", raising=False)
    assert not disabled_by_environment()
    monkeypatch.setenv("XPS_AUTOFIT_NO_UPDATE_CHECK", "1")
    assert disabled_by_environment()
    monkeypatch.setenv("XPS_AUTOFIT_NO_UPDATE_CHECK", "0")
    assert not disabled_by_environment()
    monkeypatch.setenv("XPS_AUTOFIT_SMOKE", "1")
    assert disabled_by_environment()


def test_cli_update_check(monkeypatch, capsys):
    monkeypatch.setattr(update_check, "fetch_github", lambda url, timeout: RELEASE)
    assert main(["update-check"]) == 0
    assert "9.8.7 is available" in capsys.readouterr().out
    assert main(["update-check", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["latest"] == "9.8.7" and data["current"] == __version__

    def broken(url: str, timeout: float) -> dict:
        raise UpdateCheckError("offline")

    monkeypatch.setattr(update_check, "fetch_github", broken)
    assert main(["update-check"]) == 2
    assert "failed" in capsys.readouterr().out
