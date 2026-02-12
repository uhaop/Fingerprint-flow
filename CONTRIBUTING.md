# Contributing to Fingerprint Flow

Thank you for considering contributing to Fingerprint Flow! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Data Safety Guidelines](#data-safety-guidelines)
- [Architecture Overview](#architecture-overview)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/Fingerprint-flow.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Push and open a Pull Request

## Development Setup

### Prerequisites

- Python 3.10 or higher
- [Chromaprint](https://acoustid.org/chromaprint) (`fpcalc` binary) -- optional, for fingerprinting tests

### Install

```bash
# Create a virtual environment
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # macOS/Linux

# Install with dev dependencies
pip install -e ".[dev]"
```

### Configuration

```bash
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your API keys (optional for most development)
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_file_organizer.py

# Skip slow tests (require audio files / network)
pytest -m "not slow"

# Skip integration tests
pytest -m "not integration"
```

### Linting & Type Checking

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/
```

## Code Style

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (line length 100)
- **Type hints**: Required on all public functions (`disallow_untyped_defs = true`)
- **Docstrings**: Google-style, required on all public classes and methods
- **Constants**: No magic numbers -- use named constants in `src/utils/constants.py`
- **Imports**: Top-level only (no inline imports unless genuinely needed for circular import avoidance)

### Naming Conventions

- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Private methods prefixed with `_`

## Pull Request Process

1. **Tests pass**: All existing tests must pass. Add tests for new functionality.
2. **Lint clean**: `ruff check` and `mypy` must pass with no errors.
3. **Documentation**: Update docstrings, README, and CHANGELOG.md as needed.
4. **One concern per PR**: Keep PRs focused. Large changes should be split into smaller PRs.
5. **Data safety**: If your PR touches file operations, tag writing, or the organizer, it requires extra scrutiny. See below.

### Commit Messages

Use clear, descriptive commit messages:

```
fix: backup files before writing tags to preserve originals
feat: add dry-run mode for batch operations
docs: add troubleshooting section to README
test: add coverage for sanitize_filename edge cases
```

## Data Safety Guidelines

**This is the most important section.** Fingerprint Flow touches people's personal music libraries. A bug here can destroy irreplaceable files.

### Rules for File Operations

1. **Never delete user files** -- only move them. The only files that may be deleted are OS-generated junk (`Thumbs.db`, `desktop.ini`, `.DS_Store`).
2. **Always backup before modifying** -- call `backup_before_changes()` before `write_tags()`.
3. **Verify after cross-device copies** -- check file size after `shutil.copy2()` before deleting the source.
4. **Never clean up outside the library** -- `_cleanup_empty_dirs()` must refuse to touch directories outside the library root.
5. **Test destructive operations** -- any PR that adds or modifies file operations must include tests using `tmp_path` fixtures.
6. **Dry-run must be maintained** -- if you add a new destructive operation, ensure it respects the `dry_run` flag.

### Testing File Operations

Always use pytest's `tmp_path` fixture for tests that create, move, or delete files:

```python
def test_organize_creates_backup(tmp_path):
    """Backup must be created BEFORE any tags are modified."""
    source = tmp_path / "source" / "song.mp3"
    source.parent.mkdir()
    source.write_bytes(b"fake audio data")
    # ... test that backup exists with original content
```

## Architecture Overview

```
src/
  main.py                    # Entry point, config loading, AppConfig dataclass
  core/                      # Processing pipeline
    batch_processor.py       #   Orchestrator (scan -> fingerprint -> match -> organize)
    scanner.py               #   Audio file discovery
    fingerprinter.py         #   Chromaprint fingerprinting (parallel batch) + AcoustID lookup
    metadata_fetcher.py      #   MusicBrainz / Discogs API client
    archive_org_fetcher.py   #   Internet Archive metadata source
    confidence_scorer.py     #   Weighted match scoring algorithm
    fuzzy_matcher.py         #   String similarity matching (rapidfuzz)
    tag_editor.py            #   Read/write audio metadata tags (mutagen)
    file_organizer.py        #   File moves with backup, rollback, and duplicate detection
    dj_screw_handler.py      #   DJ Screw "Diary of the Originator" chapter detection
    compilation_detector.py  #   Compilation / mixtape / DJ mix detection
    report_writer.py         #   Unmatched report generation (JSON + text)
  models/                    # Data classes
    track.py                 #   Track model (file path, tags, fingerprint, state)
    match_result.py          #   MatchResult and MatchCandidate
    processing_state.py      #   Processing state enum
    config.py                #   AppConfig typed dataclass
  db/                        # SQLite persistence layer
    database.py              #   Connection management and migrations
    repositories.py          #   Track, MoveHistory, and ApiCache repositories
  gui/                       # PyQt6 desktop interface
    app.py                   #   Main window with sidebar navigation
    worker.py                #   Background threads (processing, review apply, manual search)
    views/                   #   Import, Progress, Preview, Review, Library, Settings
    widgets/                 #   ConfidenceBadge, MatchSelector, TrackCard, SearchBar, AlbumArtViewer
    styles/                  #   Theme module (Catppuccin Mocha / Latte color palettes)
  utils/                     # Shared utilities
    constants.py             #   All named constants (thresholds, limits, patterns)
    file_utils.py            #   Safe move/copy, sanitize filename, smart title case
    logger.py                #   Logging configuration
    rate_limiter.py          #   Per-service rate limiter for API calls
```

### Key Design Principles

- **Safety first**: Backups before changes, rollback support, dry-run mode
- **Confidence-based**: Auto-apply only above 90%, review queue for uncertain matches
- **Rate-limit aware**: All API calls go through the rate limiter (MusicBrainz 1/sec, Discogs 1/sec, Archive.org 1/sec)
- **Cancellable**: All long-running operations (fingerprinting, API lookups) check pause/cancel state
- **Extensible**: New metadata sources can be added by implementing a fetcher class

### Pipeline Phases

1. **Phase 0 -- Resume skip**: Check database for tracks already processed in a previous run
2. **Phase 1 -- Batch fingerprint**: Parallel fingerprinting via ThreadPoolExecutor (no API calls)
3. **Phase 2 -- Per-track pipeline**: Sequential API lookups, scoring, classification, and tagging

### Signal Flow (GUI)

```
Import View -> scan_requested / preview_requested
  -> app.py creates ProcessingWorker on QThread
    -> worker.run() calls BatchProcessor.process_prescanned()
      -> progress_updated signal -> Progress View
      -> processing_finished signal -> Preview View / Review View

Review View -> manual_search_requested
  -> app.py creates ManualSearchWorker on QThread
    -> results_ready signal -> Review View
```

## Questions?

Open a GitHub Discussion or issue for questions about contributing, architecture, or design decisions.
