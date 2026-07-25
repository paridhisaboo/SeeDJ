"""
Parses Rekordbox's ANLZ analysis files (ANLZ0000.DAT / .EXT / .2EX), which
already contain the precomputed waveform, beat grid, and cue/loop points
for every analyzed track.

Everything in this module is grounded in pyrekordbox's actual source
(installed and read directly, not guessed from docs) — specifically
`pyrekordbox/anlz/tags.py`'s `TAGS` registry and each tag class's `.get()`
implementation. Two things worth knowing before you touch this file:

1. A track's analysis data is split across up to THREE sibling files in the
   same directory: ANLZ0000.DAT (basic tags: path, VBR, PQTZ beat grid,
   PCOB cues, PWAV/PWV2 waveform previews), ANLZ0000.EXT (richer tags:
   PSSI song structure, PCO2 extended cues, PWV3/PWV4/PWV5 higher-detail
   waveforms), and ANLZ0000.2EX (newest devices: PWV6/PWV7/PWVC — these
   don't have custom parsers in pyrekordbox yet, so we surface them as raw
   but don't attempt to interpret their contents).
   `pyrekordbox.anlz.get_anlz_paths()` finds all three; we parse whichever
   exist and merge their tags into one search space.

2. Different waveform tags return genuinely different data shapes (a tiny
   greyscale preview vs. a per-sample RGB+height color waveform), not one
   normalized format. We surface whichever the file actually contains
   rather than forcing a lossy common shape — the Stage 3 renderer can
   decide how to handle each shape when we get there.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Beat grid tags, in preference order. PQT2 is the "extended" nxs2-era grid;
# prefer it when present since it's the more modern format, fall back to
# the original PQTZ otherwise. Both return the same (beats, bpms, times)
# shape from .get().
_BEAT_GRID_TAG_PRIORITY = ["PQT2", "PQTZ"]

# Waveform tags, richest-detail first. PWV5 (color detail, per-sample
# RGB+height) is the best for visual work if the file has it; PWAV (basic
# preview) is the universal fallback that's present even on very old
# analysis files. PWV6/PWV7/PWVC are intentionally excluded here — they
# don't have a parsed .get() shape in pyrekordbox yet (see module docstring).
_WAVEFORM_TAG_PRIORITY = ["PWV5", "PWV4", "PWV3", "PWV2", "PWAV"]


@dataclass
class BeatGridPoint:
    beat_number: int  # 1-4, position within the bar
    time_seconds: float
    bpm: float


@dataclass
class TrackAnalysis:
    anlz_dir: Path
    files_found: dict[str, Path] = field(default_factory=dict)  # {"DAT": ..., "EXT": ...}
    available_tags: list[str] = field(default_factory=list)  # e.g. ["PQTZ", "PWAV", "PPTH"]

    beat_grid: list[BeatGridPoint] = field(default_factory=list)
    beat_grid_tag_used: str | None = None

    waveform_tag_used: str | None = None
    waveform_data: Any = None  # shape depends on which tag — see module docstring


def load_analysis(anlz_path: str | Path) -> TrackAnalysis:
    """
    `anlz_path` can be either the ANLZ directory itself, or a path to one
    of the files inside it (e.g. what `RekordboxLibrary.resolve_analysis_path`
    returns) — we take `.parent` in the latter case.
    """
    from pyrekordbox.anlz import AnlzFile, get_anlz_paths

    path = Path(anlz_path)
    anlz_dir = path if path.is_dir() else path.parent

    files_found = {k: v for k, v in get_anlz_paths(anlz_dir).items() if v is not None}
    if not files_found:
        raise FileNotFoundError(f"No ANLZ0000.(DAT|EXT|2EX) files found in {anlz_dir}")

    # Merge tags from every sibling file that exists into one search space,
    # since e.g. PWV5 lives in .EXT while PQTZ lives in .DAT.
    all_tags = []
    for kind, fpath in files_found.items():
        try:
            parsed = AnlzFile.parse_file(str(fpath))
            all_tags.extend(parsed.tags)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse %s (%s): %s", kind, fpath, exc)

    available_tags = sorted({tag.type for tag in all_tags})

    beat_grid, beat_grid_tag = _extract_beat_grid(all_tags)
    waveform_tag, waveform_data = _extract_waveform(all_tags)

    return TrackAnalysis(
        anlz_dir=anlz_dir,
        files_found=files_found,
        available_tags=available_tags,
        beat_grid=beat_grid,
        beat_grid_tag_used=beat_grid_tag,
        waveform_tag_used=waveform_tag,
        waveform_data=waveform_data,
    )


def _find_tag(tags: list, tag_type: str):  # noqa: ANN001, ANN202
    for tag in tags:
        if tag.type == tag_type:
            return tag
    return None


def _extract_beat_grid(tags: list) -> tuple[list[BeatGridPoint], str | None]:  # noqa: ANN001
    for tag_type in _BEAT_GRID_TAG_PRIORITY:
        tag = _find_tag(tags, tag_type)
        if tag is None:
            continue
        try:
            beats, bpms, times = tag.get()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Found %s tag but .get() failed: %s", tag_type, exc)
            continue

        points = [
            BeatGridPoint(beat_number=int(b), time_seconds=float(t), bpm=float(bpm))
            for b, bpm, t in zip(beats, bpms, times)
        ]
        return points, tag_type

    return [], None


def _extract_waveform(tags: list) -> tuple[str | None, Any]:  # noqa: ANN001
    for tag_type in _WAVEFORM_TAG_PRIORITY:
        tag = _find_tag(tags, tag_type)
        if tag is None:
            continue
        try:
            data = tag.get()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Found %s tag but .get() failed: %s", tag_type, exc)
            continue
        return tag_type, data

    return None, None