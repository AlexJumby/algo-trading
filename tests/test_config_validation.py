"""Tests for config validation (Fix #2): missing file, directory, invalid YAML, empty file."""
import os
import tempfile

import pytest

from src.core.config import AppConfig, ConfigError


class TestConfigValidation:
    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError, match="Config file not found"):
            AppConfig.from_yaml(missing)

    def test_directory_instead_of_file_raises(self, tmp_path):
        d = tmp_path / "settings_dir"
        d.mkdir()
        with pytest.raises(ConfigError, match="directory, not a file"):
            AppConfig.from_yaml(d)

    def test_invalid_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("{{invalid yaml: [")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            AppConfig.from_yaml(bad)

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        with pytest.raises(ConfigError, match="empty or not a YAML mapping"):
            AppConfig.from_yaml(empty)
