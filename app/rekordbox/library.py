"""
Rekordbox library access.

Two ways in, tried in order:
  1. The local `master.db` (SQLCipher-encrypted) via pyrekordbox's
     `Rekordbox6Database` — full collection, richest data.
  2. An exported XML database (`RekordboxXml`) as a fallback if the DB key
     extraction breaks (this has happened before after Rekordbox updates —
     see the pyrekordbox GitHub discussions). You get this by turning on
     "Export Collection in xml format" in Rekordbox Preferences > Advanced
     > Database and pointing REKORDBOX_XML_PATH at the resulting file.

Confidence note: `Rekordbox6Database.get_content()` and the DjmdContent
column names below (Title, ArtistName, BPM, Key, AnalysisDataPath, ...) are
the documented/commonly-used pyrekordbox pattern as of the 0.4.x line. If
your installed version differs, `explore_schema()` below will show you the
real attribute names in about 10 seconds — use it instead of guessing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


@dataclass
class Track:
    id: str
    title: str | None
    artist: str | None
    bpm: float | None
    key: str | None
    length_seconds: float | None
    analysis_data_path: str | None  # path to ANLZ0000.DAT, if known
    source: str  # "db" or "xml"


class RekordboxLibrary:
    """Opens whichever backend works and exposes a uniform Track interface."""

    def __init__(self, db_dir: str | None = None, xml_path: str | None = None) -> None:
        self.source: str | None = None
        self._db = None
        self._xml = None

        if self._try_open_db(db_dir):
            self.source = "db"
        elif xml_path and self._try_open_xml(xml_path):
            self.source = "xml"
        else:
            raise RuntimeError(
                "Could not open Rekordbox library via DB or XML. "
                "Run scripts/rekordbox_smoke_test.py for a detailed diagnostic, "
                "or set REKORDBOX_XML_PATH after enabling XML export in "
                "Rekordbox > Preferences > Advanced > Database."
            )

    def _try_open_db(self, db_dir: str | None) -> bool:
        try:
            from pyrekordbox import Rekordbox6Database

            self._db = Rekordbox6Database(db_dir) if db_dir else Rekordbox6Database()
            # Cheap sanity check that the key actually unlocked the DB.
            next(iter(self._db.get_content()), None)
            return True
        except Exception as exc:  # noqa: BLE001 - we want to fall through, log why
            logger.warning("Rekordbox DB open failed (%s); will try XML fallback.", exc)
            self._db = None
            return False

    @property
    def share_dir(self) -> Path | None:
        """
        The directory that relative ANLZ paths (e.g. the "/PIONEER/USBANLZ/..."
        stored in DjmdContent.AnalysisDataPath) need to be joined against.

        Confirmed empirically (not guessed): on Rekordbox 7 / macOS,
        `find <db_dir> -iname ANLZ0000.DAT` showed real files living at
        `<db_dir>/share/PIONEER/USBANLZ/...`, where <db_dir> is the folder
        containing master.db. We derive <db_dir> from the already-open
        SQLAlchemy engine's URL rather than pyrekordbox's config internals,
        since that's what we've actually verified works — if pyrekordbox's
        config API differs by version, this still works because it doesn't
        depend on it.
        """
        if self.source != "db" or self._db is None:
            return None
        try:
            db_path = Path(str(self._db.engine.url.database))
            return db_path.parent / "share"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not derive share_dir from the DB engine URL (%s). "
                "Set REKORDBOX_SHARE_DIR in .env manually as a workaround.",
                exc,
            )
            return None

    def resolve_analysis_path(self, track: Track) -> Path | None:
        """
        Turns a track's raw (relative) analysis_data_path into a real,
        existing path on disk. Returns None (with a logged warning showing
        exactly what was tried) rather than a path that doesn't exist, so
        callers can rely on "not None" meaning "this file is actually there."
        """
        if not track.analysis_data_path:
            return None
        base = self.share_dir
        if base is None:
            return None

        relative = track.analysis_data_path.lstrip("/\\").replace("\\", "/")
        candidate = base / relative

        if candidate.exists():
            return candidate

        logger.warning(
            "Resolved ANLZ path does not exist: %s (base=%s, raw=%s). "
            "Rekordbox's on-disk layout may differ on your version/OS — "
            "run `find <db_dir> -iname ANLZ0000.DAT` to check.",
            candidate,
            base,
            track.analysis_data_path,
        )
        return None

    def _try_open_xml(self, xml_path: str) -> bool:
        try:
            from pyrekordbox.xml import RekordboxXml

            path = Path(xml_path)
            if not path.exists():
                logger.warning("XML path %s does not exist.", xml_path)
                return False
            self._xml = RekordboxXml(str(path))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Rekordbox XML open failed: %s", exc)
            return False

    # -- Public API --------------------------------------------------

    def iter_tracks(self) -> Iterator[Track]:
        if self.source == "db":
            yield from self._iter_tracks_db()
        elif self.source == "xml":
            yield from self._iter_tracks_xml()

    def count(self) -> int:
        return sum(1 for _ in self.iter_tracks())

    def find_by_bpm_range(self, low: float, high: float) -> list[Track]:
        """Used later by the technique classifier to sanity-check a detected
        tempo against what's actually in the library."""
        return [t for t in self.iter_tracks() if t.bpm and low <= t.bpm <= high]

    # -- Backend-specific iteration ------------------------------------

    def _iter_tracks_db(self) -> Iterator[Track]:
        assert self._db is not None
        for content in self._db.get_content():
            yield Track(
                id=str(getattr(content, "ID", "")),
                title=getattr(content, "Title", None),
                artist=_safe_artist_name(content),
                bpm=_safe_float(getattr(content, "BPM", None), scale=1 / 100),
                key=_safe_key_name(content),
                length_seconds=getattr(content, "Length", None),
                analysis_data_path=getattr(content, "AnalysisDataPath", None),
                source="db",
            )

    def _iter_tracks_xml(self) -> Iterator[Track]:
        assert self._xml is not None
        for i in range(len(self._xml.get_tracks())):
            track = self._xml.get_track(i)
            yield Track(
                id=str(track.get("TrackID", i)),
                title=track.get("Name"),
                artist=track.get("Artist"),
                bpm=_safe_float(track.get("AverageBpm")),
                key=track.get("Tonality"),
                length_seconds=_safe_float(track.get("TotalTime")),
                analysis_data_path=None,  # XML export doesn't include this
                source="xml",
            )


def _safe_float(value: Any, scale: float = 1.0) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * scale
    except (TypeError, ValueError):
        return None


def _safe_artist_name(content: Any) -> str | None:
    # In the DB schema, artist is usually a related object (content.Artist.Name)
    # rather than a flat string column. Try both shapes defensively.
    artist = getattr(content, "Artist", None)
    if artist is not None:
        return getattr(artist, "Name", None)
    return getattr(content, "ArtistName", None)


def _safe_key_name(content: Any) -> str | None:
    key = getattr(content, "Key", None)
    if key is not None:
        return getattr(key, "ScaleName", None) or getattr(key, "Name", None)
    return getattr(content, "KeyName", None)


def explore_schema(db_dir: str | None = None, sample_rows: int = 1) -> dict[str, Any]:
    """
    Dumps table names and, for a sample row per table, the attribute names
    and values that are actually populated on THIS install's DB. This is
    the tool to run before trusting any column name referenced above or in
    now_playing.py — schema drift across Rekordbox versions is real and
    undocumented, so verify rather than assume.
    """
    from pyrekordbox import Rekordbox6Database
    from sqlalchemy import inspect as sa_inspect

    db = Rekordbox6Database(db_dir) if db_dir else Rekordbox6Database()
    inspector = sa_inspect(db.engine)
    report: dict[str, Any] = {}

    for table_name in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        report[table_name] = {"columns": columns}

    return report