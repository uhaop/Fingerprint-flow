"""Tests for configuration validation logic in main.py."""

from __future__ import annotations

import pytest

from src.main import validate_config
from src.utils.constants import DEFAULT_AUTO_APPLY_THRESHOLD, DEFAULT_REVIEW_THRESHOLD


class TestValidateConfig:
    def test_valid_config_produces_no_warnings(self):
        config = {
            "library_path": "~/Music/Library",
            "auto_apply_threshold": 90,
            "review_threshold": 70,
            "file_template": "{track:02d} - {title}",
        }
        warnings = validate_config(config)
        assert warnings == []

    def test_dangerous_library_path_system_dir(self):
        config = {"library_path": "C:\\Windows\\System32"}
        warnings = validate_config(config)
        assert any("system directory" in w.lower() or "library_path" in w for w in warnings)

    def test_dangerous_library_path_drive_root(self):
        """Drive roots like D:\\ should be flagged as too shallow."""
        config = {"library_path": "D:\\"}
        warnings = validate_config(config)
        assert len(warnings) > 0
        assert any("level" in w.lower() or "deep" in w.lower() for w in warnings)

    def test_shallow_library_path(self):
        """A path only 1 level deep (e.g. D:\\Music) should warn."""
        config = {"library_path": "D:\\Music"}
        warnings = validate_config(config)
        assert len(warnings) > 0

    def test_auto_threshold_out_of_range(self):
        config = {"auto_apply_threshold": 150}
        warnings = validate_config(config)
        assert any("auto_apply_threshold" in w for w in warnings)
        assert config["auto_apply_threshold"] == DEFAULT_AUTO_APPLY_THRESHOLD

    def test_review_threshold_out_of_range(self):
        config = {"review_threshold": -10}
        warnings = validate_config(config)
        assert any("review_threshold" in w for w in warnings)
        assert config["review_threshold"] == DEFAULT_REVIEW_THRESHOLD

    def test_auto_less_than_review_swaps(self):
        config = {
            "auto_apply_threshold": 50,
            "review_threshold": 80,
        }
        warnings = validate_config(config)
        assert any("must be >=" in w for w in warnings)
        assert config["auto_apply_threshold"] == 80
        assert config["review_threshold"] == 50

    def test_file_template_without_title(self):
        config = {"file_template": "{track:02d} - {artist}"}
        warnings = validate_config(config)
        assert any("{title}" in w for w in warnings)

    def test_non_numeric_threshold(self):
        config = {"auto_apply_threshold": "high"}
        warnings = validate_config(config)
        assert any("auto_apply_threshold" in w for w in warnings)

    def test_empty_config(self):
        """Empty config should produce no warnings (uses defaults)."""
        config = {}
        warnings = validate_config(config)
        assert warnings == []
