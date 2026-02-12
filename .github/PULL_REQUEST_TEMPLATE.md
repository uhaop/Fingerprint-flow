## Summary

Brief description of the changes.

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Data Safety Checklist

If this PR touches file operations, tag writing, or the organizer:

- [ ] Backups are created BEFORE any tag modifications
- [ ] File moves verify integrity (size check) on cross-device operations
- [ ] No directories outside the library root are deleted
- [ ] Dry-run mode is respected for all new destructive operations
- [ ] Tests cover the new/changed file operations using `tmp_path`

## Testing

- [ ] All existing tests pass (`pytest`)
- [ ] New tests added for new functionality
- [ ] Linting passes (`ruff check src/ tests/`)
- [ ] Type checking passes (`mypy src/`)

## Checklist

- [ ] I have read the [Contributing Guide](CONTRIBUTING.md)
- [ ] My code follows the project's style guidelines
- [ ] I have updated documentation as needed
- [ ] I have added an entry to CHANGELOG.md (if applicable)
