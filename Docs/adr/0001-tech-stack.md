# ADR-0001: Technology Stack Selection

**Date**: 2026-02-08  
**Status**: Accepted

## Context

We need a desktop application for organizing music files that:
- Runs on Windows, macOS, and Linux
- Reads/writes audio metadata tags
- Fingerprints audio files for identification
- Queries free metadata APIs
- Provides a modern, polished GUI

## Decision

- **Language**: Python 3.10+ (ecosystem support for audio, rapid development)
- **GUI**: PyQt6 (mature, cross-platform, professional appearance)
- **Audio Fingerprinting**: pyacoustid + Chromaprint (free, industry standard)
- **Tag Editing**: mutagen (supports all major audio formats, Python-native)
- **Metadata APIs**: MusicBrainz (via musicbrainzngs), Discogs (REST API), Cover Art Archive
- **Database**: SQLite (zero-config, embedded, sufficient for local state)
- **Config**: YAML (human-readable, widely understood)
- **Fuzzy Matching**: rapidfuzz (fast C++ backed, better than fuzzywuzzy)

## Consequences

- Users must install Chromaprint's `fpcalc` binary separately (not pip-installable)
- PyQt6 has a larger install footprint than lightweight alternatives (tkinter, etc.)
- SQLite limits concurrent write access (acceptable for a single-user desktop app)
- All APIs are free but rate-limited (MusicBrainz: 1 req/sec, Discogs: 60 req/min)
