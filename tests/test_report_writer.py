"""Tests for ReportWriter -- unmatched report generation and loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.core.report_writer import ReportWriter
from src.models.processing_state import ProcessingState
from src.models.track import Track


@dataclass
class FakeStats:
    total: int = 10
    auto_matched: int = 5
    needs_review: int = 3
    unmatched: int = 1
    errors: int = 1


class TestWriteUnmatchedReport:
    def test_generates_json_and_txt(self, tmp_path: Path):
        tracks = [
            Track(
                file_path=Path("/music/song.mp3"),
                title="Unmatched Song",
                artist="Unknown",
                state=ProcessingState.UNMATCHED,
            ),
            Track(
                file_path=Path("/music/review.mp3"),
                title="Review Song",
                artist="Someone",
                state=ProcessingState.NEEDS_REVIEW,
                confidence=75.0,
            ),
        ]
        stats = FakeStats()

        ReportWriter.write_unmatched_report(tmp_path, tracks, stats)

        json_path = tmp_path / "_unmatched_report.json"
        txt_path = tmp_path / "_unmatched_report.txt"

        assert json_path.exists()
        assert txt_path.exists()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(data["unmatched"]) == 1
        assert len(data["needs_review"]) == 1
        assert data["stats"]["total"] == 10

        txt_content = txt_path.read_text(encoding="utf-8")
        assert "Unmatched Song" in txt_content
        assert "Review Song" in txt_content

    def test_no_unmatched_tracks(self, tmp_path: Path):
        tracks = [
            Track(
                file_path=Path("/music/matched.mp3"),
                state=ProcessingState.AUTO_MATCHED,
            ),
        ]
        stats = FakeStats(unmatched=0, needs_review=0, errors=0)
        ReportWriter.write_unmatched_report(tmp_path, tracks, stats)

        json_path = tmp_path / "_unmatched_report.json"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["unmatched"] == []
        assert data["needs_review"] == []


class TestLoadUnmatchedReport:
    def test_load_existing_report(self, tmp_path: Path):
        report_data = {
            "generated_at": "2024-01-01 00:00:00",
            "stats": {"total": 5},
            "unmatched": [{"file_path": "/song.mp3"}],
            "needs_review": [],
        }
        json_path = tmp_path / "_unmatched_report.json"
        json_path.write_text(json.dumps(report_data), encoding="utf-8")

        result = ReportWriter.load_unmatched_report(tmp_path)
        assert result is not None
        assert len(result["unmatched"]) == 1

    def test_load_nonexistent_report(self, tmp_path: Path):
        result = ReportWriter.load_unmatched_report(tmp_path)
        assert result is None

    def test_load_invalid_json(self, tmp_path: Path):
        json_path = tmp_path / "_unmatched_report.json"
        json_path.write_text("not valid json {{{{", encoding="utf-8")

        result = ReportWriter.load_unmatched_report(tmp_path)
        assert result is None
