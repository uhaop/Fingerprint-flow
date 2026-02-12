# Security Policy

## Data Safety

Fingerprint Flow manipulates your music files (moving, renaming, and rewriting metadata tags). We take data safety extremely seriously.

### Built-in Protections

- **Backups before changes**: Original files are backed up *before* any tags are modified (not after). If something goes wrong, the backup contains your original, unmodified file.
- **Rollback support**: Every file move is recorded in a database. You can undo individual files or entire batch operations.
- **Dry-run mode**: Preview exactly what would happen before committing any changes.
- **Duplicate detection**: Files are never silently overwritten. If a destination already exists, the operation is skipped.
- **Safe cross-device moves**: File integrity is verified (size check) after copying across drives before the source is deleted.
- **No source directory deletion**: The app never deletes directories outside your configured library path.
- **Dangerous path protection**: System directories (e.g., `C:\Windows`, `/usr`) are blocked as library paths.

### Recommended Practices

1. **Always test with a small folder first** before processing your entire library.
2. **Keep backups enabled** (`keep_originals: true` in config -- this is the default).
3. **Use dry-run mode** for large batches to preview changes.
4. **Set your backup path to a separate drive** if possible, so backups survive drive failure.

## Reporting a Vulnerability

If you discover a bug that could cause **data loss** (files deleted, tags overwritten without backup, rollback failure, etc.), please report it as a **critical security issue**.

### How to Report

1. **Do NOT open a public GitHub issue** for data-loss bugs -- they may affect users before a fix is available.
2. Email the maintainers at the address listed in the repository's profile, or use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) feature.
3. Include:
   - Steps to reproduce
   - What happened vs. what was expected
   - Your OS, Python version, and Fingerprint Flow version
   - Whether any files were lost or corrupted

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Triage**: Within 1 week
- **Fix**: Data-loss bugs are treated as P0 and patched as soon as possible

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
