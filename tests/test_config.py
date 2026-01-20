"""Tests for config module."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from lib.config import (
    DEFAULT_CONFIG,
    get_claude_home,
    get_cowboy_data_dir,
    is_debug_enabled,
    load_config,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_returns_default_config_when_no_files_exist(self):
        """Should return default config when no settings files exist."""
        with mock.patch.object(Path, "exists", return_value=False):
            config = load_config()
            assert config["sessionDiscoveryHours"] == DEFAULT_CONFIG["sessionDiscoveryHours"]
            assert config["hideThresholdMinutes"] == DEFAULT_CONFIG["hideThresholdMinutes"]

    def test_loads_global_settings(self):
        """Should load settings from ~/.claude/settings.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            settings_file = claude_dir / "settings.json"
            settings_file.write_text(
                json.dumps({"claudeCowboy": {"sessionDiscoveryHours": 48}})
            )

            with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                config = load_config()
                assert config["sessionDiscoveryHours"] == 48

    def test_project_settings_override_global(self):
        """Project-level settings should override global settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create global settings
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            global_settings = claude_dir / "settings.json"
            global_settings.write_text(
                json.dumps({"claudeCowboy": {"sessionDiscoveryHours": 48}})
            )

            # Create project settings
            project_dir = Path(tmpdir) / "project"
            project_claude_dir = project_dir / ".claude"
            project_claude_dir.mkdir(parents=True)
            project_settings = project_claude_dir / "settings.json"
            project_settings.write_text(
                json.dumps({"claudeCowboy": {"sessionDiscoveryHours": 12}})
            )

            with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                config = load_config(project_path=str(project_dir))
                assert config["sessionDiscoveryHours"] == 12

    def test_environment_variables_override_all(self):
        """Environment variables should have highest precedence."""
        with mock.patch.dict(os.environ, {"CLAUDE_COWBOY_DISCOVERY_HOURS": "72"}):
            config = load_config()
            assert config["sessionDiscoveryHours"] == 72

    def test_handles_invalid_json_gracefully(self):
        """Should not crash on invalid JSON in settings file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            settings_file = claude_dir / "settings.json"
            settings_file.write_text("not valid json {{{")

            with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                # Should not raise, should return default config
                config = load_config()
                assert config["sessionDiscoveryHours"] == DEFAULT_CONFIG["sessionDiscoveryHours"]

    def test_boolean_env_var_conversion(self):
        """Should correctly convert boolean environment variables."""
        with mock.patch.dict(os.environ, {"CLAUDE_COWBOY_PR_MONITORING": "true"}):
            config = load_config()
            assert config["enablePrMonitoring"] is True

        with mock.patch.dict(os.environ, {"CLAUDE_COWBOY_PR_MONITORING": "false"}):
            config = load_config()
            assert config["enablePrMonitoring"] is False


class TestGetClaudeHome:
    """Tests for get_claude_home function."""

    def test_returns_claude_directory_in_home(self):
        """Should return ~/.claude path."""
        home = get_claude_home()
        assert home == Path.home() / ".claude"


class TestGetCowboyDataDir:
    """Tests for get_cowboy_data_dir function."""

    def test_returns_cowboy_subdirectory(self):
        """Should return ~/.claude/cowboy path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                data_dir = get_cowboy_data_dir()
                assert data_dir == Path(tmpdir) / ".claude" / "cowboy"
                assert data_dir.exists()  # Should be created


class TestIsDebugEnabled:
    """Tests for is_debug_enabled function."""

    def test_returns_false_by_default(self):
        """Should return False when env var not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAUDE_COWBOY_DEBUG", None)
            assert is_debug_enabled() is False

    def test_returns_true_for_truthy_values(self):
        """Should return True for various truthy values."""
        for value in ["1", "true", "True", "TRUE", "yes", "on"]:
            with mock.patch.dict(os.environ, {"CLAUDE_COWBOY_DEBUG": value}):
                assert is_debug_enabled() is True

    def test_returns_false_for_falsy_values(self):
        """Should return False for non-truthy values."""
        for value in ["0", "false", "no", "off", ""]:
            with mock.patch.dict(os.environ, {"CLAUDE_COWBOY_DEBUG": value}):
                assert is_debug_enabled() is False
