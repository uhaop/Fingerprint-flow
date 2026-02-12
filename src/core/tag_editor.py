"""Tag editor -- reads and writes audio metadata tags via mutagen."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import mutagen
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from src.utils.constants import ID3_ENCODING_UTF8, ID3_PICTURE_TYPE_COVER_FRONT
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.models.track import Track

logger = get_logger("core.tag_editor")


# --- Tag key mapping for ASF/WMA format ---
# Maps our internal field names to ASF-specific tag keys.
# ID3 and Vorbis use EasyID3 / set_vorbis_tags helpers directly.
# MP4 keys are inlined in _write_mp4_tags due to special track/disc handling.

_ASF_MAP = {
    "title": "Title",
    "artist": "Author",
    "album": "WM/AlbumTitle",
    "album_artist": "WM/AlbumArtist",
    "track_number": "WM/TrackNumber",
    "disc_number": "WM/PartOfSet",
    "year": "WM/Year",
    "genre": "WM/Genre",
}


class TagEditor:
    """Reads and writes metadata tags on audio files.

    Supports MP3, FLAC, M4A, OGG Vorbis, OGG Opus, WMA, AIFF, APE, WavPack.
    Uses mutagen under the hood. Does not modify audio data, only tags.
    """

    def read_tags(self, track: Track) -> Track:
        """Read metadata tags from the audio file and populate the Track.

        Args:
            track: Track object with file_path set.

        Returns:
            The same Track object with metadata fields populated from file tags.
        """
        path = track.file_path
        if not path.exists():
            logger.warning("File not found for tag reading: %s", path)
            return track

        try:
            audio = mutagen.File(path, easy=True)
            if audio is None:
                logger.warning("Mutagen could not open: %s", path)
                return track

            # Duration from mutagen info
            if hasattr(audio, "info") and audio.info:
                if hasattr(audio.info, "length"):
                    track.duration = audio.info.length
                if hasattr(audio.info, "bitrate"):
                    track.bitrate = audio.info.bitrate // 1000 if audio.info.bitrate else None
                if hasattr(audio.info, "sample_rate"):
                    track.sample_rate = audio.info.sample_rate

            # Read tags based on format
            track.title = self._get_tag(audio, "title")
            track.artist = self._get_tag(audio, "artist")
            track.album = self._get_tag(audio, "album")
            track.album_artist = self._get_tag(audio, "albumartist")
            track.genre = self._get_tag(audio, "genre")
            track.year = self._parse_year(self._get_tag(audio, "date"))
            raw_tracknumber = self._get_tag(audio, "tracknumber")
            track.track_number = self._parse_track_number(raw_tracknumber)
            track.total_tracks = self._parse_total_from_tag(raw_tracknumber) or track.total_tracks

            raw_discnumber = self._get_tag(audio, "discnumber")
            track.disc_number = self._parse_track_number(raw_discnumber)
            track.total_discs = self._parse_total_from_tag(raw_discnumber) or track.total_discs

            logger.debug("Read tags for: %s -> %s - %s", path.name, track.artist, track.title)

        except (mutagen.MutagenError, OSError, ValueError) as e:
            logger.error("Error reading tags from %s: %s", path, e)

        return track

    def write_tags(self, track: Track) -> bool:
        """Write metadata tags to the audio file from the Track object.

        Args:
            track: Track object with metadata to write.

        Returns:
            True if tags were written successfully, False otherwise.
        """
        path = track.file_path
        if not path.exists():
            logger.error("File not found for tag writing: %s", path)
            return False

        try:
            suffix = path.suffix.lower()

            if suffix == ".mp3":
                return self._write_mp3_tags(track)
            elif suffix == ".flac":
                return self._write_flac_tags(track)
            elif suffix in (".m4a", ".aac", ".mp4"):
                return self._write_mp4_tags(track)
            elif suffix == ".ogg":
                return self._write_ogg_tags(track)
            elif suffix == ".opus":
                return self._write_opus_tags(track)
            elif suffix in (".wma", ".asf"):
                return self._write_asf_tags(track)
            elif suffix in (".aiff", ".aif"):
                return self._write_aiff_tags(track)
            else:
                # Try generic easy tags for APE, WavPack, etc.
                return self._write_easy_tags(track)

        except (mutagen.MutagenError, OSError, ValueError) as e:
            logger.error("Error writing tags to %s: %s", path, e)
            return False

    def write_cover_art(
        self, track: Track, image_data: bytes, mime_type: str = "image/jpeg"
    ) -> bool:
        """Write cover art to the audio file.

        Args:
            track: Track object with file_path.
            image_data: Raw image bytes.
            mime_type: MIME type of the image (default: image/jpeg).

        Returns:
            True if cover art was written successfully.
        """
        path = track.file_path
        suffix = path.suffix.lower()

        try:
            if suffix == ".mp3":
                return self._write_mp3_cover(path, image_data, mime_type)
            elif suffix == ".flac":
                return self._write_flac_cover(path, image_data, mime_type)
            elif suffix in (".m4a", ".aac", ".mp4"):
                return self._write_mp4_cover(path, image_data, mime_type)
            elif suffix in (".ogg", ".opus"):
                return self._write_vorbis_cover(path, image_data, mime_type)
            else:
                logger.warning("Cover art not supported for format: %s", suffix)
                return False
        except (mutagen.MutagenError, OSError, ValueError) as e:
            logger.error("Error writing cover art to %s: %s", path, e)
            return False

    # --- Private: Read helpers ---

    def _get_tag(self, audio: mutagen.FileType, key: str) -> str | None:
        """Extract a single tag value from a mutagen file object.

        Args:
            audio: Mutagen file object (opened with easy=True).
            key: Tag key name.

        Returns:
            Tag value as string, or None.
        """
        try:
            value = audio.get(key)
            if value:
                # Mutagen returns lists for most tag types
                if isinstance(value, list):
                    return str(value[0]).strip() if value[0] else None
                return str(value).strip() or None
        except (KeyError, IndexError, TypeError):
            pass
        return None

    def _parse_year(self, date_str: str | None) -> int | None:
        """Parse a year from a date string (may be 'YYYY', 'YYYY-MM-DD', etc.).

        Args:
            date_str: Raw date string from tags.

        Returns:
            Four-digit year as int, or None.
        """
        if not date_str:
            return None
        try:
            # Take first 4 characters as the year
            year = int(date_str[:4])
            if 1900 <= year <= 2100:
                return year
        except (ValueError, IndexError):
            pass
        return None

    def _parse_track_number(self, raw: str | None) -> int | None:
        """Parse a track/disc number from a string (may be '5' or '5/12').

        Args:
            raw: Raw track number string.

        Returns:
            Track number as int, or None.
        """
        if not raw:
            return None
        try:
            # Handle "5/12" format
            return int(raw.split("/")[0].strip())
        except (ValueError, IndexError):
            return None

    def _parse_total_from_tag(self, raw: str | None) -> int | None:
        """Parse the total from a 'N/Total' tag string (e.g. '5/12' -> 12).

        Args:
            raw: Raw tag string.

        Returns:
            Total as int, or None if not present or unparseable.
        """
        if not raw or "/" not in raw:
            return None
        try:
            return int(raw.split("/")[1].strip())
        except (ValueError, IndexError):
            return None

    # --- Private: Write helpers per format ---

    def _write_mp3_tags(self, track: Track) -> bool:
        """Write tags to an MP3 file using EasyID3."""
        path = track.file_path
        try:
            audio = EasyID3(path)
        except ID3NoHeaderError:
            audio = EasyID3()
            audio.save(path)
            audio = EasyID3(path)

        self._set_easy_tags(audio, track)
        audio.save()
        logger.debug("Wrote MP3 tags: %s", path.name)
        return True

    def _write_flac_tags(self, track: Track) -> bool:
        """Write tags to a FLAC file."""
        audio = FLAC(track.file_path)
        self._set_vorbis_tags(audio, track)
        audio.save()
        logger.debug("Wrote FLAC tags: %s", track.file_path.name)
        return True

    def _write_mp4_tags(self, track: Track) -> bool:
        """Write tags to an M4A/MP4 file."""
        audio = MP4(track.file_path)

        if track.title:
            audio["\xa9nam"] = [track.title]
        if track.artist:
            audio["\xa9ART"] = [track.artist]
        if track.album:
            audio["\xa9alb"] = [track.album]
        if track.album_artist:
            audio["aART"] = [track.album_artist]
        if track.year:
            audio["\xa9day"] = [str(track.year)]
        if track.genre:
            audio["\xa9gen"] = [track.genre]
        if track.track_number is not None:
            total = track.total_tracks or 0
            audio["trkn"] = [(track.track_number, total)]
        if track.disc_number is not None:
            total = track.total_discs or 0
            audio["disk"] = [(track.disc_number, total)]

        audio.save()
        logger.debug("Wrote MP4 tags: %s", track.file_path.name)
        return True

    def _write_ogg_tags(self, track: Track) -> bool:
        """Write tags to an OGG Vorbis file."""
        audio = OggVorbis(track.file_path)
        self._set_vorbis_tags(audio, track)
        audio.save()
        logger.debug("Wrote OGG Vorbis tags: %s", track.file_path.name)
        return True

    def _write_opus_tags(self, track: Track) -> bool:
        """Write tags to an OGG Opus file."""
        audio = OggOpus(track.file_path)
        self._set_vorbis_tags(audio, track)
        audio.save()
        logger.debug("Wrote OGG Opus tags: %s", track.file_path.name)
        return True

    def _write_asf_tags(self, track: Track) -> bool:
        """Write tags to a WMA/ASF file."""
        audio = ASF(track.file_path)

        for field_name, tag_key in _ASF_MAP.items():
            value = getattr(track, field_name, None)
            if value is not None:
                audio[tag_key] = [str(value)]

        audio.save()
        logger.debug("Wrote ASF tags: %s", track.file_path.name)
        return True

    def _write_aiff_tags(self, track: Track) -> bool:
        """Write tags to an AIFF file (uses ID3 tags)."""
        audio = AIFF(track.file_path)
        if audio.tags is None:
            audio.add_tags()
        # AIFF uses ID3 under the hood, use EasyID3-compatible approach
        # Reopen with easy interface
        try:
            easy = EasyID3(track.file_path)
        except ID3NoHeaderError:
            easy = EasyID3()
            easy.save(track.file_path)
            easy = EasyID3(track.file_path)

        self._set_easy_tags(easy, track)
        easy.save()
        logger.debug("Wrote AIFF tags: %s", track.file_path.name)
        return True

    def _write_easy_tags(self, track: Track) -> bool:
        """Write tags using the generic mutagen easy interface."""
        audio = mutagen.File(track.file_path, easy=True)
        if audio is None:
            logger.warning("Cannot open for writing: %s", track.file_path)
            return False

        self._set_easy_tags(audio, track)
        audio.save()
        logger.debug("Wrote easy tags: %s", track.file_path.name)
        return True

    def _set_easy_tags(self, audio: Any, track: Track) -> None:
        """Set tags on an EasyID3-compatible mutagen object."""
        if track.title:
            audio["title"] = track.title
        if track.artist:
            audio["artist"] = track.artist
        if track.album:
            audio["album"] = track.album
        if track.album_artist:
            audio["albumartist"] = track.album_artist
        if track.year:
            audio["date"] = str(track.year)
        if track.genre:
            audio["genre"] = track.genre
        if track.track_number is not None:
            total = track.total_tracks
            if total:
                audio["tracknumber"] = f"{track.track_number}/{total}"
            else:
                audio["tracknumber"] = str(track.track_number)
        if track.disc_number is not None:
            total = track.total_discs
            if total:
                audio["discnumber"] = f"{track.disc_number}/{total}"
            else:
                audio["discnumber"] = str(track.disc_number)

    def _set_vorbis_tags(self, audio: Any, track: Track) -> None:
        """Set tags on a Vorbis-comment-compatible mutagen object (FLAC, OGG)."""
        if track.title:
            audio["title"] = [track.title]
        if track.artist:
            audio["artist"] = [track.artist]
        if track.album:
            audio["album"] = [track.album]
        if track.album_artist:
            audio["albumartist"] = [track.album_artist]
        if track.year:
            audio["date"] = [str(track.year)]
        if track.genre:
            audio["genre"] = [track.genre]
        if track.track_number is not None:
            total = track.total_tracks
            if total:
                audio["tracknumber"] = [f"{track.track_number}/{total}"]
            else:
                audio["tracknumber"] = [str(track.track_number)]
        if track.disc_number is not None:
            total = track.total_discs
            if total:
                audio["discnumber"] = [f"{track.disc_number}/{total}"]
            else:
                audio["discnumber"] = [str(track.disc_number)]

    # --- Private: Cover art writers ---

    def _write_mp3_cover(self, path: Path, image_data: bytes, mime_type: str) -> bool:
        """Write cover art to MP3."""
        try:
            audio = ID3(path)
        except ID3NoHeaderError:
            audio = ID3()

        audio.delall("APIC")
        audio.add(
            APIC(
                encoding=ID3_ENCODING_UTF8,
                mime=mime_type,
                type=ID3_PICTURE_TYPE_COVER_FRONT,
                desc="Cover",
                data=image_data,
            )
        )
        audio.save(path)
        return True

    def _write_flac_cover(self, path: Path, image_data: bytes, mime_type: str) -> bool:
        """Write cover art to FLAC."""
        audio = FLAC(path)
        pic = Picture()
        pic.type = ID3_PICTURE_TYPE_COVER_FRONT
        pic.mime = mime_type
        pic.desc = "Cover"
        pic.data = image_data
        audio.clear_pictures()
        audio.add_picture(pic)
        audio.save()
        return True

    def _write_mp4_cover(self, path: Path, image_data: bytes, mime_type: str) -> bool:
        """Write cover art to M4A/MP4."""
        audio = MP4(path)
        fmt = MP4Cover.FORMAT_PNG if mime_type == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(image_data, imageformat=fmt)]
        audio.save()
        return True

    def _write_vorbis_cover(self, path: Path, image_data: bytes, mime_type: str) -> bool:
        """Write cover art to OGG Vorbis/Opus via METADATA_BLOCK_PICTURE."""
        audio = mutagen.File(path)
        if audio is None:
            return False

        pic = Picture()
        pic.type = ID3_PICTURE_TYPE_COVER_FRONT
        pic.mime = mime_type
        pic.desc = "Cover"
        pic.data = image_data

        audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        audio.save()
        return True
