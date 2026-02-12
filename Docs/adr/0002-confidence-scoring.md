# ADR-0002: Confidence-Based Processing Flow

**Date**: 2026-02-08  
**Status**: Accepted

## Context

When identifying music files via fingerprinting and metadata APIs, match quality
varies. We need a system to handle high-confidence matches differently from
uncertain or missing matches.

## Decision

Use a weighted confidence score (0-100) with three tiers:

- **90-100% (Auto-apply)**: Tags and file organization applied automatically
- **70-89% (Review)**: Show top 3 candidates for user selection
- **Below 70% (Manual)**: Full manual review with search capability
- **No match**: Keep original, move to `_Unmatched/` (or leave in place)

Scoring weights:
- Fingerprint match score: 40%
- Title similarity (fuzzy): 20%
- Artist similarity (fuzzy): 20%
- Duration match: 10%
- Album consistency: 10%

## Consequences

- Users don't need to review every file (auto-apply saves time)
- Thresholds are configurable in config.yaml
- Album consistency scoring requires processing multiple tracks in a batch
- The 90% threshold is conservative; users can lower it if they trust the matching
