# API Reference Links

External APIs and services used by Fingerprint Flow.

## AcoustID / Chromaprint (Audio Fingerprinting)

- Documentation: https://acoustid.org/docs
- Web Service API: https://acoustid.org/webservice
- FAQ: https://acoustid.org/faq
- Chromaprint (fpcalc): https://acoustid.org/chromaprint
- Register an application (free API key): https://acoustid.org/new-application

## MusicBrainz (Music Metadata)

- API docs: https://musicbrainz.org/doc/MusicBrainz_API
- Python client: https://python-musicbrainzngs.readthedocs.io/
- Rate limit: 1 request per second (with user-agent identification)

## Discogs (Music Metadata)

- API v2 Documentation: https://www.discogs.com/developers/
- Raw data exports: https://data.discogs.com/
- Generate a personal access token: https://www.discogs.com/settings/developers
- Rate limit: 60 requests per minute (authenticated)

## Internet Archive (DJ Screw / Fallback Metadata)

- API documentation: https://archive.org/developers/index-apis.html
- No API key required
- Used as primary source for DJ Screw "Diary of the Originator" chapters
- Used as fallback when MusicBrainz/Discogs return no results

## Cover Art Archive

- API docs: https://coverartarchive.org/
- Linked via MusicBrainz release IDs
- No API key required
