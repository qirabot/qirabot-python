"""Tests for `qirabot login` / `install-browser` and API-key resolution layers."""

from __future__ import annotations

import json
import stat
import sys
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from qirabot.cli import config as user_config


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Point the user config at a temp dir (both POSIX and Windows shapes)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def _invoke(args, input=None, env_key=False, monkeypatch=None):
    from qirabot.cli.main import cli

    argv = ([] if env_key else []) + args
    return CliRunner().invoke(cli, argv, input=input)


# ---------------------------------------------------------------------------
# config file primitives
# ---------------------------------------------------------------------------


class TestConfigFile:
    def test_save_creates_file_with_0600(self, config_home):
        path = user_config.save_api_key("qk_secret")
        assert path.exists()
        assert json.loads(path.read_text())["api_key"] == "qk_secret"
        if sys.platform != "win32":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_save_preserves_unrelated_fields(self, config_home):
        path = user_config.config_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"other": 1, "api_key": "old"}))
        user_config.save_api_key("qk_new")
        data = json.loads(path.read_text())
        assert data == {"other": 1, "api_key": "qk_new"}

    def test_load_missing_or_broken_is_empty(self, config_home):
        assert user_config.load_api_key() == ""
        p = user_config.config_path()
        p.parent.mkdir(parents=True)
        p.write_text("{not json")
        assert user_config.load_api_key() == ""

    def test_mask(self):
        assert user_config.mask_key("qk_abcdefyz") == "qk_ab…yz"
        assert user_config.mask_key("short") == "*****"


# ---------------------------------------------------------------------------
# key resolution order: flag > env > (.env) > config
# ---------------------------------------------------------------------------


class TestKeyResolution:
    def _api_key_seen(self, monkeypatch, argv):
        """Run a command that echoes ctx.obj back via login --status."""
        from qirabot.cli.main import cli

        return CliRunner().invoke(cli, [*argv, "login", "--status"])

    def test_flag_beats_env_and_config(self, config_home, monkeypatch):
        user_config.save_api_key("qk_from_config")
        monkeypatch.setenv("QIRA_API_KEY", "qk_from_env99")
        result = self._api_key_seen(monkeypatch, ["--api-key", "qk_from_flag99"])
        assert "qk_fr…99" in result.output
        assert "--api-key flag" in result.output

    def test_env_beats_config(self, config_home, monkeypatch):
        user_config.save_api_key("qk_from_config")
        monkeypatch.setenv("QIRA_API_KEY", "qk_from_env99")
        result = self._api_key_seen(monkeypatch, [])
        assert "environment variable" in result.output

    def test_config_is_last_resort(self, config_home, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        user_config.save_api_key("qk_from_config")
        result = self._api_key_seen(monkeypatch, [])
        assert "login config" in result.output
        assert str(user_config.config_path()) in result.output

    def test_status_without_any_key_exits_1(self, config_home, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        result = self._api_key_seen(monkeypatch, [])
        assert result.exit_code == 1
        assert "qirabot login" in result.output

    def test_dotenv_source_is_labelled(self, config_home, monkeypatch):
        # main() marks a key that entered os.environ via ./.env.
        from qirabot.cli import main as cli_main

        monkeypatch.setattr(cli_main, "_KEY_FROM_DOTENV", True)
        monkeypatch.setenv("QIRA_API_KEY", "qk_from_dotenv")
        result = self._api_key_seen(monkeypatch, [])
        assert "./.env file" in result.output


# ---------------------------------------------------------------------------
# login (write path)
# ---------------------------------------------------------------------------


class TestLogin:
    def _login(self, monkeypatch, key="qk_live_key99", server_ok=True):
        from qirabot.cli import main as cli_main

        transport = MagicMock(name="Transport")
        if not server_ok:
            transport.return_value.request.side_effect = RuntimeError("401 bad key")
        monkeypatch.setattr(cli_main, "Transport", transport)
        result = CliRunner().invoke(cli_main.cli, ["login"], input=key + "\n")
        return result, transport

    def test_valid_key_is_verified_then_saved(self, config_home, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        result, transport = self._login(monkeypatch)
        assert result.exit_code == 0, result.output
        # verified against the server with the entered key...
        assert transport.call_args.kwargs["api_key"] == "qk_live_key99"
        transport.return_value.request.assert_called_once_with("GET", "/model-aliases")
        # ...and only then persisted
        assert user_config.load_api_key() == "qk_live_key99"
        assert "saved" in result.output

    def test_rejected_key_is_not_saved(self, config_home, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        result, _ = self._login(monkeypatch, server_ok=False)
        assert result.exit_code == 1
        assert "nothing saved" in result.output
        assert user_config.load_api_key() == ""
        assert not user_config.config_path().exists()

    def test_empty_key_is_rejected(self, config_home, monkeypatch):
        from qirabot.cli.main import cli

        result = CliRunner().invoke(cli, ["login"], input="   \n")
        assert result.exit_code != 0
        assert not user_config.config_path().exists()


# ---------------------------------------------------------------------------
# install-browser
# ---------------------------------------------------------------------------


class TestInstallBrowser:
    def test_missing_extra_raises_install_hint(self, monkeypatch):
        from qirabot.cli import main as cli_main
        from qirabot.exceptions import MissingDependencyError

        def missing(module, extra=None):
            raise MissingDependencyError(
                'Install it with:  python -m pip install "qirabot[browser]"'
            )

        monkeypatch.setattr(cli_main, "require", missing)
        result = CliRunner().invoke(cli_main.cli, ["install-browser"])
        assert result.exit_code != 0
        assert "qirabot[browser]" in str(result.exception)

    def test_delegates_to_playwright_module(self, monkeypatch):
        from qirabot.cli import main as cli_main

        monkeypatch.setattr(cli_main, "require", lambda m, e=None: MagicMock())
        calls = {}

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            return MagicMock(returncode=0)

        monkeypatch.setattr("subprocess.run", fake_run)
        result = CliRunner().invoke(cli_main.cli, ["install-browser"])
        assert result.exit_code == 0, result.output
        assert calls["cmd"] == [sys.executable, "-m", "playwright", "install", "chromium"]
        assert "ready" in result.output

    def test_nonzero_exit_becomes_error(self, monkeypatch):
        from qirabot.cli import main as cli_main

        monkeypatch.setattr(cli_main, "require", lambda m, e=None: MagicMock())
        monkeypatch.setattr("subprocess.run", lambda *a, **k: MagicMock(returncode=3))
        result = CliRunner().invoke(cli_main.cli, ["install-browser"])
        assert result.exit_code != 0
        assert "exit 3" in result.output
